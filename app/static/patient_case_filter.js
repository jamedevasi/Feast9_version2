(function () {
  "use strict";
  var checkbox = document.getElementById("show-all-cases");
  var list = document.getElementById("case-list");
  if (!checkbox || !list) {
    return;
  }
  checkbox.addEventListener("change", function () {
    var closedRows = list.querySelectorAll(".case-row-closed");
    for (var i = 0; i < closedRows.length; i++) {
      if (checkbox.checked) {
        closedRows[i].removeAttribute("hidden");
      } else {
        closedRows[i].setAttribute("hidden", "");
      }
    }
  });
})();
