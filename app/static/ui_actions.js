// App-wide UI behaviours that used to be inline onsubmit=/onclick= attributes. The CSP is
// script-src 'self', which silently blocks every inline event handler — so the "Are you
// sure?" prompts on destructive actions never appeared and the forms submitted straight away.
// Declarative instead: put data-confirm="message" on a <form>, or data-copy on an element.
(function () {
  "use strict";

  // Capture phase, so the prompt runs before any other submit handler on the page.
  document.addEventListener("submit", function (e) {
    var form = e.target;
    var message = form.getAttribute && form.getAttribute("data-confirm");
    if (message && !window.confirm(message)) {
      e.preventDefault();
      e.stopImmediatePropagation();
    }
  }, true);

  // Top-nav dropdowns (<details class="nav-dropdown">, e.g. Settings) are native <details>,
  // which only close when their own summary is clicked — close them on a click anywhere
  // else, or on Escape, like a normal menu.
  function closeNavDropdowns(except) {
    Array.prototype.forEach.call(document.querySelectorAll("details.nav-dropdown[open]"), function (menu) {
      if (menu !== except) menu.removeAttribute("open");
    });
  }
  document.addEventListener("click", function (e) {
    closeNavDropdowns(e.target.closest && e.target.closest("details.nav-dropdown"));
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeNavDropdowns(null);
  });

  // Automatic logout (Settings > Automatic Logout). The server already refuses a session
  // idle past the limit, but only when the next request arrives — this timer logs the
  // screen out on its own, so patient details aren't left open on an unattended computer.
  // Activity in any Feast9 tab keeps every tab alive (shared via localStorage), and while
  // someone is active without clicking through (typing a long note) the server is pinged
  // at most once a minute so its idle check sees the same activity.
  var logoutForm = document.getElementById("logout-form");
  var idleSeconds = logoutForm ? parseInt(logoutForm.getAttribute("data-idle-timeout"), 10) : 0;
  if (idleSeconds > 0) {
    var SHARED_KEY = "feast9-last-activity";
    var PING_EVERY_MS = 60 * 1000;
    var WRITE_EVERY_MS = 5 * 1000;
    var lastActivity = Date.now();
    var lastPing = Date.now();  // loading this page was itself a request
    var lastWrite = 0;

    var sharedActivity = function () {
      try { return parseInt(window.localStorage.getItem(SHARED_KEY), 10) || 0; } catch (e) { return 0; }
    };
    var noteActivity = function () {
      var now = Date.now();
      lastActivity = now;
      if (now - lastWrite > WRITE_EVERY_MS) {
        lastWrite = now;
        try { window.localStorage.setItem(SHARED_KEY, String(now)); } catch (e) { /* private mode etc. */ }
      }
      if (now - lastPing > PING_EVERY_MS) {
        lastPing = now;
        fetch(logoutForm.getAttribute("data-ping-url"), { credentials: "same-origin", cache: "no-store" })
          .then(function (resp) {
            // Redirected to the login page: this session already ended on the server
            // (another device, a password change, the account deactivated) — show why.
            if (resp.redirected) { window.location.href = resp.url; }
          })
          .catch(function () { /* offline for a moment — the next ping will try again */ });
      }
    };
    ["mousemove", "mousedown", "keydown", "scroll", "touchstart", "wheel"].forEach(function (name) {
      document.addEventListener(name, noteActivity, { passive: true, capture: true });
    });
    noteActivity();

    var loggingOut = false;
    window.setInterval(function () {
      var latest = Math.max(lastActivity, sharedActivity());
      if (!loggingOut && Date.now() - latest >= idleSeconds * 1000) {
        loggingOut = true;
        var reason = document.createElement("input");
        reason.type = "hidden";
        reason.name = "reason";
        reason.value = "idle";
        logoutForm.appendChild(reason);
        logoutForm.submit();
      }
    }, 15 * 1000);
  }

  // Click-to-copy (appointment reminder text). The element right after it, if it has
  // data-copy-feedback, is shown for 2s as a "Copied" confirmation.
  document.addEventListener("click", function (e) {
    var el = e.target.closest && e.target.closest("[data-copy]");
    if (!el) return;
    var text = el.textContent.trim();
    var feedback = el.nextElementSibling;
    function showFeedback() {
      if (feedback && feedback.hasAttribute("data-copy-feedback")) {
        feedback.style.display = "block";
        setTimeout(function () { feedback.style.display = "none"; }, 2000);
      }
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(showFeedback, function () {});
    }
  });
})();
