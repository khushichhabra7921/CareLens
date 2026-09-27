// CareLens dashboard. Plain JavaScript, no framework.
// Safety rule: all text from the API is inserted with textContent (never innerHTML), so
// nothing in the data can be interpreted as HTML or script.

"use strict";

// How to draw each result table. The SQL decides WHAT is computed; this decides how it looks.
//   x: label column, y: value column, series: optional column that splits into 2 colours,
//   filter: column to pick one slice with a dropdown, horizontal: bars left-to-right,
//   line: change over time, tiles: a single-row result shown as numbers, not a chart,
//   exclude: rows to leave out of the chart (they stay in the table).
const CHARTS = {
  population_overview: { x: "category", y: "patients", filter: "dimension", horizontal: true },
  chronic_disease_prevalence: { x: "age_band", y: "prevalence_pct", series: "gender", filter: "condition" },
  readmissions_30day: { x: "category", y: "readmission_rate_pct", filter: "dimension", horizontal: true },
  ed_visits_per_1000: { x: "period_end", y: "visits_per_1000", line: true },
  ed_frequent_users: { tiles: [["frequent_user_pct", "of ED users had 4+ visits", "%"],
                               ["frequent_user_visit_pct", "of ED visits were by frequent users", "%"],
                               ["ed_users", "ED users in the last 12 months", ""]] },
  cost_by_class_payer: { x: "payer", y: "total_claim_cost", filter: "encounter_class", horizontal: true, money: true },
  top_conditions_by_cost: { x: "condition", y: "total_claim_cost", horizontal: true, money: true },
  care_gaps: { tiles: "per-row", label: "measure", value: "gap_pct", of: ["patients_with_gap", "eligible_patients"] },
  polypharmacy: { x: "age_band", y: "polypharmacy_pct", exclude: { age_band: "65+ (all)" } },
  flu_vaccination: { x: "age_band", y: "vaccination_pct", exclude: { age_band: "65+ (all)" } },
};

const state = { apiKey: "" };
const charts = [];   // live Chart.js instances, redrawn when the colour scheme changes

// ------------------------------------------------------------------ small helpers

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else node.setAttribute(key, value);
  }
  for (const child of children) if (child) node.append(child);
  return node;
}

const numberFormat = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });
const moneyFormat = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

function formatValue(value, column) {
  if (value === null || value === undefined) return "suppressed";
  if (typeof value === "boolean") return value ? "yes" : "";
  if (typeof value === "number") {
    if (/cost|coverage$|out_of_pocket/.test(column) && !column.endsWith("_pct")) return moneyFormat.format(value);
    return numberFormat.format(value) + (column.endsWith("_pct") ? "%" : "");
  }
  return String(value);
}

function niceName(column) {
  return column.replace(/_pct$/, " (%)").replace(/_per_1000$/, " per 1,000").replaceAll("_", " ");
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

async function getJson(url, options = {}) {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `${response.status} ${response.statusText}`);
  return body;
}

// ------------------------------------------------------------------ tables and tiles

function tableView(table) {
  const head = el("tr", {}, ...table.columns.map((c) => el("th", { scope: "col", text: niceName(c) })));
  const body = table.rows.map((row) => el("tr", {}, ...table.columns.map((c) => {
    const value = row[c];
    const cls = value === null ? "suppressed" : typeof value === "number" ? "num" : "";
    return el("td", { class: cls, text: formatValue(value, c) });
  })));
  return el("details", {},
    el("summary", { text: `Table view (${table.rows.length} rows)` }),
    el("div", { class: "table-wrap" }, el("table", {}, el("thead", {}, head), el("tbody", {}, ...body))));
}

function tilesView(table, config) {
  const tiles = [];
  if (config.tiles === "per-row") {
    for (const row of table.rows) {
      const [part, whole] = config.of;
      const detail = row[part] === null ? "count suppressed (1-10)" : `${formatValue(row[part], part)} of ${formatValue(row[whole], whole)}`;
      tiles.push(el("div", { class: "tile" },
        el("div", { class: "tile-value", text: formatValue(row[config.value], config.value) }),
        el("div", { class: "tile-label", text: `${row[config.label]} · ${detail}` })));
    }
  } else {
    const row = table.rows[0] || {};
    for (const [column, label] of config.tiles) {
      tiles.push(el("div", { class: "tile" },
        el("div", { class: "tile-value", text: formatValue(row[column], column) }),
        el("div", { class: "tile-label", text: label })));
    }
  }
  return el("div", { class: "tiles" }, ...tiles);
}

// ------------------------------------------------------------------ charts

