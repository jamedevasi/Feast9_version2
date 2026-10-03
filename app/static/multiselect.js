// Enhances <details data-multiselect> checklists (case form's Procedures): a search box that
// filters the options, a summary line listing what's ticked, and closing when you click
// elsewhere. Without JS it's still a working <details> of checkboxes.
(function () {
  "use strict";

  Array.prototype.forEach.call(document.querySelectorAll("details[data-multiselect]"), function (box) {
    var summary = box.querySelector(".multiselect-summary");
    var count = box.querySelector(".multiselect-count");
    var search = box.querySelector(".multiselect-search");
    var empty = box.querySelector(".multiselect-empty");
    var options = Array.prototype.slice.call(box.querySelectorAll(".multiselect-options label"));
    var placeholder = summary.getAttribute("data-placeholder");

    function refreshSummary() {
      var picked = options
        .filter(function (label) { return label.querySelector("input").checked; })
        .map(function (label) { return label.textContent.trim(); });
      summary.textContent = picked.length ? picked.join(", ") : placeholder;
      summary.classList.toggle("is-placeholder", !picked.length);
      count.textContent = picked.length;
      count.hidden = !picked.length;
    }

    function filter() {
      var q = search.value.trim().toLowerCase();
      var shown = 0;
      options.forEach(function (label) {
        var match = !q || label.textContent.toLowerCase().indexOf(q) !== -1;
        label.hidden = !match;
        if (match) shown += 1;
      });
      empty.hidden = shown > 0;
    }

    search.hidden = false;
    search.addEventListener("input", filter);
    // Enter in the search box must not submit the whole case form.
    search.addEventListener("keydown", function (e) {
      if (e.key === "Enter") e.preventDefault();
    });
    // Escape closes the list from anywhere inside it — the search box or a ticked checkbox.
    box.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && box.open) {
        e.preventDefault();
        box.open = false;
        box.querySelector("summary").focus();
      }
    });
    box.addEventListener("change", refreshSummary);
    box.addEventListener("toggle", function () {
      if (box.open) search.focus();
      else { search.value = ""; filter(); }
    });
    document.addEventListener("click", function (e) {
      if (box.open && !box.contains(e.target)) box.open = false;
    });
    refreshSummary();
  });
})();
