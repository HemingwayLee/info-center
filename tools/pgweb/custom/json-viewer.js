// Pretty-prints JSON in pgweb's "Cell Content" popup (opened by double-clicking a cell, or right-click >
// Display value), with a "Pretty JSON" switch in the popup's title bar that appears only for JSON values.
// Loaded into pgweb's page by tools/pgweb/nginx.conf; pgweb's own code is unchanged.
(function () {
  var STORAGE_KEY = "pgweb-pretty-json";

  function prettyJson(text) {
    var trimmed = text.trim();
    if (!/^[[{]/.test(trimmed)) return null; // only objects and arrays, not plain strings or numbers
    try {
      return JSON.stringify(JSON.parse(trimmed), null, 2);
    } catch (e) {
      return null;
    }
  }

  function loadEnabled() {
    try {
      return localStorage.getItem(STORAGE_KEY) !== "off";
    } catch (e) {
      return true;
    }
  }

  function saveEnabled(on) {
    try {
      localStorage.setItem(STORAGE_KEY, on ? "on" : "off");
    } catch (e) {
      /* the choice just won't be remembered */
    }
  }

  function addStyles() {
    var style = document.createElement("style");
    style.textContent = [
      "#content_modal .json-toggle { float: right; display: none; align-items: center; gap: 6px;",
      "  height: 24px; margin-left: 8px; padding: 0 8px; font-size: 12px; font-weight: normal;",
      "  background: #fff; border: 1px solid #ddd; border-radius: 3px; cursor: pointer; user-select: none; }",
      "#content_modal .json-toggle:hover { border-color: #999; box-shadow: #eee 0 0 5px; }",
      "#content_modal .json-toggle .track { position: relative; width: 26px; height: 14px;",
      "  border-radius: 7px; background: #bbb; transition: background .15s; }",
      "#content_modal .json-toggle .track::after { content: ''; position: absolute; top: 2px; left: 2px;",
      "  width: 10px; height: 10px; border-radius: 50%; background: #fff; transition: left .15s; }",
      "#content_modal .json-toggle[aria-checked='true'] .track { background: #337ab7; }",
      "#content_modal .json-toggle[aria-checked='true'] .track::after { left: 14px; }",
    ].join("\n");
    document.head.appendChild(style);
  }

  function start() {
    var pre = document.querySelector("#content_modal pre");
    var actions = document.querySelector("#content_modal .actions");
    if (!pre || !actions) return;

    var enabled = loadEnabled();
    var raw = "";      // the value as pgweb put it in the popup
    var shown = null;  // what we last wrote into the popup, so our own writes aren't mistaken for new values

    addStyles();
    var toggle = document.createElement("span");
    toggle.className = "json-toggle";
    toggle.setAttribute("role", "switch");
    toggle.setAttribute("tabindex", "0");
    toggle.title = "Show this JSON indented or as stored";
    toggle.innerHTML = '<span class="track"></span><span>Pretty JSON</span>';
    actions.appendChild(toggle);

    function render() {
      var formatted = prettyJson(raw);
      toggle.style.display = formatted === null ? "none" : "inline-flex";
      toggle.setAttribute("aria-checked", String(enabled));
      if (formatted === null) {
        shown = null;
        return;
      }
      shown = enabled ? formatted : raw;
      if (pre.textContent !== shown) pre.textContent = shown;
    }

    function flip() {
      enabled = !enabled;
      saveEnabled(enabled);
      render();
    }

    toggle.addEventListener("click", flip);
    toggle.addEventListener("keydown", function (e) {
      if (e.key === " " || e.key === "Enter") {
        e.preventDefault();
        flip();
      }
    });

    // A change we didn't make means pgweb opened the popup with a new value.
    new MutationObserver(function () {
      var text = pre.textContent;
      if (text === shown) return;
      raw = text;
      render();
    }).observe(pre, { childList: true, characterData: true, subtree: true });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
