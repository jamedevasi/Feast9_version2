(function () {
  "use strict";
  var det = document.getElementById("referrals-details");
  if (!det) {
    return;
  }
  var key = "referrals_open_" + det.getAttribute("data-case-id");

  function updateIcon() {
    var icon = det.querySelector(".referral-toggle-icon");
    if (icon) {
      icon.textContent = det.open ? "▼ Hide" : "▶ Show";
    }
  }

  try {
    var stored = localStorage.getItem(key);
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
      localStorage.setItem(key, det.open);
    } catch (e) {
      // ignore — per-viewer convenience only
    }
    updateIcon();
  });
})();
