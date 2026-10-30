export default function ImageGenPromptWidget(container, props) {
  var value = (props && props.value && typeof props.value === "object") ? props.value : {};
  var onChange = props ? props.onChange : null;
  var disabled = !!(props && props.disabled);
  var widgetHeight = (props && props.height && props.height > 0) ? Math.max(380, props.height - 24) : 560;

  var state = {
    text: String(value.text || ""),
    enhance: !!value.enhance,
    refs: Array.isArray(value.refs) ? value.refs.slice() : [],
    statusMessage: String(value.statusMessage || ""),
    scanMode: !!value.scanMode,
    scanNonce: Number(value.scanNonce || 0) || 0,
    targets: Array.isArray(value.targets) ? value.targets.slice() : [],
    groups: Array.isArray(value.groups) ? value.groups.slice() : [],
    sendTarget: String(value.sendTarget || "all"),
    sendNonce: Number(value.sendNonce || 0) || 0,
    doSend: !!value.doSend,
    enhanceNonce: Number(value.enhanceNonce || 0) || 0,
    voiceNonce: Number(value.voiceNonce || 0) || 0,
    thumbScale: Math.min(3, Math.max(1, Number(value.thumbScale || 1) || 1)),
    llmEnhance: !!value.llmEnhance,
    llmModel: String(value.llmModel || "gpt-4.1-mini"),
    llmModels: (Array.isArray(value.llmModels) && value.llmModels.length)
      ? value.llmModels.slice()
      : ["gpt-6-sol", "gpt-6-luna", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna",
         "gpt-5.5", "gpt-5.4", "gpt-5.2", "gpt-5.2-chat", "gpt-5.1", "gpt-5", "gpt-5-mini",
         "gpt-5-nano", "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano", "gpt-4o",
         "claude-sonnet-5-5", "claude-opus-5-5", "claude-sonnet-5", "claude-opus-5",
         "claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5",
         "gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite",
         "gemini-3.1-pro", "gemini-3.1-flash-lite", "gemini-3-flash",
         "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite",
         "deepseek-v3", "llama3-3-70b-instruct-v1"]
  };

  // Shot Planner V2 palette: dark gray chrome with a muted amber accent.
  var FONT = "ui-monospace,'Cascadia Code','JetBrains Mono',Consolas,monospace";
  var KIND_COLORS = { image: "#d9c6a4", video: "#a58050", audio: "#8a929e" };
  var KIND_ICONS = {
    image: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>',
    video: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="4" width="15" height="16" rx="2"/><path d="M22 8l-5 4 5 4V8z"/></svg>',
    audio: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>'
  };
  var MENTION_RE = /@(image|video|audio)[\s_-]?(\d+)/gi;

  var placeholderText = state.scanMode
    ? "Describe your image... type @ to reference any image in the workflow"
    : "Describe your image... type @ to reference a connected input";

  container.innerHTML =
    "<style>" +
      ".igp-root:fullscreen{width:100vw !important;height:100vh !important;border-radius:0 !important;}" +
      ".igp-root.igp-fs{position:fixed !important;inset:0 !important;width:100vw !important;height:100vh !important;z-index:99999 !important;border-radius:0 !important;}" +
    "</style>" +
    '<div class="igp-root sdp-root nodrag nowheel" style="' +
      "display:flex;flex-direction:row;gap:8px;padding:10px;box-sizing:border-box;" +
      "background:#0c0e11;border:1px solid #21252c;border-radius:10px;" +
      "font-family:" + FONT + ";font-size:11.5px;color:#c6cad1;" +
      "height:" + widgetHeight + "px;overflow:hidden;position:relative;" +
    '">' +
      // Left sidebar: reference cards in a 2-column grid (thumbnail + tag underneath)
      '<div class="sdp-side" style="' +
        "display:flex;flex-direction:column;gap:6px;width:178px;flex:0 0 178px;min-height:0;" +
      '">' +
        '<span style="color:#8a929e;font-size:11px;">References</span>' +
        '<span class="sdp-refcount" style="color:#6c7481;font-size:10px;line-height:1.35;"></span>' +
        (state.scanMode
          ? '<button class="sdp-rescan" type="button" style="' +
              "padding:3px 8px;border-radius:6px;border:1px solid #6b5836;background:#241d13;color:#d9c6a4;" +
              "font-size:11px;cursor:pointer;font-family:inherit;width:100%;" +
            '">Rescan assets</button>'
          : "") +
        '<div style="display:flex;align-items:center;gap:6px;">' +
          '<span style="color:#6c7481;font-size:10px;">Size</span>' +
          '<input class="sdp-thumbscale" type="range" min="1" max="3" step="0.25" value="' + state.thumbScale + '" ' +
            'title="Thumbnail size (1.5x and up = one column)" style="flex:1;accent-color:#a58050;cursor:pointer;" />' +
        "</div>" +
        '<div class="sdp-cards" style="' +
          "flex:1;min-height:0;overflow-y:auto;display:grid;grid-template-columns:1fr 1fr;" +
          "gap:6px;align-content:start;padding-right:2px;" +
        '"></div>' +
      "</div>" +
      // Right column: header (font slider + fullscreen) + editor + send + toggle + status
      '<div style="display:flex;flex-direction:column;gap:8px;flex:1;min-width:0;">' +
        '<div style="display:flex;align-items:center;gap:8px;">' +
          '<span style="color:#8a929e;font-size:11px;flex:1;">Prompt</span>' +
          '<button class="sdp-mic" type="button" title="Dictate prompt (voice to text)" style="' +
            "display:inline-flex;align-items:center;gap:4px;padding:2px 10px;border-radius:6px;border:1px solid #333a44;" +
            "background:#161a20;color:#c6cad1;font-size:11px;cursor:pointer;font-family:inherit;flex:0 0 auto;" +
          '"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>Voice</button>' +
          '<span style="color:#6c7481;font-size:10px;">Aa</span>' +
          '<input class="sdp-font" type="range" min="10" max="22" step="0.5" value="' + state.fontSize + '" ' +
            'title="Prompt font size" style="width:90px;accent-color:#a58050;cursor:pointer;" />' +
          '<button class="sdp-fs" type="button" title="Toggle fullscreen" style="' +
            "padding:2px 10px;border-radius:6px;border:1px solid #333a44;background:#161a20;color:#c6cad1;" +
            "font-size:11px;cursor:pointer;font-family:inherit;flex:0 0 auto;" +
          '">&#9974; Full</button>' +
        "</div>" +
        '<label class="sdp-toggle-row" style="display:flex;align-items:center;gap:8px;cursor:pointer;user-select:none;">' +
          '<span class="sdp-toggle" style="' +
            "position:relative;width:34px;height:18px;border-radius:9px;background:#21252c;transition:background .15s;flex:0 0 auto;" +
          '"><span class="sdp-knob" style="' +
            "position:absolute;top:2px;left:2px;width:14px;height:14px;border-radius:50%;background:#6c7481;transition:left .15s,background .15s;" +
          '"></span></span>' +
          '<span style="color:#c6cad1;">Image Prompt Enhancer</span>' +
          '<span style="color:#6c7481;font-size:10px;">rule-based: subject/scene first, identity constraints last</span>' +
        "</label>" +
        '<div class="sdp-llm-row" style="display:flex;align-items:center;gap:8px;user-select:none;">' +
          '<span class="sdp-llm-toggle" style="' +
            "position:relative;width:34px;height:18px;border-radius:9px;background:#21252c;transition:background .15s;flex:0 0 auto;cursor:pointer;" +
          '"><span class="sdp-llm-knob" style="' +
            "position:absolute;top:2px;left:2px;width:14px;height:14px;border-radius:50%;background:#6c7481;transition:left .15s,background .15s;" +
          '"></span></span>' +
          '<span class="sdp-llm-label" style="color:#c6cad1;cursor:pointer;">AI Prompt Enhancer</span>' +
          '<select class="sdp-llm-model" title="LLM used to rewrite the prompt (billed via Griptape Cloud)" style="' +
            "flex:0 1 170px;min-width:0;padding:2px 6px;border-radius:6px;border:1px solid #333a44;" +
            "background:#0f1116;color:#c6cad1;font-family:inherit;font-size:10.5px;outline:none;" +
          '"></select>' +
          '<button class="sdp-update" type="button" title="Apply the enabled enhancer(s) to the prompt and show the result in the editor. Toggles switch off afterwards so Send won\'t re-apply." style="' +
            "margin-left:auto;padding:4px 14px;border-radius:6px;border:1px solid #6b5836;background:#241d13;color:#d9c6a4;" +
            "font-size:11px;font-weight:600;cursor:pointer;font-family:inherit;flex:0 0 auto;" +
          '">Update Prompt</button>' +
        "</div>" +
        '<div class="sdp-editor-wrap" style="position:relative;flex:1;min-height:120px;">' +
          '<div class="sdp-input" ' + (disabled ? "" : 'contenteditable="true"') + ' spellcheck="true" lang="en-US" style="' +
            "position:absolute;inset:0;padding:10px;box-sizing:border-box;overflow:auto;" +
            "background:#0f1116;border:1px solid #21252c;border-radius:8px;" +
            "white-space:pre-wrap;word-wrap:break-word;color:#c6cad1;outline:none;" +
            "caret-color:#d9c6a4;font:12.5px/1.7 " + FONT + ";" +
          '"></div>' +
          '<div class="sdp-placeholder" style="' +
            "position:absolute;top:10px;left:10px;right:10px;pointer-events:none;color:#6c7481;" +
            "font:12.5px/1.7 " + FONT + ";display:none;" +
          '">' + placeholderText + "</div>" +
          '<div class="sdp-menu" style="' +
            "position:absolute;display:none;z-index:30;min-width:230px;max-width:300px;max-height:200px;overflow-y:auto;" +
            "background:#12151a;border:1px solid #333a44;border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,.5);padding:4px;" +
          '"></div>' +
        "</div>" +
        '<div class="sdp-send-row" style="display:flex;gap:6px;align-items:center;">' +
          '<span class="sdp-chars" title="Prompt length as exported (with [Image N] brackets)" style="' +
            "color:#d9c6a4;font-size:10.5px;flex:0 0 auto;white-space:nowrap;" +
          '"></span>' +
          '<select class="sdp-target" title="Send to every image gen node, one node, or every image gen node in a canvas group" style="' +
            "flex:1;min-width:0;padding:4px 6px;border-radius:6px;border:1px solid #333a44;" +
            "background:#0f1116;color:#c6cad1;font-family:inherit;font-size:11px;outline:none;" +
          '"></select>' +
          '<button class="sdp-send" type="button" style="' +
            "padding:4px 14px;border-radius:6px;border:1px solid #6b5836;background:#241d13;color:#d9c6a4;" +
            "font-size:11px;font-weight:600;cursor:pointer;font-family:inherit;flex:0 0 auto;" +
          '">Send to Image Gen</button>' +
        "</div>" +
        '<div class="sdp-status" style="color:#6c7481;font-size:10px;min-height:12px;"></div>' +
      "</div>" +
      // Hover preview card (only used by mentions inside the prompt)
      '<div class="sdp-hover" style="' +
        "position:absolute;display:none;z-index:40;pointer-events:none;" +
        "background:#12151a;border:1px solid #333a44;border-radius:10px;box-shadow:0 10px 30px rgba(0,0,0,.6);" +
        "padding:6px;max-width:240px;" +
      '"></div>' +
    "</div>";

  var root = container.querySelector(".igp-root");
  var sideEl = container.querySelector(".sdp-side");
  var cardsEl = container.querySelector(".sdp-cards");
  var refCountEl = container.querySelector(".sdp-refcount");
  var input = container.querySelector(".sdp-input");
  var placeholderEl = container.querySelector(".sdp-placeholder");
  var menu = container.querySelector(".sdp-menu");
  var editorWrap = container.querySelector(".sdp-editor-wrap");
  var targetSel = container.querySelector(".sdp-target");
  var sendBtn = container.querySelector(".sdp-send");
  var charsEl = container.querySelector(".sdp-chars");
  var fontSlider = container.querySelector(".sdp-font");
  var fsBtn = container.querySelector(".sdp-fs");
  var micBtn = container.querySelector(".sdp-mic");
  var toggleRow = container.querySelector(".sdp-toggle-row");
  var toggleEl = container.querySelector(".sdp-toggle");
  var knobEl = container.querySelector(".sdp-knob");
  var llmToggleEl = container.querySelector(".sdp-llm-toggle");
  var llmKnobEl = container.querySelector(".sdp-llm-knob");
  var llmLabelEl = container.querySelector(".sdp-llm-label");
  var llmModelSel = container.querySelector(".sdp-llm-model");
  var updateBtn = container.querySelector(".sdp-update");
  var statusEl = container.querySelector(".sdp-status");
  var hoverEl = container.querySelector(".sdp-hover");

  var menuState = { open: false, items: [], active: 0 };
  var lastPayload = "";
  var dragIdx = null;
  var pendingUpdate = null;
  var lastLocalEditAt = 0;   // last local typing/insert; echoes within this window never rewrite the editor
  var expectTextUntil = 0;   // accept node-side text rewrites (Update Prompt / voice) until this time
  var syncTimer = null;

  // The canvas may host the widget behind a shadow root, where
  // document.activeElement reports a wrapper instead of the editor. Resolve
  // the real active element through the root node so focus detection works.
  function editorFocused() {
    var ae = document.activeElement;
    try {
      var rn = input.getRootNode ? input.getRootNode() : null;
      if (rn && rn.activeElement) ae = rn.activeElement;
    } catch (_) {}
    return ae === input || (ae && input.contains(ae));
  }

  function esc(text) {
    return String(text || "")
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#039;");
  }

  function stop(e) { e.stopPropagation(); }

  // The editor canvas scales nodes with a CSS transform; getBoundingClientRect
  // returns scaled pixels while style.left/top apply unscaled. Convert.
  function toLocal(clientX, clientY, el) {
    var r = el.getBoundingClientRect();
    var s = (el.offsetWidth > 0 && r.width > 0) ? (r.width / el.offsetWidth) : 1;
    return { x: (clientX - r.left) / s, y: (clientY - r.top) / s };
  }

  function chipThumb(ref) {
    if (ref.thumb) return ref.thumb;
    if (ref.kind === "image" && ref.url && /^(https?:|data:)/.test(ref.url)) return ref.url;
    return "";
  }

  function hookImgFallback(img, iconHtml) {
    img.addEventListener("error", function () {
      var span = img.parentNode;
      if (span) span.innerHTML = iconHtml || "";
    });
  }

  // ---------------------------------------------------------------- refs / tags

  function findRef(kind, num) {
    for (var i = 0; i < state.refs.length; i += 1) {
      var r = state.refs[i];
      if (String(r.kind) === kind && Number(r.index) === num) return r;
    }
    return null;
  }

  function assetDisplayName(ref, tag) {
    var name = String((ref && ref.label) || "").trim();
    return name || ("@" + tag);
  }

  // ---------------------------------------------------------------- editor (contenteditable)

  function makeMentionEl(kind, num) {
    var tag = kind.charAt(0).toUpperCase() + kind.slice(1) + num;
    var ref = findRef(kind, num);
    var color = KIND_COLORS[kind] || "#c6cad1";
    var span = document.createElement("span");
    span.className = "sdp-mention";
    span.setAttribute("data-tag", tag);
    // The tag is a fixed SLOT: pills keep their label forever and the asset
    // occupying the slot can change (data-key tracks the current occupant).
    if (ref && ref.key) span.setAttribute("data-key", String(ref.key));
    span.contentEditable = "false";
    span.style.cssText =
      "display:inline-flex;align-items:center;gap:4px;padding:0 6px 0 3px;margin:0 1px;" +
      "border-radius:10px;vertical-align:text-bottom;line-height:1.4;cursor:default;" +
      "background:" + color + "1a;border:1px solid " + color + "44;color:" + color + ";" +
      (ref ? "" : "opacity:.45;");
    var thumb = ref ? chipThumb(ref) : "";
    if (thumb) {
      var img = document.createElement("img");
      img.src = thumb;
      img.draggable = false;
      img.style.cssText = "width:15px;height:15px;border-radius:7px;object-fit:cover;flex:0 0 auto;";
      span.appendChild(img);
      hookImgFallback(img, "");
    }
    var caption = document.createElement("span");
    caption.className = "sdp-mention-name";
    caption.style.cssText = "max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;";
    caption.textContent = assetDisplayName(ref, tag);
    caption.title = ref && ref.label ? String(ref.label) + "  @" + tag : "@" + tag;
    span.appendChild(caption);
    // Hover preview: look the ref up at hover time so the preview always
    // shows the asset CURRENTLY holding this slot (assets can be swapped).
    span.addEventListener("mouseenter", function () {
      var current = findRef(kind, num);
      if (current) showHover(current, span);
    });
    span.addEventListener("mouseleave", hideHover);
    return span;
  }

  function buildRichFragment(text) {
    // Text -> DOM fragment with @Image1 tokens as mention pills.
    var frag = document.createDocumentFragment();
    var lastNode = null;
    var lines = String(text || "").split("\n");
    for (var i = 0; i < lines.length; i += 1) {
      if (i > 0) {
        lastNode = document.createElement("br");
        frag.appendChild(lastNode);
      }
      var line = lines[i];
      var last = 0;
      MENTION_RE.lastIndex = 0;
      var m;
      while ((m = MENTION_RE.exec(line)) !== null) {
        if (m.index > last) {
          lastNode = document.createTextNode(line.slice(last, m.index));
          frag.appendChild(lastNode);
        }
        lastNode = makeMentionEl(m[1].toLowerCase(), Number(m[2]));
        frag.appendChild(lastNode);
        last = m.index + m[0].length;
      }
      if (last < line.length) {
        lastNode = document.createTextNode(line.slice(last));
        frag.appendChild(lastNode);
      }
    }
    // A trailing pill hides the caret; a zero-width text node keeps it visible
    // (stripped again during serialization).
    if (lastNode && lastNode.nodeType !== 3) {
      lastNode = document.createTextNode("\u200b");
      frag.appendChild(lastNode);
    }
    return { fragment: frag, lastNode: lastNode };
  }

  function renderEditorFromText(text) {
    input.innerHTML = "";
    input.appendChild(buildRichFragment(text).fragment);
    updatePlaceholder();
  }

  function serializeNode(node) {
    var out = "";
    for (var n = node.firstChild; n; n = n.nextSibling) {
      if (n.nodeType === 3) {
        out += n.nodeValue;
      } else if (n.nodeName === "BR") {
        out += "\n";
      } else if (n.classList && n.classList.contains("sdp-mention")) {
        out += "@" + n.getAttribute("data-tag");
      } else if (n.nodeType === 1) {
        // Block wrappers (div/p from paste or browser edits) imply a newline.
        var inner = serializeNode(n);
        if (out && out.charAt(out.length - 1) !== "\n") out += "\n";
        out += inner;
      }
    }
    return out;
  }

  function updatePlaceholder() {
    var empty = !serializeNode(input).trim();
    placeholderEl.style.display = empty ? "block" : "none";
  }

  function caretRange() {
    var sel = window.getSelection();
    if (!sel || sel.rangeCount === 0) return null;
    var range = sel.getRangeAt(0);
    if (!input.contains(range.startContainer)) return null;
    return range;
  }

  function setCaretAfter(node) {
    var sel = window.getSelection();
    if (!sel) return;
    var range = document.createRange();
    range.setStartAfter(node);
    range.collapse(true);
    sel.removeAllRanges();
    sel.addRange(range);
  }

  function insertMention(ref, replaceQuery) {
    input.focus();
    var range = caretRange();
    var span = makeMentionEl(ref.kind, Number(ref.index));
    var space = document.createTextNode("\u00a0");
    if (range) {
      if (replaceQuery && range.collapsed && range.startContainer.nodeType === 3) {
        // Remove the '@query' the user was typing.
        var textNode = range.startContainer;
        var upto = textNode.nodeValue.slice(0, range.startOffset);
        var at = upto.lastIndexOf("@");
        if (at >= 0 && !(at > 0 && /[\w\]]/.test(upto.charAt(at - 1)))) {
          range.setStart(textNode, at);
        }
      }
      range.deleteContents();
      range.insertNode(span);
      span.parentNode.insertBefore(space, span.nextSibling);
    } else {
      input.appendChild(span);
      input.appendChild(space);
    }
    setCaretAfter(space);
    closeMenu();
    handleInput();
  }

  // ---------------------------------------------------------------- reordering

  function renumberRefs() {
    var counts = { image: 0, video: 0, audio: 0 };
    for (var i = 0; i < state.refs.length; i += 1) {
      var r = state.refs[i];
      counts[r.kind] = (counts[r.kind] || 0) + 1;
      r.index = counts[r.kind];
      r.tag = r.kind.charAt(0).toUpperCase() + r.kind.slice(1) + r.index;
    }
  }

  function rebindMentions() {
    // Tags are fixed slots: after assets are swapped around, each pill keeps
    // its label but rebinds to (and shows the thumbnail of) the asset that
    // NOW occupies its slot.
    var pills = input.querySelectorAll(".sdp-mention");
    for (var i = 0; i < pills.length; i += 1) {
      var pill = pills[i];
      var m = /^(image|video|audio)(\d+)$/i.exec(pill.getAttribute("data-tag") || "");
      if (!m) continue;
      var ref = findRef(m[1].toLowerCase(), Number(m[2]));
      if (ref && ref.key) pill.setAttribute("data-key", String(ref.key));
      else pill.removeAttribute("data-key");
      pill.style.opacity = ref ? "1" : "0.45";
      var thumb = ref ? chipThumb(ref) : "";
      var img = pill.querySelector("img");
      if (img && thumb) {
        img.src = thumb;
      } else if (img && !thumb) {
        try { pill.removeChild(img); } catch (_) {}
      } else if (!img && thumb) {
        var newImg = document.createElement("img");
        newImg.src = thumb;
        newImg.draggable = false;
        newImg.style.cssText = "width:15px;height:15px;border-radius:7px;object-fit:cover;flex:0 0 auto;";
        pill.insertBefore(newImg, pill.firstChild);
        hookImgFallback(newImg, "");
      }
      var nameEl = pill.querySelector(".sdp-mention-name");
      var tag = pill.getAttribute("data-tag") || "";
      if (nameEl) {
        nameEl.textContent = assetDisplayName(ref, tag);
        nameEl.title = ref && ref.label ? String(ref.label) + "  @" + tag : "@" + tag;
      }
    }
  }

  function finishReorder() {
    pendingUpdate = null; // anything queued mid-drag predates this reorder
    renumberRefs();
    renderCards();
    // The prompt TEXT is untouched by design: dragging swaps which asset
    // occupies each @ tag slot, so only the pill bindings/thumbnails change.
    rebindMentions();
    handleInput();
    syncToNode();
  }

  // ---------------------------------------------------------------- rendering

  function renderCards() {
    refCountEl.textContent = state.refs.length
      ? state.refs.length + " found - click to insert, drag to reorder"
      : (state.scanMode
          ? "no images found - add Load Image nodes, save, then press Rescan"
          : "connect images on the left");
    var html = "";
    for (var i = 0; i < state.refs.length; i += 1) {
      var r = state.refs[i];
      var color = KIND_COLORS[r.kind] || "#c6cad1";
      var thumbUrl = chipThumb(r);
      html += '<div class="sdp-card" data-idx="' + i + '" style="' +
        "display:flex;flex-direction:column;border-radius:8px;overflow:hidden;cursor:pointer;flex:0 0 auto;" +
        "background:#12151a;border:1px solid #21252c;" +
      '">' +
        '<span class="sdp-card-thumb" style="' +
          "display:flex;width:100%;aspect-ratio:1/1;align-items:center;justify-content:center;" +
          "background:#0f1116;color:" + color + ";overflow:hidden;" +
        '">' +
          (thumbUrl
            ? '<img src="' + esc(thumbUrl) + '" style="width:100%;height:100%;object-fit:contain;" draggable="false"/>'
            : KIND_ICONS[r.kind] || "") +
        "</span>" +
        '<span style="display:flex;flex-direction:column;gap:1px;padding:4px 6px;" title="' +
          esc((r.label ? r.label + "  " : "") + "@" + r.tag) + '">' +
          '<span style="color:' + color + ';font-size:11px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' +
            esc(r.label || ("@" + r.tag)) + "</span>" +
          (r.label
            ? '<span style="color:#6c7481;font-size:9.5px;">@' + esc(r.tag) + "</span>"
            : "") +
        "</span>" +
      "</div>";
    }
    cardsEl.innerHTML = html;
    applyThumbScale();
    var cards = cardsEl.querySelectorAll(".sdp-card");
    for (var j = 0; j < cards.length; j += 1) {
      (function (card) {
        var ref = state.refs[Number(card.getAttribute("data-idx"))];
        var img = card.querySelector("img");
        if (img) hookImgFallback(img, KIND_ICONS[ref.kind]);
        card.addEventListener("click", function (e) {
          stop(e);
          if (disabled) return;
          insertMention(ref, false);
        });
        card.addEventListener("mouseenter", function () { card.style.borderColor = "#333a44"; });
        card.addEventListener("mouseleave", function () { card.style.borderColor = "#21252c"; });

        // Drag to reorder: tags renumber and prompt pills re-label automatically.
        card.draggable = !disabled;
        card.addEventListener("dragstart", function (e) {
          stop(e);
          dragIdx = Number(card.getAttribute("data-idx"));
          card.style.opacity = "0.45";
          try {
            e.dataTransfer.setData("text/plain", String(dragIdx));
            e.dataTransfer.effectAllowed = "move";
          } catch (_) {}
        });
        card.addEventListener("dragend", function () {
          card.style.opacity = "1";
          dragIdx = null;
          applyPendingUpdate();
        });
        card.addEventListener("dragover", function (e) {
          e.preventDefault();
          stop(e);
          if (dragIdx !== null) card.style.borderColor = "#a58050";
        });
        card.addEventListener("dragleave", function () {
          card.style.borderColor = "#21252c";
        });
        card.addEventListener("drop", function (e) {
          e.preventDefault();
          stop(e);
          card.style.borderColor = "#21252c";
          var to = Number(card.getAttribute("data-idx"));
          if (dragIdx === null || dragIdx === to || !state.refs[dragIdx]) return;
          // Move the dragged card. The others shift to close the gap.
          // Swapping used to make a third card jump to the slot you left.
          var moved = state.refs.splice(dragIdx, 1)[0];
          state.refs.splice(to, 0, moved);
          dragIdx = null;
          finishReorder();
        });
      })(cards[j]);
    }
  }

  function groupPrefix() { return "group:"; }

  function groupMemberCount(group) {
    return Array.isArray(group && group.members) ? group.members.length : 0;
  }

  function renderTargets() {
    var groups = Array.isArray(state.groups) ? state.groups : [];
    var html = '<option value="all">All image gen nodes (' + state.targets.length + ")</option>";
    if (groups.length) {
      html += '<optgroup label="Groups">';
      for (var g = 0; g < groups.length; g += 1) {
        var group = groups[g] || {};
        var gname = String(group.name || "");
        if (!gname) continue;
        var gval = groupPrefix() + gname;
        var n = groupMemberCount(group);
        var kind = String(group.kind || "regular") === "subflow" ? "subflow" : "group";
        html += '<option value="' + esc(gval) + '"' + (state.sendTarget === gval ? " selected" : "") + ">"
          + esc(gname) + " — " + n + " node" + (n === 1 ? "" : "s") + " (" + kind + ")</option>";
      }
      html += "</optgroup>";
    }
    if (state.targets.length) {
      html += '<optgroup label="Image gen nodes">';
      for (var i = 0; i < state.targets.length; i += 1) {
        var name = String(state.targets[i] || "");
        html += '<option value="' + esc(name) + '"' + (state.sendTarget === name ? " selected" : "") + ">" + esc(name) + "</option>";
      }
      html += "</optgroup>";
    }
    targetSel.innerHTML = html;
    var wanted = state.sendTarget || "all";
    targetSel.value = wanted;
    if (targetSel.value !== wanted && wanted !== "all") {
      var stale = document.createElement("option");
      stale.value = wanted;
      stale.selected = true;
      stale.textContent = wanted.indexOf(groupPrefix()) === 0
        ? (wanted.slice(groupPrefix().length) + " (missing group)")
        : (wanted + " (missing)");
      targetSel.appendChild(stale);
    }
    sendBtn.disabled = state.targets.length === 0;
    sendBtn.style.opacity = state.targets.length === 0 ? "0.5" : "1";
    sendBtn.title = state.targets.length === 0
      ? "No Nano Banana / GPT Image / Seedream nodes found in this workflow (press Rescan after adding one)."
      : "Write the prompt + ordered reference images into the selected node, every node, or every image gen node in a group. No wires needed.";
  }

  function renderToggle() {
    toggleEl.style.background = state.enhance ? "#a58050" : "#21252c";
    knobEl.style.left = state.enhance ? "18px" : "2px";
    knobEl.style.background = state.enhance ? "#0c0e11" : "#6c7481";
  }

  function renderLlm() {
    llmToggleEl.style.background = state.llmEnhance ? "#a58050" : "#21252c";
    llmKnobEl.style.left = state.llmEnhance ? "18px" : "2px";
    llmKnobEl.style.background = state.llmEnhance ? "#0c0e11" : "#6c7481";
    var html = "";
    var found = false;
    for (var i = 0; i < state.llmModels.length; i += 1) {
      var name = String(state.llmModels[i] || "");
      var sel = state.llmModel === name;
      if (sel) found = true;
      html += '<option value="' + esc(name) + '"' + (sel ? " selected" : "") + ">" + esc(name) + "</option>";
    }
    // A saved model that fell out of the catalog stays selectable.
    if (!found && state.llmModel) {
      html = '<option value="' + esc(state.llmModel) + '" selected>' + esc(state.llmModel) + "</option>" + html;
    }
    llmModelSel.innerHTML = html;
    llmModelSel.disabled = !state.llmEnhance;
    llmModelSel.style.opacity = state.llmEnhance ? "1" : "0.5";
  }

  function renderStatus() {
    statusEl.textContent = state.statusMessage || "";
  }

  function renderCharCount() {
    // Count the prompt as exported (mentions in [Image N] bracket form).
    var exported = String(state.text || "").replace(MENTION_RE, function (_m, kind, num) {
      var k = kind.toLowerCase();
      return "[" + k.charAt(0).toUpperCase() + k.slice(1) + " " + num + "]";
    });
    var n = exported.length;
    charsEl.textContent = n ? n.toLocaleString() + " chars" : "";
  }

  // ---------------------------------------------------------------- hover card (prompt mentions only)

  function showHover(ref, anchorEl) {
    var inner = "";
    var full = (ref.url && /^(https?:|data:)/.test(ref.url)) ? ref.url : "";
    if (ref.kind === "image" && (full || ref.thumb)) {
      inner = '<img class="sdp-hover-media" src="' + esc(full || ref.thumb) + '" style="display:block;max-width:220px;max-height:160px;border-radius:6px;" draggable="false"/>';
    } else {
      var color = KIND_COLORS[ref.kind] || "#c6cad1";
      inner = '<div style="width:120px;height:60px;display:flex;align-items:center;justify-content:center;color:' + color + ';">' +
        (KIND_ICONS[ref.kind] || "") + "</div>";
    }
    inner += '<div style="margin-top:4px;color:#c6cad1;font-size:11px;">@' + esc(ref.tag) +
      (ref.label ? ' <span style="color:#6c7481;">from ' + esc(ref.label) + "</span>" : "") + "</div>";
    hoverEl.innerHTML = inner;
    var hoverImg = hoverEl.querySelector(".sdp-hover-media");
    if (hoverImg && ref.thumb && full && full !== ref.thumb) {
      hoverImg.addEventListener("error", function () { hoverImg.src = ref.thumb; });
    }

    // Measure invisibly, then anchor to the hovered element (zoom-safe).
    hoverEl.style.visibility = "hidden";
    hoverEl.style.display = "block";
    var a = anchorEl.getBoundingClientRect();
    var tl = toLocal(a.left, a.top, root);
    var br = toLocal(a.right, a.bottom, root);
    var cardW = hoverEl.offsetWidth || 160;
    var cardH = hoverEl.offsetHeight || 120;
    var x = Math.max(4, Math.min(tl.x, root.offsetWidth - cardW - 4));
    var y = br.y + 6;
    if (y + cardH > root.offsetHeight - 4) y = Math.max(4, tl.y - cardH - 6);
    hoverEl.style.left = x + "px";
    hoverEl.style.top = y + "px";
    hoverEl.style.visibility = "visible";
  }

  function hideHover() { hoverEl.style.display = "none"; }

  // ---------------------------------------------------------------- mention menu

  function mentionQuery() {
    var range = caretRange();
    if (!range || !range.collapsed || range.startContainer.nodeType !== 3) return null;
    var text = range.startContainer.nodeValue.slice(0, range.startOffset);
    var at = text.lastIndexOf("@");
    if (at < 0) return null;
    if (at > 0 && /[\w\]]/.test(text.charAt(at - 1))) return null;
    var query = text.slice(at + 1);
    if (query.length > 24 || !/^[\w-]*$/.test(query)) return null;
    return { query: query.toLowerCase() };
  }

  function openMenu() {
    var q = mentionQuery();
    if (!q || state.refs.length === 0) { closeMenu(); return; }
    var items = [];
    for (var i = 0; i < state.refs.length; i += 1) {
      var r = state.refs[i];
      var hay = (r.tag + " " + (r.label || "") + " " + r.kind).toLowerCase();
      if (!q.query || hay.indexOf(q.query) >= 0) items.push(r);
    }
    if (!items.length) { closeMenu(); return; }
    menuState.open = true;
    menuState.items = items;
    menuState.active = Math.min(menuState.active, items.length - 1);

    var html = "";
    for (var k = 0; k < items.length; k += 1) {
      var ref = items[k];
      var color = KIND_COLORS[ref.kind] || "#c6cad1";
      var itemThumb = chipThumb(ref);
      html += '<div class="sdp-item" data-idx="' + k + '" style="' +
        "display:flex;align-items:center;gap:8px;padding:5px 7px;border-radius:6px;cursor:pointer;" +
        (k === menuState.active ? "background:#1a1f26;" : "") +
      '">' +
        '<span style="display:inline-flex;width:30px;height:30px;border-radius:6px;overflow:hidden;background:#0c0e11;align-items:center;justify-content:center;color:' + color + ';flex:0 0 auto;">' +
          (itemThumb
            ? '<img src="' + esc(itemThumb) + '" style="width:100%;height:100%;object-fit:cover;" draggable="false"/>'
            : KIND_ICONS[ref.kind] || "") +
        "</span>" +
        '<span style="display:flex;flex-direction:column;min-width:0;">' +
          '<span style="color:' + color + ';font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' +
            esc(ref.label || ("@" + ref.tag)) + "</span>" +
          (ref.label
            ? '<span style="color:#6c7481;font-size:10px;">@' + esc(ref.tag) + "</span>"
            : "") +
        "</span>" +
      "</div>";
    }
    menu.innerHTML = html;
    var els = menu.querySelectorAll(".sdp-item");
    for (var n = 0; n < els.length; n += 1) {
      (function (el) {
        var ref = menuState.items[Number(el.getAttribute("data-idx"))];
        var itemImg = el.querySelector("img");
        if (itemImg) hookImgFallback(itemImg, KIND_ICONS[ref.kind]);
        el.addEventListener("mousedown", function (e) { e.preventDefault(); stop(e); insertMention(ref, true); });
        el.addEventListener("mouseenter", function () {
          menuState.active = Number(el.getAttribute("data-idx"));
          highlightActive();
        });
      })(els[n]);
    }

    // Place the menu at the caret (zoom-safe via client rect conversion).
    var pos = { x: 8, y: 24 };
    var range = caretRange();
    if (range) {
      var cr = range.cloneRange();
      cr.collapse(true);
      var rect = cr.getBoundingClientRect();
      if (rect && (rect.left || rect.top)) pos = toLocal(rect.left, rect.bottom, editorWrap);
    }
    var top = pos.y + 4;
    if (top + 200 > editorWrap.offsetHeight) top = Math.max(0, pos.y - 224);
    menu.style.top = top + "px";
    menu.style.left = Math.min(Math.max(0, pos.x), Math.max(0, editorWrap.offsetWidth - 240)) + "px";
    menu.style.display = "block";
  }

  function highlightActive() {
    var els = menu.querySelectorAll(".sdp-item");
    for (var i = 0; i < els.length; i += 1) {
      els[i].style.background = (i === menuState.active) ? "#1a1f26" : "transparent";
    }
  }

  function closeMenu() {
    menuState.open = false;
    menu.style.display = "none";
    hideHover();
  }

  // ---------------------------------------------------------------- sync

  function syncToNode() {
    if (syncTimer) { clearTimeout(syncTimer); syncTimer = null; }
    if (!onChange) return;
    var payload = {
      text: state.text,
      enhance: state.enhance,
      refs: state.refs,
      statusMessage: state.statusMessage
    };
    payload.fontSize = state.fontSize;
    payload.thumbScale = state.thumbScale;
    payload.llmEnhance = state.llmEnhance;
    payload.llmModel = state.llmModel;
    payload.enhanceNonce = state.enhanceNonce;
    payload.voiceNonce = state.voiceNonce;
    if (pendingVoiceAudio) payload.voiceAudio = pendingVoiceAudio;
    if (state.scanMode) {
      payload.scanMode = true;
      payload.scanNonce = state.scanNonce;
      payload.targets = state.targets;
      payload.groups = state.groups;
      payload.sendTarget = state.sendTarget;
    }
    payload.scanNonce = state.scanNonce;
    payload.sendNonce = state.sendNonce;
    payload.doSend = !!state.doSend;
    var serialized = "";
    try { serialized = JSON.stringify(payload); } catch (_) { serialized = ""; }
    if (serialized && serialized === lastPayload) return;
    lastPayload = serialized;
    onChange(payload);
  }

  // Debounced sync while typing: fewer round-trips means fewer stale echoes
  // racing the editor. Buttons (send/rescan/update/voice) sync immediately.
  function scheduleSync() {
    if (syncTimer) clearTimeout(syncTimer);
    syncTimer = setTimeout(function () {
      syncTimer = null;
      syncToNode();
    }, 350);
  }

  function handleInput() {
    lastLocalEditAt = Date.now();
    state.text = serializeNode(input).replace(/\u00a0/g, " ").replace(/\u200b/g, "");
    updatePlaceholder();
    renderStatus();
    renderCharCount();
    openMenu();
    scheduleSync();
  }

  // ---------------------------------------------------------------- events

  input.addEventListener("input", function (e) { stop(e); handleInput(); });
  input.addEventListener("click", function (e) { stop(e); openMenu(); });
  input.addEventListener("focus", function () { input.style.borderColor = "#6b5836"; });
  input.addEventListener("blur", function () {
    input.style.borderColor = "#21252c";
    setTimeout(closeMenu, 120);
  });
  input.addEventListener("keyup", stop);
  input.addEventListener("pointerdown", stop);
  // Right-click: let the browser's native spellcheck menu (with correction
  // suggestions) open on misspelled words; only stop the node canvas from
  // hijacking the event - do NOT preventDefault.
  input.addEventListener("contextmenu", stop);
  input.addEventListener("paste", function (e) {
    stop(e);
    e.preventDefault();
    var text = "";
    try { text = (e.clipboardData || window.clipboardData).getData("text/plain") || ""; } catch (_) { text = ""; }
    if (!text) return;
    var range = caretRange();
    if (!range) return;
    range.deleteContents();
    // Pasted @Image1 tokens become mention pills automatically.
    var rich = buildRichFragment(text.replace(/\r\n?/g, "\n"));
    range.insertNode(rich.fragment);
    if (rich.lastNode) setCaretAfter(rich.lastNode);
    handleInput();
  });
  input.addEventListener("keydown", function (e) {
    stop(e);
    if (menuState.open) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        menuState.active = (menuState.active + 1) % menuState.items.length;
        highlightActive();
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        menuState.active = (menuState.active - 1 + menuState.items.length) % menuState.items.length;
        highlightActive();
        return;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        insertMention(menuState.items[menuState.active], true);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        closeMenu();
        return;
      }
    }
    if (e.key === "Enter") {
      // Normalize newlines: insert a <br> instead of letting the browser
      // wrap lines in divs (keeps serialization exact).
      e.preventDefault();
      var range = caretRange();
      if (range) {
        range.deleteContents();
        var br = document.createElement("br");
        range.insertNode(br);
        setCaretAfter(br);
        handleInput();
      }
    }
  });

  toggleRow.addEventListener("click", function (e) {
    stop(e);
    if (disabled) return;
    state.enhance = !state.enhance;
    renderToggle();
    renderStatus();
    syncToNode();
  });

  function toggleLlm(e) {
    stop(e);
    if (disabled) return;
    state.llmEnhance = !state.llmEnhance;
    renderLlm();
    syncToNode();
  }
  llmToggleEl.addEventListener("click", toggleLlm);
  llmLabelEl.addEventListener("click", toggleLlm);
  llmModelSel.addEventListener("click", stop);
  llmModelSel.addEventListener("pointerdown", stop);
  llmModelSel.addEventListener("change", function (e) {
    stop(e);
    state.llmModel = llmModelSel.value || state.llmModel;
    syncToNode();
  });

  updateBtn.addEventListener("click", function (e) {
    stop(e);
    if (disabled) return;
    if (!state.enhance && !state.llmEnhance) {
      statusEl.textContent = "Turn on an enhancer first (Image Prompt Enhancer and/or AI Prompt Enhancer).";
      return;
    }
    // Blur the editor so the node's rewritten text is allowed to replace it.
    try { input.blur(); } catch (_) {}
    expectTextUntil = Date.now() + 60000;
    state.enhanceNonce = (state.enhanceNonce || 0) + 1;
    statusEl.textContent = state.llmEnhance
      ? "Enhancing prompt with " + state.llmModel + "... the editor will update in a moment."
      : "Enhancing prompt... the editor will update in a moment.";
    syncToNode();
  });
  updateBtn.addEventListener("pointerdown", stop);

  // Tags are fixed slots (swap-on-drop): dropping in empty sidebar space has
  // no target slot, so it does nothing.
  cardsEl.addEventListener("dragover", function (e) { e.preventDefault(); });
  cardsEl.addEventListener("drop", function (e) {
    e.preventDefault();
    stop(e);
    dragIdx = null;
  });

  // ---------------------------------------------------------------- font size

  function applyFontSize() {
    var px = state.fontSize + "px";
    input.style.fontSize = px;
    input.style.lineHeight = "1.7";
    placeholderEl.style.fontSize = px;
    placeholderEl.style.lineHeight = "1.7";
  }

  fontSlider.addEventListener("input", function (e) {
    stop(e);
    state.fontSize = Math.min(22, Math.max(10, Number(fontSlider.value) || 12.5));
    applyFontSize();
  });
  fontSlider.addEventListener("change", function (e) {
    stop(e);
    syncToNode();
  });
  fontSlider.addEventListener("pointerdown", stop);

  // ---------------------------------------------------------------- thumbnail size

  var thumbSlider = container.querySelector(".sdp-thumbscale");

  function applyThumbScale() {
    var scale = Math.min(3, Math.max(1, Number(state.thumbScale) || 1));
    var cols = scale >= 1.5 ? 1 : 2;
    var cell = Math.round(82 * scale);
    var gap = 6;
    var sideW = cols === 2 ? cell * 2 + gap + 8 : cell + 8;
    if (sideEl) {
      sideEl.style.width = sideW + "px";
      sideEl.style.flex = "0 0 " + sideW + "px";
    }
    if (cardsEl) cardsEl.style.gridTemplateColumns = cols === 1 ? "1fr" : "1fr 1fr";
    if (thumbSlider && String(thumbSlider.value) !== String(scale)) {
      thumbSlider.value = String(scale);
    }
  }

  if (thumbSlider) {
    thumbSlider.addEventListener("input", function (e) {
      stop(e);
      state.thumbScale = Math.min(3, Math.max(1, Number(thumbSlider.value) || 1));
      applyThumbScale();
    });
    thumbSlider.addEventListener("change", function (e) {
      stop(e);
      syncToNode();
    });
    thumbSlider.addEventListener("pointerdown", stop);
  }

  // ---------------------------------------------------------------- fullscreen

  function inFullscreen() {
    return document.fullscreenElement === root || root.classList.contains("igp-fs");
  }

  function fsFallback(on) {
    if (on) root.classList.add("igp-fs");
    else root.classList.remove("igp-fs");
    updateFsButton();
  }

  function toggleFullscreen() {
    if (document.fullscreenElement === root) {
      if (document.exitFullscreen) document.exitFullscreen();
      return;
    }
    if (root.classList.contains("igp-fs")) {
      fsFallback(false);
      return;
    }
    if (root.requestFullscreen) {
      root.requestFullscreen().catch(function () { fsFallback(true); });
    } else {
      fsFallback(true);
    }
  }

  function updateFsButton() {
    var active = inFullscreen();
    fsBtn.innerHTML = active ? "&#9974; Exit" : "&#9974; Full";
    fsBtn.style.borderColor = active ? "#6b5836" : "#333a44";
    fsBtn.style.color = active ? "#d9c6a4" : "#c6cad1";
  }

  function onFsChange() { updateFsButton(); }
  document.addEventListener("fullscreenchange", onFsChange);

  fsBtn.addEventListener("click", function (e) {
    stop(e);
    toggleFullscreen();
  });
  fsBtn.addEventListener("pointerdown", stop);

  // Esc exits the fallback overlay (real fullscreen handles Esc natively).
  function onDocKeydown(e) {
    if (e.key === "Escape" && root.classList.contains("igp-fs")) fsFallback(false);
  }
  document.addEventListener("keydown", onDocKeydown);

  // ---------------------------------------------------------------- voice input

  var SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition || null;
  var recog = null;
  var listening = false;
  // "speech" = live browser recognition; "record" = MediaRecorder + node-side
  // whisper transcription (works in the desktop app / anywhere without the
  // Web Speech API). Speech errors auto-switch to record mode.
  var voiceMode = SpeechRec ? "speech" : "record";
  var pendingVoiceAudio = null;
  var recorder = null;
  var recStream = null;
  var recChunks = [];
  var recTimer = null;

  var NUM_WORDS = {
    one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8,
    nine: 9, ten: 10, eleven: 11, twelve: 12, thirteen: 13, fourteen: 14,
    fifteen: 15, sixteen: 16, to: 2, too: 2, for: 4
  };

  function normalizeDictation(text) {
    // Spoken "at image three" / "image 3" becomes an @Image3 token;
    // buildRichFragment then renders it as a mention pill.
    return String(text || "").replace(
      /\b(at\s+)?(image)\s+(?:number\s+)?(\d{1,2}|one|two|to|too|three|four|for|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen)\b/gi,
      function (m, at, kind, num) {
        var word = String(num).toLowerCase();
        // Homophones (to/too/for) only count as numbers after an explicit
        // "at" - otherwise "an image for the background" would become @Image4.
        if (!at && (word === "to" || word === "too" || word === "for")) return m;
        var n = NUM_WORDS[word] || parseInt(num, 10);
        if (!n) return m;
        return "@" + kind.charAt(0).toUpperCase() + kind.slice(1).toLowerCase() + n;
      }
    );
  }

  function insertDictation(text) {
    var t = normalizeDictation(text).replace(/\s+/g, " ").trim();
    if (!t) return;
    input.focus();
    var existing = serializeNode(input).replace(/\u200b/g, "");
    var lead = (existing && !/[\s\n]$/.test(existing)) ? " " : "";
    var rich = buildRichFragment(lead + t + " ");
    var range = caretRange();
    if (range) {
      range.deleteContents();
      range.insertNode(rich.fragment);
      if (rich.lastNode) setCaretAfter(rich.lastNode);
    } else {
      input.appendChild(rich.fragment);
    }
    handleInput();
  }

  function handleVoiceFinal(text) {
    // Whole-utterance commands; anything else is dictated into the prompt.
    var cmd = String(text || "").trim().toLowerCase().replace(/[.!?,]+$/, "");
    if (cmd === "new line" || cmd === "newline") {
      input.focus();
      var br = document.createElement("br");
      var range = caretRange();
      if (range) { range.deleteContents(); range.insertNode(br); setCaretAfter(br); }
      else input.appendChild(br);
      handleInput();
      return;
    }
    if (cmd === "clear prompt" || cmd === "clear the prompt") {
      input.innerHTML = "";
      handleInput();
      return;
    }
    if (cmd === "send it" || cmd === "send prompt" || cmd === "send to image gen") {
      stopVoice();
      sendBtn.click();
      return;
    }
    insertDictation(text);
  }

  var MIC_SVG = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>';
  var STOP_SVG = '<svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" stroke="none"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>';

  function updateMicBtn() {
    micBtn.innerHTML = listening ? (STOP_SVG + "Stop") : (MIC_SVG + "Voice");
    micBtn.style.borderColor = listening ? "#c0392b" : "#333a44";
    micBtn.style.background = listening ? "#2a1210" : "#161a20";
    micBtn.style.color = listening ? "#e8a09a" : "#c6cad1";
    micBtn.title = listening
      ? (voiceMode === "speech" ? "Stop dictation" : "Stop recording and transcribe")
      : "Dictate prompt (voice to text). Say 'at image 2' for @Image2; commands: 'new line', 'clear prompt', 'send it'.";
  }

  function stopVoice() {
    listening = false;
    if (recog) { try { recog.stop(); } catch (_) {} }
    updateMicBtn();
    renderStatus();
  }

  function startVoice() {
    if (!SpeechRec) {
      statusEl.textContent = "Voice input is not available here - open the editor in Chrome or Edge (Web Speech API).";
      return;
    }
    try { recog = new SpeechRec(); } catch (_) {
      statusEl.textContent = "Voice input could not start in this environment.";
      return;
    }
    recog.lang = "en-US";
    recog.continuous = true;
    recog.interimResults = true;
    recog.onresult = function (ev) {
      var finalText = "";
      var interim = "";
      for (var i = ev.resultIndex; i < ev.results.length; i += 1) {
        var res = ev.results[i];
        if (res.isFinal) finalText += res[0].transcript;
        else interim += res[0].transcript;
      }
      if (interim) statusEl.textContent = "Hearing: " + interim;
      if (finalText) {
        statusEl.textContent = "";
        handleVoiceFinal(finalText);
      }
    };
    recog.onerror = function (ev) {
      var err = (ev && ev.error) || "unknown";
      if (err === "network" || err === "service-not-allowed" || err === "language-not-supported") {
        // No speech service in this environment (e.g. desktop app):
        // permanently fall back to record-and-transcribe.
        listening = false;
        try { recog.onend = null; recog.stop(); } catch (_) {}
        voiceMode = "record";
        statusEl.textContent = "Live speech unavailable here - switching to record & transcribe (whisper-1)...";
        startRecording();
        return;
      }
      statusEl.textContent = "Voice error: " + err +
        (err === "not-allowed" ? " - allow microphone access for this site" : "");
      stopVoice();
    };
    recog.onend = function () {
      // Chrome auto-stops after silence; keep listening until the user stops.
      if (listening) { try { recog.start(); } catch (_) { stopVoice(); } }
    };
    listening = true;
    updateMicBtn();
    statusEl.textContent = "Listening... speak your prompt. 'at image 2' inserts @Image2; say 'new line', 'clear prompt' or 'send it'.";
    try { recog.start(); } catch (_) { stopVoice(); }
  }

  // --- record & transcribe fallback (same capture as the Microphone node) ---

  function stopStream() {
    if (recTimer) { clearTimeout(recTimer); recTimer = null; }
    if (recStream) {
      try { recStream.getTracks().forEach(function (t) { t.stop(); }); } catch (_) {}
      recStream = null;
    }
  }

  function startRecording() {
    if (!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia) || typeof MediaRecorder === "undefined") {
      statusEl.textContent = "Microphone recording is not available in this environment.";
      listening = false;
      updateMicBtn();
      return;
    }
    navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
      recStream = stream;
      recChunks = [];
      var mime = (MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported("audio/webm")) ? "audio/webm" : "";
      try {
        recorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
      } catch (_) {
        statusEl.textContent = "Audio recording is not supported in this environment.";
        stopStream();
        listening = false;
        updateMicBtn();
        return;
      }
      recorder.ondataavailable = function (ev) { if (ev.data && ev.data.size) recChunks.push(ev.data); };
      recorder.onstop = function () {
        stopStream();
        listening = false;
        updateMicBtn();
        var blob = new Blob(recChunks, { type: (recorder && recorder.mimeType) || "audio/webm" });
        recChunks = [];
        if (!blob.size) {
          statusEl.textContent = "No audio captured.";
          return;
        }
        var fr = new FileReader();
        fr.onload = function () {
          pendingVoiceAudio = String(fr.result || "");
          expectTextUntil = Date.now() + 150000; // whisper polling can take a while
          state.voiceNonce = (state.voiceNonce || 0) + 1;
          statusEl.textContent = "Transcribing voice with whisper-1... text will appear in the prompt.";
          syncToNode();
          pendingVoiceAudio = null;
        };
        fr.readAsDataURL(blob);
      };
      listening = true;
      updateMicBtn();
      statusEl.textContent = "Recording... click Stop to transcribe (auto-stops after 60s).";
      recorder.start();
      recTimer = setTimeout(function () {
        if (recorder && recorder.state === "recording") { try { recorder.stop(); } catch (_) {} }
      }, 60000);
    }).catch(function (err) {
      listening = false;
      updateMicBtn();
      statusEl.textContent = "Microphone permission denied or unavailable: " + err;
    });
  }

  function stopRecording() {
    if (recorder && recorder.state === "recording") {
      try { recorder.stop(); return; } catch (_) {}
    }
    stopStream();
    listening = false;
    updateMicBtn();
  }

  micBtn.addEventListener("click", function (e) {
    stop(e);
    if (disabled) return;
    if (listening) {
      if (voiceMode === "speech") stopVoice();
      else stopRecording();
    } else if (voiceMode === "speech") {
      startVoice();
    } else {
      startRecording();
    }
  });
  micBtn.addEventListener("pointerdown", stop);

  targetSel.addEventListener("change", function (e) {
    stop(e);
    state.sendTarget = targetSel.value || "all";
    syncToNode();
  });
  targetSel.addEventListener("pointerdown", stop);
  sendBtn.addEventListener("click", function (e) {
    stop(e);
    if (disabled || state.targets.length === 0) return;
    state.doSend = true;
    state.sendNonce = (state.sendNonce || 0) + 1;
    var destLabel = "image gen node(s)";
    if (state.sendTarget && state.sendTarget.indexOf(groupPrefix()) === 0) {
      destLabel = "group '" + state.sendTarget.slice(groupPrefix().length) + "'";
    } else if (state.sendTarget && state.sendTarget !== "all") {
      destLabel = "'" + state.sendTarget + "'";
    }
    statusEl.textContent = state.llmEnhance
      ? "Rewriting prompt with " + state.llmModel + ", then sending to " + destLabel + "..."
      : "Sending prompt + reference images to " + destLabel + "...";
    syncToNode();
  });

  var rescanBtn = container.querySelector(".sdp-rescan");
  if (rescanBtn) {
    rescanBtn.addEventListener("click", function (e) {
      stop(e);
      if (disabled) return;
      // Bump the nonce so the node rescans the workflow and pushes fresh refs.
      state.scanNonce = (state.scanNonce || 0) + 1;
      statusEl.textContent = "Rescanning workflow images...";
      syncToNode();
    });
  }

  // Fill the node's widget area vertically and follow node resizes.
  var resizeObs = null;
  if (typeof ResizeObserver !== "undefined") {
    resizeObs = new ResizeObserver(function () {
      var h = Math.max(300, container.clientHeight || widgetHeight);
      root.style.height = String(h) + "px";
    });
    resizeObs.observe(container);
  }
  if (container.clientHeight > 0) {
    root.style.height = String(Math.max(300, container.clientHeight)) + "px";
  }

  renderCards();
  renderTargets();
  renderToggle();
  renderLlm();
  applyFontSize();
  renderEditorFromText(state.text);
  renderStatus();
  renderCharCount();
  syncToNode();

  // Live updates from the node (rescans, send results, reordered refs):
  // the editor calls update(props) whenever the parameter value changes,
  // as long as we return a { cleanup, update } handle instead of a bare
  // cleanup function. This is what makes Rescan work without Ctrl+R.
  function applyPendingUpdate() {
    if (pendingUpdate === null || dragIdx !== null) return;
    var queued = pendingUpdate;
    pendingUpdate = null;
    externalUpdate(queued);
  }

  function copyRef(ref) {
    var out = {};
    if (!ref || typeof ref !== "object") return out;
    for (var k in ref) {
      if (Object.prototype.hasOwnProperty.call(ref, k)) out[k] = ref[k];
    }
    return out;
  }

  function refLabel(ref) {
    return String((ref && ref.label) || "").trim().toLowerCase();
  }

  function refKey(ref) {
    return String((ref && ref.key) || "");
  }

  // Keep the user's card order. Match the source node first so @Image5
  // stays the card the user clicked. Filename is only a fallback after a
  // rename. Prompt tags stay @ImageN.
  function mergeIncomingRefs(incoming) {
    if (!Array.isArray(incoming)) return false;
    if (!state.refs.length) {
      if (!incoming.length) return false;
      state.refs = incoming.map(copyRef);
      renumberRefs();
      return true;
    }
    var used = {};
    function take(cur) {
      var label = refLabel(cur);
      var key = refKey(cur);
      var i;
      if (label) {
        for (i = 0; i < incoming.length; i += 1) {
          if (used[i]) continue;
          if (refLabel(incoming[i]) === label) { used[i] = true; return incoming[i]; }
        }
      }
      if (key) {
        for (i = 0; i < incoming.length; i += 1) {
          if (used[i]) continue;
          if (refKey(incoming[i]) === key) { used[i] = true; return incoming[i]; }
        }
      }
      return null;
    }
    var next = [];
    for (var s = 0; s < state.refs.length; s += 1) {
      var cur = state.refs[s];
      var match = take(cur);
      if (!match) continue;
      var merged = copyRef(match);
      var prevUrl = String(cur.url || "");
      var nextUrl = String(merged.url || "");
      var prevSource = String(cur.source || "");
      var nextSource = String(merged.source || "");
      var samePixels = !!(nextSource && prevSource && nextSource === prevSource);
      if (samePixels && !merged.thumb && cur.thumb) merged.thumb = cur.thumb;
      // Same baked jpeg shipped with a different picture: drop it so the
      // card shows the new url instead of the stuck thumbnail.
      var imageChanged = (nextUrl && nextUrl !== prevUrl) || (nextSource && prevSource && nextSource !== prevSource);
      if (imageChanged && merged.thumb && merged.thumb === cur.thumb) merged.thumb = "";
      next.push(merged);
    }
    for (var n = 0; n < incoming.length; n += 1) {
      if (!used[n]) next.push(copyRef(incoming[n]));
    }
    var prevJson = "";
    try { prevJson = JSON.stringify(state.refs); } catch (_) { prevJson = ""; }
    state.refs = next;
    renumberRefs();
    var nextJson = "";
    try { nextJson = JSON.stringify(state.refs); } catch (_) { nextJson = "changed"; }
    return nextJson !== prevJson;
  }

  function externalUpdate(newProps) {
    // Never touch the DOM mid-drag: rebuilding the cards kills the native
    // drag. Queue the update and apply it when the drag ends.
    if (dragIdx !== null) {
      pendingUpdate = newProps;
      return;
    }
    var v = (newProps && newProps.value && typeof newProps.value === "object") ? newProps.value : {};
    var focused = editorFocused();
    var typedRecently = Date.now() - lastLocalEditAt < 4000;

    if (typeof v.statusMessage === "string") state.statusMessage = v.statusMessage;
    if (typeof v.enhance === "boolean") state.enhance = v.enhance;
    if (typeof v.scanNonce === "number") state.scanNonce = v.scanNonce;
    if (typeof v.sendNonce === "number") state.sendNonce = v.sendNonce;
    if (typeof v.doSend === "boolean") state.doSend = v.doSend;
    if (v.sendTarget) state.sendTarget = String(v.sendTarget);
    if (typeof v.llmEnhance === "boolean") state.llmEnhance = v.llmEnhance;
    if (v.llmModel) state.llmModel = String(v.llmModel);
    if (Array.isArray(v.llmModels) && v.llmModels.length) state.llmModels = v.llmModels.slice();
    if (typeof v.enhanceNonce === "number") state.enhanceNonce = v.enhanceNonce;
    if (typeof v.voiceNonce === "number") state.voiceNonce = v.voiceNonce;
    if (v.fontSize) {
      var fs = Math.min(22, Math.max(10, Number(v.fontSize) || state.fontSize));
      if (fs !== state.fontSize) {
        state.fontSize = fs;
        fontSlider.value = String(fs);
        applyFontSize();
      }
    }
    if (v.thumbScale) {
      var ts = Math.min(3, Math.max(1, Number(v.thumbScale) || state.thumbScale));
      if (ts !== state.thumbScale) {
        state.thumbScale = ts;
        applyThumbScale();
      }
    }

    var targetsChanged = false;
    if (Array.isArray(v.targets)) {
      var incomingTargets = v.targets.slice();
      targetsChanged = JSON.stringify(incomingTargets) !== JSON.stringify(state.targets);
      state.targets = incomingTargets;
    }

    var groupsChanged = false;
    if (Array.isArray(v.groups)) {
      var incomingGroups = v.groups.slice();
      try {
        groupsChanged = JSON.stringify(incomingGroups) !== JSON.stringify(state.groups);
      } catch (_) {
        groupsChanged = true;
      }
      state.groups = incomingGroups;
    }

    var refsChanged = false;
    if (Array.isArray(v.refs)) {
      refsChanged = mergeIncomingRefs(v.refs);
    }

    if (refsChanged) renderCards();
    if (refsChanged || targetsChanged || groupsChanged) renderTargets();

    var incomingText = (typeof v.text === "string") ? v.text : state.text;
    var expectingText = Date.now() < expectTextUntil;
    // Accept node-side text only when it was explicitly requested (Update
    // Prompt / voice transcription) or when the user clearly isn't editing.
    // Everything else is a stale echo of our own sync racing the keyboard -
    // rewriting the editor from it is what made text "change by itself".
    if (incomingText !== state.text && (expectingText || (!focused && !typedRecently))) {
      state.text = incomingText;
      renderEditorFromText(state.text);
      expectTextUntil = 0;
    } else if (refsChanged) {
      if (focused || typedRecently) {
        // Don't destroy the caret mid-typing; just rebind pill thumbnails.
        rebindMentions();
      } else {
        renderEditorFromText(state.text);
      }
    }

    renderToggle();
    renderLlm();
    renderStatus();
    renderCharCount();
    updatePlaceholder();
  }

  return {
    update: externalUpdate,
    cleanup: function cleanup() {
      if (syncTimer) { clearTimeout(syncTimer); syncTimer = null; }
      stopVoice();
      stopRecording();
      if (resizeObs) { try { resizeObs.disconnect(); } catch (_) {} }
      document.removeEventListener("fullscreenchange", onFsChange);
      document.removeEventListener("keydown", onDocKeydown);
      if (document.fullscreenElement === root && document.exitFullscreen) {
        try { document.exitFullscreen(); } catch (_) {}
      }
      container.innerHTML = "";
    }
  };
}
