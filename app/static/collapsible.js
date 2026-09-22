(function () {
  "use strict";
  var sections = document.querySelectorAll("details.js-collapsible");

  Array.prototype.forEach.call(sections, function (det) {
    var key = det.getAttribute("data-storage-key");
    var icon = det.querySelector(".collapsible-toggle-icon");

    function updateIcon() {
      if (icon) {
        icon.textContent = det.open ? "▼ Hide" : "▶ Show";
      }
    }

    try {
      var stored = key ? localStorage.getItem(key) : null;
      if (stored === "true") {
        det.open = true;
      } else if (stored === "false") {
        det.open = false;
      }
    } catch (e) {
      // localStorage unavailable (private mode, etc.) — fall back to server-rendered default.
    }

    updateIcon();

    det.addEventListener("toggle", function () {
      try {
        if (key) {
          localStorage.setItem(key, det.open);
        }
      } catch (e) {
        // ignore — per-viewer convenience only
      }
      updateIcon();
    });
  });
})();
