(function () {
  "use strict";
  var canvas = document.getElementById("signature-pad");
  if (!canvas) {
    return;
  }
  var form = document.getElementById("consent-form");
  var dataInput = document.getElementById("signature-data-input");
  var clearBtn = document.getElementById("signature-clear");
  var ctx = canvas.getContext("2d");
  var drawing = false;
  var hasDrawn = false;

  function fillWhite() {
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
  }

  function resetStroke() {
    ctx.lineWidth = 2;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.strokeStyle = "#1f2933";
  }

  fillWhite();
  resetStroke();

  function pointFromEvent(evt) {
    var rect = canvas.getBoundingClientRect();
    var scaleX = canvas.width / rect.width;
    var scaleY = canvas.height / rect.height;
    var clientX = evt.touches ? evt.touches[0].clientX : evt.clientX;
    var clientY = evt.touches ? evt.touches[0].clientY : evt.clientY;
    return { x: (clientX - rect.left) * scaleX, y: (clientY - rect.top) * scaleY };
  }

  function start(evt) {
    evt.preventDefault();
    drawing = true;
    hasDrawn = true;
    var p = pointFromEvent(evt);
    ctx.beginPath();
    ctx.moveTo(p.x, p.y);
  }

  function move(evt) {
    if (!drawing) {
      return;
    }
    evt.preventDefault();
    var p = pointFromEvent(evt);
    ctx.lineTo(p.x, p.y);
    ctx.stroke();
  }

  function stop() {
    drawing = false;
  }

  canvas.addEventListener("mousedown", start);
  canvas.addEventListener("mousemove", move);
  window.addEventListener("mouseup", stop);
  canvas.addEventListener("touchstart", start, { passive: false });
  canvas.addEventListener("touchmove", move, { passive: false });
  canvas.addEventListener("touchend", stop);

  if (clearBtn) {
    clearBtn.addEventListener("click", function () {
      fillWhite();
      resetStroke();
      hasDrawn = false;
    });
  }

  if (form && dataInput) {
    form.addEventListener("submit", function () {
      dataInput.value = hasDrawn ? canvas.toDataURL("image/png") : "";
    });
  }
})();
