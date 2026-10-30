export default function SeedancePromptV9Widget(container, props) {
  var value = (props && props.value && typeof props.value === "object") ? props.value : {};
  var onChange = props ? props.onChange : null;
  var disabled = !!(props && props.disabled);
  var widgetHeight = (props && props.height && props.height > 0) ? Math.max(420, props.height - 24) : 620;

  // Board ceiling is Seedance 2.5. A selected 2.0 target clamps the meter to 9/3/3.
  var MAX_SLOTS = 30;
  var VID_CAP = 10;
  var AUD_CAP = 10;

  var state = {
    text: String(value.text || ""),
    enhance: !!value.enhance,
    refs: Array.isArray(value.refs) ? value.refs.slice() : [],
    entities: Array.isArray(value.entities) ? value.entities.slice() : [],
    budget: clampBudget(value.budget),
    statusMessage: String(value.statusMessage || ""),
    // V8 is always a scan-mode node; never let an empty initial value
    // strip scanNonce/sendNonce from the payload (dead Rescan/Send buttons).
    scanMode: true,
    scanNonce: Number(value.scanNonce || 0) || 0,
    targets: Array.isArray(value.targets) ? value.targets.slice() : [],
    targetProfiles: Array.isArray(value.targetProfiles) ? value.targetProfiles.slice() : [],
    groups: Array.isArray(value.groups) ? value.groups.slice() : [],
    sendTarget: String(value.sendTarget || "all"),
    sendNonce: Number(value.sendNonce || 0) || 0,
    doSend: !!value.doSend,
    promptFile: String(value.promptFile || ""),
    promptFileNonce: Number(value.promptFileNonce || 0) || 0,
    promptFileStatus: String(value.promptFileStatus || ""),
    promptBrowseNonce: Number(value.promptBrowseNonce || 0) || 0,
    fontSize: Math.min(22, Math.max(10, Number(value.fontSize || 12.5) || 12.5)),
    uiScale: Math.min(3, Math.max(1, Number(value.uiScale || 2) || 2)),
    thumbScale: Math.min(3, Math.max(1, Number(value.thumbScale || 1) || 1))
  };

  function clampBudget(v) {
    var n = Math.round(Number(v || MAX_SLOTS) || MAX_SLOTS);
    return Math.max(1, Math.min(MAX_SLOTS, n));
  }

  // Shot Planner V2 palette: dark gray chrome with a muted amber accent.
  var FONT = "ui-monospace,'Cascadia Code','JetBrains Mono',Consolas,monospace";
  var KIND_COLORS = { image: "#d9c6a4", video: "#a58050", audio: "#8a929e" };
  var KIND_ICONS = {
    image: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>',
    video: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="4" width="15" height="16" rx="2"/><path d="M22 8l-5 4 5 4V8z"/></svg>',
    audio: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>'
  };
  var LANES = [
    { id: "character", label: "Cast", color: "#e8b4b8" },
    { id: "wardrobe", label: "Wardrobe", color: "#d9c6a4" },
    { id: "prop", label: "Props", color: "#c9a86c" },
    { id: "set", label: "Set", color: "#9fb8a0" },
    { id: "light", label: "Light/Grade", color: "#e0d080" },
    { id: "camera", label: "Camera", color: "#a58050" },
    { id: "audio", label: "Audio", color: "#8a929e" }
  ];
  var LANE_BY_ID = {};
  for (var li = 0; li < LANES.length; li += 1) LANE_BY_ID[LANES[li].id] = LANES[li];

  var MENTION_RE = /@(image|video|audio)[\s_-]?(\d+)/gi;
  // Combined tokenizer: raw kind tags first, then candidate entity names.
  var TOKEN_RE = /@(image|video|audio)[\s_-]?(\d+)|@([A-Za-z][\w-]{0,32})/gi;
  var KIND_NAME_RE = /^(image|video|audio)\d*$/i;

  var placeholderText =
    "Describe your shot... type @ to mention an entity (@Maya) or any asset in the workflow";

  container.innerHTML =
    "<style>" +
      ".sdp-root:fullscreen{width:100vw !important;height:100vh !important;border-radius:0 !important;}" +
      ".sdp-root.sdp7-fs{position:fixed !important;inset:0 !important;width:100vw !important;height:100vh !important;z-index:99999 !important;border-radius:0 !important;}" +
      ".sdp7-thumbwrap .sdp7-thumb-x{display:none;}" +
      ".sdp7-thumbwrap:hover .sdp7-thumb-x{display:flex;}" +
    "</style>" +
    '<div class="sdp-root nodrag nowheel" style="' +
      "display:flex;flex-direction:row;gap:8px;padding:10px;box-sizing:border-box;" +
      "background:#0c0e11;border:1px solid #21252c;border-radius:10px;" +
      "font-family:" + FONT + ";font-size:11.5px;color:#c6cad1;" +
      "height:" + widgetHeight + "px;overflow:hidden;position:relative;" +
    '">' +
      // Left: the reference board (budget meter, lanes with entities, pool)
      '<div class="sdp-side" style="' +
        "display:flex;flex-direction:column;gap:6px;width:206px;flex:0 0 206px;min-height:0;" +
      '">' +
        '<div style="display:flex;align-items:center;gap:6px;">' +
          '<span style="color:#8a929e;font-size:11px;flex:1;">Reference board</span>' +
          '<button class="sdp-rescan" type="button" style="' +
            "padding:2px 8px;border-radius:6px;border:1px solid #6b5836;background:#241d13;color:#d9c6a4;" +
            "font-size:10.5px;cursor:pointer;font-family:inherit;flex:0 0 auto;" +
          '">Rescan</button>' +
        "</div>" +
        '<div style="display:flex;align-items:center;gap:6px;">' +
          '<span style="color:#6c7481;font-size:10px;">Thumbs</span>' +
          '<input class="sdp-thumbscale" type="range" min="1" max="3" step="0.25" value="' + state.thumbScale + '" ' +
            'title="Pool thumbnail size (1.5x and up = one column)" style="flex:1;accent-color:#a58050;cursor:pointer;" />' +
        "</div>" +
        // Slot budget meter
        '<div class="sdp-budget" style="' +
          "display:flex;flex-direction:column;gap:3px;padding:6px 7px;border-radius:8px;" +
          "background:#12151a;border:1px solid #21252c;flex:0 0 auto;" +
        '">' +
          '<div style="display:flex;align-items:center;gap:5px;">' +
            '<span class="sdp-budget-label" style="flex:1;font-size:10.5px;color:#c6cad1;"></span>' +
            '<input class="sdp-budget-input" type="number" min="1" max="' + MAX_SLOTS + '" step="1" style="' +
              "width:44px;padding:1px 4px;border-radius:5px;border:1px solid #333a44;background:#0f1116;" +
              "color:#c6cad1;font-family:inherit;font-size:10.5px;outline:none;" +
            '" title="Image slot budget. Seedance 2.5 accepts up to ' + MAX_SLOTS + ' images / ' + VID_CAP + ' videos / ' + AUD_CAP + ' audio. Seedance 2.0 is clamped to 9 / 3 / 3 on send."/>' +
          "</div>" +
          '<div style="height:5px;border-radius:3px;background:#21252c;overflow:hidden;">' +
            '<div class="sdp-budget-bar" style="height:100%;width:0%;background:#a58050;border-radius:3px;transition:width .2s,background .2s;"></div>' +
          "</div>" +
        "</div>" +
        '<div class="sdp-board" style="' +
          "flex:1;min-height:0;overflow-y:auto;display:flex;flex-direction:column;gap:7px;padding-right:2px;" +
        '"></div>' +
      "</div>" +
      // Right: header (voice + font + fullscreen) + editor + send + toggle + status
      '<div style="display:flex;flex-direction:column;gap:8px;flex:1;min-width:0;">' +
        '<div style="display:flex;align-items:center;gap:8px;">' +
          '<span style="color:#8a929e;font-size:11px;flex:1;">Prompt</span>' +
          '<button class="sdp-mic" type="button" title="Dictate prompt (voice to text)" style="' +
            "display:inline-flex;align-items:center;gap:4px;padding:2px 10px;border-radius:6px;border:1px solid #333a44;" +
            "background:#161a20;color:#c6cad1;font-size:11px;cursor:pointer;font-family:inherit;flex:0 0 auto;" +
          '"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>Voice</button>' +
          '<span style="color:#6c7481;font-size:10px;">Aa</span>' +
          '<input class="sdp-font" type="range" min="10" max="22" step="0.5" value="' + state.fontSize + '" ' +
            'title="Prompt font size" style="width:70px;accent-color:#a58050;cursor:pointer;" />' +
          '<span style="color:#6c7481;font-size:10px;">UI</span>' +
          '<input class="sdp-uiscale" type="range" min="1" max="3" step="0.25" value="' + state.uiScale + '" ' +
            'title="UI scale: makes the whole widget bigger (2 = double size)" style="width:70px;accent-color:#a58050;cursor:pointer;" />' +
          '<button class="sdp-fs" type="button" title="Toggle fullscreen" style="' +
            "padding:2px 10px;border-radius:6px;border:1px solid #333a44;background:#161a20;color:#c6cad1;" +
            "font-size:11px;cursor:pointer;font-family:inherit;flex:0 0 auto;" +
          '">&#9974; Full</button>' +
        "</div>" +
        '<div class="sdp-promptfile-row" style="display:flex;align-items:center;gap:6px;">' +
          '<button class="sdp-promptfile-load" type="button" title="Opens Windows Explorer so you can pick a .txt prompt" style="' +
            "padding:4px 10px;border-radius:6px;border:1px solid #6b5836;background:#241d13;color:#d9c6a4;" +
            "font-size:11px;font-weight:600;cursor:pointer;font-family:inherit;flex:0 0 auto;white-space:nowrap;" +
          '">Load Prompt</button>' +
          '<button class="sdp-promptfile-btn" type="button" title="Re-read the file you already picked" style="' +
            "padding:4px 10px;border-radius:6px;border:1px solid #333a44;background:#161a20;color:#c6cad1;" +
            "font-size:11px;cursor:pointer;font-family:inherit;flex:0 0 auto;white-space:nowrap;" +
          '">Get Latest</button>' +
          '<span class="sdp-promptfile-name" title="" style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#8b93a0;font-size:11px;"></span>' +
        "</div>" +
        '<div class="sdp-promptfile-status" style="color:#6c7481;font-size:10px;min-height:12px;"></div>' +
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
            "position:absolute;display:none;z-index:30;min-width:240px;max-width:320px;max-height:220px;overflow-y:auto;" +
            "background:#12151a;border:1px solid #333a44;border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,.5);padding:4px;" +
          '"></div>' +
        "</div>" +
        '<div class="sdp-send-row" style="display:flex;gap:6px;align-items:center;">' +
          '<span class="sdp-chars" title="Prompt length as exported (entities expanded, [Image N] brackets)" style="' +
            "color:#d9c6a4;font-size:10.5px;flex:0 0 auto;white-space:nowrap;" +
          '"></span>' +
          '<select class="sdp-target" title="Send to every Seedance node, one node, or every Seedance node in a canvas group" style="' +
            "flex:1;min-width:0;padding:4px 6px;border-radius:6px;border:1px solid #333a44;" +
            "background:#0f1116;color:#c6cad1;font-family:inherit;font-size:11px;outline:none;" +
          '"></select>' +
          '<button class="sdp-send" type="button" style="' +
            "padding:4px 14px;border-radius:6px;border:1px solid #6b5836;background:#241d13;color:#d9c6a4;" +
            "font-size:11px;font-weight:600;cursor:pointer;font-family:inherit;flex:0 0 auto;" +
          '">Send to Seedance</button>' +
        "</div>" +
        '<label class="sdp-toggle-row" style="display:flex;align-items:center;gap:8px;cursor:pointer;user-select:none;">' +
          '<span class="sdp-toggle" style="' +
            "position:relative;width:34px;height:18px;border-radius:9px;background:#21252c;transition:background .15s;flex:0 0 auto;" +
          '"><span class="sdp-knob" style="' +
            "position:absolute;top:2px;left:2px;width:14px;height:14px;border-radius:50%;background:#6c7481;transition:left .15s,background .15s;" +
          '"></span></span>' +
          '<span style="color:#c6cad1;">Role-aware Prompt Enhancer</span>' +
          '<span style="color:#6c7481;font-size:10px;">per-lane constraints: identity for Cast, grade for Light, motion for Camera...</span>' +
        "</label>" +
        '<div class="sdp-status" style="color:#6c7481;font-size:10px;min-height:12px;"></div>' +
      "</div>" +
      // Hover preview card (only used by mentions inside the prompt)
      '<div class="sdp-hover" style="' +
        "position:absolute;display:none;z-index:40;pointer-events:none;" +
        "background:#12151a;border:1px solid #333a44;border-radius:10px;box-shadow:0 10px 30px rgba(0,0,0,.6);" +
        "padding:6px;max-width:240px;" +
      '"></div>' +
    "</div>";

  var root = container.querySelector(".sdp-root");
  var sideEl = container.querySelector(".sdp-side");
  var boardEl = container.querySelector(".sdp-board");
  var budgetLabelEl = container.querySelector(".sdp-budget-label");
  var budgetBarEl = container.querySelector(".sdp-budget-bar");
  var budgetInput = container.querySelector(".sdp-budget-input");
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
  var promptFileLoadBtn = container.querySelector(".sdp-promptfile-load");
  var promptFileBtn = container.querySelector(".sdp-promptfile-btn");
  var promptFileNameEl = container.querySelector(".sdp-promptfile-name");
  var promptFileStatusEl = container.querySelector(".sdp-promptfile-status");
  var toggleRow = container.querySelector(".sdp-toggle-row");
  var toggleEl = container.querySelector(".sdp-toggle");
  var knobEl = container.querySelector(".sdp-knob");
  var statusEl = container.querySelector(".sdp-status");
  var hoverEl = container.querySelector(".sdp-hover");

  var menuState = { open: false, items: [], active: 0 };
  var lastPayload = "";
  var dragKey = null;        // pool ref being dragged (identity key)
  var dragIdx = null;        // pool ref being dragged (index into state.refs)
  var pendingUpdate = null;
  var lastReorderAt = 0;
  var lastEntityEditAt = 0;  // local entity edits are authoritative vs echoes
  var addingLane = null;     // lane id currently showing the "new entity" input
  var lastLocalEditAt = 0;   // last local typing/insert; echoes within this window never rewrite the editor
  var syncTimer = null;

  function esc(text) {
    return String(text || "")
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#039;");
  }

  function escRe(text) {
    return String(text || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function stop(e) { e.stopPropagation(); }

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

  // ---------------------------------------------------------------- refs / entities

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

  function refByKey(key) {
    for (var i = 0; i < state.refs.length; i += 1) {
      if (String(state.refs[i].key) === String(key)) return state.refs[i];
    }
    return null;
  }

  function entityByName(name) {
    var lowered = String(name || "").toLowerCase();
    for (var i = 0; i < state.entities.length; i += 1) {
      if (String(state.entities[i].name || "").toLowerCase() === lowered) return state.entities[i];
    }
    return null;
  }

  function entityRefs(entity) {
    var out = [];
    var keys = entity.refKeys || [];
    for (var i = 0; i < keys.length; i += 1) {
      var r = refByKey(keys[i]);
      if (r) out.push(r);
    }
    return out;
  }

  function entityBrackets(entity) {
    var refs = entityRefs(entity);
    var tags = [];
    for (var i = 0; i < refs.length; i += 1) {
      var k = String(refs[i].kind);
      tags.push("[" + k.charAt(0).toUpperCase() + k.slice(1) + " " + Number(refs[i].index) + "]");
    }
    return tags;
  }

  function assignedKeys() {
    var set = {};
    for (var i = 0; i < state.entities.length; i += 1) {
      var keys = state.entities[i].refKeys || [];
      for (var j = 0; j < keys.length; j += 1) set[String(keys[j])] = true;
    }
    return set;
  }

  function laneColor(laneId) {
    return (LANE_BY_ID[laneId] || LANE_BY_ID.prop).color;
  }

  function markEntityEdit() {
    lastEntityEditAt = Date.now();
  }

  function sanitizeEntityName(raw) {
    var name = String(raw || "").trim().replace(/\s+/g, "-").replace(/[^\w-]/g, "");
    if (!name || !/^[A-Za-z]/.test(name)) return "";
    name = name.slice(0, 32);
    if (KIND_NAME_RE.test(name)) name = name + "-e";
    if (!entityByName(name)) return name;
    for (var n = 2; n < 99; n += 1) {
      var candidate = (name.slice(0, 29) + "-" + n);
      if (!entityByName(candidate)) return candidate;
    }
    return "";
  }

  // ---------------------------------------------------------------- export / budget

  function exportedText() {
    // Mirror the node: expand entity mentions, then bracket kind mentions.
    var text = String(state.text || "");
    var ents = state.entities.slice().sort(function (a, b) {
      return String(b.name).length - String(a.name).length;
    });
    for (var i = 0; i < ents.length; i += 1) {
      var brackets = entityBrackets(ents[i]);
      var replacement = brackets.length ? brackets.join(", ") : String(ents[i].name);
      text = text.replace(
        new RegExp("@" + escRe(ents[i].name) + "(?![\\w-])", "gi"),
        replacement
      );
    }
    return text.replace(MENTION_RE, function (_m, kind, num) {
      var k = kind.toLowerCase();
      return "[" + k.charAt(0).toUpperCase() + k.slice(1) + " " + num + "]";
    });
  }

  function mentionedCounts() {
    var seen = { image: {}, video: {}, audio: {} };
    var counts = { image: 0, video: 0, audio: 0 };
    var re = /\[(image|video|audio)\s*(\d+)\]/gi;
    var text = exportedText();
    var m;
    while ((m = re.exec(text)) !== null) {
      var kind = m[1].toLowerCase();
      if (!seen[kind][m[2]]) { seen[kind][m[2]] = true; counts[kind] += 1; }
    }
    return counts;
  }

  function profilesForSelection() {
    var profiles = Array.isArray(state.targetProfiles) ? state.targetProfiles : [];
    var pick = state.sendTarget || "all";
    if (!profiles.length) return [];
    if (pick === "all" || !pick) return profiles.slice();
    if (pick.indexOf(groupPrefix()) === 0) {
      var groupName = pick.slice(groupPrefix().length);
      var members = {};
      var groups = Array.isArray(state.groups) ? state.groups : [];
      for (var g = 0; g < groups.length; g += 1) {
        if (String((groups[g] || {}).name || "") !== groupName) continue;
        var list = (groups[g] || {}).members || [];
        for (var m = 0; m < list.length; m += 1) members[String(list[m])] = true;
      }
      return profiles.filter(function (p) { return members[String((p || {}).name || "")]; });
    }
    return profiles.filter(function (p) { return String((p || {}).name || "") === pick; });
  }

  function activeCaps() {
    var chosen = profilesForSelection();
    var image = state.budget;
    var video = VID_CAP;
    var audio = AUD_CAP;
    var families = {};
    for (var i = 0; i < chosen.length; i += 1) {
      var profile = chosen[i] || {};
      image = Math.min(image, Number(profile.imageCap) || MAX_SLOTS);
      video = Math.min(video, Number(profile.videoCap) || VID_CAP);
      audio = Math.min(audio, Number(profile.audioCap) || AUD_CAP);
      if (profile.label) families[String(profile.label)] = true;
    }
    image = Math.max(1, image);
    var labels = Object.keys(families);
    return { image: image, video: video, audio: audio, labels: labels };
  }

  function renderBudget() {
    var used = mentionedCounts();
    var caps = activeCaps();
    var overImg = used.image > caps.image;
    var overVid = used.video > caps.video;
    var overAud = used.audio > caps.audio;
    var over = overImg || overVid || overAud;
    var familyNote = caps.labels.length ? (" \u00b7 " + caps.labels.join("+")) : "";
    budgetLabelEl.textContent =
      used.image + "/" + caps.image + " img \u00b7 " +
      used.video + "/" + caps.video + " vid \u00b7 " +
      used.audio + "/" + caps.audio + " aud" + familyNote;
    budgetLabelEl.style.color = over ? "#e08a8a" : "#c6cad1";
    // Bar shows the tightest kind so any over-cap situation is visible.
    var frac = Math.max(
      used.image / Math.max(1, caps.image),
      used.video / Math.max(1, caps.video),
      used.audio / Math.max(1, caps.audio)
    );
    var pct = Math.min(100, Math.round(frac * 100));
    budgetBarEl.style.width = pct + "%";
    budgetBarEl.style.background = over ? "#c25a5a" : (pct > 85 ? "#e0d080" : "#a58050");
    budgetInput.value = String(state.budget);
    budgetLabelEl.title = over
      ? "Over the selected node's envelope: on push, nice-to-have entities drop first. Seedance 2.0 is 9/3/3; Seedance 2.5 is 30/10/10."
      : "Slots this prompt will use on the selected target (Seedance 2.0: 9/3/3, Seedance 2.5: " +
        state.budget + "/" + VID_CAP + "/" + AUD_CAP + ").";
  }

  // ---------------------------------------------------------------- editor (contenteditable)

  function makeMentionEl(kind, num) {
    var tag = kind.charAt(0).toUpperCase() + kind.slice(1) + num;
    var ref = findRef(kind, num);
    var color = KIND_COLORS[kind] || "#c6cad1";
    var span = document.createElement("span");
    span.className = "sdp-mention";
    span.setAttribute("data-tag", tag);
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
    span.addEventListener("mouseenter", function () {
      var current = findRef(kind, num);
      if (current) showHover(current, span);
    });
    span.addEventListener("mouseleave", hideHover);
    return span;
  }

  function makeEntityMentionEl(name) {
    var entity = entityByName(name);
    var display = entity ? entity.name : name;
    var color = entity ? laneColor(entity.lane) : "#6c7481";
    var span = document.createElement("span");
    span.className = "sdp-mention sdp-ent-mention";
    span.setAttribute("data-etag", display);
    span.contentEditable = "false";
    span.style.cssText =
      "display:inline-flex;align-items:center;gap:4px;padding:0 6px;margin:0 1px;" +
      "border-radius:10px;vertical-align:text-bottom;line-height:1.4;cursor:default;" +
      "background:" + color + "1a;border:1px solid " + color + "55;color:" + color + ";font-weight:600;" +
      (entity ? "" : "opacity:.45;");
    span.appendChild(document.createTextNode("@" + display));
    var count = entity ? entityRefs(entity).length : 0;
    var badge = document.createElement("span");
    badge.className = "sdp-ent-count";
    badge.textContent = "\u00d7" + count;
    badge.style.cssText = "font-size:9px;font-weight:400;opacity:.8;";
    span.appendChild(badge);
    return span;
  }

  function buildRichFragment(text) {
    // Text -> DOM fragment: @Image1-style tokens and known @EntityName tokens
    // become mention pills; unknown @words stay plain text.
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
      TOKEN_RE.lastIndex = 0;
      var m;
      while ((m = TOKEN_RE.exec(line)) !== null) {
        var pill = null;
        if (m[1]) {
          pill = makeMentionEl(m[1].toLowerCase(), Number(m[2]));
        } else if (m[3] && entityByName(m[3])) {
          pill = makeEntityMentionEl(m[3]);
        }
        if (!pill) continue; // unknown @word: leave it as part of plain text
        if (m.index > last) {
          lastNode = document.createTextNode(line.slice(last, m.index));
          frag.appendChild(lastNode);
        }
        lastNode = pill;
        frag.appendChild(lastNode);
        last = m.index + m[0].length;
      }
      if (last < line.length) {
        lastNode = document.createTextNode(line.slice(last));
        frag.appendChild(lastNode);
      }
    }
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
        var etag = n.getAttribute("data-etag");
        out += "@" + (etag || n.getAttribute("data-tag"));
      } else if (n.nodeType === 1) {
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

  function insertPill(span, replaceQuery) {
    input.focus();
    var range = caretRange();
    var space = document.createTextNode("\u00a0");
    if (range) {
      if (replaceQuery && range.collapsed && range.startContainer.nodeType === 3) {
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

  function insertMention(ref, replaceQuery) {
    insertPill(makeMentionEl(ref.kind, Number(ref.index)), replaceQuery);
  }

  function insertEntityMention(entity, replaceQuery) {
    insertPill(makeEntityMentionEl(entity.name), replaceQuery);
  }

  // ------------------------------------------------- drop-into-prompt support

  function caretRangeAtPoint(x, y) {
    var range = null;
    try {
      var doc = input.getRootNode ? input.getRootNode() : document;
      if (doc.caretRangeFromPoint) range = doc.caretRangeFromPoint(x, y);
      else if (document.caretRangeFromPoint) range = document.caretRangeFromPoint(x, y);
      else if (document.caretPositionFromPoint) {
        var pos = document.caretPositionFromPoint(x, y);
        if (pos) {
          range = document.createRange();
          range.setStart(pos.offsetNode, pos.offset);
          range.collapse(true);
        }
      }
    } catch (_) {}
    if (range && !input.contains(range.startContainer)) range = null;
    return range;
  }

  function insertPillAtPoint(span, x, y) {
    var range = caretRangeAtPoint(x, y);
    var space = document.createTextNode("\u00a0");
    if (range) {
      range.collapse(true);
      range.insertNode(span);
      span.parentNode.insertBefore(space, span.nextSibling);
    } else {
      // No usable caret from the drop point: append at the end.
      input.appendChild(span);
      input.appendChild(space);
    }
    input.focus();
    setCaretAfter(space);
    handleInput();
  }

  // ---------------------------------------------------------------- reordering / rebinding

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
    // Kind pills: tags are fixed slots; rebind to whichever asset now owns
    // the slot. Entity pills: refresh count badge and validity opacity.
    var pills = input.querySelectorAll(".sdp-mention");
    for (var i = 0; i < pills.length; i += 1) {
      var pill = pills[i];
      var etag = pill.getAttribute("data-etag");
      if (etag) {
        var entity = entityByName(etag);
        pill.style.opacity = entity ? "1" : "0.45";
        var badge = pill.querySelector(".sdp-ent-count");
        if (badge) badge.textContent = "\u00d7" + (entity ? entityRefs(entity).length : 0);
        if (entity) {
          var c = laneColor(entity.lane);
          pill.style.background = c + "1a";
          pill.style.borderColor = c + "55";
          pill.style.color = c;
        }
        continue;
      }
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
    lastReorderAt = Date.now();
    pendingUpdate = null;
    renumberRefs();
    renderBoard();
    rebindMentions();
    handleInput();
  }

  // ---------------------------------------------------------------- board rendering

  function entityCardHtml(entity, entIdx) {
    var color = laneColor(entity.lane);
    var refs = entityRefs(entity);
    var must = entity.priority !== "nice";
    var thumbsHtml = "";
    for (var i = 0; i < refs.length; i += 1) {
      var r = refs[i];
      var t = chipThumb(r);
      thumbsHtml += '<span class="sdp7-thumbwrap" data-key="' + esc(String(r.key)) + '" title="@' + esc(r.tag) + '" style="' +
        "position:relative;width:26px;height:26px;border-radius:5px;overflow:hidden;flex:0 0 auto;" +
        "background:#0f1116;display:flex;align-items:center;justify-content:center;color:" + (KIND_COLORS[r.kind] || "#c6cad1") + ";" +
      '">' +
        (t ? '<img src="' + esc(t) + '" style="width:100%;height:100%;object-fit:cover;" draggable="false"/>' : (KIND_ICONS[r.kind] || "")) +
        '<span class="sdp7-thumb-x" data-key="' + esc(String(r.key)) + '" title="Remove from ' + esc(entity.name) + '" style="' +
          "position:absolute;top:0;right:0;width:11px;height:11px;align-items:center;justify-content:center;" +
          "background:rgba(0,0,0,.75);color:#e08a8a;font-size:9px;line-height:1;cursor:pointer;border-bottom-left-radius:4px;" +
        '">&#215;</span>' +
      "</span>";
    }
    return '<div class="sdp7-ent" data-ent="' + entIdx + '" style="' +
      "display:flex;flex-direction:column;gap:4px;padding:5px 6px;border-radius:7px;" +
      "background:#12151a;border:1px solid " + color + "33;cursor:pointer;" +
    '">' +
      '<div style="display:flex;align-items:center;gap:4px;min-width:0;">' +
        '<span class="sdp7-ent-name" style="color:' + color + ';font-weight:600;font-size:11px;' +
          'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1;min-width:0;" title="Click to insert @' + esc(entity.name) + '">@' + esc(entity.name) + "</span>" +
        '<span style="color:#6c7481;font-size:9.5px;flex:0 0 auto;">' + refs.length + "</span>" +
        '<span class="sdp7-ent-star" data-ent="' + entIdx + '" title="' +
          (must ? "Must-have: survives the slot budget cut" : "Nice-to-have: dropped first when over budget") +
        '" style="cursor:pointer;font-size:11px;flex:0 0 auto;color:' + (must ? "#e0d080" : "#4a5058") + ';">' +
          (must ? "&#9733;" : "&#9734;") + "</span>" +
        '<span class="sdp7-ent-del" data-ent="' + entIdx + '" title="Delete entity (refs return to the pool)" style="' +
          "cursor:pointer;color:#6c7481;font-size:11px;flex:0 0 auto;padding:0 1px;" +
        '">&#215;</span>' +
      "</div>" +
      (refs.length
        ? '<div style="display:flex;flex-wrap:wrap;gap:3px;">' + thumbsHtml + "</div>"
        : '<div style="color:#4a5058;font-size:9px;">drop refs here</div>') +
    "</div>";
  }

  var boardSig = "";
  function rosterSig() {
    var bits = [String(addingLane || "")];
    for (var i = 0; i < state.refs.length; i += 1) {
      var r = state.refs[i] || {};
      bits.push([r.key, r.kind, r.index, r.tag, r.label, r.thumb ? "t" : ""].join("|"));
    }
    for (var e = 0; e < state.entities.length; e += 1) {
      var ent = state.entities[e] || {};
      bits.push([ent.id, ent.lane, ent.name, ent.priority, (ent.refKeys || []).join(",")].join("|"));
    }
    return bits.join(";");
  }

  function renderBoard() {
    var sig = rosterSig();
    if (sig === boardSig && boardEl.querySelector(".sdp7-lane")) {
      renderBudget();
      applyThumbScale();
      return;
    }
    boardSig = sig;
    var assigned = assignedKeys();
    var html = "";

    // Lanes with their entities (lane header always visible: it is the "+" home).
    for (var l = 0; l < LANES.length; l += 1) {
      var lane = LANES[l];
      html += '<div class="sdp7-lane" data-lane="' + lane.id + '" style="display:flex;flex-direction:column;gap:4px;">' +
        '<div style="display:flex;align-items:center;gap:5px;">' +
          '<span style="width:7px;height:7px;border-radius:50%;background:' + lane.color + ';flex:0 0 auto;"></span>' +
          '<span style="color:#8a929e;font-size:10px;flex:1;">' + esc(lane.label) + "</span>" +
          '<span class="sdp7-lane-add" data-lane="' + lane.id + '" title="New ' + esc(lane.label) + ' entity" style="' +
            "cursor:pointer;color:#6c7481;font-size:12px;padding:0 3px;border-radius:4px;" +
          '">+</span>' +
        "</div>";
      if (addingLane === lane.id) {
        html += '<input class="sdp7-newent" data-lane="' + lane.id + '" type="text" maxlength="32" ' +
          'placeholder="entity name (letters, - )" style="' +
          "padding:3px 6px;border-radius:6px;border:1px solid " + lane.color + "66;background:#0f1116;" +
          "color:#c6cad1;font-family:inherit;font-size:10.5px;outline:none;" +
        '"/>';
      }
      for (var e = 0; e < state.entities.length; e += 1) {
        if (state.entities[e].lane === lane.id) html += entityCardHtml(state.entities[e], e);
      }
      html += "</div>";
    }

    // Pool: refs not owned by any entity.
    var poolRefs = [];
    for (var i = 0; i < state.refs.length; i += 1) {
      if (!assigned[String(state.refs[i].key)]) poolRefs.push(i);
    }
    html += '<div style="display:flex;flex-direction:column;gap:4px;">' +
      '<div style="display:flex;align-items:center;gap:5px;">' +
        '<span style="color:#8a929e;font-size:10px;flex:1;">Pool (' + poolRefs.length + " unassigned)</span>" +
      "</div>" +
      '<div class="sdp7-pool" style="display:grid;grid-template-columns:1fr 1fr;gap:5px;">';
    for (var p = 0; p < poolRefs.length; p += 1) {
      var idx = poolRefs[p];
      var r = state.refs[idx];
      var color = KIND_COLORS[r.kind] || "#c6cad1";
      var thumbUrl = chipThumb(r);
      html += '<div class="sdp-card" data-idx="' + idx + '" data-key="' + esc(String(r.key)) + '" style="' +
        "display:flex;flex-direction:column;border-radius:7px;overflow:hidden;cursor:pointer;" +
        "background:#12151a;border:1px solid #21252c;" +
      '">' +
        // Square via padding-trick (aspect-ratio unsupported here); contain +
        // gray letterbox so portrait/landscape assets are fully visible.
        '<span style="position:relative;display:block;width:100%;padding-top:100%;' +
          "background:#333941;color:" + color + ';overflow:hidden;">' +
          (thumbUrl
            ? '<img src="' + esc(thumbUrl) + '" style="position:absolute;top:0;left:0;width:100%;height:100%;object-fit:contain;" draggable="false"/>'
            : '<span style="position:absolute;top:0;left:0;width:100%;height:100%;display:flex;align-items:center;justify-content:center;">' + (KIND_ICONS[r.kind] || "") + "</span>") +
        "</span>" +
        '<span style="display:flex;flex-direction:column;gap:0;padding:2px 5px 3px;" title="' +
          esc((r.label ? r.label + "  " : "") + "@" + r.tag) + '">' +
          '<span class="sdp-card-label" style="color:' + color + ';font-size:9.5px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' +
            esc(r.label || ("@" + r.tag)) + "</span>" +
          (r.label
            ? '<span class="sdp-card-tag" style="color:#6c7481;font-size:8.5px;">@' + esc(r.tag) + "</span>"
            : "") +
        "</span>" +
      "</div>";
    }
    html += "</div></div>";

    if (!state.refs.length) {
      html = '<div style="color:#6c7481;font-size:10px;line-height:1.5;">' +
        (state.scanMode
          ? "No assets found. Add Load Image / Video / Audio nodes, run them once, then press Rescan."
          : "Connect media on the left.") +
        "</div>" + html;
    }

    boardEl.innerHTML = html;
    try {
      wireBoardEvents();
      renderBudget();
      applyThumbScale();
    } catch (err) {
      // A board hiccup must never kill the editor / targets / sync.
      statusEl.textContent = "Board render issue: " + err;
    }
  }

  function wireBoardEvents() {
    // Lane "+" -> inline name input.
    var adds = boardEl.querySelectorAll(".sdp7-lane-add");
    for (var a = 0; a < adds.length; a += 1) {
      (function (el) {
        el.addEventListener("click", function (e) {
          stop(e);
          if (disabled) return;
          addingLane = (addingLane === el.getAttribute("data-lane")) ? null : el.getAttribute("data-lane");
          renderBoard();
          var inp = boardEl.querySelector(".sdp7-newent");
          if (inp) inp.focus();
        });
      })(adds[a]);
    }
    var newEnt = boardEl.querySelector(".sdp7-newent");
    if (newEnt) {
      newEnt.addEventListener("pointerdown", stop);
      newEnt.addEventListener("keydown", function (e) {
        stop(e);
        if (e.key === "Escape") {
          addingLane = null;
          renderBoard();
          return;
        }
        if (e.key !== "Enter") return;
        var name = sanitizeEntityName(newEnt.value);
        var lane = newEnt.getAttribute("data-lane");
        addingLane = null;
        if (name) {
          state.entities.push({
            id: "e" + Date.now().toString(36) + Math.floor(Math.random() * 1e4).toString(36),
            name: name,
            lane: lane,
            refKeys: [],
            priority: "must"
          });
          markEntityEdit();
          state.statusMessage = "Created @" + name + " - drop pool refs onto it, then mention it in the prompt.";
        }
        renderBoard();
        renderStatus();
        syncToNode();
      });
    }

    // Entity cards: click name to insert mention; star toggles priority;
    // x deletes; thumbnails' x removes a ref; drop target for pool refs.
    var entCards = boardEl.querySelectorAll(".sdp7-ent");
    for (var c = 0; c < entCards.length; c += 1) {
      (function (card) {
        var entity = state.entities[Number(card.getAttribute("data-ent"))];
        if (!entity) return;
        card.addEventListener("click", function (e) {
          stop(e);
          if (disabled) return;
          var t = e.target;
          if (t.classList.contains("sdp7-ent-star")) {
            entity.priority = (entity.priority === "nice") ? "must" : "nice";
            markEntityEdit();
            renderBoard();
            rebindMentions();
            syncToNode();
            return;
          }
          if (t.classList.contains("sdp7-ent-del")) {
            var i = state.entities.indexOf(entity);
            if (i >= 0) state.entities.splice(i, 1);
            markEntityEdit();
            renderBoard();
            rebindMentions();
            handleInput();
            return;
          }
          if (t.classList.contains("sdp7-thumb-x")) {
            var key = t.getAttribute("data-key");
            entity.refKeys = (entity.refKeys || []).filter(function (k) { return String(k) !== String(key); });
            markEntityEdit();
            renderBoard();
            rebindMentions();
            handleInput();
            return;
          }
          insertEntityMention(entity, false);
        });
        card.addEventListener("dragover", function (e) {
          e.preventDefault();
          stop(e);
          if (dragKey !== null) card.style.borderColor = laneColor(entity.lane);
        });
        card.addEventListener("dragleave", function () {
          card.style.borderColor = laneColor(entity.lane) + "33";
        });
        card.addEventListener("drop", function (e) {
          e.preventDefault();
          stop(e);
          if (dragKey === null) return;
          var key = String(dragKey);
          dragKey = null;
          dragIdx = null;
          // Move semantics: a ref lives in at most one entity.
          for (var i = 0; i < state.entities.length; i += 1) {
            state.entities[i].refKeys = (state.entities[i].refKeys || []).filter(function (k) {
              return String(k) !== key;
            });
          }
          entity.refKeys = (entity.refKeys || []).concat([key]);
          markEntityEdit();
          renderBoard();
          rebindMentions();
          handleInput();
        });
      })(entCards[c]);
    }

    // Pool cards: click inserts raw mention; drag onto an entity assigns it,
    // drag onto another pool card swaps their tag slots (V6 behavior).
    var cards = boardEl.querySelectorAll(".sdp-card");
    for (var j = 0; j < cards.length; j += 1) {
      (function (card) {
        var ref = state.refs[Number(card.getAttribute("data-idx"))];
        if (!ref) return;
        var img = card.querySelector("img");
        if (img) hookImgFallback(img, KIND_ICONS[ref.kind]);
        card.addEventListener("click", function (e) {
          stop(e);
          if (disabled) return;
          insertMention(ref, false);
        });
        card.addEventListener("mouseenter", function () { card.style.borderColor = "#333a44"; });
        card.addEventListener("mouseleave", function () { card.style.borderColor = "#21252c"; });

        card.draggable = !disabled;
        card.addEventListener("dragstart", function (e) {
          stop(e);
          dragIdx = Number(card.getAttribute("data-idx"));
          dragKey = card.getAttribute("data-key");
          card.style.opacity = "0.45";
          try {
            e.dataTransfer.setData("text/plain", String(dragKey));
            e.dataTransfer.effectAllowed = "move";
          } catch (_) {}
        });
        card.addEventListener("dragend", function () {
          card.style.opacity = "1";
          dragIdx = null;
          dragKey = null;
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
          if (dragIdx === null || dragIdx === to) { dragKey = null; return; }
          var tmp = state.refs[dragIdx];
          state.refs[dragIdx] = state.refs[to];
          state.refs[to] = tmp;
          dragIdx = null;
          dragKey = null;
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
    var html = '<option value="all">All Seedance nodes (' + state.targets.length + ")</option>";
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
      html += '<optgroup label="Seedance nodes">';
      for (var i = 0; i < state.targets.length; i += 1) {
        var name = String(state.targets[i] || "");
        var profileLabel = "";
        var profiles = Array.isArray(state.targetProfiles) ? state.targetProfiles : [];
        for (var p = 0; p < profiles.length; p += 1) {
          if (String((profiles[p] || {}).name || "") === name && profiles[p].label) {
            profileLabel = " (Seedance " + profiles[p].label + ")";
            break;
          }
        }
        html += '<option value="' + esc(name) + '"' + (state.sendTarget === name ? " selected" : "") + ">"
          + esc(name) + esc(profileLabel) + "</option>";
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
      ? "No Seedance nodes found in this workflow (press Rescan after adding one)."
      : "Write the prompt + ordered references (images, videos, audio) into the selected node, every node, or every Seedance node in a group. No wires needed.";
  }

  function renderToggle() {
    toggleEl.style.background = state.enhance ? "#a58050" : "#21252c";
    knobEl.style.left = state.enhance ? "18px" : "2px";
    knobEl.style.background = state.enhance ? "#0c0e11" : "#6c7481";
  }

  function renderStatus() {
    statusEl.textContent = state.statusMessage || "";
    if (promptFileStatusEl) promptFileStatusEl.textContent = state.promptFileStatus || "";
    if (promptFileNameEl) {
      var picked = String(state.promptFile || "").trim();
      var slash = Math.max(picked.lastIndexOf("/"), picked.lastIndexOf("\\"));
      var fileName = slash >= 0 ? picked.slice(slash + 1) : picked;
      promptFileNameEl.textContent = fileName || "No file picked";
      promptFileNameEl.title = picked;
    }
  }

  function renderCharCount() {
    var n = exportedText().length;
    charsEl.textContent = n ? n.toLocaleString() + " chars" : "";
  }

  // ---------------------------------------------------------------- hover card (prompt mentions only)

  function showHover(ref, anchorEl) {
    var inner = "";
    var full = (ref.url && /^(https?:|data:)/.test(ref.url)) ? ref.url : "";
    if (ref.kind === "image" && (full || ref.thumb)) {
      inner = '<img class="sdp-hover-media" src="' + esc(full || ref.thumb) + '" style="display:block;max-width:220px;max-height:160px;border-radius:6px;" draggable="false"/>';
    } else if (ref.kind === "video" && (full || ref.thumb)) {
      if (full) {
        inner = '<video src="' + esc(full) + '"' + (ref.thumb ? ' poster="' + esc(ref.thumb) + '"' : "") +
          ' muted autoplay loop playsinline style="display:block;max-width:220px;max-height:160px;border-radius:6px;"></video>';
      } else {
        inner = '<img src="' + esc(ref.thumb) + '" style="display:block;max-width:220px;max-height:160px;border-radius:6px;" draggable="false"/>';
      }
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
    if (!q || (state.refs.length === 0 && state.entities.length === 0)) { closeMenu(); return; }
    var items = [];
    // Entities first: with 50 refs they're the primary way to mention things.
    for (var e = 0; e < state.entities.length; e += 1) {
      var ent = state.entities[e];
      var laneLabel = (LANE_BY_ID[ent.lane] || {}).label || ent.lane;
      var entHay = (ent.name + " " + laneLabel + " entity").toLowerCase();
      if (!q.query || entHay.indexOf(q.query) >= 0) items.push({ type: "entity", entity: ent });
    }
    for (var i = 0; i < state.refs.length; i += 1) {
      var r = state.refs[i];
      var hay = (r.tag + " " + (r.label || "") + " " + r.kind).toLowerCase();
      if (!q.query || hay.indexOf(q.query) >= 0) items.push({ type: "ref", ref: r });
    }
    if (!items.length) { closeMenu(); return; }
    menuState.open = true;
    menuState.items = items;
    menuState.active = Math.min(menuState.active, items.length - 1);

    var html = "";
    for (var k = 0; k < items.length; k += 1) {
      var item = items[k];
      if (item.type === "entity") {
        var ent2 = item.entity;
        var color2 = laneColor(ent2.lane);
        var refs2 = entityRefs(ent2);
        var stack = "";
        for (var s = 0; s < Math.min(4, refs2.length); s += 1) {
          var st = chipThumb(refs2[s]);
          stack += '<span style="width:14px;height:22px;overflow:hidden;flex:0 0 auto;">' +
            (st ? '<img src="' + esc(st) + '" style="width:22px;height:22px;object-fit:cover;border-radius:4px;" draggable="false"/>' : "") +
          "</span>";
        }
        html += '<div class="sdp-item" data-idx="' + k + '" style="' +
          "display:flex;align-items:center;gap:8px;padding:5px 7px;border-radius:6px;cursor:pointer;" +
          (k === menuState.active ? "background:#1a1f26;" : "") +
        '">' +
          '<span style="display:inline-flex;width:30px;height:30px;border-radius:6px;overflow:hidden;background:#0c0e11;' +
            "align-items:center;justify-content:center;flex:0 0 auto;gap:0;padding:0 2px;box-sizing:border-box;" +
            "border:1px solid " + color2 + '44;">' + (stack || '<span style="color:' + color2 + ';font-weight:700;">@</span>') + "</span>" +
          '<span style="display:flex;flex-direction:column;min-width:0;">' +
            '<span style="color:' + color2 + ';font-weight:600;">@' + esc(ent2.name) + "</span>" +
            '<span style="color:#6c7481;font-size:10px;">' + esc((LANE_BY_ID[ent2.lane] || {}).label || ent2.lane) +
              " &#183; " + refs2.length + " ref" + (refs2.length === 1 ? "" : "s") +
              (ent2.priority === "nice" ? " &#183; nice-to-have" : "") + "</span>" +
          "</span>" +
        "</div>";
      } else {
        var ref = item.ref;
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
    }
    menu.innerHTML = html;
    var els = menu.querySelectorAll(".sdp-item");
    for (var n = 0; n < els.length; n += 1) {
      (function (el) {
        var item = menuState.items[Number(el.getAttribute("data-idx"))];
        var itemImg = el.querySelector("img");
        if (itemImg && item.type === "ref") hookImgFallback(itemImg, KIND_ICONS[item.ref.kind]);
        el.addEventListener("mousedown", function (e) {
          e.preventDefault();
          stop(e);
          if (item.type === "entity") insertEntityMention(item.entity, true);
          else insertMention(item.ref, true);
        });
        el.addEventListener("mouseenter", function () {
          menuState.active = Number(el.getAttribute("data-idx"));
          highlightActive();
        });
      })(els[n]);
    }

    var pos = { x: 8, y: 24 };
    var range = caretRange();
    if (range) {
      var cr = range.cloneRange();
      cr.collapse(true);
      var rect = cr.getBoundingClientRect();
      if (rect && (rect.left || rect.top)) pos = toLocal(rect.left, rect.bottom, editorWrap);
    }
    var top = pos.y + 4;
    if (top + 220 > editorWrap.offsetHeight) top = Math.max(0, pos.y - 244);
    menu.style.top = top + "px";
    menu.style.left = Math.min(Math.max(0, pos.x), Math.max(0, editorWrap.offsetWidth - 250)) + "px";
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
      entities: state.entities,
      budget: state.budget,
      statusMessage: state.statusMessage
    };
    payload.fontSize = state.fontSize;
    payload.uiScale = state.uiScale;
    payload.thumbScale = state.thumbScale;
    if (state.scanMode) {
      payload.scanMode = true;
      payload.scanNonce = state.scanNonce;
      payload.targets = state.targets;
      payload.targetProfiles = state.targetProfiles;
      payload.groups = state.groups;
      payload.sendTarget = state.sendTarget;
      payload.promptFile = state.promptFile;
      payload.promptFileNonce = state.promptFileNonce;
      payload.promptFileStatus = state.promptFileStatus;
      payload.promptBrowseNonce = state.promptBrowseNonce;
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
  // racing the editor. Buttons (send/rescan/entity edits) sync immediately.
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
    renderBudget();
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
  // Right-click: keep the browser's native spellcheck menu working.
  input.addEventListener("contextmenu", stop);
  // Drop target: pool cards dropped here become mention tags at the drop point.
  input.addEventListener("dragover", function (e) {
    if (dragKey === null) return;
    e.preventDefault();
    stop(e);
    try { e.dataTransfer.dropEffect = "copy"; } catch (_) {}
    input.style.borderColor = "#a58050";
  });
  input.addEventListener("dragleave", function () {
    input.style.borderColor = "#21252c";
  });
  input.addEventListener("drop", function (e) {
    if (dragKey === null) return;
    e.preventDefault();
    stop(e);
    input.style.borderColor = "#21252c";
    var ref = refByKey(dragKey);
    dragIdx = null;
    dragKey = null;
    if (ref) insertPillAtPoint(makeMentionEl(String(ref.kind), Number(ref.index)), e.clientX, e.clientY);
  });
  input.addEventListener("paste", function (e) {
    stop(e);
    e.preventDefault();
    var text = "";
    try { text = (e.clipboardData || window.clipboardData).getData("text/plain") || ""; } catch (_) { text = ""; }
    if (!text) return;
    var range = caretRange();
    if (!range) return;
    range.deleteContents();
    // Pasted @Image1 / @EntityName tokens become mention pills automatically.
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
        var item = menuState.items[menuState.active];
        if (item.type === "entity") insertEntityMention(item.entity, true);
        else insertMention(item.ref, true);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        closeMenu();
        return;
      }
    }
    if (e.key === "Enter") {
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

  boardEl.addEventListener("dragover", function (e) { e.preventDefault(); });
  boardEl.addEventListener("drop", function (e) {
    e.preventDefault();
    stop(e);
    dragIdx = null;
    dragKey = null;
  });

  budgetInput.addEventListener("pointerdown", stop);
  budgetInput.addEventListener("keydown", stop);
  budgetInput.addEventListener("change", function (e) {
    stop(e);
    state.budget = clampBudget(budgetInput.value);
    renderBudget();
    syncToNode();
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

  // ---------------------------------------------------------------- UI scale

  var uiSlider = container.querySelector(".sdp-uiscale");

  // CSS zoom scales everything uniformly; the declared height shrinks by the
  // same factor so the zoomed output still fits the node's widget area.
  var lastFitHeight = 0;
  function fitHeight() {
    if (inFullscreen()) {
      applyFsSize();
      return;
    }
    var h = Math.max(280, Math.round((container.clientHeight || widgetHeight) / (state.uiScale || 1)));
    if (h === lastFitHeight) return;
    lastFitHeight = h;
    root.style.height = h + "px";
  }

  function applyUiScale() {
    try { root.style.zoom = String(state.uiScale); } catch (_) {}
    fitHeight();
  }

  uiSlider.addEventListener("input", function (e) {
    stop(e);
    state.uiScale = Math.min(3, Math.max(1, Number(uiSlider.value) || 1));
    applyUiScale();
  });
  uiSlider.addEventListener("change", function (e) {
    stop(e);
    syncToNode();
  });
  uiSlider.addEventListener("pointerdown", stop);

  // ---------------------------------------------------------------- thumbnail size (pool cards only)

  var thumbSlider = container.querySelector(".sdp-thumbscale");

  function applyThumbScale() {
    var scale = Math.min(3, Math.max(1, Number(state.thumbScale) || 1));
    var cols = scale >= 1.5 ? 1 : 2;
    var cell = Math.round(94 * scale);
    var gap = 5;
    var sideW = cols === 2 ? cell * 2 + gap + 12 : cell + 12;
    if (sideEl) {
      sideEl.style.width = sideW + "px";
      sideEl.style.flex = "0 0 " + sideW + "px";
    }
    var pool = boardEl ? boardEl.querySelector(".sdp7-pool") : null;
    if (pool) pool.style.gridTemplateColumns = cols === 1 ? "1fr" : "1fr 1fr";
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
    return document.fullscreenElement === root || root.classList.contains("sdp7-fs");
  }

  // Under CSS zoom the 100vw/100vh rules would render zoom-times too large;
  // inline !important sizes (divided by the scale) win the cascade.
  function applyFsSize() {
    if (inFullscreen()) {
      root.style.setProperty("width", Math.round(window.innerWidth / (state.uiScale || 1)) + "px", "important");
      root.style.setProperty("height", Math.round(window.innerHeight / (state.uiScale || 1)) + "px", "important");
    } else {
      root.style.removeProperty("width");
      root.style.height = Math.max(280, Math.round((container.clientHeight || widgetHeight) / (state.uiScale || 1))) + "px";
    }
  }

  function fsFallback(on) {
    if (on) root.classList.add("sdp7-fs");
    else root.classList.remove("sdp7-fs");
    updateFsButton();
    applyFsSize();
  }

  function toggleFullscreen() {
    if (document.fullscreenElement === root) {
      if (document.exitFullscreen) document.exitFullscreen();
      return;
    }
    if (root.classList.contains("sdp7-fs")) {
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

  function onFsChange() {
    updateFsButton();
    applyFsSize();
  }
  document.addEventListener("fullscreenchange", onFsChange);

  fsBtn.addEventListener("click", function (e) {
    stop(e);
    toggleFullscreen();
  });
  fsBtn.addEventListener("pointerdown", stop);

  function onDocKeydown(e) {
    if (e.key === "Escape" && root.classList.contains("sdp7-fs")) fsFallback(false);
  }
  document.addEventListener("keydown", onDocKeydown);

  // ---------------------------------------------------------------- voice input

  var SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition || null;
  var recog = null;
  var listening = false;

  var NUM_WORDS = {
    one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8,
    nine: 9, ten: 10, eleven: 11, twelve: 12, thirteen: 13, fourteen: 14,
    fifteen: 15, sixteen: 16, to: 2, too: 2, for: 4
  };

  function normalizeDictation(text) {
    // "at image three" -> @Image3; "at maya" -> @Maya when the entity exists.
    var out = String(text || "").replace(
      /\b(at\s+)?(image|video|audio)\s+(?:number\s+)?(\d{1,2}|one|two|to|too|three|four|for|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen)\b/gi,
      function (m, at, kind, num) {
        var word = String(num).toLowerCase();
        if (!at && (word === "to" || word === "too" || word === "for")) return m;
        var n = NUM_WORDS[word] || parseInt(num, 10);
        if (!n) return m;
        return "@" + kind.charAt(0).toUpperCase() + kind.slice(1).toLowerCase() + n;
      }
    );
    out = out.replace(/\bat\s+([A-Za-z][\w-]{0,32})\b/gi, function (m, word) {
      var entity = entityByName(word);
      return entity ? "@" + entity.name : m;
    });
    return out;
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
    if (cmd === "send it" || cmd === "send prompt" || cmd === "send to seedance") {
      stopVoice();
      sendBtn.click();
      return;
    }
    insertDictation(text);
  }

  function updateMicBtn() {
    micBtn.style.borderColor = listening ? "#a58050" : "#333a44";
    micBtn.style.background = listening ? "#241d13" : "#161a20";
    micBtn.style.color = listening ? "#d9c6a4" : "#c6cad1";
    micBtn.title = listening
      ? "Stop dictation"
      : "Dictate prompt. Say 'at image 2' for @Image2 or 'at maya' for @Maya; commands: 'new line', 'clear prompt', 'send it'.";
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
      statusEl.textContent = "Voice error: " + err +
        (err === "not-allowed" ? " - allow microphone access for this site" : "") +
        (err === "network" ? " - speech service unreachable (browser required)" : "");
      stopVoice();
    };
    recog.onend = function () {
      if (listening) { try { recog.start(); } catch (_) { stopVoice(); } }
    };
    listening = true;
    updateMicBtn();
    statusEl.textContent = "Listening... 'at image 2' inserts @Image2, 'at maya' inserts @Maya; say 'new line', 'clear prompt' or 'send it'.";
    try { recog.start(); } catch (_) { stopVoice(); }
  }

  micBtn.addEventListener("click", function (e) {
    stop(e);
    if (disabled) return;
    if (listening) stopVoice();
    else startVoice();
  });
  micBtn.addEventListener("pointerdown", stop);

  targetSel.addEventListener("change", function (e) {
    stop(e);
    state.sendTarget = targetSel.value || "all";
    renderBudget();
    syncToNode();
  });
  targetSel.addEventListener("pointerdown", stop);
  if (promptFileLoadBtn) {
    promptFileLoadBtn.addEventListener("pointerdown", stop);
    promptFileLoadBtn.addEventListener("click", function (e) {
      stop(e);
      if (disabled) return;
      state.promptBrowseNonce = (state.promptBrowseNonce || 0) + 1;
      state.promptFileStatus = "Opening the file picker (check the taskbar if it opens behind)...";
      renderStatus();
      syncToNode();
    });
  }
  if (promptFileBtn) {
    promptFileBtn.addEventListener("pointerdown", stop);
    promptFileBtn.addEventListener("click", function (e) {
      stop(e);
      if (disabled) return;
      state.promptFileNonce = (state.promptFileNonce || 0) + 1;
      state.promptFileStatus = "Reading prompt file...";
      renderStatus();
      syncToNode();
    });
  }

  sendBtn.addEventListener("click", function (e) {
    stop(e);
    if (disabled || state.targets.length === 0) return;
    state.doSend = true;
    state.sendNonce = (state.sendNonce || 0) + 1;
    var destLabel = "Seedance";
    if (state.sendTarget && state.sendTarget.indexOf(groupPrefix()) === 0) {
      destLabel = "group '" + state.sendTarget.slice(groupPrefix().length) + "'";
    } else if (state.sendTarget && state.sendTarget !== "all") {
      destLabel = "'" + state.sendTarget + "'";
    }
    statusEl.textContent = "Sending prompt + images / videos / audio to " + destLabel + "...";
    syncToNode();
  });

  var rescanBtn = container.querySelector(".sdp-rescan");
  if (rescanBtn) {
    rescanBtn.addEventListener("click", function (e) {
      stop(e);
      if (disabled) return;
      state.scanNonce = (state.scanNonce || 0) + 1;
      statusEl.textContent = "Rescanning workflow assets...";
      syncToNode();
    });
  }

  // Fill the node's widget area vertically and follow node resizes
  // (scale-aware: the zoomed output must match the container exactly).
  var resizeObs = null;
  var lastContainerH = 0;
  if (typeof ResizeObserver !== "undefined") {
    resizeObs = new ResizeObserver(function () {
      var h = container.clientHeight || 0;
      if (h === lastContainerH) return;
      lastContainerH = h;
      fitHeight();
    });
    resizeObs.observe(container);
  }
  applyUiScale();

  try { renderBoard(); } catch (err) { statusEl.textContent = "Board render issue: " + err; }
  renderTargets();
  renderToggle();
  applyFontSize();
  renderEditorFromText(state.text);
  renderStatus();
  renderCharCount();
  syncToNode();

  // ---------------------------------------------------------------- live updates

  function applyPendingUpdate() {
    if (pendingUpdate === null || dragIdx !== null) return;
    var queued = pendingUpdate;
    pendingUpdate = null;
    externalUpdate(queued);
  }

  function entitySig(list) {
    var bits = [];
    for (var i = 0; i < list.length; i += 1) {
      var ent = list[i] || {};
      bits.push([ent.id, ent.lane, ent.name, ent.priority, (ent.refKeys || []).join(",")].join("|"));
    }
    return bits.join(";");
  }

  function cardForKey(key) {
    var cards = boardEl.querySelectorAll(".sdp-card");
    for (var i = 0; i < cards.length; i += 1) {
      if (cards[i].getAttribute("data-key") === key) return cards[i];
    }
    return null;
  }

  function applyIncomingRefs(incoming) {
    // Keep the cards in the order already on screen. A scan echo must not
    // reshuffle them; only added or removed files rebuild the column.
    var byKey = {};
    for (var i = 0; i < incoming.length; i += 1) {
      var item = incoming[i] || {};
      var key = String(item.key || "");
      if (key) byKey[key] = item;
    }
    var seen = {};
    var next = [];
    var structural = false;
    for (var j = 0; j < state.refs.length; j += 1) {
      var prev = state.refs[j];
      var prevKey = String(prev.key || "");
      var inc = byKey[prevKey];
      if (!inc) {
        structural = true;
        continue;
      }
      seen[prevKey] = true;
      if (String(inc.kind || "") !== String(prev.kind || "") || String(inc.label || "") !== String(prev.label || "")) {
        structural = true;
      }
      var nextTag = String(inc.tag || prev.tag || "");
      var nextLabel = String(inc.label || prev.label || "");
      if (nextTag !== String(prev.tag || "") || nextLabel !== String(prev.label || "")) {
        var card = cardForKey(prevKey);
        var labelEl = card ? card.querySelector(".sdp-card-label") : null;
        var tagEl = card ? card.querySelector(".sdp-card-tag") : null;
        if (labelEl) labelEl.textContent = nextLabel || ("@" + nextTag);
        if (tagEl) tagEl.textContent = "@" + nextTag;
        else if (nextLabel && nextTag && !structural) structural = !card;
      }
      var thumb = String(inc.thumb || "");
      var hadThumb = String(prev.thumb || "");
      prev.tag = nextTag || prev.tag;
      prev.kind = inc.kind || prev.kind;
      prev.index = inc.index || prev.index;
      prev.label = nextLabel || prev.label;
      prev.url = inc.url || prev.url;
      if (thumb && thumb !== hadThumb) {
        prev.thumb = thumb;
        var imgCard = cardForKey(prevKey);
        var img = imgCard ? imgCard.querySelector("img") : null;
        if (img) img.src = thumb;
        else structural = true;
      }
      next.push(prev);
    }
    for (var n = 0; n < incoming.length; n += 1) {
      var incomingKey = String((incoming[n] && incoming[n].key) || "");
      if (incomingKey && !seen[incomingKey]) {
        next.push(incoming[n]);
        structural = true;
      }
    }
    state.refs = next;
    return structural;
  }

  function sameKeyOrderIgnored(incoming) {
    if (!Array.isArray(incoming) || incoming.length !== state.refs.length) return false;
    var a = [], b = [];
    for (var i = 0; i < incoming.length; i += 1) a.push(String((incoming[i] || {}).key || ""));
    for (var j = 0; j < state.refs.length; j += 1) b.push(String((state.refs[j] || {}).key || ""));
    if (a.join("|") === b.join("|")) return false;
    return a.slice().sort().join("|") === b.slice().sort().join("|");
  }

  function externalUpdate(newProps) {
    // Never touch the DOM mid-drag: rebuilding the board kills the native drag.
    if (dragIdx !== null || dragKey !== null) {
      pendingUpdate = newProps;
      return;
    }
    var v = (newProps && newProps.value && typeof newProps.value === "object") ? newProps.value : {};
    var focused = editorFocused();
    var typedRecently = Date.now() - lastLocalEditAt < 4000;
    var typingEntityName = !!boardEl.querySelector(".sdp7-newent") &&
      document.activeElement === boardEl.querySelector(".sdp7-newent");

    if (typeof v.statusMessage === "string") state.statusMessage = v.statusMessage;
    if (typeof v.enhance === "boolean") state.enhance = v.enhance;
    if (typeof v.scanNonce === "number") state.scanNonce = v.scanNonce;
    if (typeof v.sendNonce === "number") state.sendNonce = v.sendNonce;
    if (typeof v.doSend === "boolean") state.doSend = v.doSend;
    if (v.sendTarget) state.sendTarget = String(v.sendTarget);
    if (typeof v.promptFile === "string") state.promptFile = v.promptFile;
    if (typeof v.promptFileStatus === "string") state.promptFileStatus = v.promptFileStatus;
    if (typeof v.promptFileNonce === "number") state.promptFileNonce = v.promptFileNonce;
    if (typeof v.promptBrowseNonce === "number") state.promptBrowseNonce = v.promptBrowseNonce;
    if (v.budget) state.budget = clampBudget(v.budget);
    if (v.fontSize) {
      var fs = Math.min(22, Math.max(10, Number(v.fontSize) || state.fontSize));
      if (fs !== state.fontSize) {
        state.fontSize = fs;
        fontSlider.value = String(fs);
        applyFontSize();
      }
    }
    if (v.uiScale) {
      var us = Math.min(3, Math.max(1, Number(v.uiScale) || state.uiScale));
      if (us !== state.uiScale) {
        state.uiScale = us;
        uiSlider.value = String(us);
        applyUiScale();
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
    if (Array.isArray(v.targetProfiles)) {
      var incomingProfiles = v.targetProfiles.slice();
      try {
        if (JSON.stringify(incomingProfiles) !== JSON.stringify(state.targetProfiles)) {
          targetsChanged = true;
          state.targetProfiles = incomingProfiles;
        }
      } catch (_) {
        state.targetProfiles = incomingProfiles;
        targetsChanged = true;
      }
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

    var entitiesChanged = false;
    if (Array.isArray(v.entities) && Date.now() - lastEntityEditAt > 4000) {
      // Recent local entity edits win over stale echoes from the node.
      entitiesChanged = entitySig(v.entities) !== entitySig(state.entities);
      if (entitiesChanged) state.entities = v.entities.slice();
    }

    var refsChanged = false;
    if (Array.isArray(v.refs)) {
      var staleEcho = (Date.now() - lastReorderAt < 4000) && sameKeyOrderIgnored(v.refs);
      if (!staleEcho) refsChanged = applyIncomingRefs(v.refs);
    }

    if ((refsChanged || entitiesChanged) && !typingEntityName) renderBoard();
    if (refsChanged || targetsChanged || groupsChanged) renderTargets();

    var incomingText = (typeof v.text === "string") ? v.text : state.text;
    // Text changes only apply when the user clearly isn't editing; anything
    // else is a stale echo of our own sync racing the keyboard.
    var fileFollows = String(state.promptFile || "").trim().length > 0;
    if (incomingText !== state.text && !focused && (fileFollows || !typedRecently)) {
      state.text = incomingText;
      renderEditorFromText(state.text);
    } else if (refsChanged || entitiesChanged) {
      if (focused || typedRecently) {
        rebindMentions();
      } else {
        renderEditorFromText(state.text);
      }
    }

    renderToggle();
    renderStatus();
    renderCharCount();
    renderBudget();
    updatePlaceholder();
  }

  return {
    update: externalUpdate,
    cleanup: function cleanup() {
      if (syncTimer) { clearTimeout(syncTimer); syncTimer = null; }
      stopVoice();
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
