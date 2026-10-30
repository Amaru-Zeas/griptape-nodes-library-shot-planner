"""Image Omni Prompt - Seedance Omni Prompt V5 process for IMAGE generation nodes.

Same workflow as the Seedance V5 composer, but the targets are image
generation nodes instead of video: Google Nano Banana
(``GoogleImageGeneration``), OpenAI GPT Image (``OpenAiImageGeneration``),
and ByteDance Seedream (``SeedreamImageGeneration``). Google/OpenAI expose
``prompt`` + ``input_images``; Seedream exposes ``prompt`` + ``images``.

The node scans the workflow for IMPORTED images (Load Image / Input-Output
nodes), auto-tags them ``@Image1``, ``@Image2``, ... in node-creation order,
and lets you compose a prompt with @ mentions. "Send to Image Gen" writes the
bracket-converted prompt ([Image N]) and ONLY the mentioned images - in slot
order matching the brackets - straight into every (or one selected) image
generation node, or every image-gen node inside a chosen canvas group. No wiring needed.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import threading
import time
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

LIBRARY_NAME = "GTN Shot Planner"
WIDGET_NAME = "ImageGenPromptWidget"

DEFAULT_COMPOSER: dict[str, Any] = {
    "text": "",
    "enhance": False,
    "refs": [],
    "statusMessage": "",
    "scanMode": True,
    "scanNonce": 0,
    "targets": [],
    "groups": [],
    "sendTarget": "all",
    "sendNonce": 0,
    "doSend": False,
    "enhanceNonce": 0,
    "voiceNonce": 0,
    "llmEnhance": False,
    "llmModel": "gpt-4.1-mini",
    "llmModels": [],
    "thumbScale": 1,
}

# Fallback chat-model list for the AI Prompt Enhancer dropdown. Prefer the
# live Griptape Cloud catalog (see _llm_model_choices); this is used when
# that file can't be read, and extra ids here are merged in if the catalog
# is older than the proxy.
LLM_MODEL_CHOICES = [
    "gpt-6-sol",
    "gpt-6-luna",
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.2",
    "gpt-5.2-chat",
    "gpt-5.1",
    "gpt-5",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4.1-nano",
    "gpt-4o",
    "claude-sonnet-5-5",
    "claude-opus-5-5",
    "claude-sonnet-5",
    "claude-opus-5",
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-pro",
    "gemini-3.1-flash-lite",
    "gemini-3-flash",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "deepseek-v3",
    "llama3-3-70b-instruct-v1",
]
DEFAULT_LLM_MODEL = "gpt-4.1-mini"
_CHAT_FAMILY_PREFIXES = ("claude", "deepseek", "llama", "gemini", "gpt", "o-series")
_CHAT_FAMILY_EXCLUDE = ("image", "omni", "veo", "sora", "whisper", "dall")

_LLM_SYSTEM_PROMPT = """You are an expert prompt writer for AI image generation models (Google Nano Banana, OpenAI GPT Image, ByteDance Seedream).
Rewrite the user's rough prompt into one polished, detailed image-generation prompt.
Rules:
- Keep every reference tag like [Image 1], [Image 2] EXACTLY as written. Never add, remove, renumber, or reformat tags.
- Preserve the user's intent, subjects, layout and composition instructions.
- Fix spelling and grammar.
- Add concise photographic / style detail (lighting, lens, mood) only where it supports the user's intent.
- Output ONLY the rewritten prompt text: no commentary, no quotes, no markdown."""

# Image generation node classes this composer pushes into.
_TARGET_CLASS_NAMES = (
    "GoogleImageGeneration",
    "OpenAiImageGeneration",
    "SeedreamImageGeneration",
)

# ParameterList that holds reference images. Seedream uses ``images``; the
# Google / OpenAI proxies use ``input_images``.
_TARGET_IMAGE_CONTAINERS = {
    "GoogleImageGeneration": "input_images",
    "OpenAiImageGeneration": "input_images",
    "SeedreamImageGeneration": "images",
}
_IMAGE_LIST_CANDIDATES = ("input_images", "images")

# Per-node cap on reference images (Google 14, OpenAI 16, Seedream 14 / Pro 10).
_TARGET_IMAGE_CAPS = {
    "GoogleImageGeneration": 14,
    "OpenAiImageGeneration": 16,
    "SeedreamImageGeneration": 14,
}
_DEFAULT_IMAGE_CAP = 14

# Seedream 5.0 Pro is the only Seedream model that caps below the default 14.
_SEEDREAM_MODEL_CAPS = {
    "dola-seedream-5-0-pro-260628": 10,
    "Seedream 5.0 Pro": 10,
    "gtc_seedream_5_0_pro": 10,
}

# Dynamic per-tag output parameters look like image_1 / image_2.
_TAG_PARAM_RE = re.compile(r"^image_(\d+)$")

_MENTION_RE = re.compile(r"@(image)[\s_-]?(\d+)", re.IGNORECASE)
_BRACKET_RE = re.compile(r"\[(image)\s*(\d+)\]", re.IGNORECASE)

_ARTIFACT_KINDS = {
    "ImageArtifact": "image",
    "ImageUrlArtifact": "image",
}

_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff")

# Parameter names on this node whose values must never be scanned as assets
# (they echo other nodes' assets and would create duplicates).
_SELF_CLASS_PREFIX = "ImageOmniPrompt"
_GROUP_TARGET_PREFIX = "group:"
# Extra Load-Image equivalents that are not named Load* and may predate
# library_node_metadata.group = Input/Output (PSD Flatten / PSD Layer).
_IMPORT_NODE_CLASSES = frozenset({"PsdFlattenNode", "PsdLayerNode"})


def _default_composer() -> dict[str, Any]:
    state = dict(DEFAULT_COMPOSER)
    state["refs"] = []
    state["groups"] = []
    return state


def _classify_url(text: str) -> str:
    """Return 'image' when the URL/path string looks like an image; '' otherwise."""
    lowered = text.lower().split("?", 1)[0].split("#", 1)[0]
    if lowered.startswith("data:"):
        mime = lowered[5:].split(";", 1)[0].split("/", 1)[0]
        return "image" if mime == "image" else ""
    if lowered.endswith(_IMAGE_EXTS):
        return "image"
    return ""


class ImageOmniPromptNode(DataNode):
    """Prompt composer that pushes straight into image generation nodes - no wiring.

    * Scans the workflow for imported images, tags them @Image1, @Image2, ...
    * Stable tag order + drag-to-reorder thumbnails.
    * "Send to Image Gen" writes the bracket-converted prompt and the ordered
      mentioned images directly into every (or one selected) Nano Banana /
      GPT Image / Seedream node in the workflow: prompt + Input Images 1..N,
      where slot N always matches ``[Image N]``.
    * Per-tag fallback outputs (``image_1``, ``image_2``, ...) for manual wiring.
    """

    def __init__(self, name: str, metadata: dict[str, Any] | None = None, **kwargs) -> None:
        node_metadata = {
            "category": "ShotPlanner",
            "description": "Image-generation prompt composer that pushes prompt + ordered reference images directly into Nano Banana / GPT Image / Seedream nodes - no wires needed.",
        }
        if metadata:
            node_metadata.update(metadata)
        super().__init__(name=name, metadata=node_metadata, **kwargs)
        self.set_initial_node_size(width=780, height=760)

        self._last_scan_nonce: Any = None
        self._last_send_nonce: Any = None
        self._last_enhance_nonce: Any = None
        self._last_voice_nonce: Any = None
        self._scanned_refs: list[dict[str, Any]] = []
        self._scan_error = ""
        self._nodes_lookup_error = ""
        self._syncing = False
        # Thumbnail data-URL cache keyed by pixel stamp (thumbs are expensive).
        # Empty results are never cached, so a failed fetch can succeed later.
        self._thumb_cache: dict[str, str] = {}
        # Full (non-truncated) URL per source node, for the list outputs.
        self._asset_urls: dict[str, str] = {}
        self._last_import_sig: tuple[tuple[str, str], ...] | None = None
        self._thumb_watch_started = False
        self._scan_lock = threading.Lock()
        self._model_choices_cache: list[str] | None = None
        threading.Timer(0.8, self._ensure_image_watch).start()

        self.add_parameter(
            Parameter(
                name="composer",
                input_types=["dict"],
                type="dict",
                output_type="dict",
                default_value=_default_composer(),
                tooltip="Prompt editor: type @ to mention any image found in the workflow. Drag sidebar thumbnails to reorder tags.",
                allowed_modes={ParameterMode.PROPERTY},
                traits={Widget(name=WIDGET_NAME, library=LIBRARY_NAME)},
            )
        )
        self._sanitize_composer_callbacks()
        self.add_parameter(
            Parameter(
                name="prompt",
                output_type="str",
                tooltip="Final prompt with @ mentions converted to [Image N].",
                allowed_modes={ParameterMode.OUTPUT},
            )
        )
        self.add_parameter(
            Parameter(
                name="reference_images",
                output_type="list",
                tooltip="Images in @Image tag order. Wire once into the image node's Input Images list; slot N always matches [Image N].",
                allowed_modes={ParameterMode.OUTPUT},
                serializable=False,
                ui_options={"hide": True},
            )
        )

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
            for item in value[:64]:
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
                        mime = getattr(value, "mime_type", None) or "image/*"
                        found.append((kind, f"data:{mime};base64,{b64}", True))
                except Exception:
                    pass

    @staticmethod
    def _is_import_node(node: Any) -> bool:
        """True only for asset *import* nodes (LoadImage etc., Input-Output group, PSD Flatten/Layer).

        Generation nodes (Nano Banana, GPT Image, Seedream, Seedance, ...) and anything
        else holding derived or echoed media are excluded so only
        user-imported assets get tagged.
        """
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

    def _source_stamp(self, url: str) -> str:
        """Pixel identity. A new image must not keep the previous thumbnail.

        The filename is not enough: Load / PSD nodes often republish the same
        name, or a brand new static-file name, for a different picture.
        """
        if not url:
            return ""
        if url.startswith("data:"):
            size = len(url)
            sample = (url[:256] + url[max(0, size - 256) :]).encode("utf-8", "replace")
            digest = hashlib.sha1(sample).hexdigest()[:16]
            return f"data:{size}:{digest}"
        clean = url.split("?", 1)[0].split("#", 1)[0]
        extra = ""
        if not clean.startswith(("http://", "https://")):
            try:
                path = Path(os.path.expandvars(os.path.expanduser(clean.removeprefix("file://"))))
                if path.is_file():
                    st = path.stat()
                    extra = f":{st.st_mtime_ns}:{st.st_size}"
            except Exception:
                extra = ""
        digest = hashlib.sha1(clean.encode("utf-8", "replace")).hexdigest()[:16]
        return digest + extra

    def _node_primary_asset(self, node: Any) -> tuple[str, str] | None:
        """The single best (kind, url) for an import node.

        Loaders expose the same file through several parameters ('image'
        artifact, 'path' string, status text, mask settings...). Prefer
        artifact values on a parameter literally named image, then
        resolvable URLs.
        """
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
                if param_name.strip().lower() == "image":
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

    def _thumb_for(self, url: str, stamp: str = "") -> str:
        if not url:
            return ""
        cache_key = stamp or self._source_stamp(url)
        cached = self._thumb_cache.get(cache_key)
        if cached:
            return cached
        thumb = self._image_thumb(url)
        # Don't remember a failure. The file may not be readable yet.
        if thumb:
            self._thumb_cache[cache_key] = thumb
        return thumb

    def _discover_imports(self) -> list[dict[str, str]]:
        """One image per import node. Order here is irrelevant; callers sort."""
        discovered: list[dict[str, str]] = []
        try:
            all_nodes = self._workflow_nodes()
        except Exception as exc:
            self._scan_error = f"node registry scan failed: {exc}"
            return discovered
        if getattr(self, "_nodes_lookup_error", ""):
            self._scan_error = f"node registry scan failed: {self._nodes_lookup_error}"
            return discovered
        self._scan_error = ""
        seen_labels: set[str] = set()
        for node_name, node in all_nodes.items():
            if node is self or type(node).__name__.startswith(_SELF_CLASS_PREFIX):
                continue
            # Only user-IMPORTED assets (Load* nodes), never generated outputs
            # or media echoed through generation/processing nodes.
            if not self._is_import_node(node):
                continue
            if node_name in seen_labels:
                continue
            primary = self._node_primary_asset(node)
            if primary is None:
                continue
            kind, url = primary
            if kind != "image" or not url:
                continue
            seen_labels.add(node_name)
            discovered.append(
                {
                    "kind": "image",
                    "url": url,
                    "key": self._identity_key(url),
                    "label": node_name,
                    "stamp": self._source_stamp(url),
                }
            )
        return discovered

    def _claim_asset(
        self,
        discovered: list[dict[str, str]],
        used: set[int],
        prev: dict[str, Any],
    ) -> tuple[dict[str, str], dict[str, Any]] | None:
        """Find the discovered image that still belongs in this saved slot.

        The source node name is the slot. A new file on that node keeps the
        card where the user left it. The filename is only a fallback, so a
        rename can still update the displayed name. Prompt tags stay @ImageN.
        """
        label = str(prev.get("label") or "")
        key = str(prev.get("key") or "")
        for index, asset in enumerate(discovered):
            if index in used:
                continue
            if label and asset["label"] == label:
                used.add(index)
                return asset, prev
        # Filename is a last resort, and only when it is unique. Two Load
        # nodes that share a basename (D0_D_body / D0_D_body) used to steal
        # each other's cards, and Send then packed the wrong file.
        if key:
            matches = [
                index
                for index, asset in enumerate(discovered)
                if index not in used and asset["key"] == key
            ]
            if len(matches) == 1:
                used.add(matches[0])
                return discovered[matches[0]], prev
        return None

    def _scan_workflow(
        self,
        prev_refs: list[dict[str, Any]] | None = None,
        generate_thumbs: bool = True,
    ) -> list[dict[str, Any]]:
        """Collect imported images without shuffling cards the user arranged.

        A known source node keeps its slot. New nodes append. A thumbnail is
        reused only when ``source`` (the pixel stamp) is unchanged, so loading
        a new image on that node replaces the picture instead of leaving the
        old jpeg in place.

        ``generate_thumbs=False`` skips generating MISSING thumbnails - used
        on the run path, where network fetches + PIL work would block the engine.
        """
        discovered = self._discover_imports()
        if self._scan_error and not discovered:
            return []

        used: set[int] = set()
        ordered: list[tuple[dict[str, str], dict[str, Any] | None]] = []
        for ref in prev_refs or []:
            if not isinstance(ref, dict):
                continue
            claimed = self._claim_asset(discovered, used, ref)
            if claimed is not None:
                ordered.append(claimed)
        for index, asset in enumerate(discovered):
            if index not in used:
                ordered.append((asset, None))

        refs: list[dict[str, Any]] = []
        self._asset_urls = {}
        for counter, (asset, prev) in enumerate(ordered, start=1):
            url = asset["url"]
            stamp = asset["stamp"]
            label = asset["label"]
            self._asset_urls[label] = url
            key = asset["key"]
            if key and key not in self._asset_urls:
                self._asset_urls[key] = url
            thumb = ""
            if isinstance(prev, dict) and str(prev.get("source") or "") == stamp:
                thumb = str(prev.get("thumb") or "")
            if not thumb and generate_thumbs:
                thumb = self._thumb_for(url, stamp)
            # Keep the widget payload bounded: huge data URLs are
            # replaced by their thumbnail (websocket-friendly).
            payload_url = url
            if url.startswith("data:") and len(url) > 300_000:
                payload_url = ""
            refs.append(
                {
                    "tag": f"Image{counter}",
                    "kind": "image",
                    "index": counter,
                    "key": key,
                    "label": label,
                    "url": payload_url,
                    "thumb": thumb,
                    "source": stamp,
                }
            )
        return refs

    # ------------------------------------------------------------------ outputs

    def _make_artifact(self, url: str) -> Any:
        try:
            if ImageUrlArtifact is not None:
                return ImageUrlArtifact(url)
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
        """@ImageN is the Nth roster card. Refresh that card's file from its node.

        Do not rematch by filename. Two Load nodes can share a basename, and
        that is what packed Image 4 into the [Image 1] slot.
        """
        discovered = self._discover_imports()
        by_label = {asset["label"]: asset for asset in discovered}
        by_label_ci = {str(asset["label"]).strip().lower(): asset for asset in discovered}

        refs: list[dict[str, Any]] = []
        self._asset_urls = {}
        for position, raw in enumerate(widget_refs or [], start=1):
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
                stamp = asset.get("stamp")
                if stamp:
                    ref["source"] = stamp
                self._asset_urls[asset["label"]] = asset["url"]
            ref["index"] = position
            ref["kind"] = "image"
            ref["tag"] = f"Image{position}"
            refs.append(ref)
        return refs

    def _ref_for_image_index(self, refs: list[dict[str, Any]], index: int) -> dict[str, Any] | None:
        """The roster card the user sees as @ImageN (Nth card after send renumber)."""
        if index <= 0:
            return None
        if index <= len(refs):
            return refs[index - 1]
        return None

    def _slot_refs_for_mentions(
        self, refs: list[dict[str, Any]], mentioned: list[int]
    ) -> list[dict[str, Any]]:
        """Only the cards named in the prompt, in prompt order (no padding)."""
        out: list[dict[str, Any]] = []
        seen: set[int] = set()
        for index in mentioned:
            if index in seen:
                continue
            seen.add(index)
            ref = self._ref_for_image_index(refs, index)
            if ref is not None:
                out.append(ref)
        return out

    def _compact_prompt(self, prompt: str, packed_original_indices: list[int]) -> str:
        """Rewrite tags so [Image 1] is Input Images 1, [Image 2] is slot 2, ..."""
        remap: dict[int, int] = {}
        for slot, original in enumerate(packed_original_indices, start=1):
            if original not in remap:
                remap[original] = slot

        def renumber(match: re.Match[str]) -> str:
            new_index = remap.get(int(match.group(2)))
            return f"[Image {new_index}]" if new_index else ""

        compacted = _BRACKET_RE.sub(renumber, prompt)
        compacted = re.sub(r"[ \t]{2,}", " ", compacted)
        return compacted.strip()


    @staticmethod
    def _value_url(value: Any) -> str:
        """URL inside a string, artifact, or dict. Never the source object's identity."""
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

    def _live_media_value(self, ref: dict[str, Any]) -> Any:
        """A new image artifact for the gen node.

        PSD Flatten's ``image`` output is output-only. Handing that same object
        to Input Images ties the slot to the PSD node, so deleting the mention
        does not drop the row. Load Image works because its value is a normal
        file. Copy the URL into a fresh artifact either way.
        """
        src = self._node_by_label(str(ref.get("label") or ""))
        url = ""
        if src is not None:
            for store in (
                getattr(src, "parameter_output_values", {}) or {},
                getattr(src, "parameter_values", {}) or {},
            ):
                for key in ("image", "output_image", "output", "image_path"):
                    found = self._value_url(store.get(key))
                    if found:
                        url = found
                        break
                if url:
                    break
        if not url:
            url = self._ref_full_url(ref)
        return self._make_artifact(url) if url else None

    def _publish_outputs(self, refs: list[dict[str, Any]]) -> None:
        """Emit the ordered list plus per-tag fallback outputs (image_1, image_2, ...)."""
        images: list[Any] = []
        desired: dict[str, Any] = {}
        for ref in refs:
            url = self._ref_full_url(ref)
            if not url:
                continue
            artifact = self._make_artifact(url)
            images.append(artifact)
            desired[f"image_{int(ref.get('index') or 0)}"] = artifact
        try:
            self.parameter_output_values["reference_images"] = images
        except Exception:
            pass

        # Per-tag fallback outputs: hidden by default (the push makes wiring
        # unnecessary); they still exist so power users can unhide/wire them.
        for name, artifact in desired.items():
            num = name.split("_", 1)[1]
            display = f"@Image{num}"
            existing = self.get_parameter_by_name(name)
            if existing is None:
                try:
                    self.add_parameter(
                        Parameter(
                            name=name,
                            output_type="ImageUrlArtifact",
                            tooltip=f"{display}: always the image currently holding this tag (manual-wiring fallback).",
                            allowed_modes={ParameterMode.OUTPUT},
                            settable=False,
                            user_defined=True,
                            ui_options={"display_name": display, "hide": True, "hide_property": True},
                        )
                    )
                except Exception:
                    continue
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

    # ------------------------------------------------------------------ send to image gen

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
        actually refreshes Input Images / prompt on the open node.
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
        # A ui_options-only change is ignored by the editor (it does not
        # rebuild list children). Including the existing tooltip makes this a
        # structural refresh, the same rebuild Ctrl+Shift+R does for this node.
        tooltip = getattr(param, "tooltip", None) or "Input Images"
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
        """Redraw the target list after this send has finished.

        Removes broadcast while the composer set is still running. The editor
        fetches the node immediately and can paint the list from before the
        delete landed, so the extra slot stays until the next Send. A later
        top-level refresh reads the committed children and is the last paint.
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
        """ParameterList children plus numbered siblings like input_images_1."""
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
            # The editor draws ParameterList children. A stray input_images_1
            # sibling must not hide those, or the visible slot is never deleted.
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
        """Drop one extra Input Images / list child so the editor loses the slot."""
        name = str(getattr(child, "name", "") or "")
        container_name = str(getattr(container, "name", "") or "")
        before = len(self._slot_params(node, container, container_name))
        if name:
            self._disconnect_slot(node, name)
            try:
                # List slots the node created itself are not user-defined, so the
                # engine refuses to remove them. Marking the slot user-defined
                # lets the same request the minus button uses delete it.
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
                    detail = str(getattr(result, "result_details", "") or "remove refused")
                    self._last_slot_remove_error = detail
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

    def _wipe_list(self, node: Any, container: Any, container_name: str) -> None:
        """Remove every child and any wire into the list itself.

        One image often lives on the Input Images container, not on a child
        slot. Deleting only the child leaves that wire, so the image stays
        no matter how many times Send is clicked.
        """
        names = {container_name}
        for child in self._slot_params(node, container, container_name):
            child_name = str(getattr(child, "name", "") or "")
            if child_name:
                names.add(child_name)
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
        for child in self._slot_params(node, container, container_name):
            self._drop_stored_value(node, str(getattr(child, "name", "") or ""))

    def _trim_container(self, node: Any, container: Any, container_name: str, keep: int) -> list[str]:
        """Delete leftover list slots until the target has exactly ``keep`` images.

        Do not call ParameterList.ensure_length first: that shrinks the Python
        object without telling the editor, so leftover Input Images stay on
        screen until a full GTN refresh.
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
            if not self._remove_list_slot(node, container, extra):
                if keep <= 0:
                    self._wipe_list(node, container, container_name)
                    slots = self._slot_params(node, container, container_name)
                    if len(slots) <= keep:
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

    def _find_target_nodes(self) -> list[Any]:
        """Every Nano Banana / GPT Image / Seedream generation node in the workflow.

        Matches the standard-library proxy classes by name first; anything
        else exposing both ``prompt`` and an ``input_images`` list is accepted
        as a duck-typed fallback so compatible image nodes also work.
        Seedream is matched by class name because its list is ``images``, not
        ``input_images`` (duck-typing ``images`` + ``prompt`` would also catch
        non-generators like Describe Image).
        """
        try:
            all_nodes = self._workflow_nodes()
        except Exception:
            return []
        found: list[Any] = []
        for _name, node in all_nodes.items():
            if node is self or type(node).__name__.startswith(_SELF_CLASS_PREFIX):
                continue
            if self._is_node_group(node):
                continue
            cls_name = type(node).__name__
            try:
                if cls_name in _TARGET_CLASS_NAMES:
                    found.append(node)
                elif (
                    node.get_parameter_by_name("input_images") is not None
                    and node.get_parameter_by_name("prompt") is not None
                ):
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
        """Canvas groups that contain at least one image-generation target."""
        try:
            all_nodes = self._workflow_nodes()
        except Exception:
            return []
        targets = self._find_target_nodes()
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

        # Groups that only show up as parent_group on image-gen nodes.
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

    @staticmethod
    def _image_list_param(node: Any) -> Any:
        """The ParameterList that holds reference images on this target, if any."""
        cls_name = type(node).__name__
        preferred = _TARGET_IMAGE_CONTAINERS.get(cls_name)
        names = (preferred, *_IMAGE_LIST_CANDIDATES) if preferred else _IMAGE_LIST_CANDIDATES
        seen: set[str] = set()
        for name in names:
            if name in seen:
                continue
            seen.add(name)
            try:
                param = node.get_parameter_by_name(name)
            except Exception:
                param = None
            if param is not None:
                return param
        return None

    @staticmethod
    def _image_cap_for(node: Any) -> int:
        cls_name = type(node).__name__
        cap = _TARGET_IMAGE_CAPS.get(cls_name, _DEFAULT_IMAGE_CAP)
        if cls_name == "SeedreamImageGeneration":
            try:
                model = str(node.get_parameter_value("model") or "")
            except Exception:
                model = ""
            for key, limit in _SEEDREAM_MODEL_CAPS.items():
                if model == key or key in model:
                    cap = limit
                    break
        try:
            container = ImageOmniPromptNode._image_list_param(node)
            max_items = getattr(container, "max_items", None) if container is not None else None
            if isinstance(max_items, int) and max_items > 0:
                # Seedream does not set max_items (cap is model-dependent). Never raise
                # a model cap (Pro is 10) if the ParameterList default is larger.
                cap = min(cap, max_items)
        except Exception:
            pass
        return cap

    def _fill_container(self, node: Any, container_name: str, values: list[Any]) -> list[str]:
        """Grow/shrink a target ParameterList and set its children in order.

        Extra slots from a previous send are removed so the node only keeps
        the images currently in the prompt.
        """
        warnings: list[str] = []
        container = node.get_parameter_by_name(container_name)
        if container is None:
            if values:
                warnings.append(f"{node.name}: no '{container_name}' list to fill.")
            return warnings

        for child in self._slot_params(node, container, container_name):
            self._register_list_child(node, child)

        guard = 0
        while len(self._slot_params(node, container, container_name)) < len(values) and guard < max(24, len(values) + 2):
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
            try:
                self._set_on_node(node, target.name, value)
                filled += 1
            except Exception as exc:
                slot_errors.append(str(exc))
        warnings.extend(self._trim_container(node, container, container_name, len(values)))
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

    def _push_into_node(self, node: Any, prompt: str, refs: list[dict[str, Any]]) -> list[str]:
        """Write prompt and ordered reference images into one image gen node.

        Returns non-fatal warnings.
        """
        warnings: list[str] = []
        self._set_on_node(node, "prompt", prompt or "")

        cap = self._image_cap_for(node)
        if len(refs) > cap:
            warnings.append(f"{node.name}: only the first {cap} of {len(refs)} images were sent (node limit).")
        image_values: list[Any] = []
        missing = 0
        for ref in refs[:cap]:
            value = self._live_media_value(ref)
            if value in (None, ""):
                url = self._ref_full_url(ref)
                value = self._make_artifact(url) if url else None
            if value in (None, ""):
                missing += 1
                image_values.append("")
                continue
            image_values.append(value)
        if missing:
            warnings.append(f"{node.name}: {missing} mentioned image(s) had no file to copy.")
        container = self._image_list_param(node)
        container_name = getattr(container, "name", None) if container is not None else None
        if not container_name:
            warnings.append(f"{node.name}: no reference-image list parameter found (expected input_images or images).")
            return warnings
        warnings.extend(self._fill_container(node, container_name, image_values))
        return warnings

    # ------------------------------------------------------------------ LLM enhance

    def _gt_cloud_api_key(self) -> str:
        engine = self._engine()
        try:
            if engine is not None:
                key = engine.SecretsManager().get_secret("GT_CLOUD_API_KEY") or ""
                if key:
                    return key
        except Exception:
            pass
        return os.environ.get("GT_CLOUD_API_KEY", "")

    def _llm_model_choices(self) -> list[str]:
        """Chat models for the enhancer dropdown, live from the engine catalog.

        Same source as the Agent node's model list. Extra ids from
        LLM_MODEL_CHOICES are appended when the on-disk catalog is behind.
        """
        cached = getattr(self, "_model_choices_cache", None)
        if cached:
            return list(cached)

        models: list[str] = []
        try:
            if GriptapeNodes is None:
                raise RuntimeError("engine unavailable")
            catalog_path = (
                Path(GriptapeNodes.ConfigManager().workspace_path)
                / "libraries"
                / "griptape-nodes-library-standard"
                / "griptape_nodes_library.json"
            )
            data = json.loads(catalog_path.read_text(encoding="utf-8"))

            def walk(node: Any) -> None:
                if isinstance(node, dict):
                    for key, v in node.items():
                        if (
                            str(key).startswith("gtc_")
                            and isinstance(v, dict)
                            and v.get("provider_model_id")
                        ):
                            model_id = str(v.get("provider_model_id") or "")
                            family = str(v.get("family") or "").lower()
                            if family.startswith(_CHAT_FAMILY_PREFIXES) and not any(
                                bad in family for bad in _CHAT_FAMILY_EXCLUDE
                            ):
                                if model_id not in models:
                                    models.append(model_id)
                        else:
                            walk(v)
                elif isinstance(node, list):
                    for v in node:
                        walk(v)

            walk(data)
        except Exception:
            models = []

        if not models:
            models = list(LLM_MODEL_CHOICES)
        else:
            for extra in LLM_MODEL_CHOICES:
                if extra not in models:
                    models.append(extra)
            if DEFAULT_LLM_MODEL in models:
                models.remove(DEFAULT_LLM_MODEL)
                models.insert(0, DEFAULT_LLM_MODEL)
        self._model_choices_cache = list(models)
        return models

    def _llm_enhance(self, prompt: str, model: str) -> tuple[str, str]:
        """Rewrite the prompt with a Griptape Cloud chat model.

        Returns (enhanced_prompt, error). On any failure - or if the model
        altered the [Image N] tags - the original prompt is returned along
        with a short error string.
        """
        if not prompt.strip():
            return prompt, "prompt is empty"
        try:
            from griptape.common import PromptStack  # type: ignore[reportMissingImports]
            from griptape.drivers.prompt.griptape_cloud import (  # type: ignore[reportMissingImports]
                GriptapeCloudPromptDriver,
            )
        except Exception as exc:
            return prompt, f"griptape driver unavailable: {exc}"

        api_key = self._gt_cloud_api_key()
        if not api_key:
            return prompt, "GT_CLOUD_API_KEY is not set"

        try:
            driver = GriptapeCloudPromptDriver(model=model, api_key=api_key, stream=False)
            stack = PromptStack()
            stack.add_system_message(_LLM_SYSTEM_PROMPT)
            stack.add_user_message(prompt)
            enhanced = driver.run(stack).to_text().strip()
        except Exception as exc:
            return prompt, f"{model} call failed: {exc}"
        if not enhanced:
            return prompt, f"{model} returned an empty response"

        # The bracket tags drive the reference slots; if the model touched
        # them the enhanced prompt is unusable.
        original_tags = {m.group(0).lower().replace(" ", "") for m in _BRACKET_RE.finditer(prompt)}
        enhanced_tags = {m.group(0).lower().replace(" ", "") for m in _BRACKET_RE.finditer(enhanced)}
        if original_tags != enhanced_tags:
            return prompt, f"{model} altered the [Image N] tags; kept your original prompt"
        return enhanced, ""

    # ------------------------------------------------------------------ voice transcription

    _VOICE_NUM_WORDS = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
        "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
        "fourteen": 14, "fifteen": 15, "sixteen": 16, "to": 2, "too": 2, "for": 4,
    }
    _VOICE_MENTION_RE = re.compile(
        r"\b(at\s+)?(image)\s+(?:number\s+)?"
        r"(\d{1,2}|one|two|to|too|three|four|for|five|six|seven|eight|nine|ten"
        r"|eleven|twelve|thirteen|fourteen|fifteen|sixteen)\b",
        re.IGNORECASE,
    )

    @classmethod
    def _normalize_voice_mentions(cls, text: str) -> str:
        """Spoken 'at image three' / 'image 3' becomes an @Image3 mention token."""

        def repl(m: re.Match[str]) -> str:
            word = m.group(3).lower()
            # Homophones (to/too/for) only count as numbers after an explicit
            # "at" - otherwise "an image for the background" would become @Image4.
            if not m.group(1) and word in ("to", "too", "for"):
                return m.group(0)
            n = cls._VOICE_NUM_WORDS.get(word) or (int(word) if word.isdigit() else 0)
            return f"@Image{n}" if n else m.group(0)

        return cls._VOICE_MENTION_RE.sub(repl, text or "")

    def _transcribe_voice(self, state: dict[str, Any]) -> None:
        """Transcribe recorded widget audio via the Griptape proxy (whisper-1).

        Fallback for environments without the browser Web Speech API (e.g. the
        desktop app): the widget records the microphone with MediaRecorder and
        ships a data-URI here; the transcribed text is appended to the prompt.
        Same proxy endpoint and billing as the standard Transcribe Audio node.
        """
        state = dict(state)
        audio_uri = str(state.pop("voiceAudio", "") or "")

        def fail(msg: str) -> None:
            state["statusMessage"] = f"Voice transcription failed: {msg}"
            self._push_state(state)

        if not audio_uri.startswith("data:audio"):
            fail("no audio received from the recorder")
            return
        if len(audio_uri) > 34_000_000:  # ~25MB decoded, the whisper limit
            fail("recording too large (25MB limit)")
            return
        api_key = self._gt_cloud_api_key()
        if not api_key:
            fail("GT_CLOUD_API_KEY is not set")
            return
        try:
            import requests  # type: ignore[reportMissingImports]
        except Exception as exc:
            fail(f"requests unavailable: {exc}")
            return

        base = os.getenv("GT_CLOUD_PROXY_BASE_URL") or os.getenv("GT_CLOUD_BASE_URL", "https://cloud.griptape.ai")
        base = base.rstrip("/") + "/api/proxy/v2/"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        try:
            resp = requests.post(
                base + "models/whisper-1",
                json={"file": audio_uri, "response_format": "json"},
                headers=headers,
                timeout=120,
            )
            resp.raise_for_status()
            gen_id = str(resp.json().get("generation_id") or "")
            if not gen_id:
                fail("proxy returned no generation id")
                return
            status = ""
            for _ in range(45):
                poll = requests.get(base + f"generations/{gen_id}", headers=headers, timeout=30)
                poll.raise_for_status()
                status = str(poll.json().get("status") or "")
                if status in ("COMPLETED", "FAILED", "ERRORED", "CANCELLED"):
                    break
                time.sleep(2)
            if status != "COMPLETED":
                fail(f"generation ended with status {status or 'TIMEOUT'}")
                return
            result = requests.get(base + f"generations/{gen_id}/result", headers=headers, timeout=60)
            result.raise_for_status()
            text = str(result.json().get("text") or "").strip()
        except Exception as exc:
            fail(str(exc))
            return
        if not text:
            fail("whisper returned no speech")
            return

        spoken = self._normalize_voice_mentions(text)
        current = str(state.get("text") or "")
        state["text"] = ((current.rstrip() + " ") if current.strip() else "") + spoken.strip()
        state["statusMessage"] = "Voice transcribed (whisper-1) and added to the prompt."
        self._push_state(state)
        self._publish_prompt(state)

    def _update_prompt_in_place(self, state: dict[str, Any]) -> None:
        """Apply the enabled enhancer(s) and write the result INTO the editor.

        The enhanced prompt (brackets converted back to @Image mentions so the
        pills render) replaces the editor text, and both enhancer toggles are
        switched off so a later Send doesn't re-apply them on top.
        """
        self._rescan_and_push(state)
        state = self._current_state()
        text = str(state.get("text") or "")
        if not text.strip():
            state["statusMessage"] = "Nothing to enhance: the prompt is empty."
            self._push_state(state)
            return

        converted = self._to_brackets(text)
        notes: list[str] = []
        if bool(state.get("enhance")):
            converted = self._enhance(converted, self._scanned_refs)
            notes.append("structure rules applied")
        if bool(state.get("llmEnhance")):
            model = str(state.get("llmModel") or DEFAULT_LLM_MODEL)
            converted, llm_error = self._llm_enhance(converted, model)
            notes.append(f"LLM skipped: {llm_error}" if llm_error else f"rewritten by {model}")

        mention_text = _BRACKET_RE.sub(lambda m: f"@Image{int(m.group(2))}", converted)
        state["text"] = mention_text
        # The editor now holds the enhanced prompt; turn the enhancers off so
        # Send / run pushes it verbatim instead of enhancing twice.
        state["enhance"] = False
        state["llmEnhance"] = False
        state["statusMessage"] = "Prompt updated in editor (" + "; ".join(notes) + "). Enhancer toggles switched off."
        self._push_state(state)
        self._publish_prompt(state)

    def _send_to_image_gen(self, state: dict[str, Any]) -> None:
        """Push only the images named in the prompt; drop leftover target slots.

        Two mentions become Input Images 1 and 2, and the prompt is rewritten
        to [Image 1] [Image 2] so GPT Image lines up. Extra slots from a
        previous send are deleted.
        """
        widget_refs = state.get("refs") if isinstance(state.get("refs"), list) else []
        refs = self._refs_for_send(widget_refs)
        self._scanned_refs = refs
        prompt_full = self._build_prompt(state, refs)

        mentioned = self._mentioned_ordered(prompt_full)
        push_refs = []
        for ref in self._slot_refs_for_mentions(refs, mentioned):
            if self._live_media_value(ref) in (None, "") and not self._ref_full_url(ref):
                continue
            push_refs.append(ref)
        prompt_push = self._compact_prompt(
            prompt_full, [int(r.get("index") or 0) for r in push_refs]
        )

        # Optional LLM rewrite (off by default). Runs after the prompt still
        # carries the original [Image N] tags so slot numbers stay aligned.
        llm_note = ""
        if bool(state.get("llmEnhance")):
            model = str(state.get("llmModel") or DEFAULT_LLM_MODEL)
            prompt_push, llm_error = self._llm_enhance(prompt_push, model)
            llm_note = f" LLM enhance skipped: {llm_error}." if llm_error else f" Prompt rewritten by {model}."

        all_targets = self._find_target_nodes()
        pick = str(state.get("sendTarget") or "all")
        group_name = pick[len(_GROUP_TARGET_PREFIX) :] if pick.startswith(_GROUP_TARGET_PREFIX) else ""
        targets = self._select_send_targets(state, all_targets)

        sent = 0
        errors: list[str] = []
        for node in targets:
            try:
                errors.extend(self._push_into_node(node, prompt_push, push_refs))
                sent += 1
            except Exception as exc:
                errors.append(f"{getattr(node, 'name', '?')}: {exc}")

        if not targets:
            if group_name:
                known = {str(g.get("name") or "") for g in self._find_groups()}
                if group_name in known:
                    status = f"Send failed: group '{group_name}' has no image gen nodes."
                else:
                    status = (
                        f"Send failed: group '{group_name}' not found. "
                        "Press Rescan after adding a group."
                    )
            elif pick not in ("", "all"):
                status = f"Send failed: image gen node '{pick}' not found."
            else:
                status = "Send failed: no Nano Banana / GPT Image / Seedream nodes found in this workflow."
        else:
            skipped = max(0, len(refs) - len(push_refs))
            dest = f"{sent} image gen node(s)"
            if group_name:
                dest += f" in group '{group_name}'"
            packed = ", ".join(
                f"[Image {i}]={(r.get('label') or r.get('tag') or '?')} (from @{r.get('tag') or ('Image' + str(r.get('index') or i))})"
                for i, r in enumerate(push_refs, start=1)
            )
            status = f"Sent {len(push_refs)} mentioned image(s) to {dest}."
            if packed:
                status += f" {packed}."
            if skipped > 0:
                status += f" {skipped} unmentioned image(s) not sent."
            if refs and not mentioned:
                status += " Tag images in the prompt with @Image1, @Image2, ... to send them."
            status += llm_note
            if errors:
                status += " Problems: " + "; ".join(errors[:3])
        final_state = self._current_state()
        final_state["statusMessage"] = status
        self._push_state(final_state)

    # ------------------------------------------------------------------ state

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
        lock = getattr(self, "_scan_lock", None)
        if lock is not None and not lock.acquire(timeout=8):
            return
        try:
            self._rescan_and_push_body(state, force=force)
        finally:
            if lock is not None:
                lock.release()

    def _rescan_and_push_body(self, state: dict[str, Any] | None = None, force: bool = False) -> None:
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
        status = f"Scanned workflow: {counts}."
        if self._scan_error:
            status = f"Scan problem ({self._scan_error}). Found {counts}."
        elif not refs:
            status = "Scan found no images. Run upstream Load Image nodes once, then press Rescan."
        prev_status = str(state.get("statusMessage") or "")
        prev_targets = list(state.get("targets") or [])
        prev_groups = list(state.get("groups") or [])
        targets = [getattr(n, "name", "") for n in self._find_target_nodes()]
        groups = self._find_groups()
        state["refs"] = refs
        state["scanMode"] = True
        state["statusMessage"] = status
        state["targets"] = targets
        state["groups"] = groups
        models = self._llm_model_choices()
        prev_models = list(state.get("llmModels") or [])
        state["llmModels"] = models
        # force=True on explicit Rescan clicks: the widget shows a
        # "Rescanning..." status that must always be replaced, even when
        # the scan found nothing new.
        if (
            force
            or not unchanged
            or status != prev_status
            or targets != prev_targets
            or groups != prev_groups
            or prev_models != models
        ):
            self._push_state(state)
        self._publish_prompt(state)
        try:
            self._last_import_sig = self._import_signature()
        except Exception:
            pass

    def _import_signature(self) -> tuple[tuple[str, str], ...]:
        """Sorted (source node, pixel stamp). Order changes do not count."""
        found = self._discover_imports()
        return tuple(sorted((asset["label"], asset["stamp"]) for asset in found))

    def _ensure_image_watch(self) -> None:
        """Refresh cards when a Load / PSD node publishes a different image.

        A rescan used to be the only way to notice, and it reused the old
        thumbnail whenever the filename matched. This watch only pushes when
        the pixel stamp changes, and it keeps the user's card order.
        """
        if getattr(self, "_thumb_watch_started", False):
            return
        self._thumb_watch_started = True

        def loop() -> None:
            misses = 0
            while misses < 5:
                time.sleep(1.5)
                try:
                    nodes = self._workflow_nodes()
                    alive = self in nodes.values() or getattr(self, "name", None) in nodes
                except Exception:
                    alive = False
                if not alive:
                    misses += 1
                    continue
                misses = 0
                try:
                    if self._syncing:
                        continue
                    sig = self._import_signature()
                    if sig == self._last_import_sig:
                        continue
                    self._last_import_sig = sig
                    self._rescan_and_push()
                except Exception:
                    continue

        threading.Thread(target=loop, name="omni-image-watch", daemon=True).start()

    @staticmethod
    def _count_text(refs: list[dict[str, Any]]) -> str:
        return f"{len(refs)} image assets"

    # ------------------------------------------------------------------ prompt

    @staticmethod
    def _to_brackets(text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            return f"[Image {match.group(2)}]"

        return _MENTION_RE.sub(repl, text or "")

    @staticmethod
    def _mentioned(converted: str) -> set[int]:
        return {int(m.group(2)) for m in _BRACKET_RE.finditer(converted)}

    @staticmethod
    def _mentioned_ordered(converted: str) -> list[int]:
        """Unique [Image N] numbers in the order they appear in the prompt."""
        out: list[int] = []
        seen: set[int] = set()
        for match in _BRACKET_RE.finditer(converted or ""):
            index = int(match.group(2))
            if index in seen:
                continue
            seen.add(index)
            out.append(index)
        return out

    def _enhance(self, converted: str, refs: list[dict[str, Any]]) -> str:
        """Structure the prompt for reference-image generation.

        Only adds constraints for images the user actually mentioned
        (scanned-but-unmentioned assets are not assumed to be wanted).
        """
        mentioned = sorted(self._mentioned(converted))
        role_lines: list[str] = []
        if mentioned:
            tags = ", ".join(f"[Image {i}]" for i in mentioned)
            role_lines.append(
                f"Preserve the subject's identity, wardrobe, proportions, and distinctive details from {tags} exactly."
            )
            role_lines.append("Blend the referenced elements into one coherent, photorealistic composition.")

        body = re.sub(r"[ \t]+", " ", (converted or "").strip())
        if body:
            body = body[0].upper() + body[1:]
            if body[-1] not in ".!?":
                body += "."
        if role_lines:
            body = (body + "\n\n" if body else "") + " ".join(role_lines)
        return body.strip()

    def _build_prompt(self, state: dict[str, Any], refs: list[dict[str, Any]]) -> str:
        converted = self._to_brackets(str(state.get("text") or ""))
        if bool(state.get("enhance")):
            converted = self._enhance(converted, refs)
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
        if param_name == "composer" and isinstance(value, dict) and not self._syncing:
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
        send_nonce = value.get("sendNonce")
        enhance_nonce = value.get("enhanceNonce")
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
                self._send_to_image_gen(value)
            except Exception as exc:
                try:
                    failed = dict(value)
                    failed["doSend"] = False
                    failed["statusMessage"] = f"Send failed: {exc}"
                    self._push_state(failed)
                except Exception:
                    pass
            return
        if self._last_enhance_nonce is None:
            self._last_enhance_nonce = enhance_nonce or 0
        elif enhance_nonce and enhance_nonce != self._last_enhance_nonce:
            self._last_enhance_nonce = enhance_nonce
            self._update_prompt_in_place(value)
            return
        voice_nonce = value.get("voiceNonce")
        if self._last_voice_nonce is None:
            self._last_voice_nonce = voice_nonce or 0
        elif voice_nonce and voice_nonce != self._last_voice_nonce:
            self._last_voice_nonce = voice_nonce
            self._transcribe_voice(value)
            return
        needs_scan = (
            self._last_scan_nonce is None
            or (nonce and nonce != self._last_scan_nonce)
            or not widget_refs
        )
        if needs_scan:
            explicit_rescan = bool(
                nonce and self._last_scan_nonce is not None and nonce != self._last_scan_nonce
            )
            self._last_scan_nonce = nonce or 0
            self._rescan_and_push(value, force=explicit_rescan)
        else:
            self._adopt_widget_order(widget_refs)
            self._publish_prompt(value)

    def _adopt_widget_order(self, widget_refs: Any) -> None:
        """When the user drags thumbnails, adopt the widget's new tag order."""
        if not isinstance(widget_refs, list) or not widget_refs:
            return

        def slot_id(ref: dict[str, Any]) -> str:
            label = str(ref.get("label") or "").strip().lower()
            if label:
                return "label:" + label
            return "key:" + str(ref.get("key") or "")

        widget_ids = [slot_id(r) for r in widget_refs if isinstance(r, dict) and slot_id(r) != "key:"]
        known = [r for r in self._scanned_refs if isinstance(r, dict)]
        known_ids = [slot_id(r) for r in known]
        if not widget_ids or set(widget_ids) != set(known_ids):
            return
        if widget_ids == known_ids:
            return
        by_id = {slot_id(r): r for r in known}
        ordered: list[dict[str, Any]] = []
        for ref in widget_refs:
            if not isinstance(ref, dict):
                continue
            match = by_id.get(slot_id(ref))
            if match is not None:
                ordered.append(match)
        if len(ordered) != len(known):
            return
        renumbered: list[dict[str, Any]] = []
        for index, match in enumerate(ordered, start=1):
            ref = dict(match)
            ref["index"] = index
            ref["tag"] = f"Image{index}"
            renumbered.append(ref)
        self._scanned_refs = renumbered
        self._publish_outputs(self._scanned_refs)

    def process(self) -> None:
        # Run path must stay CHEAP: the engine queues every unwired data node
        # as a flow entry point, so this executes once per queued run, on the
        # engine's event loop. Reuse the refs from the editor session when we
        # have them (node instances are long-lived); only a fresh instance
        # after an engine restart pays for one thumb-free scan. No widget
        # state push here - that stays an editor-time concern (Rescan button
        # / after_value_set).
        state = self._current_state()
        refs = self._scanned_refs
        if not refs:
            prev_refs = state.get("refs") if isinstance(state.get("refs"), list) else []
            refs = self._scan_workflow(prev_refs=prev_refs, generate_thumbs=False)
            self._scanned_refs = refs
        self._publish_outputs(refs)

        prompt = self._build_prompt(state, refs)
        if bool(state.get("llmEnhance")):
            model = str(state.get("llmModel") or DEFAULT_LLM_MODEL)
            prompt, _llm_error = self._llm_enhance(prompt, model)

        self.parameter_output_values["prompt"] = prompt
