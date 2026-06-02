const state = {
  currentView: "overview",
  status: null,
  settings: null,
  snapshots: [],
  alerts: [],
  unreadAlertCount: 0,
  alertSettings: null,
  latestBreakdown: null,
  breakdownMetric: "download_count",
  breakdownSort: "metric",
  currentComparison: null,
  currentSort: "newest",
  currentFilter: "all",
  showUnchanged: false,
  showAllVersions: false,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const fmt = (value) => value === null || value === undefined ? "N/A" : Number(value).toLocaleString();
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
const pad2 = (value) => String(value).padStart(2, "0");
const parsedDate = (value) => {
  const date = value ? new Date(value) : null;
  return date && !Number.isNaN(date.getTime()) ? date : null;
};
const dateOnlyFmt = (value) => {
  const date = parsedDate(value);
  return date ? `${pad2(date.getDate())}/${pad2(date.getMonth() + 1)}/${date.getFullYear()}` : "Unknown";
};
const dateFmt = (value) => {
  const date = parsedDate(value);
  return date ? `${dateOnlyFmt(value)} ${pad2(date.getHours())}:${pad2(date.getMinutes())}` : "Never";
};
const deltaClass = (value) => value > 0 ? "ct-positive" : value < 0 ? "ct-negative" : "";
const signed = (value) => `${value > 0 ? "+" : ""}${fmt(value)}`;
const dateValue = (value) => {
  const parsed = value ? Date.parse(value) : NaN;
  return Number.isNaN(parsed) ? null : parsed;
};
const sourceLabel = (value) => ({ manual: "Manual", cli: "CLI", scheduled: "Scheduled" }[value] || value || "Unknown");
const noteTypeLabel = (value) => ({
  normal_check: "Normal check / no special change",
  uploaded_new_model: "Uploaded new model",
  published_new_version: "Published new version",
  changed_preview_images: "Changed preview images",
  updated_model_description: "Updated model description",
  changed_tags_keywords: "Changed tags / keywords",
  shared_promoted_model: "Shared/promoted model",
  other_manual_note: "Other manual note",
}[value] || (value ? value : "Unspecified"));
const qualityLabel = (value) => value ? value[0].toUpperCase() + value.slice(1) : "Unavailable";
const qualityBadge = (value) => `<span class="ct-quality ct-quality-${esc(value || "unavailable")}">${esc(qualityLabel(value))}</span>`;
const rangeUnavailableMessage = (days) => `No snapshot is available at least ${days} day${days === 1 ? "" : "s"} before the latest snapshot. Take snapshots over time and this shortcut will enable automatically.`;

function compareDates(a, b, direction) {
  const aTime = dateValue(a.published_at);
  const bTime = dateValue(b.published_at);
  if (aTime === null && bTime === null) return a.model_name.localeCompare(b.model_name);
  if (aTime === null) return 1;
  if (bTime === null) return -1;
  return direction === "oldest" ? aTime - bTime : bTime - aTime;
}

function setView(view, updateHash = true) {
  const views = ["overview", "models", "snapshots", "alerts", "settings"];
  const nextView = views.includes(view) ? view : "overview";
  state.currentView = nextView;
  $$("[data-view-panel]").forEach((panel) => panel.classList.toggle("d-none", panel.dataset.viewPanel !== nextView));
  $$(".ct-side-tab").forEach((tab) => {
    const active = tab.dataset.view === nextView;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  if (updateHash) history.replaceState(null, "", `#${nextView}`);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok || data.ok === false) throw new Error(data.error || "Request failed.");
  return data;
}

function toast(message, type = "info") {
  const item = document.createElement("div");
  item.className = `ct-alert ct-alert-${type}`;
  item.textContent = message;
  $("#alertArea").append(item);
  setTimeout(() => item.remove(), 5200);
}

function busy(button, enabled, label = "Loading...") {
  if (!button) return;
  if (enabled) {
    button.dataset.original = button.innerHTML;
    button.disabled = true;
    button.innerHTML = `<span class="spinner-border spinner-border-sm"></span> ${esc(label)}`;
  } else {
    button.disabled = false;
    if (button.dataset.original) button.innerHTML = button.dataset.original;
  }
}

function renderStatus() {
  const ready = state.status.api_key_configured && state.status.username;
  const pillClass = ready ? "ct-pill-success" : "ct-pill-warning";
  const pillText = ready ? "API Ready" : "Setup Needed";
  $("#apiStatusPill").className = `ct-pill ${pillClass}`;
  $("#apiStatusPill").textContent = pillText;
  $("#setupPill").className = `ct-pill ${pillClass}`;
  $("#setupPill").textContent = pillText;
  $("#navLastSnapshot").textContent = state.status.last_snapshot ? `Last snapshot ${dateFmt(state.status.last_snapshot)}` : "No snapshots yet";
  $("#setupHelp").textContent = ready ? "Configuration is loaded from the local .env file. Password values remain server-side." : "Add a CivitAI API key and username below, then save the settings before taking a snapshot.";
  const latestQuality = state.status.latest_quality_status;
  const warningText = state.status.latest_quality_warning_count ? ` - ${state.status.latest_quality_warning_count} warning${state.status.latest_quality_warning_count === 1 ? "" : "s"}` : "";
  $("#latestQualityLine").textContent = state.status.last_snapshot ? `Latest snapshot quality: ${qualityLabel(latestQuality)}${warningText}` : "Latest snapshot quality: no snapshot yet";
  renderSetupChecklist();
}

function renderSetupChecklist() {
  const items = [
    ["API key", state.status.api_key_configured, "Add your CivitAI API key below."],
    ["Username", Boolean(state.status.username), "Add the creator username below."],
    ["Database", state.status.database_ready, "Check the SQLite database path below."],
    ["Model type filter", state.status.model_type_filter_configured, "Choose at least one model type below."],
    ["Latest snapshot", Boolean(state.status.last_snapshot), "Take your first snapshot from Overview."],
    ["CLI / scheduler", state.status.cli_scheduler_available, "Run python cli.py snapshot from an external scheduler."],
  ];
  const requiredReady = items.slice(0, 4).every(([, ready]) => ready);
  $("#checklistPill").className = `ct-pill ${requiredReady ? "ct-pill-success" : "ct-pill-warning"}`;
  $("#checklistPill").textContent = requiredReady ? "Ready" : "Needs setup";
  $("#setupChecklist").innerHTML = items.map(([label, itemReady]) => `
    <div class="ct-checklist-row">
      <span><i class="bi ${itemReady ? "bi-check-circle-fill ct-positive" : "bi-exclamation-circle-fill ct-warning"}"></i> ${esc(label)}</span>
      <strong class="${itemReady ? "ct-positive" : "ct-warning"}">${itemReady ? "Ready" : "Not ready"}</strong>
    </div>`).join("");
  const next = items.find(([, itemReady]) => !itemReady);
  $("#setupNextStep").textContent = next ? `Next step: ${next[2]}` : "Next step: Take snapshots over time and compare which models gained stats.";
}

function renderSettings() {
  const fields = state.settings?.fields || {};
  $$("#settingsForm [name]").forEach((input) => {
    const field = fields[input.name];
    if (!field) return;
    input.value = input.type === "password" ? "" : field.value;
    if (input.type === "password") {
      input.placeholder = field.configured ? "Leave blank to keep saved value" : "No saved value";
    }
  });
  $$("#settingsForm [data-clear-secret]").forEach((checkbox) => {
    checkbox.checked = false;
    $(`#settingsForm [name="${checkbox.dataset.clearSecret}"]`).disabled = false;
  });
}

const metricSpec = [
  ["Downloads", "total_download_count", "Total model downloads"],
  ["Reactions", "total_reaction_count", "Combined reaction signals"],
  ["Collections", "total_collected_count", "Added to CivitAI collections"],
  ["Comments", "total_comment_count", "Conversation activity"],
  ["Models", "model_count", "Tracked models"],
];

function renderMetrics() {
  const latest = state.currentComparison?.to_totals || state.status?.last_totals;
  const summary = state.currentComparison?.summary;
  $("#metricsGrid").innerHTML = latest ? metricSpec.map(([label, key, help]) => {
    const deltaKey = key === "model_count" ? "model_count_delta" : `${key}_delta`;
    const delta = summary ? summary[deltaKey] : null;
    const change = summary && delta !== null && delta !== undefined ? `<span class="ct-metric-delta ${deltaClass(delta)}">${signed(delta)} in selected range</span>` : `<span class="ct-metric-delta">${esc(help)}</span>`;
    return `<article class="ct-card ct-metric"><span class="ct-metric-label">${esc(label)}</span><strong class="ct-metric-value">${fmt(latest[key])}</strong>${change}</article>`;
  }).join("") : "";
  $("#emptyState").classList.toggle("d-none", Boolean(latest));
}

function renderSnapshots() {
  const options = state.snapshots.map((snapshot) => `<option value="${snapshot.id}">${esc(dateFmt(snapshot.checked_at))} | ${fmt(snapshot.model_count)} models</option>`).join("");
  $("#fromSnapshot").innerHTML = options || `<option>No snapshots saved</option>`;
  $("#toSnapshot").innerHTML = options || `<option>No snapshots saved</option>`;
  if (state.snapshots.length >= 2) {
    $("#fromSnapshot").value = state.snapshots[1].id;
    $("#toSnapshot").value = state.snapshots[0].id;
  }
  const enough = state.snapshots.length >= 2;
  $$(".js-compare-latest").forEach((button) => button.disabled = !enough);
  $$(".js-compare-range").forEach((button) => {
    const range = rangeComparison(Number(button.dataset.rangeDays));
    const tooltipText = range
      ? `Compare ${dateFmt(range.from.checked_at)} to ${dateFmt(range.to.checked_at)}`
      : rangeUnavailableMessage(Number(button.dataset.rangeDays));
    button.classList.toggle("ct-btn-unavailable", !range);
    button.setAttribute("aria-disabled", String(!range));
    button.setAttribute("data-bs-title", tooltipText);
    bootstrap.Tooltip.getInstance(button)?.dispose();
    bootstrap.Tooltip.getOrCreateInstance(button, { title: tooltipText, trigger: "hover focus" });
  });
  $("#compareSelected").disabled = !enough;
  $("#compareDate").disabled = !enough;
  $("#compareHelp").textContent = enough ? `${state.snapshots.length} snapshots available. Latest comparison is ready.` : state.snapshots.length === 1 ? "One snapshot saved. Take another later to compare growth." : "Need at least 2 snapshots to compare growth.";
  $("#snapshotListHelp").textContent = state.snapshots.length ? `${state.snapshots.length} stored snapshot${state.snapshots.length === 1 ? "" : "s"}, newest first.` : "No snapshots stored yet.";
  $("#snapshotRows").innerHTML = state.snapshots.length ? state.snapshots.map((snapshot) => `
    <tr>
      <td><span class="ct-status">#${snapshot.id}</span></td>
      <td>${esc(dateFmt(snapshot.checked_at))}</td>
      <td>${esc(noteTypeLabel(snapshot.note_type))}</td>
      <td>${esc(snapshot.note || "-")}</td>
      <td>${esc(sourceLabel(snapshot.source))}</td>
      <td>${qualityBadge(snapshot.quality_status)}</td>
      <td>${fmt(snapshot.model_count)}</td>
      <td>${fmt(snapshot.total_download_count)}</td>
      <td>${fmt(snapshot.total_reaction_count)}</td>
      <td>${fmt(snapshot.total_collected_count)}</td>
      <td>${fmt(snapshot.total_comment_count)}</td>
      <td><span class="ct-row-actions"><button class="btn ct-btn-quiet js-quality-report" type="button" data-snapshot-id="${snapshot.id}"><i class="bi bi-clipboard-data"></i> Details</button><button class="btn ct-btn-danger js-delete-snapshot" type="button" data-snapshot-id="${snapshot.id}"><i class="bi bi-trash3"></i> Delete</button></span></td>
    </tr>`).join("") : `<tr><td colspan="12" class="ct-table-empty">Take your first snapshot to start tracking growth.</td></tr>`;
  $$(".js-delete-snapshot").forEach((button) => button.addEventListener("click", deleteSnapshot));
  $$(".js-quality-report").forEach((button) => button.addEventListener("click", showSnapshotQuality));
}

function rangeComparison(days) {
  const to = state.snapshots[0];
  const toTime = dateValue(to?.checked_at);
  if (!to || toTime === null) return null;
  const targetTime = toTime - days * 24 * 60 * 60 * 1000;
  const from = state.snapshots.find((snapshot) => {
    const snapshotTime = dateValue(snapshot.checked_at);
    return snapshot.id !== to.id && snapshotTime !== null && snapshotTime <= targetTime;
  });
  return from ? { from, to } : null;
}

function renderBreakdown() {
  const breakdown = state.latestBreakdown;
  const metric = state.breakdownMetric;
  const metricSpecs = {
    download_count: ["Downloads", "total_download_count"],
    reaction_count: ["Reactions", "total_reaction_count"],
    collected_count: ["Collections", "total_collected_count"],
  };
  const [label, totalKey] = metricSpecs[metric];
  const total = Number(breakdown?.totals?.[totalKey] || 0);
  const sortDescription = state.breakdownSort === "metric"
    ? `Ranked by ${label.toLowerCase()}, with share of that total.`
    : `Sorted by ${state.breakdownSort} publication date, with share of total ${label.toLowerCase()}.`;
  const firstBadge = state.breakdownSort === "metric" ? "Top" : state.breakdownSort === "newest" ? "Newest" : "Oldest";
  const query = $("#breakdownSearch").value.trim().toLowerCase();
  const rows = [...(breakdown?.models || [])]
    .filter((row) => Number(row[metric] || 0) > 0)
    .filter((row) => !query || row.model_name.toLowerCase().includes(query))
    .sort((a, b) => state.breakdownSort === "metric"
      ? Number(b[metric] || 0) - Number(a[metric] || 0) || a.model_name.localeCompare(b.model_name)
      : compareDates(a, b, state.breakdownSort));
  $("#breakdownMetricHeading").textContent = label;
  $("#breakdownHelp").textContent = breakdown?.snapshot
    ? `${fmt(total)} total ${label.toLowerCase()} in the latest snapshot. ${sortDescription}`
    : "Take a snapshot to see which models make up your totals.";
  $("#breakdownRows").innerHTML = rows.length ? rows.map((row, index) => {
    const value = Number(row[metric] || 0);
    const share = total > 0 ? value / total * 100 : 0;
    return `
      <tr data-model-id="${row.model_id}">
        <td>${index + 1}</td>
        <td><strong>${esc(row.model_name)}</strong>${index === 0 ? `<span class="ct-top-badge">${firstBadge}</span>` : ""}</td>
        <td>${esc(dateOnlyFmt(row.published_at))}</td>
        <td><span class="ct-delta">${fmt(row.download_count)}</span></td>
        <td><span class="ct-delta">${fmt(row.reaction_count)}</span></td>
        <td><span class="ct-delta">${fmt(row.collected_count)}</span></td>
        <td><span class="ct-share"><span class="ct-share-bar"><span class="ct-share-fill" style="width:${Math.min(100, share).toFixed(2)}%"></span></span><span class="ct-share-value">${share.toFixed(1)}%</span></span></td>
        <td>${esc(row.latest_version_name || "-")}</td>
        <td><a href="${esc(row.page_url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()" aria-label="Open ${esc(row.model_name)} on CivitAI"><i class="bi bi-box-arrow-up-right"></i></a></td>
      </tr>`;
  }).join("") : `<tr><td colspan="9" class="ct-table-empty">${breakdown?.snapshot ? `No models with ${label.toLowerCase()} in the latest snapshot.` : "Take a snapshot to see your current model totals."}</td></tr>`;
  $$("#breakdownRows tr[data-model-id]").forEach((row) => row.addEventListener("click", () => showHistory(row.dataset.modelId)));
}

function rawMetricDelta(row, metric) { return row[`${metric}_delta`]; }
function metricDelta(row, metric) { return Number(rawMetricDelta(row, metric) || 0); }
function changed(row) { return ["download_count", "reaction_count", "collected_count", "comment_count"].some((key) => metricDelta(row, key) !== 0) || row.status !== "normal"; }
function deltaCell(value) { return `<span class="ct-delta ${deltaClass(value)}">${signed(value)}</span>`; }

function filteredModels() {
  const query = $("#modelSearch").value.trim().toLowerCase();
  return [...(state.currentComparison?.models || [])]
    .filter((row) => state.showUnchanged || changed(row))
    .filter((row) => !query || row.model_name.toLowerCase().includes(query))
    .filter((row) => state.currentFilter === "all" || metricDelta(row, state.currentFilter) !== 0)
    .sort((a, b) => ["newest", "oldest"].includes(state.currentSort)
      ? compareDates(a, b, state.currentSort)
      : metricDelta(b, state.currentSort) - metricDelta(a, state.currentSort) || metricDelta(b, "download_count") - metricDelta(a, "download_count"));
}

function renderModels() {
  const rows = filteredModels();
  const top = rows.length && !["newest", "oldest"].includes(state.currentSort) ? metricDelta(rows[0], state.currentSort) : null;
  $("#modelRows").innerHTML = rows.length ? rows.map((row, index) => `
    <tr data-model-id="${row.model_id}">
      <td>${index + 1}</td>
      <td><strong>${esc(row.model_name)}</strong>${top > 0 && metricDelta(row, state.currentSort) === top ? '<span class="ct-top-badge">Top</span>' : ""}</td>
      <td>${esc(dateOnlyFmt(row.published_at))}</td>
      <td>${esc(row.model_type || "-")}</td>
      <td>${esc(row.base_model || "-")}</td>
      <td>${deltaCell(metricDelta(row, "download_count"))}</td>
      <td>${deltaCell(metricDelta(row, "reaction_count"))}</td>
      <td>${deltaCell(metricDelta(row, "collected_count"))}</td>
      <td>${deltaCell(metricDelta(row, "comment_count"))}</td>
      <td>${esc(row.latest_version_name || "-")}</td>
      <td><a href="${esc(row.page_url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()" aria-label="Open ${esc(row.model_name)} on CivitAI"><i class="bi bi-box-arrow-up-right"></i></a></td>
    </tr>`).join("") : `<tr><td colspan="11" class="ct-table-empty">${state.currentComparison ? "No model changed in this range." : "Take two snapshots to reveal model growth."}</td></tr>`;
  $$("#modelRows tr[data-model-id]").forEach((row) => row.addEventListener("click", () => showHistory(row.dataset.modelId)));
  const missing = state.currentComparison?.missing_models || [];
  $("#missingModels").classList.toggle("d-none", !missing.length);
  $("#missingModels").innerHTML = missing.length ? `<strong>${missing.length} missing model${missing.length === 1 ? "" : "s"}:</strong> ${missing.map((row) => esc(row.model_name)).join(", ")}. These appeared in the earlier snapshot but not the current API response, so they are kept separate to avoid false negative growth.` : "";
}

function renderVersions() {
  const allRows = state.currentComparison?.versions || [];
  const rows = state.showAllVersions ? allRows : allRows.slice(0, 20);
  $("#versionRows").innerHTML = rows.length ? rows.map((row, index) => `
    <tr>
      <td>${index + 1}</td><td>${esc(row.model_name)}</td><td>${esc(row.version_name || "-")}</td>
      <td>${esc(row.base_model || "-")}</td><td>${deltaCell(metricDelta(row, "download_count"))}</td>
      <td>${row.version_contribution_percent === null ? "N/A" : `<span class="ct-contribution"><span class="ct-share-bar"><span class="ct-share-fill" style="width:${Math.min(100, Math.max(0, row.version_contribution_percent)).toFixed(1)}%"></span></span><strong>${fmt(row.version_contribution_percent)}%</strong></span>`}</td>
      <td><span class="ct-status">${esc(row.status.replaceAll("_", " "))}</span></td>
    </tr>`).join("") : `<tr><td colspan="7" class="ct-table-empty">No version data in this comparison.</td></tr>`;
  $("#showAllVersions").classList.toggle("d-none", allRows.length <= 20 || state.showAllVersions);
}

function renderInsight() {
  const comparison = state.currentComparison;
  $("#insightStrip").classList.toggle("d-none", !comparison);
  if (!comparison) return;
  const delta = comparison.summary.total_download_count_delta;
  const movers = comparison.models.filter(changed);
  const top = [...comparison.models].sort((a, b) => metricDelta(b, "download_count") - metricDelta(a, "download_count"))[0];
  const context = [comparison.from_context, comparison.to_context]
    .filter((item) => item && (item.note || (item.note_type && item.note_type !== "normal_check")))
    .map((item) => `${noteTypeLabel(item.note_type)}${item.note ? `: ${item.note}` : ""}`);
  const growth = delta === 0 && !movers.length ? "No growth detected in this range." : `Downloads changed by ${signed(delta)} across ${movers.length} model${movers.length === 1 ? "" : "s"}.${top && metricDelta(top, "download_count") > 0 ? ` Top mover: ${top.model_name} gained ${signed(metricDelta(top, "download_count"))} downloads.` : ""}`;
  $("#insightStrip").textContent = `${growth}${context.length ? ` Snapshot context: ${context.join(" | ")}` : ""}`;
}

function bestMover(models, metric, predicate = () => true) {
  return [...models]
    .filter(predicate)
    .sort((a, b) => metricDelta(b, metric) - metricDelta(a, metric))[0] || null;
}

function renderTopMovers() {
  const comparison = state.currentComparison;
  $("#topMoversSection").classList.toggle("d-none", !comparison);
  if (!comparison) {
    $("#topMoversGrid").innerHTML = "";
    return;
  }
  const models = comparison.models;
  const specs = [
    ["Most downloads gained", "download_count", bestMover(models, "download_count")],
    ["Most collections gained", "collected_count", bestMover(models, "collected_count")],
    ["Most reactions gained", "reaction_count", bestMover(models, "reaction_count")],
    ["Top newly detected model", "download_count", bestMover(models, "download_count", (row) => row.status === "new_in_current")],
  ];
  $("#topMoversGrid").innerHTML = specs.map(([label, metric, row]) => {
    const value = row ? metricDelta(row, metric) : 0;
    const detail = row && value > 0 ? row.model_name : "No positive growth in this range";
    return `<article class="ct-card ct-mover-card">
      <span class="ct-metric-label">${esc(label)}</span>
      <strong class="ct-mover-value ${deltaClass(value)}">${signed(value)}</strong>
      <span class="ct-mover-name">${esc(detail)}</span>
    </article>`;
  }).join("");
}

function renderComparison(comparison) {
  state.currentComparison = comparison;
  renderMetrics();
  renderInsight();
  renderTopMovers();
  renderModels();
  renderVersions();
  $("#exportCsv").classList.remove("disabled");
  $("#exportCsv").setAttribute("aria-disabled", "false");
  $("#exportCsv").href = `/api/export-csv?from_id=${comparison.from_id}&to_id=${comparison.to_id}`;
}

function clearComparison() {
  state.currentComparison = null;
  $("#exportCsv").classList.add("disabled");
  $("#exportCsv").setAttribute("aria-disabled", "true");
  $("#exportCsv").href = "#";
  renderInsight();
  renderTopMovers();
  renderModels();
  renderVersions();
}

async function refresh() {
  const [status, settings, snapshots, breakdown, logs, alerts, alertSettings] = await Promise.all([api("/api/status"), api("/api/settings"), api("/api/snapshots"), api("/api/latest-breakdown"), api("/api/logs"), api("/api/alerts"), api("/api/alert-settings")]);
  state.status = status;
  state.settings = settings;
  state.snapshots = snapshots.snapshots;
  state.latestBreakdown = breakdown;
  state.alerts = alerts.alerts;
  state.unreadAlertCount = alerts.unread_count;
  state.alertSettings = alertSettings;
  renderStatus();
  renderSettings();
  renderSnapshots();
  renderMetrics();
  renderBreakdown();
  renderLogs(logs.logs);
  renderAlerts();
  renderAlertSettings();
}

function renderLogs(logs) {
  $("#logRows").innerHTML = logs.length ? logs.map((row) => `<div class="ct-log-${esc(row.level)}">[${esc(dateFmt(row.created_at))}] ${esc(row.level.toUpperCase())}: ${esc(row.message)}</div>`).join("") : `<div class="ct-log-info">Logs will appear here.</div>`;
}

function renderAlerts() {
  const alerts = state.alerts;
  const unread = state.unreadAlertCount;
  $("#alertNavBadge").classList.toggle("d-none", !unread);
  $("#alertNavBadge").textContent = unread > 99 ? "99+" : String(unread);
  $("#markAllAlertsRead").disabled = !unread;
  $("#alertsHelp").textContent = alerts.length
    ? `${fmt(unread)} unread alert${unread === 1 ? "" : "s"}. Showing the latest ${alerts.length} local notification${alerts.length === 1 ? "" : "s"}.`
    : "Alerts will appear after snapshot capture when CivitTrack detects something actionable.";
  $("#alertInboxRows").innerHTML = alerts.length ? alerts.map((alert) => `
    <article class="ct-inbox-item ct-inbox-${esc(alert.level)} ${alert.is_read ? "" : "ct-inbox-unread"}">
      <div class="ct-inbox-icon"><i class="bi ${alert.level === "error" ? "bi-exclamation-octagon-fill" : alert.level === "warning" ? "bi-exclamation-triangle-fill" : alert.level === "success" ? "bi-graph-up-arrow" : "bi-info-circle-fill"}"></i></div>
      <div class="ct-inbox-content">
        <div class="ct-inbox-heading">
          <strong>${esc(alert.title)}</strong>
          ${alert.is_read ? "" : '<span class="ct-unread-dot">Unread</span>'}
        </div>
        <p>${esc(alert.message)}</p>
        <small>${esc(dateFmt(alert.created_at))}${alert.snapshot_id ? ` | Snapshot #${alert.snapshot_id}` : ""}</small>
      </div>
      <div class="ct-inbox-actions">
        ${alert.page_url ? `<a class="btn ct-btn-quiet" href="${esc(alert.page_url)}" target="_blank" rel="noopener" title="Open model on CivitAI"><i class="bi bi-box-arrow-up-right"></i></a>` : ""}
        ${alert.is_read ? "" : `<button class="btn ct-btn-quiet js-read-alert" type="button" data-alert-id="${alert.id}" title="Mark alert as read"><i class="bi bi-check2"></i></button>`}
      </div>
    </article>`).join("") : `<div class="ct-inbox-empty">No local alerts yet. Take snapshots over time to detect changes.</div>`;
  $$(".js-read-alert").forEach((button) => button.addEventListener("click", markAlertRead));
}

function renderAlertSettings() {
  const settings = state.alertSettings;
  if (!settings) return;
  const labels = {
    new_model: "New model detected",
    missing_model: "Missing model",
    new_version: "New version detected",
    download_milestone: "Download milestone reached",
    generation_support_changed: "Generation support changed",
    download_velocity_spike: "Download velocity spike",
    snapshot_warning: "Snapshot warning",
    snapshot_failed: "Snapshot failed",
  };
  $("#alertToggleGrid").innerHTML = Object.entries(labels).map(([key, label]) => `
    <label class="ct-toggle-row"><span>${esc(label)}</span><input type="checkbox" data-alert-toggle="${key}" ${settings.enabled[key] ? "checked" : ""}></label>`).join("");
  $("#alertMilestones").value = settings.download_milestones.join(",");
  $("#alertMinimumDownloads").value = settings.minimum_download_gain_alert;
  $("#alertMinimumCollections").value = settings.minimum_collection_gain_alert;
  $("#alertVelocityMultiplier").value = settings.velocity_spike_multiplier;
  $("#alertVelocityCurrent").value = settings.velocity_minimum_current_delta;
  $("#alertVelocityPrevious").value = settings.velocity_minimum_previous_delta;
}

function openSnapshotModal() {
  $("#snapshotNote").value = "";
  $("#snapshotNoteType").value = "normal_check";
  const latestDate = parsedDate(state.snapshots[0]?.checked_at);
  const ageMinutes = latestDate ? Math.max(0, (Date.now() - latestDate.getTime()) / 60000) : null;
  const tooSoon = ageMinutes !== null && ageMinutes < 5;
  $("#snapshotSoonWarning").classList.toggle("d-none", !tooSoon);
  $("#snapshotSoonWarning").textContent = tooSoon ? `You took a snapshot about ${Math.max(0, Math.floor(ageMinutes))} minute${Math.floor(ageMinutes) === 1 ? "" : "s"} ago. You can still continue, but this comparison may not show meaningful growth.` : "";
  $("#confirmSnapshot").innerHTML = tooSoon ? '<i class="bi bi-camera"></i> Continue Snapshot' : '<i class="bi bi-camera"></i> Take Snapshot';
  bootstrap.Modal.getOrCreateInstance($("#snapshotModal")).show();
  setTimeout(() => $("#snapshotNoteType").focus(), 180);
}

async function takeSnapshot(event) {
  event.preventDefault();
  const button = $("#confirmSnapshot");
  busy(button, true, "Saving snapshot...");
  try {
    const result = await api("/api/snapshot", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note_type: $("#snapshotNoteType").value, note: $("#snapshotNote").value }),
    });
    bootstrap.Modal.getOrCreateInstance($("#snapshotModal")).hide();
    await refresh();
    const newIndex = state.snapshots.findIndex((snapshot) => snapshot.id === result.snapshot_id);
    const previous = newIndex >= 0 ? state.snapshots[newIndex + 1] : null;
    if (previous) {
      try {
        renderComparison(await api(`/api/compare?from_id=${previous.id}&to_id=${result.snapshot_id}`));
        setView("overview");
        toast(`Snapshot saved. Compared with previous snapshot.${result.alert_count ? ` ${fmt(result.alert_count)} new alert${result.alert_count === 1 ? "" : "s"}.` : ""}`);
      } catch (_) {
        clearComparison();
        toast("Snapshot saved, but automatic comparison could not be loaded.", "warning");
      }
    } else {
      clearComparison();
      setView("overview");
      toast(`Snapshot ${result.snapshot_id} saved. Take another later to compare growth.`);
    }
  } catch (error) { toast(error.message, "error"); await Promise.all([loadLogs(), loadAlerts()]); }
  finally { busy(button, false); }
}

async function saveAlertSettings(event) {
  event.preventDefault();
  const button = $("#saveAlertSettings");
  const enabled = Object.fromEntries($$("[data-alert-toggle]").map((input) => [input.dataset.alertToggle, input.checked]));
  busy(button, true, "Saving...");
  try {
    const result = await api("/api/alert-settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        enabled,
        download_milestones: $("#alertMilestones").value,
        minimum_download_gain_alert: $("#alertMinimumDownloads").value,
        minimum_collection_gain_alert: $("#alertMinimumCollections").value,
        velocity_spike_multiplier: $("#alertVelocityMultiplier").value,
        velocity_minimum_current_delta: $("#alertVelocityCurrent").value,
        velocity_minimum_previous_delta: $("#alertVelocityPrevious").value,
      }),
    });
    state.alertSettings = result.settings;
    renderAlertSettings();
    toast("Alert preferences saved.");
  } catch (error) { toast(error.message, "error"); }
  finally { busy(button, false); }
}

async function saveSettings(event) {
  event.preventDefault();
  const button = $("#saveSettings");
  const values = Object.fromEntries($$("#settingsForm [name]").map((input) => [input.name, input.value]));
  const clearSecrets = $$("#settingsForm [data-clear-secret]:checked").map((checkbox) => checkbox.dataset.clearSecret);
  busy(button, true, "Saving...");
  try {
    const result = await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ values, clear_secrets: clearSecrets }),
    });
    state.settings = result.settings;
    await refresh();
    $("#settingsRestartHelp").textContent = result.restart_required ? "Restart CivitTrack to apply the new application host or port." : "";
    toast(result.changed.length ? "Local settings saved." : "Settings are already up to date.");
  } catch (error) { toast(error.message, "error"); }
  finally { busy(button, false); }
}

async function restoreDatabase(event) {
  event.preventDefault();
  const button = $("#restoreDatabase");
  const file = $("#restoreFile").files[0];
  if (!file) return;
  if (!window.confirm("Restore this backup? The current local database will be replaced after validation.")) return;
  const body = new FormData();
  body.append("backup", file);
  busy(button, true, "Restoring...");
  try {
    const result = await api("/api/database-restore", { method: "POST", body });
    clearComparison();
    await refresh();
    $("#restoreForm").reset();
    toast(result.safety_backup ? "Database restored. A pre-restore safety backup was saved." : "Database restored.");
  } catch (error) { toast(error.message, "error"); }
  finally { busy(button, false); }
}

async function deleteSnapshot(event) {
  const button = event.currentTarget;
  const snapshotId = Number(button.dataset.snapshotId);
  if (!window.confirm(`Delete snapshot #${snapshotId}? This removes its stored model, version, and linked alert history permanently.`)) return;
  busy(button, true, "Deleting...");
  try {
    await api(`/api/snapshots/${encodeURIComponent(snapshotId)}`, { method: "DELETE" });
    if ([state.currentComparison?.from_id, state.currentComparison?.to_id].includes(snapshotId)) clearComparison();
    toast(`Snapshot ${snapshotId} deleted.`);
    await refresh();
  } catch (error) { toast(error.message, "error"); }
  finally { busy(button, false); }
}

async function markAlertRead(event) {
  const button = event.currentTarget;
  busy(button, true, "...");
  try {
    await api(`/api/alerts/${encodeURIComponent(button.dataset.alertId)}/read`, { method: "POST" });
    await loadAlerts();
  } catch (error) { toast(error.message, "error"); }
  finally { busy(button, false); }
}

async function markAllAlertsRead(event) {
  const button = event.currentTarget;
  busy(button, true, "Marking...");
  try {
    const result = await api("/api/alerts/read-all", { method: "POST" });
    await loadAlerts();
    toast(`${fmt(result.updated)} alert${result.updated === 1 ? "" : "s"} marked as read.`);
  } catch (error) { toast(error.message, "error"); }
  finally { busy(button, false); }
}

async function loadAlerts() {
  const result = await api("/api/alerts");
  state.alerts = result.alerts;
  state.unreadAlertCount = result.unread_count;
  renderAlerts();
}

async function compare(url, button) {
  busy(button, true, "Comparing...");
  try { renderComparison(await api(url)); setView("overview"); }
  catch (error) { toast(error.message, "error"); }
  finally { busy(button, false); }
}

async function compareRange(event) {
  const days = Number(event.currentTarget.dataset.rangeDays);
  const range = rangeComparison(days);
  if (!range) {
    toast(rangeUnavailableMessage(days), "warning");
    return;
  }
  $("#fromSnapshot").value = range.from.id;
  $("#toSnapshot").value = range.to.id;
  await compare(`/api/compare?from_id=${range.from.id}&to_id=${range.to.id}`, event.currentTarget);
}

async function loadLogs() {
  try { renderLogs((await api("/api/logs")).logs); } catch (_) {}
}

async function showSnapshotQuality(event) {
  event.stopPropagation();
  try {
    const result = await api(`/api/snapshot-quality?snapshot_id=${encodeURIComponent(event.currentTarget.dataset.snapshotId)}`);
    const snapshot = result.snapshot;
    const quality = result.quality;
    const summary = quality ? {
      good: "This snapshot looks complete. CivitTrack loaded the available model stats and extra collection/minor-model data without warnings.",
      partial: "This snapshot was saved successfully, but some extra CivitAI data was unavailable. Downloads and reactions are still usable, but collections or minor-model coverage may be incomplete.",
      warning: "This snapshot was saved, but CivitTrack detected something that may affect comparison accuracy.",
      failed: "This snapshot failed and should not be used for comparisons.",
    }[quality.quality_status] : "Quality report is not available for this older snapshot.";
    const detailRows = quality ? [
      ["Quality status", qualityBadge(quality.quality_status)],
      ["REST models fetched", fmt(quality.rest_model_count)],
      ["API pages fetched", fmt(quality.api_page_count)],
      ["Minor-model discovery", esc(quality.minor_discovery_status || "Unavailable")],
      ["Extra minor models discovered", fmt(quality.minor_model_count)],
      ["Collection metrics", esc(quality.collection_metric_status || "Unavailable")],
      ["Collection metrics loaded", fmt(quality.collection_metric_count)],
      ["Creator profile", esc(quality.creator_profile_status || "Unavailable")],
      ["Follower count available", quality.follower_count_available ? "Yes" : "No"],
    ] : [];
    $("#qualityModalBody").innerHTML = `
      <p class="ct-quality-summary">${esc(summary)}</p>
      <div class="ct-quality-grid">
        <div><span>Snapshot</span><strong>#${snapshot.id}</strong></div>
        <div><span>Checked at</span><strong>${esc(dateFmt(snapshot.checked_at))}</strong></div>
        <div><span>Source</span><strong>${esc(sourceLabel(snapshot.source))}</strong></div>
        <div><span>Note type</span><strong>${esc(noteTypeLabel(snapshot.note_type))}</strong></div>
      </div>
      ${snapshot.note ? `<p class="ct-quality-note"><strong>Note:</strong> ${esc(snapshot.note)}</p>` : ""}
      ${quality ? `<div class="ct-quality-detail">${detailRows.map(([label, value]) => `<div><span>${esc(label)}</span><strong>${value}</strong></div>`).join("")}</div>
      <h3>Warnings</h3><div class="ct-report-list">${quality.warnings.length ? quality.warnings.map((item) => `<p>${esc(item)}</p>`).join("") : "<p>No warnings recorded.</p>"}</div>
      <h3>Info</h3><div class="ct-report-list">${quality.info.length ? quality.info.map((item) => `<p>${esc(item)}</p>`).join("") : "<p>No info messages recorded.</p>"}</div>` : ""}`;
    bootstrap.Modal.getOrCreateInstance($("#qualityModal")).show();
  } catch (error) { toast(error.message, "error"); }
}

async function showHistory(modelId) {
  try {
    const result = await api(`/api/model-history?model_id=${encodeURIComponent(modelId)}`);
    const rows = result.history;
    const first = rows[0], latest = rows[rows.length - 1];
    const cover = latest.cover_image_url ? `<img class="ct-history-cover" src="${esc(latest.cover_image_url)}" alt="${esc(latest.model_name)} cover image" loading="lazy" referrerpolicy="no-referrer" onerror="this.hidden=true">` : "";
    $("#historyTitle").textContent = latest.model_name;
    $("#historyBody").innerHTML = `
      ${cover}
      <p class="ct-history-summary"><strong>${signed(latest.download_count - first.download_count)}</strong> downloads across ${rows.length} stored snapshot${rows.length === 1 ? "" : "s"}.</p>
      <a class="btn ct-btn-secondary mb-3" href="${esc(latest.page_url)}" target="_blank" rel="noopener">Open on CivitAI <i class="bi bi-box-arrow-up-right"></i></a>
      <div class="table-responsive"><table class="table ct-table"><thead><tr><th>Checked at</th><th>Downloads</th><th>Reactions</th><th>Collections</th><th>Comments</th></tr></thead>
      <tbody>${rows.map((row) => `<tr><td>${esc(dateFmt(row.checked_at))}</td><td>${fmt(row.download_count)}</td><td>${fmt(row.reaction_count)}</td><td>${fmt(row.collected_count)}</td><td>${fmt(row.comment_count)}</td></tr>`).join("")}</tbody></table></div>`;
    bootstrap.Offcanvas.getOrCreateInstance($("#historyDrawer")).show();
  } catch (error) { toast(error.message, "error"); }
}

$$(".js-snapshot").forEach((button) => button.addEventListener("click", openSnapshotModal));
$$(".js-compare-latest").forEach((button) => button.addEventListener("click", (event) => compare("/api/compare-latest", event.currentTarget)));
$$(".js-compare-range").forEach((button) => button.addEventListener("click", compareRange));
$$(".ct-side-tab").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
$("#snapshotForm").addEventListener("submit", takeSnapshot);
$("#settingsForm").addEventListener("submit", saveSettings);
$("#alertSettingsForm").addEventListener("submit", saveAlertSettings);
$("#restoreForm").addEventListener("submit", restoreDatabase);
$("#markAllAlertsRead").addEventListener("click", markAllAlertsRead);
$("#compareSelected").addEventListener("click", (event) => compare(`/api/compare?from_id=${$("#fromSnapshot").value}&to_id=${$("#toSnapshot").value}`, event.currentTarget));
$("#compareDate").addEventListener("click", (event) => {
  const fromValue = $("#fromDate").value;
  const toValue = $("#toDate").value;
  const fromDate = fromValue ? new Date(fromValue).toISOString() : "";
  const toDate = toValue ? new Date(toValue).toISOString() : "";
  compare(`/api/compare-by-date?from_dt=${encodeURIComponent(fromDate)}&to_dt=${encodeURIComponent(toDate)}`, event.currentTarget);
});
$("#modelSearch").addEventListener("input", renderModels);
$("#breakdownSearch").addEventListener("input", renderBreakdown);
$("#breakdownFilters").addEventListener("click", (event) => {
  if (!event.target.dataset.breakdownMetric) return;
  $$("#breakdownFilters .ct-filter").forEach((button) => button.classList.remove("active"));
  event.target.classList.add("active");
  state.breakdownMetric = event.target.dataset.breakdownMetric;
  renderBreakdown();
});
$("#breakdownSorts").addEventListener("click", (event) => {
  if (!event.target.dataset.breakdownSort) return;
  $$("#breakdownSorts .ct-filter").forEach((button) => button.classList.remove("active"));
  event.target.classList.add("active");
  state.breakdownSort = event.target.dataset.breakdownSort;
  renderBreakdown();
});
$("#showUnchanged").addEventListener("change", (event) => { state.showUnchanged = event.target.checked; renderModels(); });
$("#modelFilters").addEventListener("click", (event) => {
  if (!event.target.dataset.filter) return;
  $$("#modelFilters .ct-filter").forEach((button) => button.classList.remove("active"));
  event.target.classList.add("active");
  state.currentFilter = event.target.dataset.filter;
  renderModels();
});
$("#modelSorts").addEventListener("click", (event) => {
  if (!event.target.dataset.modelSort) return;
  $$("#modelSorts .ct-filter").forEach((button) => button.classList.remove("active"));
  event.target.classList.add("active");
  state.currentSort = event.target.dataset.modelSort;
  renderModels();
});
$("#showAllVersions").addEventListener("click", () => { state.showAllVersions = true; renderVersions(); });
$$("[data-clear-secret]").forEach((checkbox) => checkbox.addEventListener("change", () => {
  const input = $(`#settingsForm [name="${checkbox.dataset.clearSecret}"]`);
  input.value = "";
  input.disabled = checkbox.checked;
}));
$$('[data-bs-toggle="tooltip"]').forEach((element) => bootstrap.Tooltip.getOrCreateInstance(element));

function viewFromHash() {
  const hash = location.hash.slice(1);
  if (hash === "snapshot-manager") return "snapshots";
  return ["overview", "models", "snapshots", "alerts", "settings"].includes(hash) ? hash : "overview";
}

window.addEventListener("hashchange", () => setView(viewFromHash(), false));
setView(viewFromHash(), false);
refresh().catch((error) => toast(error.message, "error"));