function chartRows(table, config, slice) {
  return table.rows.filter((row) => {
    if (config.filter && row[config.filter] !== slice) return false;
    if (config.exclude) {
      for (const [col, value] of Object.entries(config.exclude)) if (row[col] === value) return false;
    }
    return true;
  });
}

function buildChart(canvas, table, config, slice) {
  const rows = chartRows(table, config, slice);
  const text2 = cssVar("--text-2"), grid = cssVar("--grid"), axis = cssVar("--axis");
  let labels, datasets;
  if (config.series) {
    labels = [...new Set(rows.map((r) => r[config.x]))];
    const groups = [...new Set(rows.map((r) => r[config.series]))].sort();
    datasets = groups.map((group, i) => ({
      label: `${niceName(config.series)}: ${group}`,
      data: labels.map((x) => rows.find((r) => r[config.x] === x && r[config.series] === group)?.[config.y] ?? null),
      backgroundColor: cssVar(i === 0 ? "--series-1" : "--series-2"),
    }));
  } else {
    const ordered = config.line ? [...rows].reverse() : rows;   // oldest period first on a time axis
    labels = ordered.map((r) => r[config.x]);
    datasets = [{
      label: niceName(config.y),
      data: ordered.map((r) => r[config.y]),
      backgroundColor: cssVar("--series-1"),
      borderColor: cssVar("--series-1"),
    }];
  }
  for (const ds of datasets) {
    Object.assign(ds, config.line
      ? { borderWidth: 2, pointRadius: 4, pointHoverRadius: 6, spanGaps: false }
      : { borderRadius: 4, borderSkipped: "start", maxBarThickness: 28, categoryPercentage: 0.8, barPercentage: 0.9 });
  }
  const valueAxis = {
    beginAtZero: true,
    grid: { color: grid }, border: { color: axis },
    ticks: { color: text2, callback: (v) => (config.money ? moneyFormat.format(v) : numberFormat.format(v)) },
  };
  const labelAxis = { grid: { display: false }, border: { color: axis }, ticks: { color: text2, autoSkip: false } };
  return new Chart(canvas, {
    type: config.line ? "line" : "bar",
    data: { labels, datasets },
    options: {
      indexAxis: config.horizontal ? "y" : "x",
      maintainAspectRatio: false,
      interaction: { mode: config.line ? "index" : "nearest", intersect: false },
      scales: config.horizontal ? { x: valueAxis, y: labelAxis } : { x: labelAxis, y: valueAxis },
      plugins: {
        legend: { display: datasets.length > 1, labels: { color: text2 } },
        tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${formatValue(ctx.raw, config.y)}` } },
      },
    },
  });
}

function chartView(table, config) {
  const box = el("div", { class: "chart-box" });
  const note = el("p", { class: "note" });
  const wrapper = el("div", { class: "table-block" });
  let current = null;
  const slices = config.filter ? [...new Set(table.rows.map((r) => r[config.filter]))] : [null];

  function draw(slice) {
    box.replaceChildren();
    const canvas = el("canvas", { role: "img", "aria-label": `${table.title}: chart of ${niceName(config.y)}. The table view below lists every value.` });
    box.append(canvas);
    if (current) {   // replace the previous chart for this table
      charts.splice(charts.indexOf(current), 1);
      current.chart.destroy();
    }
    current = { chart: buildChart(canvas, table, config, slice), redraw: () => draw(slice) };
    charts.push(current);
    const hidden = chartRows(table, config, slice).filter((r) => r[config.y] === null).length;
    note.textContent = hidden ? `${hidden} value(s) not drawn: suppressed because they involve 1-10 patients or events.` : "";
  }

  if (config.filter) {
    const select = el("select", { "aria-label": `Choose ${niceName(config.filter)}` },
      ...slices.map((s) => el("option", { value: s, text: s })));
    select.addEventListener("change", () => draw(select.value));
    wrapper.append(el("label", { class: "controls" }, el("span", { text: niceName(config.filter) }), select));
  }
  wrapper.append(box, note);
  draw(slices[0]);
  return wrapper;
}

// ------------------------------------------------------------------ cards

function renderTable(table) {
  const config = CHARTS[table.name] || {};
  const block = el("section", { class: "table-block" });
  if (table.title) block.append(el("h3", { text: table.title }));
  if (config.tiles) block.append(tilesView(table, config));
  else if (config.x && table.rows.length) block.append(chartView(table, config));
  block.append(tableView(table));
  return block;
}

function renderCard(summary) {
  const card = el("article", { class: "card", "aria-labelledby": `title-${summary.id}` });
  const button = el("button", { class: "button", type: "button", text: "Generate AI insight" });
  button.addEventListener("click", () => generateReport(summary.id, button));
  card.append(el("div", { class: "card-head" },
    el("div", {}, el("h2", { id: `title-${summary.id}`, text: summary.title }),
      el("p", { class: "question", text: summary.question })),
    button));
  const content = el("div", { class: "table-block" }, el("p", { class: "note", text: "Loading…" }));
  card.append(content);
  getJson(`/api/analyses/${encodeURIComponent(summary.id)}`)
    .then((analysis) => {
      content.replaceChildren(...analysis.tables.map((t, i) => {
        // The first table's title repeats the card title, so only later tables show theirs.
        return renderTable(i === 0 ? { ...t, title: "" } : t);
      }));
      content.append(el("details", {}, el("summary", { text: "Method, assumptions and limitations" }),
        el("p", { class: "note", text: `Method: ${analysis.method}` }),
        el("p", { class: "note", text: `Assumptions: ${analysis.assumptions}` }),
        el("p", { class: "note", text: `Limitations: ${analysis.limitations}` })));
    })
    .catch((err) => content.replaceChildren(el("p", { class: "error", text: `Could not load: ${err.message}` })));
  return card;
}

// ------------------------------------------------------------------ reports

async function generateReport(analysisId, button) {
  if (!state.apiKey) {
    document.getElementById("api-key").focus();
    showReportError("Enter the admin API key at the top of the page first.");
    return;
  }
  button.disabled = true;
  button.textContent = "Generating…";
  try {
    const record = await getJson("/api/reports", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-API-Key": state.apiKey },
      body: JSON.stringify({ analysis_id: analysisId }),
    });
    showReport(record);
  } catch (err) {
    showReportError(`Could not generate the report: ${err.message}`);
  } finally {
    button.disabled = false;
    button.textContent = "Generate AI insight";
  }
}

function showReport(record) {
  const r = record.report;
  const redacted = Object.values(record.redactions || {}).reduce((a, b) => a + b, 0);
  const grounding = record.grounding.status;
  const groundingLabel = { passed: "Grounding: all numbers match the data", partial: "Grounding: some findings dropped",
    failed: "Grounding: failed", not_checked: "Grounding: not checked (template report)" }[grounding];
  const body = document.getElementById("report-body");
  body.replaceChildren(
    el("h2", { id: "report-title", text: r.title }),
    el("div", { class: "status-row" },
      el("span", { class: "pill", text: record.source === "llm" ? `AI model: ${record.model}` : "Template report (no AI model)" }),
      el("span", { class: `pill ${grounding === "passed" ? "good" : grounding === "failed" ? "bad" : ""}`, text: groundingLabel }),
      el("span", { class: "pill", text: `${redacted} item(s) redacted` }),
      el("span", { class: "pill", text: `Data up to ${record.reference_date}` })),
    el("p", { text: r.summary }),
    el("h3", { text: "Findings" }),
    el("ul", {}, ...r.findings.map((f) => el("li", {}, el("span", { text: f.statement }),
      f.values_cited.length ? el("span", { class: "cited", text: ` (cites ${f.values_cited.join(", ")})` }) : null))),
    el("h3", { text: "Recommended actions" }),
    el("ul", {}, ...r.recommended_actions.map((a) => el("li", { text: a }))),
    el("h3", { text: "Limitations" }),
    el("ul", {}, ...r.limitations.map((l) => el("li", { text: l }))),
    el("p", { class: "note", text: `${record.disclaimer} Report ${record.report_id}, created ${new Date(record.created_at).toLocaleString()}.` }),
  );
  document.getElementById("report-dialog").showModal();
}

function showReportError(message) {
  document.getElementById("report-body").replaceChildren(el("p", { class: "error", text: message }));
  document.getElementById("report-dialog").showModal();
}

// ------------------------------------------------------------------ start

async function start() {
  const keyInput = document.getElementById("api-key");
  // Kept in memory only: not in localStorage, so it's gone when the tab closes.
  keyInput.addEventListener("input", () => { state.apiKey = keyInput.value.trim(); });
  document.getElementById("key-form").addEventListener("submit", (e) => e.preventDefault());

  const main = document.getElementById("analyses");
  try {
    const list = await getJson("/api/analyses");
    document.getElementById("reference-date").textContent =
      `Data up to ${list.reference_date} (latest encounter). "Last 12 months" ends on this date.`;
    main.replaceChildren(...list.analyses.map(renderCard));
  } catch (err) {
    main.replaceChildren(el("p", { class: "error", text: `Could not load analyses: ${err.message}` }));
  }
  // Redraw charts in the new colours when the OS switches light/dark.
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change",
    () => [...charts].forEach((c) => c.redraw()));
}

document.addEventListener("DOMContentLoaded", start);
