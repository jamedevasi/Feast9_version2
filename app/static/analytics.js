(function () {
  "use strict";

  var yearSelect = document.getElementById("year-select");
  if (yearSelect) {
    yearSelect.addEventListener("change", function () {
      document.getElementById("year-form").submit();
    });
  }
  var compareToggle = document.getElementById("compare-toggle");
  if (compareToggle) {
    compareToggle.addEventListener("change", function () {
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
  // Categorical slots for the multi-series charts, in fixed order (never cycled) — validated
  // with the dataviz skill's validate_palette.js on the white card surface: CVD and
  // normal-vision separation pass; slots 3-5 are under 3:1 contrast, so every chart using
  // them carries a legend (and Revenue by Procedure a table view) rather than colour alone.
  var CATEGORICAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"];
  var OTHER = "#9aa4af";

  function rupees(v) {
    return "₹" + Number(v).toLocaleString("en-IN", { maximumFractionDigits: 0 });
  }
  var currencyTooltip = {
    callbacks: {
      label: function (ctx) {
        return (ctx.dataset.label ? ctx.dataset.label + ": " : "") + rupees(ctx.parsed.y);
      },
    },
  };

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

  // Year-on-year overlay: last year as a dashed grey line, drawn behind this year's marks.
  var PREV = data.previous || null;
  var PREV_COLOR = "#8a94a0";
  function previousDataset(values) {
    return {
      type: "line",
      label: String(PREV.year),
      data: values,
      borderColor: PREV_COLOR,
      backgroundColor: PREV_COLOR,
      borderDash: [6, 4],
      borderWidth: 2,
      pointRadius: 2,
      tension: 0.25,
      fill: false,
      order: 5,
    };
  }

  function lineChart(canvasId, label, values, labels, previousValues) {
    var el = document.getElementById(canvasId);
    if (!el) return;
    new Chart(el, {
      type: "line",
      data: {
        labels: labels || data.months,
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
        }].concat(previousValues ? [previousDataset(previousValues)] : []),
      },
      options: {
        maintainAspectRatio: false,
        interaction: previousValues ? { mode: "index", intersect: false } : undefined,
        plugins: { legend: { display: !!previousValues } },
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

  function columnChart(canvasId, label, labels, values, isCurrency, previousValues) {
    // Single-series vertical bars — one hue, since the bars differ only in magnitude.
    var el = document.getElementById(canvasId);
    if (!el) return;
    new Chart(el, {
      type: "bar",
      data: {
        labels: labels,
        datasets: [{
          label: label,
          data: values,
          backgroundColor: BLUE,
          maxBarThickness: 36,
          borderRadius: 4,
          borderSkipped: "start",
        }].concat(previousValues ? [{
          label: String(PREV.year),
          data: previousValues,
          backgroundColor: PREV_COLOR,
          maxBarThickness: 36,
          borderRadius: 4,
          borderSkipped: "start",
        }] : []),
      },
      options: {
        maintainAspectRatio: false,
        interaction: previousValues ? { mode: "index", intersect: false } : undefined,
        plugins: { legend: { display: !!previousValues }, tooltip: isCurrency ? currencyTooltip : {} },
        scales: {
          y: {
            beginAtZero: true, grid: { color: GRID },
            ticks: isCurrency ? { callback: function (v) { return rupees(v); } } : { precision: 0 },
          },
          x: { grid: { display: false } },
        },
      },
    });
  }

  function totalVsNewChart(canvasId, totals, news, totalLabel, newLabel, previousNews) {
    // Same unit on one axis: a month-end level as a line, that month's additions as bars.
    var el = document.getElementById(canvasId);
    if (!el) return;
    new Chart(el, {
      data: {
        labels: data.months,
        datasets: [
          {
            type: "line", label: totalLabel, data: totals, order: 0,
            borderColor: CATEGORICAL[0], backgroundColor: CATEGORICAL[0],
            borderWidth: 2, pointRadius: 3, tension: 0.25,
          },
          {
            type: "bar", label: newLabel, data: news, order: 1,
            backgroundColor: CATEGORICAL[1], maxBarThickness: 24, borderRadius: 4, borderSkipped: "start",
          },
        ].concat(previousNews ? [Object.assign(previousDataset(previousNews), {
          label: newLabel + " " + PREV.year,
        })] : []),
      },
      options: {
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { display: true } },
        scales: {
          y: { beginAtZero: true, grid: { color: GRID }, ticks: { precision: 0 } },
          x: { grid: { display: false } },
        },
      },
    });
  }

  function stackedColumnChart(canvasId, series) {
    // Composition over time — fixed categorical order; the "Other" fold is always grey.
    var el = document.getElementById(canvasId);
    if (!el) return;
    new Chart(el, {
      type: "bar",
      data: {
        labels: data.months,
        datasets: series.map(function (s, i) {
          var isOther = !!s.is_other;
          return {
            label: s.name,
            data: s.values,
            backgroundColor: isOther ? OTHER : CATEGORICAL[i % CATEGORICAL.length],
            borderColor: "#ffffff",
            borderWidth: 1,
            maxBarThickness: 44,
          };
        }),
      },
      options: {
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { display: true }, tooltip: currencyTooltip },
        scales: {
          x: { stacked: true, grid: { display: false } },
          y: { stacked: true, beginAtZero: true, grid: { color: GRID }, ticks: { callback: function (v) { return rupees(v); } } },
        },
      },
    });
  }

  lineChart("chart-monthly-revenue", String(data.year || "Revenue"), data.monthly_revenue, null,
            PREV && PREV.monthly_revenue);
  totalVsNewChart("chart-patients-total-new", data.monthly_total_patients, data.monthly_new_patients,
                  "Total patients", "New patients", PREV && PREV.monthly_new_patients);
  totalVsNewChart("chart-cases-active-new", data.monthly_active_cases, data.monthly_new_cases,
                  "Active cases (month-end)", "New cases", PREV && PREV.monthly_new_cases);
  if (data.yearly_active_cases && data.yearly_active_cases.length) {
    lineChart(
      "chart-active-cases-yearly", "Active cases",
      data.yearly_active_cases.map(function (y) { return y.active; }),
      data.yearly_active_cases.map(function (y) { return String(y.year); })
    );
  }
  columnChart("chart-weekday-appointments", String(data.year || "Appointments"), data.weekday.labels,
              data.weekday.appointments, false, PREV && PREV.weekday.appointments);
  columnChart("chart-weekday-revenue", String(data.year || "Revenue"), data.weekday.labels,
              data.weekday.revenue, true, PREV && PREV.weekday.revenue);
  lineChart("chart-monthly-appointments", String(data.year || "Appointments"), data.monthly_appointments, null,
            PREV && PREV.monthly_appointments);

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

  var demo = data.demographics;
  var demoSegments = [
    { label: "Men (" + demo.Men + ")", value: demo.Men, color: CATEGORICAL[0] },
    { label: "Women (" + demo.Women + ")", value: demo.Women, color: CATEGORICAL[1] },
    { label: "Children <18 (" + demo.Children + ")", value: demo.Children, color: CATEGORICAL[2] },
  ];
  if (demo.Unknown) {
    demoSegments.push({ label: "Not recorded (" + demo.Unknown + ")", value: demo.Unknown, color: OTHER });
  }
  stackedShareChart("chart-demographics", demoSegments);

  if (data.revenue_by_procedure && data.revenue_by_procedure.length) {
    stackedColumnChart("chart-revenue-by-procedure", data.revenue_by_procedure);
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
