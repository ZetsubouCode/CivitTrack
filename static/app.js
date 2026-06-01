const state = {
  currentView: "overview",
  status: null,
  snapshots: [],
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

function compareDates(a, b, direction) {
  const aTime = dateValue(a.published_at);
  const bTime = dateValue(b.published_at);
  if (aTime === null && bTime === null) return a.model_name.localeCompare(b.model_name);
  if (aTime === null) return 1;
  if (bTime === null) return -1;
  return direction === "oldest" ? aTime - bTime : bTime - aTime;
}

function setView(view, updateHash = true) {
  const views = ["overview", "models", "snapshots", "settings"];
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
  item.className = `ct-alert ${type === "error" ? "ct-alert-error" : ""}`;
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
  $("#setupUsername").textContent = state.status.username || "Missing";
  $("#setupApiKey").textContent = state.status.api_key_configured ? "Configured locally" : "Missing";
  $("#setupModelFilter").textContent = state.status.model_type_filter;
  $("#setupRestrictedModels").textContent = state.status.include_nsfw && state.status.include_minor ? "Included for analytics" : "Partially excluded";
  $("#setupDbPath").textContent = state.status.db_path;
  $("#setupHelp").textContent = ready ? "Configuration is loaded. Credentials remain server-side." : "Add CIVITAI_API_KEY and CIVITAI_USERNAME to .env, restart the app, then try again.";
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
  $("#compareSelected").disabled = !enough;
  $("#compareDate").disabled = !enough;
  $("#compareHelp").textContent = enough ? `${state.snapshots.length} snapshots available. Latest comparison is ready.` : state.snapshots.length === 1 ? "One snapshot saved. Take another later to compare growth." : "Need at least 2 snapshots to compare growth.";
  $("#snapshotListHelp").textContent = state.snapshots.length ? `${state.snapshots.length} stored snapshot${state.snapshots.length === 1 ? "" : "s"}, newest first.` : "No snapshots stored yet.";
  $("#snapshotRows").innerHTML = state.snapshots.length ? state.snapshots.map((snapshot) => `
    <tr>
      <td><span class="ct-status">#${snapshot.id}</span></td>
      <td>${esc(dateFmt(snapshot.checked_at))}</td>
      <td>${esc(snapshot.note || "-")}</td>
      <td>${esc(snapshot.source || "-")}</td>
      <td>${fmt(snapshot.model_count)}</td>
      <td>${fmt(snapshot.total_download_count)}</td>
      <td>${fmt(snapshot.total_reaction_count)}</td>
      <td>${fmt(snapshot.total_collected_count)}</td>
      <td>${fmt(snapshot.total_comment_count)}</td>
      <td><button class="btn ct-btn-danger js-delete-snapshot" type="button" data-snapshot-id="${snapshot.id}"><i class="bi bi-trash3"></i> Delete</button></td>
    </tr>`).join("") : `<tr><td colspan="10" class="ct-table-empty">Take your first snapshot to start tracking growth.</td></tr>`;
  $$(".js-delete-snapshot").forEach((button) => button.addEventListener("click", deleteSnapshot));
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
      <td><span class="ct-status">${esc(row.status.replaceAll("_", " "))}</span></td>
    </tr>`).join("") : `<tr><td colspan="6" class="ct-table-empty">No version data in this comparison.</td></tr>`;
  $("#showAllVersions").classList.toggle("d-none", allRows.length <= 20 || state.showAllVersions);
}

function renderInsight() {
  const comparison = state.currentComparison;
  $("#insightStrip").classList.toggle("d-none", !comparison);
  if (!comparison) return;
  const delta = comparison.summary.total_download_count_delta;
  const movers = comparison.models.filter(changed);
  const top = [...comparison.models].sort((a, b) => metricDelta(b, "download_count") - metricDelta(a, "download_count"))[0];
  $("#insightStrip").textContent = delta === 0 && !movers.length ? "No growth detected in this range." : `Downloads changed by ${signed(delta)} across ${movers.length} model${movers.length === 1 ? "" : "s"}.${top && metricDelta(top, "download_count") > 0 ? ` Top mover: ${top.model_name} gained ${signed(metricDelta(top, "download_count"))} downloads.` : ""}`;
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
  const [status, snapshots, breakdown, logs] = await Promise.all([api("/api/status"), api("/api/snapshots"), api("/api/latest-breakdown"), api("/api/logs")]);
  state.status = status;
  state.snapshots = snapshots.snapshots;
  state.latestBreakdown = breakdown;
  renderStatus();
  renderSnapshots();
  renderMetrics();
  renderBreakdown();
  renderLogs(logs.logs);
}

function renderLogs(logs) {
  $("#logRows").innerHTML = logs.length ? logs.map((row) => `<div class="ct-log-${esc(row.level)}">[${esc(dateFmt(row.created_at))}] ${esc(row.level.toUpperCase())}: ${esc(row.message)}</div>`).join("") : `<div class="ct-log-info">Logs will appear here.</div>`;
}

function openSnapshotModal() {
  $("#snapshotNote").value = "";
  bootstrap.Modal.getOrCreateInstance($("#snapshotModal")).show();
  setTimeout(() => $("#snapshotNote").focus(), 180);
}

async function takeSnapshot(event) {
  event.preventDefault();
  const button = $("#confirmSnapshot");
  busy(button, true, "Saving snapshot...");
  try {
    const result = await api("/api/snapshot", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note: $("#snapshotNote").value }),
    });
    bootstrap.Modal.getOrCreateInstance($("#snapshotModal")).hide();
    toast(`Snapshot ${result.snapshot_id} saved.`);
    clearComparison();
    await refresh();
  } catch (error) { toast(error.message, "error"); await loadLogs(); }
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
  if (!window.confirm(`Delete snapshot #${snapshotId}? This removes its stored model and version history permanently.`)) return;
  busy(button, true, "Deleting...");
  try {
    await api(`/api/snapshots/${encodeURIComponent(snapshotId)}`, { method: "DELETE" });
    if ([state.currentComparison?.from_id, state.currentComparison?.to_id].includes(snapshotId)) clearComparison();
    toast(`Snapshot ${snapshotId} deleted.`);
    await refresh();
  } catch (error) { toast(error.message, "error"); }
  finally { busy(button, false); }
}

async function compare(url, button) {
  busy(button, true, "Comparing...");
  try { renderComparison(await api(url)); setView("overview"); }
  catch (error) { toast(error.message, "error"); }
  finally { busy(button, false); }
}

async function loadLogs() {
  try { renderLogs((await api("/api/logs")).logs); } catch (_) {}
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
$$(".ct-side-tab").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
$("#snapshotForm").addEventListener("submit", takeSnapshot);
$("#restoreForm").addEventListener("submit", restoreDatabase);
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

function viewFromHash() {
  const hash = location.hash.slice(1);
  if (hash === "snapshot-manager") return "snapshots";
  return ["overview", "models", "snapshots", "settings"].includes(hash) ? hash : "overview";
}

window.addEventListener("hashchange", () => setView(viewFromHash(), false));
setView(viewFromHash(), false);
refresh().catch((error) => toast(error.message, "error"));
