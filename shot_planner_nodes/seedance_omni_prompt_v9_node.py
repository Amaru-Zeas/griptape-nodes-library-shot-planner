"""Seedance Omni Prompt V9 - one board for Seedance 2.0 and Seedance 2.5.

V9 = V8's entity board, but Send picks the envelope from the target node
instead of always using the 2.5 lists:

* SEEDANCE 2.5 (and any newer list-based Seedance node) - 30 images /
  10 videos / 10 audio, written into the ``reference_images``,
  ``reference_videos``, and ``reference_audio`` lists after switching the
  task to Reference to Video.
* SEEDANCE 2.0 - 9 images / 3 videos / 3 audio. The node stays in Text Only
  until ``input_mode`` is Multimodal References, which is also what unhides
  the reference inputs. Videos are the fixed slots ``reference_video_1``
  through ``reference_video_3`` (2 and 3 stay hidden until the previous
  slot has a file). Audio is a list capped at 3.

The board meter still goes up to the 2.5 ceiling. On push, each target is
capped on its own, nice-to-have entities first, and that node's prompt is
renumbered to match the files it actually received.

Everything from V7 carries over:

* ENTITIES - group refs under a name (``@Maya``, ``@Hero-Jacket``). A single
  entity mention expands on export to every bracket tag it owns
  (``[Image 3], [Image 7], [Image 12]``). Numbers become an internal detail.
* LANES - every entity lives in a production lane (Cast / Wardrobe / Props /
  Set / Light / Camera / Audio). The Prompt Enhancer becomes role-aware:
  Cast refs get identity constraints, Light refs get grade-matching
  constraints, Camera video refs get motion-matching constraints, etc.
* SLOT BUDGET - now per kind (30 img / 10 vid / 10 aud). On push, if the
  mentioned refs of any kind exceed its cap, nice-to-have entities are
  dropped before must-have ones and the prompt is compacted, with a warning.

Everything else carries over from V6: connection-free workflow scanning of
IMPORTED media (Load Image / Load Video / Load Audio), stable tag order,
"Send to Seedance" pushing prompt + ordered refs straight into generator
nodes, mentioned-only compaction, spellcheck, and voice dictation.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from griptape_nodes.exe_types.core_types import Parameter, ParameterMode
from griptape_nodes.exe_types.node_types import BaseNode, DataNode
from griptape_nodes.traits.widget import Widget

try:
    from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes  # type: ignore[reportMissingImports]
except Exception:  # pragma: no cover
    GriptapeNodes = None  # type: ignore[assignment]

try:
    from PIL import Image  # type: ignore[reportMissingImports]
except Exception:  # pragma: no cover
    Image = None  # type: ignore[assignment]

try:
    from griptape.artifacts import ImageUrlArtifact  # type: ignore[reportMissingImports]
except Exception:  # pragma: no cover
    ImageUrlArtifact = None  # type: ignore[assignment]

try:
    from griptape.artifacts.video_url_artifact import VideoUrlArtifact  # type: ignore[reportMissingImports]
except Exception:  # pragma: no cover
    VideoUrlArtifact = None  # type: ignore[assignment]

try:
    from griptape.artifacts.audio_url_artifact import AudioUrlArtifact  # type: ignore[reportMissingImports]
except Exception:  # pragma: no cover
    try:
        from griptape.artifacts import AudioUrlArtifact  # type: ignore[reportMissingImports]
    except Exception:
        AudioUrlArtifact = None  # type: ignore[assignment]

LIBRARY_NAME = "GTN Shot Planner"
WIDGET_NAME = "SeedancePromptV9Widget"

# Seedance 2.5 reference envelope: 50 total, capped per kind.
# This is also the board's ceiling. Seedance 2.0 is clamped per target on push.
MAX_IMAGE_SLOTS = 30
MAX_VIDEO_SLOTS = 10
MAX_AUDIO_SLOTS = 10

# Seedance 2.0 multimodal envelope (BytePlus / the 2.0 generator node).
MAX_IMAGE_SLOTS_20 = 9
MAX_VIDEO_SLOTS_20 = 3
MAX_AUDIO_SLOTS_20 = 3

INPUT_MODE_MULTIMODAL = "Multimodal References"
TASK_REFERENCE_TO_VIDEO = "Reference to Video"

DEFAULT_COMPOSER: dict[str, Any] = {
    "text": "",
    "enhance": False,
    "refs": [],
    "entities": [],
    "budget": MAX_IMAGE_SLOTS,
    "statusMessage": "",
    "scanMode": True,
    "scanNonce": 0,
    "targets": [],
    "groups": [],
    "sendTarget": "all",
    "sendNonce": 0,
    "doSend": False,
    "thumbScale": 1,
    "promptFile": "",
    "promptFileNonce": 0,
    "promptFileStatus": "",
    "promptBrowseNonce": 0,
}

# Lanes in push/enhancer priority order.
LANE_ORDER = ("character", "wardrobe", "prop", "set", "light", "camera", "audio")

# Dynamic per-tag output parameters look like image_1 / video_2 / audio_1.
_TAG_PARAM_RE = re.compile(r"^(image|video|audio)_(\d+)$")

_MENTION_RE = re.compile(r"@(image|video|audio)[\s_-]?(\d+)", re.IGNORECASE)
_BRACKET_RE = re.compile(r"\[(image|video|audio)\s*(\d+)\]", re.IGNORECASE)
# Entity names: letter first, then letters/digits/_/-, matched case-insensitively.
_KIND_TAG_NAME_RE = re.compile(r"^(image|video|audio)\d*$", re.IGNORECASE)

_ARTIFACT_KINDS = {
    "ImageArtifact": "image",
    "ImageUrlArtifact": "image",
    "VideoArtifact": "video",
    "VideoUrlArtifact": "video",
    "AudioArtifact": "audio",
    "AudioUrlArtifact": "audio",
}

_EXT_KINDS = {
    "image": (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff"),
    "video": (".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v"),
    "audio": (".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac"),
}

_SELF_CLASS_PREFIX = "SeedanceOmniPrompt"
_GROUP_TARGET_PREFIX = "group:"
# Extra Load-Image equivalents that are not named Load* and may predate
# library_node_metadata.group = Input/Output (PSD Flatten / PSD Layer).
_IMPORT_NODE_CLASSES = frozenset({"PsdFlattenNode", "PsdLayerNode"})


def _default_composer() -> dict[str, Any]:
    state = dict(DEFAULT_COMPOSER)
    state["refs"] = []
    state["entities"] = []
    state["groups"] = []
    return state


def _classify_url(text: str) -> str:
    """Guess media kind from a URL/path string; '' if not a media reference."""
    lowered = text.lower().split("?", 1)[0].split("#", 1)[0]
    if lowered.startswith("data:"):
        mime = lowered[5:].split(";", 1)[0].split("/", 1)[0]
        return mime if mime in ("image", "video", "audio") else ""
    for kind, exts in _EXT_KINDS.items():
        if lowered.endswith(exts):
            return kind
    return ""


class SeedanceOmniPromptV9Node(DataNode):
    """Prompt composer that pushes into Seedance 2.0 and Seedance 2.5.

    * Entities: ``@Maya`` expands to every bracket tag the entity owns.
    * Lanes drive a role-aware Prompt Enhancer (identity / wardrobe / prop /
      set / grade / camera-motion / audio constraints).
    * Per-kind slot budgets follow the target: 2.5 keeps 30/10/10; 2.0 is
      clamped to 9/3/3, its inputs are unhidden, and videos go to the fixed
      slots. Over-budget refs drop nice-to-have entities first.
    """

    def __init__(self, name: str, metadata: dict[str, Any] | None = None, **kwargs) -> None:
        node_metadata = {
            "category": "ShotPlanner",
            "description": (
                "Prompt composer for Seedance 2.0 and Seedance 2.5: group refs into named entities "
                "(@Maya), organize them on a production lane board, and push prompt + ordered "
                "references into each generator using that node's own envelope (2.0: 9 images / "
                "3 videos / 3 audio; 2.5: 30 / 10 / 10)."
            ),
        }
        if metadata:
            node_metadata.update(metadata)
        super().__init__(name=name, metadata=node_metadata, **kwargs)
        self.set_initial_node_size(width=900, height=820)

        self._last_scan_nonce: Any = None
        self._last_send_nonce: Any = None
        self._last_prompt_browse_nonce: Any = None
        self._scanned_refs: list[dict[str, Any]] = []
        self._scan_error = ""
        self._nodes_lookup_error = ""
        self._syncing = False
        # Thumbnail data-URL cache keyed by source URL (thumbs are expensive).
        self._thumb_cache: dict[str, str] = {}
        # Full (non-truncated) URL per identity key, for the list outputs.
        self._asset_urls: dict[str, str] = {}

        self.add_parameter(
            Parameter(
                name="composer",
                input_types=["dict"],
                type="dict",
                output_type="dict",
                default_value=_default_composer(),
                tooltip=(
                    "Prompt editor + entity board: type @ to mention an entity (@Maya) or a raw "
                    "asset tag. Drag pool refs onto entities; lanes drive the role-aware enhancer."
                ),
                allowed_modes={ParameterMode.PROPERTY},
                traits={Widget(name=WIDGET_NAME, library=LIBRARY_NAME)},
            )
        )
        self._sanitize_composer_callbacks()
        self.add_parameter(
            Parameter(
                name="prompt",
                output_type="str",
                tooltip="Final prompt: entity mentions expanded and converted to [Image N] / [Video N] / [Audio N].",
                allowed_modes={ParameterMode.OUTPUT},
            )
        )
        self.add_parameter(
            Parameter(
                name="reference_images",
                output_type="list",
                tooltip="Images in @Image tag order. Wire once into the Seedance node's Reference Images list; slot N always matches [Image N].",
                allowed_modes={ParameterMode.OUTPUT},
                serializable=False,
                ui_options={"hide": True},
            )
        )
        self.add_parameter(
            Parameter(
                name="reference_videos",
                output_type="list",
                tooltip="Videos in @Video tag order.",
                allowed_modes={ParameterMode.OUTPUT},
                serializable=False,
                ui_options={"hide": True},
            )
        )
        self.add_parameter(
            Parameter(
                name="reference_audio",
                output_type="list",
                tooltip="Audio in @Audio tag order.",
                allowed_modes={ParameterMode.OUTPUT},
                serializable=False,
                ui_options={"hide": True},
            )
        )
        self._prompt_file_path = ""
        self._prompt_file_stamp: tuple[int, int] | None = None
        self._prompt_file_nonce = 0
        self._prompt_file_watch_started = False
        self._ensure_prompt_file_watch()

    # ------------------------------------------------------------------ prompt file

    def _ensure_prompt_file_watch(self) -> None:
        if self._prompt_file_watch_started:
            return
        self._prompt_file_watch_started = True

        def loop() -> None:
            while True:
                threading.Event().wait(1.0)
                try:
                    self._watch_prompt_file()
                except Exception:
                    pass

        threading.Thread(target=loop, name="omni-v9-prompt-file", daemon=True).start()

    @staticmethod
    def _native_prompt_dialog(initial_dir: str) -> str:
        """Open the Windows file picker and return the chosen .txt path."""
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            try:
                root.attributes("-topmost", True)
            except Exception:
                pass
            picked = filedialog.askopenfilename(
                initialdir=initial_dir or None,
                title="Pick a prompt text file",
                filetypes=[("Text prompt", "*.txt"), ("All files", "*.*")],
                parent=root,
            )
            root.destroy()
            return str(picked or "")
        except Exception:
            return ""

    def _browse_prompt_file(self, state: dict[str, Any]) -> None:
        """Open Explorer off-thread so picking a .txt never freezes the node."""
        initial = str(state.get("promptFile") or "").strip().strip('"')
        initial_dir = ""
        if initial:
            parent = Path(os.path.expandvars(os.path.expanduser(initial))).parent
            if parent.is_dir():
                initial_dir = str(parent)

        def run() -> None:
            picked = self._native_prompt_dialog(initial_dir)
            fresh = self._current_state()
            if picked:
                fresh["promptFile"] = picked
                self._prompt_file_path = picked
                self._prompt_file_stamp = None
                self._read_prompt_file_into(fresh, force=True)
            else:
                fresh["promptFileStatus"] = "File picker closed without a selection."
            self._push_state(fresh)

        threading.Thread(target=run, daemon=True, name="omni-v9-prompt-browse").start()

    def _watch_prompt_file(self) -> None:
        if self._syncing:
            return
        state = self._current_state()
        path_text = str(state.get("promptFile") or "").strip().strip('"')
        if path_text != str(getattr(self, "_prompt_file_path", "") or ""):
            self._prompt_file_path = path_text
            self._prompt_file_stamp = None
        if not path_text:
            return
        if self._read_prompt_file_into(state, force=False):
            self._push_state(state)

    def _note_prompt_file_request(self, state: dict[str, Any]) -> None:
        """Load the .txt when the path changes or Get Latest Prompt is clicked."""
        path_text = str(state.get("promptFile") or "").strip().strip('"')
        nonce = self._nonce_int(state.get("promptFileNonce"))
        path_changed = path_text != str(getattr(self, "_prompt_file_path", "") or "")
        nonce_changed = bool(nonce) and nonce != self._nonce_int(getattr(self, "_prompt_file_nonce", 0))
        if path_changed:
            self._prompt_file_path = path_text
            self._prompt_file_stamp = None
        if nonce_changed:
            self._prompt_file_nonce = nonce
        if path_changed or nonce_changed:
            self._read_prompt_file_into(state, force=True)

    def _read_prompt_file_into(self, state: dict[str, Any], *, force: bool) -> bool:
        """Copy the prompt file into ``state['text']``. True when text or status changed."""
        raw = str(state.get("promptFile") or getattr(self, "_prompt_file_path", "") or "").strip().strip('"')
        if not raw:
            if force:
                state["promptFileStatus"] = "Click Load Prompt and pick a .txt file."
                return True
            return False
        path = Path(os.path.expandvars(os.path.expanduser(raw)))
        if not path.is_file():
            message = f"Prompt file not found: {path}"
            if state.get("promptFileStatus") == message and not force:
                return False
            state["promptFileStatus"] = message
            return True
        try:
            stat = path.stat()
            stamp = (int(stat.st_mtime_ns), int(stat.st_size))
        except OSError as exc:
            state["promptFileStatus"] = f"Could not read prompt file: {exc}"
            return True
        if not force and stamp == getattr(self, "_prompt_file_stamp", None):
            return False
        try:
            text = self._read_prompt_text(path)
        except OSError as exc:
            state["promptFileStatus"] = f"Could not read prompt file: {exc}"
            return True
        self._prompt_file_stamp = stamp
        from datetime import datetime

        clock = datetime.now().strftime("%H:%M:%S")
        current = str(state.get("text") or "")
        changed = current != text
        if changed:
            state["text"] = text
        status = f"Loaded {path.name} at {clock}" if changed or force else f"Already current: {path.name}"
        status_changed = state.get("promptFileStatus") != status
        state["promptFileStatus"] = status
        return changed or status_changed

    @staticmethod
    def _read_prompt_text(path: Path) -> str:
        data = path.read_bytes()
        text = ""
        for encoding in ("utf-8-sig", "cp1252"):
            try:
                text = data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = data.decode("utf-8", errors="replace")
        return text.replace("\r\n", "\n").replace("\r", "\n")

    @staticmethod
    def _migrate_entity_keys(state: dict[str, Any], prev_refs: list[Any], refs: list[dict[str, Any]]) -> None:
        """Point entity membership at the node name when an older filename key is retired."""
        current = {str(r.get("key") or "") for r in refs if r.get("key")}
        by_label = {str(r.get("label") or ""): str(r.get("key") or "") for r in refs if r.get("label")}
        old_map: dict[str, str] = {}
        ambiguous: set[str] = set()
        for old in prev_refs:
            if not isinstance(old, dict):
                continue
            old_key = str(old.get("key") or "")
            label = str(old.get("label") or "")
            new_key = by_label.get(label, "")
            if not old_key or not new_key or old_key in current:
                continue
            previous = old_map.get(old_key)
            if previous and previous != new_key:
                ambiguous.add(old_key)
            else:
                old_map[old_key] = new_key
        for key in ambiguous:
            old_map.pop(key, None)
        entities = state.get("entities")
        if not isinstance(entities, list) or not old_map:
            return
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            keys = entity.get("refKeys")
            if not isinstance(keys, list):
                continue
            entity["refKeys"] = [old_map.get(str(key), str(key)) for key in keys]

    # ------------------------------------------------------------------ scanning

    def _harvest_value(self, value: Any, found: list[tuple[str, str, bool]], depth: int = 0) -> None:
        """Append (kind, url, is_artifact) tuples discovered inside a parameter value."""
        if value is None or depth > 3:
            return
        if isinstance(value, str):
            text = value.strip()
            kind = _classify_url(text) if text else ""
            if kind:
                found.append((kind, text, False))
            return
        if isinstance(value, (list, tuple)):
            for item in value[:128]:
                self._harvest_value(item, found, depth + 1)
            return
        if isinstance(value, dict):
            type_name = str(value.get("type") or "")
            kind = _ARTIFACT_KINDS.get(type_name, "")
            is_artifact = bool(kind)
            url = ""
            for key in ("value", "url", "src", "path"):
                candidate = value.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    url = candidate.strip()
                    break
            if url:
                if not kind:
                    kind = _classify_url(url)
                if kind:
                    found.append((kind, url, is_artifact))
            return
        type_name = type(value).__name__
        kind = _ARTIFACT_KINDS.get(type_name, "")
        if kind:
            inner = getattr(value, "value", None)
            if isinstance(inner, str) and inner.strip():
                found.append((kind, inner.strip(), True))
            else:
                # Bytes-backed artifact: try a data URL so thumbnails still work.
                try:
                    b64 = getattr(value, "base64", None)
                    if b64:
                        mime = getattr(value, "mime_type", None) or f"{kind}/*"
                        found.append((kind, f"data:{mime};base64,{b64}", True))
                except Exception:
                    pass

    @staticmethod
    def _is_import_node(node: Any) -> bool:
        """True only for asset *import* nodes (LoadImage/LoadVideo/LoadAudio, Input/Output, PSD Flatten/Layer)."""
        cls_name = type(node).__name__
        if cls_name.startswith("Load") or cls_name in _IMPORT_NODE_CLASSES:
            return True
        try:
            metadata = getattr(node, "metadata", None) or {}
            lib_meta = metadata.get("library_node_metadata") or {}
            if isinstance(lib_meta, dict):
                group = str(lib_meta.get("group") or "").strip().lower()
            else:
                group = str(getattr(lib_meta, "group", "") or "").strip().lower()
            if group == "input/output" and cls_name not in ("SaveImage", "SaveVideo", "SaveAudio", "SaveText"):
                return True
        except Exception:
            pass
        return False

    @staticmethod
    def _url_is_resolvable(url: str) -> bool:
        if url.startswith(("http://", "https://", "data:")):
            return True
        try:
            path = Path(os.path.expandvars(os.path.expanduser(url.removeprefix("file://"))))
            return path.is_file()
        except Exception:
            return False

    @staticmethod
    def _identity_key(url: str) -> str:
        """Dedupe key: the same file often appears as '{inputs}/x.jpg' AND 'A:\\...\\x.jpg'."""
        if url.startswith("data:"):
            return url[:256]
        clean = url.split("?", 1)[0].split("#", 1)[0].replace("\\", "/")
        base = clean.rstrip("/").rsplit("/", 1)[-1].strip().lower()
        return base or clean.lower()

    def _node_primary_asset(self, node: Any) -> tuple[str, str] | None:
        """The single best (kind, url) for an import node."""
        candidates: list[tuple[int, int, str, str]] = []
        sources: list[tuple[str, Any]] = []
        try:
            sources.extend(node.parameter_output_values.items())
        except Exception:
            pass
        try:
            sources.extend(node.parameter_values.items())
        except Exception:
            pass
        order = 0
        for param_name, value in sources:
            found: list[tuple[str, str, bool]] = []
            try:
                self._harvest_value(value, found)
            except Exception:
                continue
            for kind, url, is_artifact in found:
                score = 0
                if is_artifact:
                    score += 4
                if param_name.strip().lower() in (
                    "image",
                    "video",
                    "audio",
                    "output_image",
                    "output_video",
                    "output_audio",
                    "audio_file",
                ):
                    score += 2
                if self._url_is_resolvable(url):
                    score += 1
                candidates.append((score, -order, kind, url))
                order += 1
        if not candidates:
            return None
        best = max(candidates)
        return best[2], best[3]

    # ------------------------------------------------------------------ thumbnails

    @staticmethod
    def _fetch_bytes(url: str, max_bytes: int = 32 * 1024 * 1024) -> bytes:
        """Read bytes from a data URL, http(s) URL, file:// URI, or local path."""
        if not url:
            return b""
        if url.startswith("data:"):
            try:
                _header, payload = url.split(",", 1)
                return base64.b64decode(payload)
            except Exception:
                return b""
        if url.startswith(("http://", "https://")):
            try:
                with urlopen(url, timeout=5) as resp:  # noqa: S310
                    return resp.read(max_bytes)
            except Exception:
                return b""
        try:
            if url.startswith("file://"):
                from urllib.request import url2pathname

                path = Path(url2pathname(url[len("file://"):]))
            else:
                path = Path(os.path.expandvars(os.path.expanduser(url)))
            if path.is_file() and path.stat().st_size <= max_bytes:
                return path.read_bytes()
        except Exception:
            pass
        return b""

    @staticmethod
    def _jpeg_data_url(pil_image: Any) -> str:
        img = pil_image
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.thumbnail((320, 320))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=70, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode("ascii")

    def _image_thumb(self, url: str) -> str:
        if Image is None:
            return ""
        data = self._fetch_bytes(url)
        if not data:
            return ""
        try:
            return self._jpeg_data_url(Image.open(io.BytesIO(data)))
        except Exception:
            return ""

    def _video_thumb(self, url: str) -> str:
        """First-frame JPEG via the bundled ffmpeg (imageio-ffmpeg)."""
        try:
            import imageio_ffmpeg  # type: ignore[reportMissingImports]

            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return ""

        src = url
        tmp_path = ""
        try:
            if url.startswith("data:"):
                data = self._fetch_bytes(url)
                if not data:
                    return ""
                fd, tmp_path = tempfile.mkstemp(suffix=".mp4")
                with os.fdopen(fd, "wb") as fh:
                    fh.write(data)
                src = tmp_path
            elif not url.startswith(("http://", "https://")):
                path = Path(os.path.expandvars(os.path.expanduser(url.removeprefix("file://"))))
                if not path.is_file():
                    return ""
                src = str(path)
            cmd = [
                ffmpeg, "-ss", "0.5", "-i", src, "-frames:v", "1",
                "-vf", "scale=320:-2", "-f", "image2pipe", "-vcodec", "mjpeg", "-",
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=12, check=False)  # noqa: S603
            if result.returncode != 0 or not result.stdout:
                # Some clips have no frame at 0.5s; retry from the start.
                cmd[2] = "0"
                result = subprocess.run(cmd, capture_output=True, timeout=12, check=False)  # noqa: S603
            if result.returncode == 0 and result.stdout:
                return "data:image/jpeg;base64," + base64.b64encode(result.stdout).decode("ascii")
        except Exception:
            return ""
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
        return ""

    def _thumb_for(self, kind: str, url: str) -> str:
        if not url or kind == "audio":
            return ""
        cached = self._thumb_cache.get(url)
        if cached is not None:
            return cached
        thumb = self._image_thumb(url) if kind == "image" else self._video_thumb(url)
        self._thumb_cache[url] = thumb
        return thumb

    def _scan_workflow(
        self,
        prev_refs: list[dict[str, Any]] | None = None,
        generate_thumbs: bool = True,
    ) -> list[dict[str, Any]]:
        """Collect imported media assets with a STABLE order (V6 semantics).

        Thumbnails saved in ``prev_refs`` are always reused (they survive
        engine restarts / fresh node instances). ``generate_thumbs=False``
        skips generating MISSING thumbnails - used on the run path, where
        network fetches, PIL work, and ffmpeg subprocesses (video thumbs)
        would block the engine.
        """
        refs: list[dict[str, Any]] = []
        try:
            all_nodes = self._workflow_nodes()
        except Exception as exc:
            self._scan_error = f"node registry scan failed: {exc}"
            return refs
        if getattr(self, "_nodes_lookup_error", ""):
            self._scan_error = f"node registry scan failed: {self._nodes_lookup_error}"
            return refs
        self._scan_error = ""

        # Pass 1: discover assets (kind, url, identity, label) in creation order.
        discovered: list[dict[str, str]] = []
        seen_labels: set[str] = set()
        for node_name, node in all_nodes.items():
            if node is self or type(node).__name__.startswith(_SELF_CLASS_PREFIX):
                continue
            if not self._is_import_node(node):
                continue
            if node_name in seen_labels:
                continue
            primary = self._node_primary_asset(node)
            if primary is None:
                continue
            kind, url = primary
            seen_labels.add(node_name)
            discovered.append(
                {
                    "kind": kind,
                    "url": url,
                    "key": node_name,
                    "fileKey": self._identity_key(url),
                    "label": node_name,
                }
            )

        # Pass 2: keep the user's card order. Node name is the slot; filename
        # is only a fallback so a rename still updates the displayed name.
        used: set[int] = set()
        ordered: list[dict[str, str]] = []
        prev_thumbs: dict[str, str] = {}
        for ref in prev_refs or []:
            if not isinstance(ref, dict):
                continue
            label = str(ref.get("label") or "")
            key = str(ref.get("key") or "")
            thumb = str(ref.get("thumb") or "")
            if label and thumb:
                prev_thumbs[label] = thumb
            elif key and thumb:
                prev_thumbs[key] = thumb
            claimed = None
            if label:
                for index, asset in enumerate(discovered):
                    if index in used:
                        continue
                    if asset["label"] == label:
                        used.add(index)
                        claimed = asset
                        break
            if claimed is None and key:
                for index, asset in enumerate(discovered):
                    if index in used:
                        continue
                    if asset["label"] == key or asset.get("fileKey") == key:
                        used.add(index)
                        claimed = asset
                        break
            if claimed is not None:
                ordered.append(claimed)
        for index, asset in enumerate(discovered):
            if index not in used:
                ordered.append(asset)

        # Pass 3: number per kind and build the widget roster.
        counters = {"image": 0, "video": 0, "audio": 0}
        tag_prefix = {"image": "Image", "video": "Video", "audio": "Audio"}
        self._asset_urls = {}
        for asset in ordered:
            kind = asset["kind"]
            url = asset["url"]
            counters[kind] += 1
            self._asset_urls[asset["label"]] = url
            if asset["key"] and asset["key"] not in self._asset_urls:
                self._asset_urls[asset["key"]] = url
            thumb = prev_thumbs.get(asset["label"]) or prev_thumbs.get(asset.get("fileKey") or "", "")
            if not thumb and generate_thumbs:
                thumb = self._thumb_for(kind, url)
            payload_url = url
            if url.startswith("data:") and len(url) > 300_000:
                payload_url = ""
            refs.append(
                {
                    "tag": f"{tag_prefix[kind]}{counters[kind]}",
                    "kind": kind,
                    "index": counters[kind],
                    "key": asset["key"],
                    "label": asset["label"],
                    "url": payload_url,
                    "thumb": thumb,
                }
            )
        return refs

    # ------------------------------------------------------------------ entities

    @staticmethod
    def _valid_entities(state: dict[str, Any]) -> list[dict[str, Any]]:
        """Sanitized entity list: dicts with a usable name, lane, refKeys, priority."""
        raw = state.get("entities")
        if not isinstance(raw, list):
            return []
        out: list[dict[str, Any]] = []
        seen_names: set[str] = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name or not re.match(r"^[A-Za-z][\w-]{0,32}$", name):
                continue
            # Names that collide with raw tags (@Image3) would break parsing.
            if _KIND_TAG_NAME_RE.match(name):
                continue
            lowered = name.lower()
            if lowered in seen_names:
                continue
            seen_names.add(lowered)
            lane = str(item.get("lane") or "prop").strip().lower()
            if lane not in LANE_ORDER:
                lane = "prop"
            ref_keys = [str(k) for k in (item.get("refKeys") or []) if k]
            priority = "nice" if str(item.get("priority") or "") == "nice" else "must"
            out.append({"id": str(item.get("id") or name), "name": name, "lane": lane, "refKeys": ref_keys, "priority": priority})
        return out

    @staticmethod
    def _ref_by_key(refs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            for field in ("key", "label"):
                token = str(ref.get(field) or "")
                if token and token not in out:
                    out[token] = ref
        return out

    def _entity_brackets(self, entity: dict[str, Any], refs: list[dict[str, Any]]) -> list[str]:
        """Ordered bracket tags for the refs an entity currently resolves to."""
        by_key = self._ref_by_key(refs)
        tags: list[str] = []
        for key in entity.get("refKeys") or []:
            ref = by_key.get(str(key))
            if ref is None:
                continue
            kind = str(ref.get("kind") or "")
            index = int(ref.get("index") or 0)
            if kind and index:
                tags.append(f"[{kind.capitalize()} {index}]")
        return tags

    @staticmethod
    def _entity_mention_re(name: str) -> re.Pattern[str]:
        return re.compile(rf"@{re.escape(name)}(?![\w-])", re.IGNORECASE)

    def _mentioned_entities(self, text: str, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [e for e in entities if self._entity_mention_re(e["name"]).search(text or "")]

    def _expand_entities(self, text: str, entities: list[dict[str, Any]], refs: list[dict[str, Any]]) -> str:
        """Replace @EntityName mentions with the entity's bracket tags.

        Longest names first so @Maya-Night wins over @Maya. Entities whose refs
        all vanished degrade to their plain name (prompt stays readable).
        """
        out = text or ""
        for entity in sorted(entities, key=lambda e: len(e["name"]), reverse=True):
            brackets = self._entity_brackets(entity, refs)
            replacement = ", ".join(brackets) if brackets else entity["name"]
            out = self._entity_mention_re(entity["name"]).sub(replacement.replace("\\", "\\\\"), out)
        return out

    # ------------------------------------------------------------------ outputs

    def _make_artifact(self, kind: str, url: str) -> Any:
        try:
            if kind == "image" and ImageUrlArtifact is not None:
                return ImageUrlArtifact(url)
            if kind == "video" and VideoUrlArtifact is not None:
                return VideoUrlArtifact(url)
            if kind == "audio" and AudioUrlArtifact is not None:
                return AudioUrlArtifact(url)
        except Exception:
            pass
        return url

    def _node_by_label(self, label: str) -> Any:
        """The canvas node whose name is this roster label. Never filename matching."""
        want = str(label or "").strip()
        if not want:
            return None
        try:
            nodes = self._workflow_nodes()
        except Exception:
            return None
        if want in nodes:
            return nodes[want]
        lowered = want.lower()
        for name, node in nodes.items():
            if str(name).strip().lower() == lowered:
                return node
            if str(getattr(node, "name", "")).strip().lower() == lowered:
                return node
        return None

    def _ref_full_url(self, ref: dict[str, Any]) -> str:
        label = str(ref.get("label") or "")
        if label and label in self._asset_urls:
            return self._asset_urls[label]
        return str(ref.get("url") or "")

    def _refs_for_send(self, widget_refs: list[Any]) -> list[dict[str, Any]]:
        """Keep the roster tag numbers the user sees; refresh files from those nodes.

        Never rematch by filename. Shared basenames packed the wrong Load node.
        """
        discovered: list[dict[str, str]] = []
        try:
            all_nodes = self._workflow_nodes()
        except Exception:
            all_nodes = {}
        for node_name, node in all_nodes.items():
            if node is self or type(node).__name__.startswith(_SELF_CLASS_PREFIX):
                continue
            if not self._is_import_node(node):
                continue
            primary = self._node_primary_asset(node)
            if primary is None:
                continue
            kind, url = primary
            discovered.append(
                {
                    "kind": kind,
                    "url": url,
                    "key": node_name,
                    "fileKey": self._identity_key(url),
                    "label": node_name,
                }
            )
        by_label = {asset["label"]: asset for asset in discovered}
        by_label_ci = {str(asset["label"]).strip().lower(): asset for asset in discovered}

        prefix = {"image": "Image", "video": "Video", "audio": "Audio"}
        refs: list[dict[str, Any]] = []
        self._asset_urls = {}
        for raw in widget_refs or []:
            if not isinstance(raw, dict):
                continue
            ref = dict(raw)
            label = str(ref.get("label") or "")
            asset = by_label.get(label) if label else None
            if asset is None and label:
                asset = by_label_ci.get(label.strip().lower())
            if asset is not None:
                ref["label"] = asset["label"]
                ref["key"] = asset["key"]
                ref["url"] = asset["url"]
                ref["kind"] = asset["kind"]
                self._asset_urls[asset["label"]] = asset["url"]
            kind = str(ref.get("kind") or "image")
            try:
                index = int(ref.get("index") or 0)
            except Exception:
                index = 0
            if index <= 0:
                continue
            ref["index"] = index
            ref["kind"] = kind
            ref["tag"] = f"{prefix.get(kind, kind.capitalize())}{index}"
            refs.append(ref)
        return refs

    @staticmethod
    def _value_url(value: Any) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            for key in ("value", "url", "uri"):
                inner = value.get(key)
                if isinstance(inner, str) and inner.strip():
                    return inner.strip()
            return ""
        inner = getattr(value, "value", None)
        if isinstance(inner, str) and inner.strip():
            return inner.strip()
        return ""

    def _live_media_value(self, ref: dict[str, Any], kind: str) -> Any:
        """A new artifact for the Seedance slot, not the source node's output object.

        PSD Flatten publishes an output-only image. Reusing that object keeps the
        reference slot linked, so a later send does not delete it.
        """
        keys = {
            "image": ("image", "output_image", "output", "image_path"),
            "video": ("video", "output_video", "output"),
            "audio": ("audio", "output_audio", "audio_file", "file", "output"),
        }.get(kind, (kind,))
        src = self._node_by_label(str(ref.get("label") or ""))
        url = ""
        if src is not None:
            for store in (
                getattr(src, "parameter_output_values", {}) or {},
                getattr(src, "parameter_values", {}) or {},
            ):
                for key in keys:
                    found = self._value_url(store.get(key))
                    if found:
                        url = found
                        break
                if url:
                    break
        if not url:
            url = self._ref_full_url(ref)
        return self._make_artifact(kind, url) if url else None

    def _media_list_param(self, node: Any, names: tuple[str, ...]) -> Any:
        """A ParameterList on the target matching one of ``names``, if any."""
        for name in names:
            try:
                param = node.get_parameter_by_name(name)
            except Exception:
                param = None
            if param is None:
                continue
            if (
                type(param).__name__ == "ParameterList"
                or callable(getattr(param, "add_child_parameter", None))
                or callable(getattr(param, "get_child_parameters", None))
            ):
                return param
        return None

    def _publish_outputs(self, refs: list[dict[str, Any]]) -> None:
        """Emit ordered lists plus per-tag fallback outputs (image_1, image_2, ...)."""
        buckets: dict[str, list[Any]] = {"image": [], "video": [], "audio": []}
        desired: dict[str, Any] = {}
        for ref in refs:
            kind = str(ref.get("kind") or "")
            if kind not in buckets:
                continue
            url = self._ref_full_url(ref)
            if not url:
                continue
            artifact = self._make_artifact(kind, url)
            buckets[kind].append(artifact)
            desired[f"{kind}_{int(ref.get('index') or 0)}"] = artifact
        try:
            self.parameter_output_values["reference_images"] = buckets["image"]
            self.parameter_output_values["reference_videos"] = buckets["video"]
            self.parameter_output_values["reference_audio"] = buckets["audio"]
        except Exception:
            pass

        out_types = {"image": "ImageUrlArtifact", "video": "VideoUrlArtifact", "audio": "str"}
        for name, artifact in desired.items():
            kind, num = name.split("_", 1)
            display = f"@{kind.capitalize()}{num}"
            existing = self.get_parameter_by_name(name)
            if existing is None:
                try:
                    self.add_parameter(
                        Parameter(
                            name=name,
                            output_type=out_types.get(kind, "str"),
                            tooltip=f"{display}: always the asset currently holding this tag (manual-wiring fallback).",
                            allowed_modes={ParameterMode.OUTPUT},
                            settable=False,
                            user_defined=True,
                            ui_options={"display_name": display, "hide": True, "hide_property": True},
                        )
                    )
                except Exception:
                    continue
            else:
                try:
                    ui = dict(existing.ui_options or {})
                    if not ui.get("hide"):
                        ui["hide"] = True
                        ui["hide_property"] = True
                        existing.ui_options = ui
                except Exception:
                    pass
            try:
                self.parameter_output_values[name] = artifact
            except Exception:
                pass
        try:
            for param in list(self.root_ui_element.find_elements_by_type(Parameter)):
                if _TAG_PARAM_RE.match(param.name) and param.name not in desired:
                    try:
                        if param.name in self.parameter_output_values:
                            del self.parameter_output_values[param.name]
                    except Exception:
                        pass
                    try:
                        self.remove_parameter_element(param)
                    except Exception:
                        pass
        except Exception:
            pass

    # ------------------------------------------------------------------ send to Seedance

    @staticmethod
    def _engine() -> Any:
        if GriptapeNodes is not None:
            return GriptapeNodes
        try:
            from griptape_nodes.retained_mode.griptape_nodes import (  # type: ignore[reportMissingImports]
                GriptapeNodes as engine,
            )
        except Exception:
            return None
        return engine

    @staticmethod
    def _nonce_int(value: Any) -> int:
        try:
            return int(value or 0)
        except Exception:
            return 0

    def _dispatch(self, request: Any) -> Any:
        """Route a retained-mode request through GriptapeNodes so the editor updates.

        Prefer the singleton facade first (same path V5 uses). ``self.engine``
        can apply the change locally without broadcasting to the open UI.
        """
        handles: list[Any] = []
        facade = self._engine()
        if facade is not None:
            handles.append(getattr(facade, "handle_request", None))
        try:
            eng = getattr(self, "engine", None)
            if eng is not None and eng is not facade:
                handles.append(getattr(eng, "handle_request", None))
        except Exception:
            pass
        last_err: Exception | None = None
        for handle in handles:
            if not callable(handle):
                continue
            try:
                return handle(request)
            except Exception as exc:
                last_err = exc
                continue
        if last_err is not None:
            raise last_err
        raise RuntimeError("engine handle_request unavailable")

    def _set_on_node(self, node: Any, param: str, value: Any) -> None:
        """Write a parameter on another canvas node so the editor sees it live.

        Local ``parameter_values`` writes persist after a full GTN refresh but
        do not notify the UI. The engine SetParameterValueRequest is what
        actually refreshes reference lists / prompt on the open node.
        """
        if node.get_parameter_by_name(param) is None:
            raise RuntimeError(f"parameter '{param}' not found on {getattr(node, 'name', '?')}")
        errors: list[str] = []
        wrote = False
        try:
            from griptape_nodes.retained_mode.events.parameter_events import (  # type: ignore[reportMissingImports]
                SetParameterValueRequest,
            )

            result = self._dispatch(
                SetParameterValueRequest(
                    parameter_name=param, node_name=getattr(node, "name", ""), value=value
                )
            )
            if hasattr(result, "failed") and result.failed():
                details = getattr(result, "result_details", "") or ""
                errors.append(details or "SetParameterValue failed")
            else:
                wrote = True
        except Exception as exc:
            errors.append(str(exc))
        setter = getattr(node, "set_parameter_value", None)
        if callable(setter):
            try:
                setter(param, value)
                wrote = True
            except Exception as exc:
                errors.append(str(exc))
        try:
            node.parameter_values[param] = value
            wrote = True
        except Exception as exc:
            errors.append(str(exc))
        try:
            node.parameter_output_values[param] = value
        except Exception:
            pass
        try:
            publish = getattr(node, "publish_update_to_parameter", None)
            if callable(publish):
                publish(param, value)
        except Exception:
            pass
        try:
            emit = getattr(node, "_emit_parameter_lifecycle_event", None)
            param_obj = node.get_parameter_by_name(param)
            if param_obj is not None and callable(emit):
                emit(param_obj)
        except Exception:
            pass
        if wrote:
            return
        raise RuntimeError(f"could not set '{param}': " + "; ".join(e for e in errors if e))

    def _nudge_node_ui(self, node: Any, container_name: str = "") -> None:
        """Force the open editor to redraw list slots on the target node."""
        if not container_name:
            return
        param = node.get_parameter_by_name(container_name)
        if param is None:
            return
        ui = dict(getattr(param, "ui_options", None) or {})
        ui["_omniRev"] = int(ui.get("_omniRev") or 0) + 1
        tooltip = getattr(param, "tooltip", None) or "References"
        try:
            from griptape_nodes.retained_mode.events.parameter_events import (  # type: ignore[reportMissingImports]
                AlterParameterDetailsRequest,
            )

            self._dispatch(
                AlterParameterDetailsRequest(
                    parameter_name=container_name,
                    node_name=getattr(node, "name", ""),
                    ui_options=ui,
                    tooltip=tooltip,
                )
            )
        except Exception:
            try:
                param.ui_options = ui
            except Exception:
                pass
        emit = getattr(node, "emit_parameter_changes", None)
        if callable(emit):
            try:
                emit()
            except Exception:
                pass

    def _node_by_name(self, name: str) -> Any:
        if not name:
            return None
        engine = self._engine()
        if engine is None:
            return None
        try:
            return engine.ObjectManager().attempt_get_object_by_name_as_type(name, BaseNode)
        except Exception:
            return None

    def _schedule_list_refresh(self, node_name: str, container_name: str) -> None:
        """Redraw a reference list after this send has finished.

        The editor fetches the node while the send is still running and can
        paint the list from before the delete landed. A later refresh reads
        the committed children.
        """
        if not node_name or not container_name:
            return
        key = (node_name, container_name)
        gens = getattr(self, "_list_refresh_gens", None)
        if not isinstance(gens, dict):
            gens = {}
            self._list_refresh_gens = gens
        gens[key] = int(gens.get(key, 0) or 0) + 1
        expected = gens[key]
        timers = getattr(self, "_list_refresh_timers", None)
        if not isinstance(timers, dict):
            timers = {}
            self._list_refresh_timers = timers
        for old in list(timers.get(key) or []):
            try:
                old.cancel()
            except Exception:
                pass
        bucket: list[Any] = []
        timers[key] = bucket

        def fire(expected_gen: int = expected, refresh_key: tuple[str, str] = key) -> None:
            current = getattr(self, "_list_refresh_gens", None)
            if not isinstance(current, dict) or int(current.get(refresh_key, 0) or 0) != expected_gen:
                return
            node = self._node_by_name(refresh_key[0])
            if node is None:
                return
            try:
                self._nudge_node_ui(node, refresh_key[1])
            except Exception:
                pass

        for delay in (0.45, 1.15):
            timer = threading.Timer(delay, fire)
            timer.daemon = True
            bucket.append(timer)
            timer.start()

    def _list_children(self, container: Any) -> list[Any]:
        getter = getattr(container, "get_child_parameters", None)
        if callable(getter):
            try:
                kids = list(getter())
                if kids:
                    return kids
            except Exception:
                pass
        try:
            return list(container.find_elements_by_type(Parameter, find_recursively=False))
        except Exception:
            return []

    def _slot_params(self, node: Any, container: Any, container_name: str) -> list[Any]:
        """ParameterList children plus numbered siblings like reference_images_1."""
        by_name: dict[str, Any] = {}
        for kid in self._list_children(container):
            name = str(getattr(kid, "name", "") or "")
            if name:
                by_name[name] = kid
        prefix = str(container_name or "").rstrip("_") + "_"
        params: list[Any] = []
        try:
            params = list(getattr(node, "parameters", None) or [])
        except Exception:
            params = []
        if not params:
            try:
                params = list(node.find_elements_by_type(Parameter, find_recursively=False))
            except Exception:
                params = []
        numbered: list[tuple[int, Any]] = []
        for param in params:
            name = str(getattr(param, "name", "") or "")
            if name.startswith(prefix) and name[len(prefix) :].isdigit():
                by_name[name] = param
                numbered.append((int(name[len(prefix) :]), param))
        kids = self._list_children(container)
        if kids:
            return kids
        if numbered:
            numbered.sort(key=lambda item: item[0])
            return [item[1] for item in numbered]
        return list(by_name.values())

    def _disconnect_parameters(self, node: Any, names: set[str]) -> None:
        """Drop wires into these parameters so a cleared list can actually shrink."""
        names = {name for name in names if name}
        if not names:
            return
        try:
            from griptape_nodes.retained_mode.events.connection_events import (  # type: ignore[reportMissingImports]
                DeleteConnectionRequest,
                ListConnectionsForNodeRequest,
            )
        except Exception:
            return
        try:
            listed = self._dispatch(ListConnectionsForNodeRequest(node_name=getattr(node, "name", "")))
        except Exception:
            return
        node_name = getattr(node, "name", "")
        for conn in list(getattr(listed, "incoming_connections", None) or []):
            target = str(getattr(conn, "target_parameter_name", "") or "")
            if target not in names:
                continue
            try:
                self._dispatch(
                    DeleteConnectionRequest(
                        source_node_name=getattr(conn, "source_node_name", None),
                        source_parameter_name=getattr(conn, "source_parameter_name", ""),
                        target_node_name=node_name,
                        target_parameter_name=target,
                    )
                )
            except Exception:
                pass
        for conn in list(getattr(listed, "outgoing_connections", None) or []):
            source = str(getattr(conn, "source_parameter_name", "") or "")
            if source not in names:
                continue
            try:
                self._dispatch(
                    DeleteConnectionRequest(
                        source_node_name=node_name,
                        source_parameter_name=source,
                        target_node_name=getattr(conn, "target_node_name", None),
                        target_parameter_name=getattr(conn, "target_parameter_name", ""),
                    )
                )
            except Exception:
                pass

    def _disconnect_slot(self, node: Any, param_name: str) -> None:
        self._disconnect_parameters(node, {param_name})

    def _drop_stored_value(self, node: Any, name: str) -> None:
        if not name:
            return
        for bag_name in ("parameter_values", "parameter_output_values"):
            bag = getattr(node, bag_name, None)
            if not isinstance(bag, dict) or name not in bag:
                continue
            try:
                del bag[name]
            except Exception:
                pass

    def _remove_list_slot(self, node: Any, container: Any, child: Any) -> bool:
        """Drop one extra list child so the editor loses the slot."""
        name = str(getattr(child, "name", "") or "")
        container_name = str(getattr(container, "name", "") or "")
        before = len(self._slot_params(node, container, container_name))
        if name:
            self._disconnect_slot(node, name)
            try:
                child.user_defined = True
            except Exception:
                pass
            try:
                from griptape_nodes.retained_mode.events.parameter_events import (  # type: ignore[reportMissingImports]
                    RemoveParameterFromNodeRequest,
                )

                result = self._dispatch(
                    RemoveParameterFromNodeRequest(
                        parameter_name=name, node_name=getattr(node, "name", "")
                    )
                )
                if hasattr(result, "failed") and result.failed():
                    self._last_slot_remove_error = str(getattr(result, "result_details", "") or "remove refused")
                elif len(self._slot_params(node, container, container_name)) < before:
                    self._drop_stored_value(node, name)
                    return True
            except Exception as exc:
                self._last_slot_remove_error = str(exc)
        for method_name in ("remove_last_child_parameter", "remove_child_parameter"):
            fn = getattr(container, method_name, None)
            if not callable(fn):
                continue
            try:
                if method_name == "remove_last_child_parameter":
                    fn()
                else:
                    fn(child)
            except Exception:
                continue
            if len(self._slot_params(node, container, container_name)) < before:
                self._drop_stored_value(node, name)
                return True
        if name:
            for method_name in ("remove_parameter", "remove_parameter_element"):
                fn = getattr(node, method_name, None)
                if not callable(fn):
                    continue
                try:
                    fn(child)
                except Exception:
                    try:
                        fn(name)
                    except Exception:
                        continue
                if len(self._slot_params(node, container, container_name)) < before:
                    self._drop_stored_value(node, name)
                    return True
        return len(self._slot_params(node, container, container_name)) < before

    def _wired_into(self, node: Any, container_name: str) -> set[str]:
        """Parameter names wired to this list or to one of its slots."""
        prefix = f"{container_name}_"
        found: set[str] = set()
        try:
            from griptape_nodes.retained_mode.events.connection_events import (  # type: ignore[reportMissingImports]
                ListConnectionsForNodeRequest,
            )
        except Exception:
            return found
        try:
            listed = self._dispatch(ListConnectionsForNodeRequest(node_name=getattr(node, "name", "")))
        except Exception:
            return found
        for conn in list(getattr(listed, "incoming_connections", None) or []):
            target = str(getattr(conn, "target_parameter_name", "") or "")
            if target == container_name or target.startswith(prefix):
                found.add(target)
        for conn in list(getattr(listed, "outgoing_connections", None) or []):
            source = str(getattr(conn, "source_parameter_name", "") or "")
            if source == container_name or source.startswith(prefix):
                found.add(source)
        return found

    def _wipe_list(self, node: Any, container: Any, container_name: str) -> None:
        """Remove every child and any wire into the list itself."""
        names = {container_name}
        for child in self._slot_params(node, container, container_name):
            child_name = str(getattr(child, "name", "") or "")
            if child_name:
                names.add(child_name)
        names.update(self._wired_into(node, container_name))
        self._disconnect_parameters(node, names)
        killer = getattr(node, "kill_parameter_children", None)
        if callable(killer):
            try:
                killer(container)
            except Exception:
                pass
        for child in list(self._slot_params(node, container, container_name)):
            self._remove_list_slot(node, container, child)
        clearer = getattr(container, "clear_list", None)
        if callable(clearer):
            try:
                clearer()
            except Exception:
                pass
        self._disconnect_parameters(node, {container_name})
        self._drop_stored_value(node, container_name)

    def _trim_container(self, node: Any, container: Any, container_name: str, keep: int) -> list[str]:
        """Delete leftover list slots until the target has exactly ``keep`` items.

        Do not call ParameterList.ensure_length first: that shrinks the Python
        object without telling the editor, so leftover slots stay on screen
        until a full GTN refresh.
        """
        warnings: list[str] = []
        self._last_slot_remove_error = ""
        if keep <= 0:
            self._wipe_list(node, container, container_name)
        guard = 0
        while guard < 40:
            guard += 1
            slots = self._slot_params(node, container, container_name)
            if len(slots) <= keep:
                break
            extra = slots[-1]
            if self._remove_list_slot(node, container, extra):
                continue
            # Same removal clear-all uses. The engine often refuses to delete
            # one list child, which is why 11 stays 11 until every slot is cleared.
            try:
                extra.user_defined = True
            except Exception:
                pass
            try:
                container.remove_child(extra)
            except Exception:
                pass
            self._drop_stored_value(node, str(getattr(extra, "name", "") or ""))
            if len(self._slot_params(node, container, container_name)) < len(slots):
                continue
            if keep <= 0:
                self._wipe_list(node, container, container_name)
                if len(self._slot_params(node, container, container_name)) <= keep:
                    break
            detail = str(getattr(self, "_last_slot_remove_error", "") or "").strip()
            msg = f"{getattr(node, 'name', '?')}.{container_name}: leftover slot could not be deleted"
            if detail:
                msg += f" ({detail})"
            warnings.append(msg)
            break
        if keep <= 0:
            self._drop_stored_value(node, container_name)
            left = len(self._slot_params(node, container, container_name))
            if left:
                warnings.append(
                    f"{getattr(node, 'name', '?')}.{container_name}: {left} slot(s) still present after clear."
                )
        return warnings


    def _register_list_child(self, node: Any, child: Any) -> None:
        name = getattr(child, "name", None)
        if not name:
            return
        if node.get_parameter_by_name(name) is not None:
            return
        adder = getattr(node, "add_parameter", None)
        if callable(adder):
            try:
                adder(child)
            except Exception:
                pass

    def _add_list_slot(self, node: Any, container: Any, container_name: str) -> bool:
        """Grow one ParameterList child through the engine so the editor shows it."""
        before = len(self._slot_params(node, container, container_name))
        try:
            from griptape_nodes.retained_mode.events.parameter_events import (  # type: ignore[reportMissingImports]
                AddParameterToNodeRequest,
            )

            result = self._dispatch(
                AddParameterToNodeRequest(
                    node_name=getattr(node, "name", None),
                    parent_container_name=container_name,
                )
            )
            if not (hasattr(result, "failed") and result.failed()):
                if len(self._slot_params(node, container, container_name)) > before:
                    return True
        except Exception:
            pass
        child = None
        for method_name in ("add_child_parameter", "append_child_parameter"):
            fn = getattr(container, method_name, None)
            if not callable(fn):
                continue
            try:
                child = fn()
                break
            except Exception:
                child = None
        if child is not None:
            self._register_list_child(node, child)
        return len(self._slot_params(node, container, container_name)) > before

    def _sanitize_composer_callbacks(self) -> None:
        """Drop None converters/validators the updated engine tries to call on composer."""
        parameter = self.get_parameter_by_name("composer")
        if parameter is None:
            return
        try:
            from griptape_nodes.exe_types.core_types import Trait as TraitType
        except Exception:
            try:
                from griptape_nodes.exe_types.elements.trait import Trait as TraitType
            except Exception:
                TraitType = None  # type: ignore[assignment]
        if TraitType is not None:
            try:
                for trait in parameter.find_elements_by_type(TraitType):
                    orig_c = getattr(trait, "converters_for_trait", None)
                    if not callable(orig_c):
                        trait.converters_for_trait = lambda: []  # type: ignore[method-assign]
                    else:
                        def _safe_converters(fn=orig_c) -> list:
                            try:
                                result = fn()
                            except Exception:
                                return []
                            return [c for c in (result or []) if callable(c)]

                        trait.converters_for_trait = _safe_converters  # type: ignore[method-assign]
                    orig_v = getattr(trait, "validators_for_trait", None)
                    if not callable(orig_v):
                        trait.validators_for_trait = lambda: []  # type: ignore[method-assign]
                    else:
                        def _safe_validators(fn=orig_v) -> list:
                            try:
                                result = fn()
                            except Exception:
                                return []
                            return [v for v in (result or []) if callable(v)]

                        trait.validators_for_trait = _safe_validators  # type: ignore[method-assign]
            except Exception:
                pass
        convs = getattr(parameter, "_converters", None)
        if isinstance(convs, list):
            parameter._converters = [c for c in convs if callable(c)]
        vals = getattr(parameter, "_validators", None)
        if isinstance(vals, list):
            parameter._validators = [v for v in vals if callable(v)]

    def _workflow_nodes(self) -> dict[str, Any]:
        """Canvas BaseNodes. Prefer the node's Engine.object_manager (new GT engine)."""
        self._nodes_lookup_error = ""
        mgr: Any = None
        try:
            eng = getattr(self, "engine", None)
            mgr = getattr(eng, "object_manager", None) if eng is not None else None
        except Exception as exc:
            self._nodes_lookup_error = str(exc)
            mgr = None
        if mgr is None:
            engine = self._engine()
            try:
                if engine is not None:
                    inst = None
                    try:
                        inst = engine() if callable(engine) else engine
                    except Exception:
                        inst = engine
                    mgr = getattr(inst, "object_manager", None)
                    if mgr is None:
                        getter = getattr(engine, "ObjectManager", None)
                        if callable(getter):
                            mgr = getter()
            except Exception as exc:
                self._nodes_lookup_error = str(exc)
                mgr = None
        try:
            subset = getattr(mgr, "get_filtered_subset", None)
            if not callable(subset):
                if not self._nodes_lookup_error:
                    self._nodes_lookup_error = "object_manager.get_filtered_subset is missing"
                return {}
            found = subset(type=BaseNode)
            return dict(found) if isinstance(found, dict) else {}
        except Exception as exc:
            self._nodes_lookup_error = str(exc)
            return {}

    def _find_seedance_nodes(self) -> list[Any]:
        """Every node in the workflow that looks like a Seedance generator.

        Two match paths so BOTH Seedance 2.0 and 2.5 are detected:
        * class name contains "Seedance" and the node has a ``prompt`` plus
          any reference input (2.0 fixed slots or 2.5 lists), or
        * the classic 2.0 parameter signature (reference_images + prompt +
          input_mode) for generators not named "Seedance".
        """
        try:
            all_nodes = self._workflow_nodes()
        except Exception:
            return []
        found: list[Any] = []
        for _name, node in all_nodes.items():
            cls_name = type(node).__name__
            if node is self or cls_name.startswith(_SELF_CLASS_PREFIX):
                continue
            if self._is_node_group(node):
                continue
            try:
                has_prompt = node.get_parameter_by_name("prompt") is not None
                if not has_prompt:
                    continue
                has_ref_list = (
                    node.get_parameter_by_name("reference_images") is not None
                    or node.get_parameter_by_name("reference_videos") is not None
                    or node.get_parameter_by_name("reference_video_1") is not None
                )
                if "seedance" in cls_name.lower():
                    if has_ref_list or node.get_parameter_by_name("first_frame") is not None:
                        found.append(node)
                    continue
                if has_ref_list and node.get_parameter_by_name("input_mode") is not None:
                    found.append(node)
            except Exception:
                continue
        return found

    @staticmethod
    def _is_node_group(node: Any) -> bool:
        """True for Griptape canvas groups (regular / subflow / iterative)."""
        if node is None:
            return False
        cls = type(node).__name__
        if cls in ("BaseNodeGroup", "NodeGroupNode", "NodeGroup", "SubflowNodeGroup"):
            return True
        if "NodeGroup" in cls or cls.endswith("Group"):
            nodes_dict = getattr(node, "nodes", None)
            if isinstance(nodes_dict, dict):
                return True
        try:
            metadata = getattr(node, "metadata", None) or {}
            if isinstance(metadata, dict) and metadata.get("is_node_group"):
                return True
        except Exception:
            pass
        return False

    @staticmethod
    def _group_kind(node: Any) -> str:
        """'regular' for organizational groups; 'subflow' when the group itself executes."""
        try:
            metadata = getattr(node, "metadata", None) or {}
            if isinstance(metadata, dict) and metadata.get("executable"):
                return "subflow"
        except Exception:
            pass
        cls = type(node).__name__
        if "Subflow" in cls or "Iterative" in cls:
            return "subflow"
        return "regular"

    @staticmethod
    def _group_member_names(group: Any) -> list[str]:
        names: list[str] = []
        nodes_dict = getattr(group, "nodes", None)
        if isinstance(nodes_dict, dict):
            names.extend(str(n) for n in nodes_dict.keys())
        try:
            metadata = getattr(group, "metadata", None) or {}
            extra = metadata.get("node_names_in_group") if isinstance(metadata, dict) else None
            if isinstance(extra, list):
                names.extend(str(n) for n in extra if n)
        except Exception:
            pass
        seen: set[str] = set()
        out: list[str] = []
        for name in names:
            if name and name not in seen:
                seen.add(name)
                out.append(name)
        return out

    def _expand_group_members(self, group: Any, all_nodes: dict[str, Any], seen: set[str] | None = None) -> list[str]:
        """Member node names, expanding nested groups."""
        walking = set() if seen is None else set(seen)
        walking.add(getattr(group, "name", "") or "")
        names: list[str] = []
        found: set[str] = set()
        for name in self._group_member_names(group):
            if name in walking or name in found:
                continue
            member = all_nodes.get(name)
            if member is not None and self._is_node_group(member):
                for nested in self._expand_group_members(member, all_nodes, walking):
                    if nested not in found:
                        found.add(nested)
                        names.append(nested)
            else:
                found.add(name)
                names.append(name)
        return names

    def _find_groups(self) -> list[dict[str, Any]]:
        """Canvas groups that contain at least one Seedance target."""
        try:
            all_nodes = self._workflow_nodes()
        except Exception:
            return []
        targets = self._find_seedance_nodes()
        target_names = {getattr(n, "name", "") for n in targets}
        groups: list[dict[str, Any]] = []
        seen_names: set[str] = set()
        for name, node in all_nodes.items():
            if not self._is_node_group(node):
                continue
            members = [m for m in self._expand_group_members(node, all_nodes) if m in target_names]
            for target in targets:
                parent = getattr(target, "parent_group", None)
                parent_name = getattr(parent, "name", "") if parent is not None else ""
                tname = getattr(target, "name", "")
                if parent_name == name and tname and tname not in members:
                    members.append(tname)
            if not members:
                continue
            seen_names.add(name)
            groups.append({"name": name, "kind": self._group_kind(node), "members": members})

        for target in targets:
            parent = getattr(target, "parent_group", None)
            if parent is None:
                continue
            parent_name = getattr(parent, "name", "") or ""
            if not parent_name or parent_name in seen_names:
                continue
            members: list[str] = []
            for other in targets:
                other_parent = getattr(other, "parent_group", None)
                other_parent_name = getattr(other_parent, "name", "") if other_parent is not None else ""
                other_name = getattr(other, "name", "")
                if other_parent_name == parent_name and other_name:
                    members.append(other_name)
            if not members:
                continue
            seen_names.add(parent_name)
            groups.append(
                {
                    "name": parent_name,
                    "kind": self._group_kind(parent),
                    "members": members,
                }
            )

        groups.sort(key=lambda g: str(g.get("name") or "").lower())
        return groups

    def _select_send_targets(self, state: dict[str, Any], targets: list[Any]) -> list[Any]:
        pick = str(state.get("sendTarget") or "all")
        if pick == "all" or not pick:
            return targets
        if pick.startswith(_GROUP_TARGET_PREFIX):
            group_name = pick[len(_GROUP_TARGET_PREFIX) :]
            member_names: set[str] = set()
            for group in self._find_groups():
                if str(group.get("name") or "") == group_name:
                    member_names = {str(m) for m in (group.get("members") or [])}
                    break
            return [n for n in targets if getattr(n, "name", "") in member_names]
        return [n for n in targets if getattr(n, "name", "") == pick]

    def _fill_container(self, node: Any, container_name: str, values: list[Any]) -> list[str]:
        """Grow/shrink a target ParameterList and set its children in order.

        Extra slots from a previous send are removed.
        """
        warnings: list[str] = []
        container = node.get_parameter_by_name(container_name)
        if container is None:
            if values:
                warnings.append(f"{node.name}: no '{container_name}' list to fill.")
            return warnings

        for child in self._slot_params(node, container, container_name):
            self._register_list_child(node, child)

        # Drop extras before writing. A wire into the list keeps the previous
        # full set on screen, so removing 1 of 11 still shows 11, and slot 1
        # stays on the file that was just taken out of the prompt.
        if len(self._slot_params(node, container, container_name)) > len(values):
            self._disconnect_parameters(node, {container_name})
        warnings.extend(self._trim_container(node, container, container_name, len(values)))

        guard = 0
        while len(self._slot_params(node, container, container_name)) < len(values) and guard < max(40, len(values) + 2):
            guard += 1
            if not self._add_list_slot(node, container, container_name):
                break

        kids = self._slot_params(node, container, container_name)
        filled = 0
        slot_errors: list[str] = []
        for i, value in enumerate(values):
            slot_name = f"{container_name}_{i + 1}"
            target = node.get_parameter_by_name(slot_name)
            if target is None and i < len(kids):
                target = kids[i]
            if target is None:
                break
            self._disconnect_slot(node, str(getattr(target, "name", "") or ""))
            try:
                self._set_on_node(node, target.name, value)
                filled += 1
            except Exception as exc:
                slot_errors.append(str(exc))
        if values:
            try:
                node.parameter_values[container_name] = list(values)
            except Exception:
                pass
        else:
            self._drop_stored_value(node, container_name)
        self._schedule_list_refresh(str(getattr(node, "name", "") or ""), container_name)
        if values and filled == 0:
            extra = f" ({slot_errors[0]})" if slot_errors else ""
            warnings.append(
                f"{node.name}.{container_name}: could not fill {len(values)} file slot(s){extra}."
            )
        elif values and filled < len(values):
            warnings.append(
                f"{node.name}.{container_name}: filled {filled} of {len(values)} file slot(s)."
            )
        return warnings

    @staticmethod
    def _show_parameters(node: Any, names: list[str]) -> None:
        """Unhide inputs. 2.0 keeps references hidden until multimodal mode is on."""
        show = getattr(node, "show_parameter_by_name", None)
        if not callable(show):
            return
        try:
            show(names)
            return
        except Exception:
            pass
        for name in names:
            try:
                show(name)
            except Exception:
                pass

    def _seedance_family(self, node: Any) -> str:
        """``20`` for the Seedance 2.0 generator, ``25`` for the list-based 2.5 node.

        2.0 has ``input_mode`` and fixed ``reference_video_1`` .. ``reference_video_3``.
        2.5 has a ``task`` dropdown and a ``reference_videos`` list. A class name
        that says 2.0 wins over a shared parameter, so a subclass of the 2.0
        node is not treated as 2.5.
        """
        names = [type(node).__name__]
        try:
            names.extend(base.__name__ for base in type(node).__mro__)
        except Exception:
            pass
        cls = " ".join(names).lower().replace("_", "")
        if "seedance20" in cls or "seedance2.0" in cls:
            return "20"
        if any(token in cls for token in ("seedance25", "seedance22", "seedance2.5", "seedance2.2")):
            return "25"
        try:
            has_video_list = node.get_parameter_by_name("reference_videos") is not None
            has_task = node.get_parameter_by_name("task") is not None
            has_input_mode = node.get_parameter_by_name("input_mode") is not None
            has_fixed_video = node.get_parameter_by_name("reference_video_1") is not None
        except Exception:
            return "25"
        if has_video_list or (has_task and not has_input_mode):
            return "25"
        if has_input_mode or has_fixed_video:
            return "20"
        return "25"

    def _caps_for_node(self, node: Any, image_budget: int) -> dict[str, Any]:
        """Slot caps for this generator. The image budget can only lower the ceiling."""
        family = self._seedance_family(node)
        if family == "20":
            image_max, video_max, audio_max = MAX_IMAGE_SLOTS_20, MAX_VIDEO_SLOTS_20, MAX_AUDIO_SLOTS_20
        else:
            image_max, video_max, audio_max = MAX_IMAGE_SLOTS, MAX_VIDEO_SLOTS, MAX_AUDIO_SLOTS
        try:
            image_budget = int(image_budget)
        except Exception:
            image_budget = image_max
        return {
            "family": family,
            "label": "2.0" if family == "20" else "2.5",
            "image": max(1, min(image_max, image_budget)),
            "video": video_max,
            "audio": audio_max,
        }

    def _target_profiles(self) -> list[dict[str, Any]]:
        profiles: list[dict[str, Any]] = []
        for node in self._find_seedance_nodes():
            caps = self._caps_for_node(node, MAX_IMAGE_SLOTS)
            profiles.append(
                {
                    "name": getattr(node, "name", ""),
                    "family": caps["family"],
                    "label": caps["label"],
                    "imageCap": caps["image"],
                    "videoCap": caps["video"],
                    "audioCap": caps["audio"],
                }
            )
        return profiles

    def _reveal_reference_inputs(self, node: Any, family: str, has_media: bool) -> list[str]:
        """Switch the generator into reference mode and unhide the inputs we are about to fill."""
        warnings: list[str] = []
        if family == "20":
            if node.get_parameter_by_name("input_mode") is not None:
                try:
                    self._set_on_node(node, "input_mode", INPUT_MODE_MULTIMODAL)
                except Exception as exc:
                    warnings.append(f"{node.name}.input_mode: {exc}")
            updater = getattr(node, "_update_parameter_visibility", None)
            if callable(updater):
                try:
                    updater()
                except Exception:
                    pass
            self._show_parameters(node, ["reference_images", "reference_audio", "reference_video_1"])
            return warnings

        if has_media and node.get_parameter_by_name("task") is not None:
            try:
                current_task = str(node.get_parameter_value("task") or "")
            except Exception:
                current_task = ""
            if current_task in ("", "Text to Video"):
                try:
                    self._set_on_node(node, "task", TASK_REFERENCE_TO_VIDEO)
                except Exception as exc:
                    warnings.append(f"{node.name}.task: {exc}")
            updater = getattr(node, "_update_parameter_visibility", None)
            if callable(updater):
                try:
                    updater()
                except Exception:
                    pass
        self._show_parameters(node, ["reference_images", "reference_videos", "reference_audio"])
        return warnings

    def _values_for_kind(self, refs: list[dict[str, Any]], kind: str, limit: int) -> list[Any]:
        values = [
            v
            for v in (
                self._live_media_value(ref, kind)
                for ref in refs
                if str(ref.get("kind")) == kind
            )
            if v not in (None, "")
        ]
        return values[: max(0, limit)]

    def _push_fixed_videos(self, node: Any, values: list[Any], limit: int) -> list[str]:
        """Write Seedance 2.0's ``reference_video_1`` .. ``reference_video_3``.

        Slots 2 and 3 are created hidden and only shown once the previous slot
        has a value. Set, then refresh visibility, then set the next slot.
        """
        warnings: list[str] = []
        refresh = getattr(node, "_update_reference_video_visibility", None)
        for i in range(1, limit + 1):
            slot = f"reference_video_{i}"
            if node.get_parameter_by_name(slot) is None:
                continue
            self._show_parameters(node, [slot])
            if i <= len(values):
                try:
                    self._set_on_node(node, slot, values[i - 1])
                except Exception as exc:
                    warnings.append(f"{getattr(node, 'name', '?')}.{slot}: {exc}")
            else:
                self._disconnect_parameters(node, {slot})
                self._drop_stored_value(node, slot)
                for empty in (None, ""):
                    try:
                        self._set_on_node(node, slot, empty)
                        break
                    except Exception:
                        continue
            if callable(refresh):
                try:
                    refresh()
                except Exception:
                    pass
        if node.get_parameter_by_name("reference_video_1") is not None:
            self._schedule_list_refresh(str(getattr(node, "name", "") or ""), "reference_video_1")
        return warnings

    def _push_into_node(
        self, node: Any, prompt: str, refs: list[dict[str, Any]], caps: dict[str, Any]
    ) -> list[str]:
        """Write prompt and ordered references using this node's Seedance envelope."""
        warnings: list[str] = []
        family = str(caps.get("family") or self._seedance_family(node))
        image_cap = int(caps.get("image") or MAX_IMAGE_SLOTS)
        video_cap = int(caps.get("video") or MAX_VIDEO_SLOTS)
        audio_cap = int(caps.get("audio") or MAX_AUDIO_SLOTS)
        has_media = any(str(r.get("kind")) in ("image", "video", "audio") for r in refs)

        warnings.extend(self._reveal_reference_inputs(node, family, has_media))
        self._set_on_node(node, "prompt", prompt or "")

        image_values = self._values_for_kind(refs, "image", image_cap)
        warnings.extend(self._fill_container(node, "reference_images", image_values))

        video_values = self._values_for_kind(refs, "video", video_cap)
        if family != "20" and node.get_parameter_by_name("reference_videos") is not None:
            warnings.extend(self._fill_container(node, "reference_videos", video_values))
        elif family == "20" or node.get_parameter_by_name("reference_video_1") is not None:
            warnings.extend(self._push_fixed_videos(node, video_values, video_cap))

        audio_values = self._values_for_kind(refs, "audio", audio_cap)
        audio_refs = [r for r in refs if str(r.get("kind")) == "audio"]
        if audio_refs and not audio_values:
            warnings.append(f"{node.name}: {len(audio_refs)} mentioned audio clip(s) had no file to copy.")
        audio_list = self._media_list_param(
            node, ("reference_audios", "reference_audio", "audios", "audio_references")
        )
        if audio_list is not None:
            warnings.extend(self._fill_container(node, audio_list.name, audio_values))
        elif node.get_parameter_by_name("reference_audio") is not None:
            warnings.extend(self._release_fixed_slots(node, "reference_audio", audio_values[:1], 1))
        else:
            warnings.extend(self._release_fixed_slots(node, "reference_audio", audio_values, audio_cap))
            if audio_values and node.get_parameter_by_name("reference_audio_1") is None:
                warnings.append(
                    f"{node.name}: no reference-audio list found (expected reference_audios or reference_audio)."
                )
        return warnings

    def _release_fixed_slots(self, node: Any, prefix: str, values: list[Any], limit: int) -> list[str]:
        """Write fixed slots in order and drop wires on the ones no longer mentioned.

        Seedance 2.0 video inputs are ``reference_video_1`` .. ``reference_video_3``,
        not a list. Clearing the value leaves the wire in place, which is the
        same stuck connection the image lists had.
        """
        warnings: list[str] = []
        first = ""
        touched = False
        for i in range(1, limit + 1):
            slot = prefix if limit == 1 and prefix == "reference_audio" else f"{prefix}_{i}"
            if limit == 1 and prefix == "reference_audio" and i > 1:
                break
            if node.get_parameter_by_name(slot) is None:
                continue
            touched = True
            if not first:
                first = slot
            if i <= len(values):
                try:
                    self._set_on_node(node, slot, values[i - 1])
                except Exception as exc:
                    warnings.append(f"{getattr(node, 'name', '?')}.{slot}: {exc}")
                continue
            self._disconnect_parameters(node, {slot})
            self._drop_stored_value(node, slot)
            for empty in (None, ""):
                try:
                    self._set_on_node(node, slot, empty)
                    break
                except Exception:
                    continue
        if touched and first:
            self._schedule_list_refresh(str(getattr(node, "name", "") or ""), first)
        return warnings

    def _apply_budget(
        self,
        prompt: str,
        push_refs: list[dict[str, Any]],
        entities: list[dict[str, Any]],
        caps: dict[str, int],
    ) -> tuple[str, list[dict[str, Any]], dict[str, int]]:
        """Enforce the per-kind slot budgets (30 img / 10 vid / 10 aud).

        Ranking within each kind: refs owned by a must-have entity survive
        first, then nice-to-have entities, then unassigned refs; ties keep
        tag order. Dropped refs lose their bracket mentions in the prompt.
        """
        must_keys: set[str] = set()
        nice_keys: set[str] = set()
        for entity in entities:
            target = nice_keys if entity.get("priority") == "nice" else must_keys
            target.update(str(k) for k in (entity.get("refKeys") or []))

        def rank(ref: dict[str, Any]) -> int:
            key = str(ref.get("key") or "")
            if key in must_keys:
                return 0
            if key in nice_keys:
                return 1
            return 2

        drop_ids: set[tuple[str, str]] = set()
        dropped_counts: dict[str, int] = {"image": 0, "video": 0, "audio": 0}
        dropped_refs: list[dict[str, Any]] = []
        for kind, cap in caps.items():
            kind_refs = [r for r in push_refs if str(r.get("kind")) == kind]
            if len(kind_refs) <= cap:
                continue
            order = sorted(range(len(kind_refs)), key=lambda i: (rank(kind_refs[i]), i))
            for i in order[cap:]:
                ref = kind_refs[i]
                drop_ids.add((kind, str(ref.get("key") or "")))
                dropped_refs.append(ref)
                dropped_counts[kind] += 1

        if not dropped_refs:
            return prompt, push_refs, dropped_counts

        kept_refs = [
            r for r in push_refs
            if (str(r.get("kind")), str(r.get("key") or "")) not in drop_ids
        ]
        for ref in dropped_refs:
            kind = str(ref.get("kind") or "image")
            prompt = prompt.replace(f"[{kind.capitalize()} {int(ref.get('index') or 0)}]", "")
        # Tidy comma runs and stray separators the removals leave behind.
        prompt = re.sub(r",\s*(?:,\s*)+", ", ", prompt)
        prompt = re.sub(r"\(\s*,\s*", "(", prompt)
        prompt = re.sub(r"\s*,\s*([.!?)])", r"\1", prompt)
        prompt = re.sub(r"[ \t]{2,}", " ", prompt)
        return prompt.strip(), kept_refs, dropped_counts

    def _send_to_seedance(self, state: dict[str, Any]) -> None:
        """Push the prompt + ONLY the mentioned refs into the target Seedance nodes."""
        widget_refs = state.get("refs") if isinstance(state.get("refs"), list) else []
        refs = self._refs_for_send(widget_refs)
        self._scanned_refs = refs
        entities = self._valid_entities(state)
        budget = self._budget(state)
        prompt_full = self._build_prompt(state, refs)

        # Keep only mentioned refs (in tag order).
        mentioned = self._mentioned(prompt_full)
        by_kind_index: dict[tuple[str, int], dict[str, Any]] = {}
        for ref in refs:
            try:
                by_kind_index[(str(ref.get("kind")), int(ref.get("index") or 0))] = ref
            except Exception:
                continue
        ordered: list[tuple[str, int]] = []
        seen: set[tuple[str, int]] = set()
        for match in _BRACKET_RE.finditer(prompt_full):
            pair = (match.group(1).lower(), int(match.group(2)))
            if pair in seen:
                continue
            seen.add(pair)
            ordered.append(pair)
        push_refs: list[dict[str, Any]] = []
        for kind, idx in ordered:
            ref = by_kind_index.get((kind, idx))
            if ref is None:
                continue
            if self._live_media_value(ref, kind) in (None, "") and not self._ref_full_url(ref):
                continue
            push_refs.append(ref)

        def compact_for(
            node_caps: dict[str, Any],
        ) -> tuple[str, list[dict[str, Any]], dict[str, int], dict[str, int]]:
            """Drop refs past this node's envelope and renumber the prompt to match."""
            kind_caps = {
                "image": int(node_caps["image"]),
                "video": int(node_caps["video"]),
                "audio": int(node_caps["audio"]),
            }
            trimmed, kept, dropped_counts = self._apply_budget(prompt_full, list(push_refs), entities, kind_caps)
            remap: dict[tuple[str, int], int] = {}
            counters = {"image": 0, "video": 0, "audio": 0}
            for ref in kept:
                kind = str(ref.get("kind"))
                if kind not in counters:
                    continue
                counters[kind] += 1
                remap[(kind, int(ref.get("index") or 0))] = counters[kind]

            def renumber(match: re.Match[str]) -> str:
                kind = match.group(1).lower()
                new_index = remap.get((kind, int(match.group(2))))
                return f"[{kind.capitalize()} {new_index}]" if new_index else ""

            prompt_push = re.sub(r"[ \t]{2,}", " ", _BRACKET_RE.sub(renumber, trimmed)).strip()
            return prompt_push, kept, counters, dropped_counts

        all_targets = self._find_seedance_nodes()
        pick = str(state.get("sendTarget") or "all")
        group_name = pick[len(_GROUP_TARGET_PREFIX) :] if pick.startswith(_GROUP_TARGET_PREFIX) else ""
        targets = self._select_send_targets(state, all_targets)

        sent = 0
        errors: list[str] = []
        summaries: list[str] = []
        dropped_notes: list[str] = []
        for node in targets:
            try:
                node_caps = self._caps_for_node(node, budget)
                prompt_push, node_refs, counters, dropped = compact_for(node_caps)
                errors.extend(self._push_into_node(node, prompt_push, node_refs, node_caps))
                sent += 1
                summaries.append(
                    f"{getattr(node, 'name', '?')} (Seedance {node_caps['label']}: "
                    f"{counters['image']}/{node_caps['image']} img, "
                    f"{counters['video']}/{node_caps['video']} vid, "
                    f"{counters['audio']}/{node_caps['audio']} aud)"
                )
                if sum(dropped.values()):
                    parts = ", ".join(f"{n} {kind}" for kind, n in dropped.items() if n)
                    dropped_notes.append(f"{getattr(node, 'name', '?')} dropped {parts}")
            except Exception as exc:
                errors.append(f"{getattr(node, 'name', '?')}: {exc}")

        if not targets:
            if group_name:
                known = {str(g.get("name") or "") for g in self._find_groups()}
                if group_name in known:
                    status = f"Send failed: group '{group_name}' has no Seedance nodes."
                else:
                    status = (
                        f"Send failed: group '{group_name}' not found. "
                        "Press Rescan after adding a group."
                    )
            elif pick not in ("", "all"):
                status = f"Send failed: Seedance node '{pick}' not found."
            else:
                status = "Send failed: no Seedance nodes found in this workflow."
        else:
            skipped = len(refs) - len(push_refs)
            dest = f"{sent} Seedance node(s)"
            if group_name:
                dest += f" in group '{group_name}'"
            shown = summaries[:4]
            status = f"Sent mentioned refs to {dest}: " + "; ".join(shown)
            if len(summaries) > len(shown):
                status += f"; +{len(summaries) - len(shown)} more"
            status += "."
            if dropped_notes:
                status += " Over budget (nice-to-have first): " + "; ".join(dropped_notes[:3]) + "."
            if skipped > 0:
                status += f" {skipped} unmentioned asset(s) excluded."
            if refs and not push_refs:
                status += " Tag assets in the prompt with @Image1 / @Video1 / @Audio1 (or an entity name) to send them."
            if errors:
                status += " Problems: " + "; ".join(errors[:3])
        final_state = self._current_state()
        final_state["statusMessage"] = status
        self._push_state(final_state)

    # ------------------------------------------------------------------ state

    @staticmethod
    def _budget(state: dict[str, Any]) -> int:
        try:
            budget = int(state.get("budget") or MAX_IMAGE_SLOTS)
        except Exception:
            budget = MAX_IMAGE_SLOTS
        return max(1, min(MAX_IMAGE_SLOTS, budget))

    def _current_state(self) -> dict[str, Any]:
        state = self.parameter_values.get("composer")
        if not isinstance(state, dict):
            state = _default_composer()
        state = dict(state)
        state["scanMode"] = True
        return state

    def _push_state(self, state: dict[str, Any]) -> None:
        try:
            state["doSend"] = False
        except Exception:
            pass
        self._syncing = True
        self._sanitize_composer_callbacks()
        try:
            self.parameter_values["composer"] = state
        except Exception:
            pass
        try:
            super().set_parameter_value("composer", state)
        except Exception:
            try:
                param = self.get_parameter_by_name("composer")
                emit = getattr(self, "_emit_parameter_lifecycle_event", None)
                if param is not None and callable(emit):
                    emit(param)
            except Exception:
                pass
        try:
            self.publish_update_to_parameter("composer", state)
        except Exception:
            pass
        self._syncing = False

    def _rescan_and_push(self, state: dict[str, Any] | None = None, force: bool = False) -> None:
        state = dict(state) if isinstance(state, dict) else self._current_state()
        prev_refs = state.get("refs") if isinstance(state.get("refs"), list) else []
        refs = self._scan_workflow(prev_refs=prev_refs)
        self._scanned_refs = refs
        self._publish_outputs(refs)
        try:
            unchanged = json.dumps(state.get("refs", []), sort_keys=True, default=str) == json.dumps(
                refs, sort_keys=True, default=str
            )
        except Exception:
            unchanged = False
        counts = self._count_text(refs)
        profiles = self._target_profiles()
        targets = [str(p.get("name") or "") for p in profiles]
        families = ", ".join(
            f"{sum(1 for p in profiles if p.get('family') == fam)}x {label}"
            for fam, label in (("20", "2.0"), ("25", "2.5"))
            if any(p.get("family") == fam for p in profiles)
        )
        status = f"Scanned workflow: {counts}. Seedance targets: {len(targets)}"
        if families:
            status += f" ({families})"
        status += "."
        if self._scan_error:
            status = f"Scan problem ({self._scan_error}). Found {counts}."
        elif not refs:
            status = (
                f"Scan found no media assets (Seedance targets: {len(targets)}"
                + (f", {families}" if families else "")
                + "). Run upstream media nodes once, then press Rescan."
            )
        prev_status = str(state.get("statusMessage") or "")
        prev_targets = list(state.get("targets") or [])
        prev_groups = list(state.get("groups") or [])
        prev_profiles = list(state.get("targetProfiles") or [])
        groups = self._find_groups()
        self._migrate_entity_keys(state, prev_refs if isinstance(prev_refs, list) else [], refs)
        state["refs"] = refs
        state["scanMode"] = True
        state["statusMessage"] = status
        state["targets"] = targets
        state["targetProfiles"] = profiles
        state["groups"] = groups
        # force: explicit Rescan click - ALWAYS push so the widget's
        # "Rescanning..." status resolves even when nothing changed.
        if (
            force
            or not unchanged
            or status != prev_status
            or targets != prev_targets
            or groups != prev_groups
            or prev_profiles != profiles
        ):
            self._push_state(state)
        self._publish_prompt(state)

    @staticmethod
    def _count_text(refs: list[dict[str, Any]]) -> str:
        images = sum(1 for r in refs if r.get("kind") == "image")
        videos = sum(1 for r in refs if r.get("kind") == "video")
        audio = sum(1 for r in refs if r.get("kind") == "audio")
        return f"{images} image / {videos} video / {audio} audio assets"

    # ------------------------------------------------------------------ prompt

    @staticmethod
    def _to_brackets(text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            return f"[{match.group(1).capitalize()} {match.group(2)}]"

        return _MENTION_RE.sub(repl, text or "")

    @staticmethod
    def _mentioned(converted: str) -> set[tuple[str, int]]:
        return {(m.group(1).lower(), int(m.group(2))) for m in _BRACKET_RE.finditer(converted)}

    # Role-aware constraint templates; {name} / {tags} are substituted.
    _LANE_CONSTRAINTS = {
        "character": "Maintain {name}'s exact identity, facial features, and body proportions from {tags} in every frame.",
        "wardrobe": "Keep the {name} wardrobe exactly as shown in {tags} - fabric, fit, and color must not drift.",
        "prop": "Preserve the exact design, scale, and detailing of {name} from {tags}.",
        "set": "Match the environment layout, architecture, and set dressing of {name} from {tags}.",
        "light": "Match the lighting mood, contrast, and color grade of {tags} throughout.",
        "camera": "Replicate the camera movement, framing, and pacing from {tags} exactly.",
        "audio": "Sync the action, cuts, and timing to {tags}.",
    }

    def _enhance(
        self,
        converted: str,
        refs: list[dict[str, Any]],
        entities: list[dict[str, Any]],
        raw_text: str,
    ) -> str:
        """Structure per the Seedance prompt guide, with role-aware constraints.

        Mentioned entities get lane-specific constraint lines; mentioned refs
        that belong to no mentioned entity fall back to the V6 generic lines.
        """
        mentioned = self._mentioned(converted)
        mentioned_ents = self._mentioned_entities(raw_text, entities)

        role_lines: list[str] = []
        covered: set[tuple[str, int]] = set()
        for lane in LANE_ORDER:
            for entity in mentioned_ents:
                if entity["lane"] != lane:
                    continue
                brackets = self._entity_brackets(entity, refs)
                if not brackets:
                    continue
                for b in brackets:
                    m = _BRACKET_RE.match(b)
                    if m:
                        covered.add((m.group(1).lower(), int(m.group(2))))
                template = self._LANE_CONSTRAINTS.get(lane, self._LANE_CONSTRAINTS["prop"])
                role_lines.append(template.format(name=entity["name"], tags=", ".join(brackets)))

        leftover = mentioned - covered
        leftover_images = sorted(idx for kind, idx in leftover if kind == "image")
        leftover_videos = sorted(idx for kind, idx in leftover if kind == "video")
        if leftover_images:
            tags = ", ".join(f"[Image {i}]" for i in leftover_images)
            role_lines.append(f"Maintain the subject's identity, wardrobe, and proportions from {tags} throughout.")
        if leftover_videos:
            tags = ", ".join(f"[Video {i}]" for i in leftover_videos)
            role_lines.append(f"Match the camera movement and pacing from {tags} exactly.")

        body = re.sub(r"[ \t]+", " ", (converted or "").strip())
        if body:
            body = body[0].upper() + body[1:]
            if body[-1] not in ".!?":
                body += "."
        if role_lines:
            body = (body + "\n\n" if body else "") + " ".join(role_lines)
        return body.strip()

    def _build_prompt(self, state: dict[str, Any], refs: list[dict[str, Any]]) -> str:
        raw_text = str(state.get("text") or "")
        entities = self._valid_entities(state)
        converted = self._expand_entities(raw_text, entities, refs)
        converted = self._to_brackets(converted)
        if bool(state.get("enhance")):
            converted = self._enhance(converted, refs, entities, raw_text)
        return converted

    def _publish_prompt(self, state: dict[str, Any]) -> None:
        try:
            prompt = self._build_prompt(state, self._scanned_refs)
            self.publish_update_to_parameter("prompt", prompt)
        except Exception:
            pass

    # ------------------------------------------------------------------ lifecycle

    def set_parameter_value(self, param_name: str, value: Any, **kwargs: Any) -> None:  # type: ignore[override]
        if param_name == "composer":
            self._sanitize_composer_callbacks()
        super_ok = False
        try:
            super().set_parameter_value(param_name, value, **kwargs)
            super_ok = True
        except TypeError as exc:
            if "not callable" not in str(exc):
                raise
        except Exception:
            if param_name != "composer":
                raise
        if not super_ok:
            try:
                self.parameter_values[param_name] = value
            except Exception:
                pass
        if param_name == "composer" and isinstance(value, dict) and not self._syncing and not super_ok:
            parameter = self.get_parameter_by_name(param_name)
            if parameter is not None:
                try:
                    self._on_composer_changed(parameter, value)
                except Exception:
                    pass
        if not super_ok:
            try:
                param = self.get_parameter_by_name(param_name)
                emit = getattr(self, "_emit_parameter_lifecycle_event", None)
                if param is not None and callable(emit):
                    emit(param)
            except Exception:
                pass

    def after_value_set(self, parameter: Parameter, value: Any) -> None:
        try:
            self._on_composer_changed(parameter, value)
        except Exception:
            pass
        try:
            super().after_value_set(parameter, value)
        except Exception:
            pass

    def _on_composer_changed(self, parameter: Parameter, value: Any) -> None:
        if parameter.name != "composer" or self._syncing or not isinstance(value, dict):
            return
        nonce = value.get("scanNonce")
        widget_refs = value.get("refs")
        browse_nonce = self._nonce_int(value.get("promptBrowseNonce"))
        if self._last_prompt_browse_nonce is None:
            self._last_prompt_browse_nonce = browse_nonce
        elif browse_nonce and browse_nonce != self._nonce_int(self._last_prompt_browse_nonce):
            self._last_prompt_browse_nonce = browse_nonce
            self._browse_prompt_file(value)
            return
        text_before = str(value.get("text") or "")
        status_before = str(value.get("promptFileStatus") or "")
        self._note_prompt_file_request(value)
        file_touched = text_before != str(value.get("text") or "") or status_before != str(value.get("promptFileStatus") or "")
        if file_touched:
            stored = self.parameter_values.get("composer")
            if isinstance(stored, dict) and stored is not value:
                stored["text"] = value.get("text")
                stored["promptFile"] = value.get("promptFile")
                stored["promptFileNonce"] = value.get("promptFileNonce")
                stored["promptFileStatus"] = value.get("promptFileStatus")
        send_nonce = value.get("sendNonce")
        incoming_send = self._nonce_int(send_nonce)
        primed_send = self._last_send_nonce is not None
        if not primed_send:
            self._last_send_nonce = incoming_send
        if bool(value.get("doSend")) or (
            primed_send and incoming_send and incoming_send != self._nonce_int(self._last_send_nonce)
        ):
            try:
                value["doSend"] = False
            except Exception:
                pass
            self._last_send_nonce = incoming_send or (self._nonce_int(self._last_send_nonce) + 1)
            try:
                self._send_to_seedance(value)
            except Exception as exc:
                try:
                    failed = dict(value)
                    failed["doSend"] = False
                    failed["statusMessage"] = f"Send failed: {exc}"
                    self._push_state(failed)
                except Exception:
                    pass
            return
        explicit_scan = bool(nonce and self._last_scan_nonce is not None and nonce != self._last_scan_nonce)
        # An empty ref list is the widget booting, not a request to scan again.
        # Rescanning on every empty echo rebuilds the asset column in a loop.
        needs_scan = self._last_scan_nonce is None or explicit_scan
        if needs_scan:
            self._last_scan_nonce = nonce or 0
            self._rescan_and_push(value, force=explicit_scan or file_touched)
        else:
            self._adopt_widget_order(widget_refs)
            self._publish_prompt(value)
            if file_touched:
                self._push_state(value)

    def _adopt_widget_order(self, widget_refs: Any) -> None:
        """When the user drags thumbnails, adopt the widget's new tag order."""
        if not isinstance(widget_refs, list) or not widget_refs:
            return
        widget_keys = [str(r.get("key") or "") for r in widget_refs if isinstance(r, dict)]
        known_keys = [str(r.get("key") or "") for r in self._scanned_refs]
        if not widget_keys or set(widget_keys) != set(known_keys):
            return
        if widget_keys == known_keys:
            return
        self._scanned_refs = [r for r in widget_refs if isinstance(r, dict)]
        self._publish_outputs(self._scanned_refs)

    def process(self) -> None:
        # Run path must stay CHEAP: the engine queues every unwired data node
        # as a flow entry point, so this executes once per queued run, on the
        # engine's event loop. Reuse the refs from the editor session when we
        # have them (node instances are long-lived); only a fresh instance
        # after an engine restart pays for one thumb-free scan. A prompt-file
        # change is the only case that pushes widget state from here.
        state = self._current_state()
        text_before = str(state.get("text") or "")
        if self._read_prompt_file_into(state, force=True) and str(state.get("text") or "") != text_before:
            self._push_state(state)
        refs = self._scanned_refs
        if not refs:
            prev_refs = state.get("refs") if isinstance(state.get("refs"), list) else []
            refs = self._scan_workflow(prev_refs=prev_refs, generate_thumbs=False)
            self._scanned_refs = refs
        self._publish_outputs(refs)

        self.parameter_output_values["prompt"] = self._build_prompt(state, refs)
