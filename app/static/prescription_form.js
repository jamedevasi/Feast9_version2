// New Prescription form: every medicine row is in the page (so it works without this script);
// here the empty rows after the first are folded away behind "+ Add another medicine".
(function () {
  "use strict";
  var form = document.querySelector("[data-rx-form]");
  if (!form) {
    return;
  }
  var rows = form.querySelectorAll("[data-rx-row]");
  var addButton = form.querySelector("[data-rx-add]");

  function isFilled(row) {
    var inputs = row.querySelectorAll("input");
    for (var i = 0; i < inputs.length; i++) {
      if (inputs[i].value.trim() !== "") {
        return true;
      }
    }
    return false;
  }

  function hiddenRows() {
    return form.querySelectorAll("[data-rx-row][hidden]");
  }

  for (var i = 1; i < rows.length; i++) {
    if (!isFilled(rows[i])) {
      rows[i].setAttribute("hidden", "");
    }
  }
  // The "not filled in yet" warning lists only the chosen prescribing doctor's missing details.
  var gaps = form.querySelector("[data-rx-gaps]");
  var prescriber = form.querySelector("select[name=prescriber_id]");
  if (gaps && prescriber) {
    prescriber.addEventListener("change", function () {
      var items = gaps.querySelectorAll("li");
      var shown = 0;
      for (var j = 0; j < items.length; j++) {
        var owner = items[j].getAttribute("data-rx-gap-doctor");
        var show = owner === null || owner === prescriber.value;
        items[j].hidden = !show;
        if (show) {
          shown += 1;
        }
      }
      gaps.hidden = shown === 0;
    });
  }

  if (addButton && hiddenRows().length) {
    addButton.removeAttribute("hidden");
    addButton.addEventListener("click", function () {
      var next = hiddenRows()[0];
      if (next) {
        next.removeAttribute("hidden");
        var first = next.querySelector("input");
        if (first) {
          first.focus();
        }
      }
      if (!hiddenRows().length) {
        addButton.setAttribute("hidden", "");
      }
    });
  }
})();
