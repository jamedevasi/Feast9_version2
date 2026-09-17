(function () {
  "use strict";
  var btn = document.getElementById("print-trigger");
  if (btn) {
    btn.addEventListener("click", function () {
      window.print();
    });
  }
})();
