(function () {
  "use strict";

  var yearSelect = document.getElementById("year-select");
  if (yearSelect) {
    yearSelect.addEventListener("change", function () {
      document.getElementById("year-form").submit();
    });
  }

  if (typeof Chart === "undefined") {
    return; // vendor script failed to load — the page still works without charts
  }

  var dataEl = document.getElementById("analytics-data");
  if (!dataEl) {
    return;
  }
  var data;
  try {
    data = JSON.parse(dataEl.textContent);
  } catch (e) {
    return;
  }

  var INK_MUTED = "#5b6672";
  var GRID = "#e5e9ee";
  var BLUE = "#2b6cb0";
  var GREEN = "#0ca30c";
  var GREY = "#5b6672";
  var RED = "#b91c1c";

  Chart.defaults.font.family = "system-ui, -apple-system, 'Segoe UI', sans-serif";
  Chart.defaults.color = INK_MUTED;
  Chart.defaults.borderColor = GRID;
  Chart.defaults.plugins.legend.labels.boxWidth = 12;
  Chart.defaults.plugins.legend.labels.usePointStyle = true;

  function hexToRgba(hex, alpha) {
    var r = parseInt(hex.slice(1, 3), 16);
    var g = parseInt(hex.slice(3, 5), 16);
    var b = parseInt(hex.slice(5, 7), 16);
    return "rgba(" + r + ", " + g + ", " + b + ", " + alpha + ")";
  }

  function lineChart(canvasId, label, values) {
    var el = document.getElementById(canvasId);
    if (!el) return;
    new Chart(el, {
      type: "line",
      data: {
        labels: data.months,
        datasets: [{
          label: label,
          data: values,
          borderColor: BLUE,
          backgroundColor: hexToRgba(BLUE, 0.1),
          borderWidth: 2,
          pointRadius: 3,
          pointBackgroundColor: BLUE,
          tension: 0.25,
          fill: true,
        }],
      },
      options: {
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          y: { beginAtZero: true, grid: { color: GRID }, ticks: { precision: 0 } },
          x: { grid: { display: false } },
        },
      },
    });
  }

  function stackedShareChart(canvasId, segments) {
    // One horizontal bar, split into colored segments — part-to-whole without a pie.
    var el = document.getElementById(canvasId);
    if (!el) return;
    new Chart(el, {
      type: "bar",
      data: {
        labels: [""],
        datasets: segments.map(function (seg) {
          return {
            label: seg.label,
            data: [seg.value],
            backgroundColor: seg.color,
            maxBarThickness: 40,
            borderRadius: 4,
            borderSkipped: false,
          };
        }),
      },
      options: {
        maintainAspectRatio: false,
        indexAxis: "y",
        plugins: { legend: { display: segments.length > 1 } },
        scales: {
          x: { stacked: true, beginAtZero: true, grid: { color: GRID }, ticks: { precision: 0 } },
          y: { stacked: true, grid: { display: false } },
        },
      },
    });
  }

  function rankedBarChart(canvasId, labels, values, color) {
    var el = document.getElementById(canvasId);
    if (!el) return;
    new Chart(el, {
      type: "bar",
      data: {
        labels: labels,
        datasets: [{
          data: values,
          backgroundColor: color,
          maxBarThickness: 24,
          borderRadius: 4,
          borderSkipped: false,
        }],
      },
      options: {
        maintainAspectRatio: false,
        indexAxis: "y",
        plugins: { legend: { display: false } },
        scales: {
          x: { beginAtZero: true, grid: { color: GRID }, ticks: { precision: 0 } },
          y: { grid: { display: false } },
        },
      },
    });
  }

  lineChart("chart-monthly-revenue", "Revenue (₹)", data.monthly_revenue);
  lineChart("chart-monthly-patients", "New Patients", data.monthly_new_patients);
  lineChart("chart-monthly-cases", "New Cases", data.monthly_new_cases);
  lineChart("chart-monthly-appointments", "Appointments", data.monthly_appointments);

  stackedShareChart("chart-case-status", [
    { label: "Active", value: data.case_status.Active, color: BLUE },
    { label: "Closed", value: data.case_status.Closed, color: GREY },
  ]);

  stackedShareChart("chart-appointment-status", [
    { label: "Scheduled", value: data.appointment_status.Scheduled, color: BLUE },
    { label: "Completed", value: data.appointment_status.Completed, color: GREEN },
    { label: "Cancelled", value: data.appointment_status.Cancelled, color: GREY },
    { label: "No-show", value: data.appointment_status["No-show"], color: RED },
  ]);

  if (data.doctor_revenue && data.doctor_revenue.length) {
    stackedShareChart(
      "chart-doctor-revenue",
      data.doctor_revenue.map(function (d) {
        return { label: d.doctor_name, value: d.collected, color: d.doctor_color || GREY };
      })
    );
  }

  if (data.procedure_popularity && data.procedure_popularity.length) {
    rankedBarChart(
      "chart-procedure-popularity",
      data.procedure_popularity.map(function (p) { return p.name; }),
      data.procedure_popularity.map(function (p) { return p.count; }),
      BLUE
    );
  }
})();
