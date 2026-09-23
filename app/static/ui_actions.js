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
