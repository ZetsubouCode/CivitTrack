const state = {
  currentView: "overview",
  status: null,
  settings: null,
  snapshots: [],
  alerts: [],
  unreadAlertCount: 0,
  alertSettings: null,
  buzzStatus: null,
  buzzSettings: null,
  reactionUsage: null,
  buzzTransactions: [],
  imageStatus: null,
  articleStatus: null,
  articles: [],
  articleTotal: 0,
  articleLoading: false,
  articleSearchTimer: null,
  imageFilterOptions: { models: [], versions: [] },
  images: [],
  imageTotal: 0,
  imageOffset: 0,
  imageHasMore: false,
  imageLoading: false,
  imageDetailLoading: false,
  currentImageId: null,
  imageHideOwn: true,
  imageSearchTimer: null,
  buzzAccountFilter: "all",
  buzzCategoryFilter: "all",
  buzzDirectionFilter: "all",
  imageRatingFilters: [],
  articleRatingFilters: [],
  latestBreakdown: null,
  breakdownMetric: "download_count",
  breakdownSort: "metric",
  currentComparison: null,
  currentSort: "newest",
  currentFilter: "all",
  showUnchanged: false,
  showAllVersions: false,
  imageVirtual: {
    columns: 1,
    rowHeight: 344,
    gap: 14,
    overscanRows: 3,
    frame: null,
  },
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const fmt = (value) => value === null || value === undefined ? "N/A" : Number(value).toLocaleString();
const byteFmt = (value) => {
  const bytes = Number(value || 0);
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`;
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${fmt(bytes)} B`;
};
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
const htmlText = (value) => {
  const doc = new DOMParser().parseFromString(String(value || ""), "text/html");
  return doc.body.textContent || "";
};
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
const signedOptional = (value) => value === null || value === undefined ? "N/A" : signed(value);
const buzzFilterLabels = {
  Blue: "Blue", Yellow: "Yellow", Green: "Green",
  model: "Models", image: "Images", article: "Articles", comment: "Comments", tip: "Tips",
  reward: "Rewards", spend: "Spending", unknown: "Unknown",
  gained: "Gained", spent: "Spent",
};
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
const imageRatingLabel = (value, nsfw = false) => {
  const text = String(value || "").trim().toLowerCase();
  if (["pg", "none", "sfw"].includes(text)) return "PG";
  if (["pg-13", "pg13", "soft"].includes(text)) return "PG-13";
  if (["r", "mature"].includes(text)) return "R";
  if (text === "x") return "X";
  if (text === "xxx") return "XXX";
  return value || (nsfw ? "NSFW" : "PG");
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
  const views = ["overview", "models", "images", "articles", "buzz", "snapshots", "alerts", "settings"];
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
  if (nextView === "images") {
    ensureImagesPanelLoaded();
    setTimeout(() => {
      updateImageVirtualMetrics();
      renderImageGallery();
      maybeLoadMoreImages();
    }, 60);
  } else if (nextView === "articles") {
    ensureArticlesPanelLoaded();
  }
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  const contentType = response.headers.get("content-type") || "";
  const text = await response.text();
  let data = null;
  if (contentType.includes("application/json")) {
    try {
      data = text ? JSON.parse(text) : {};
    } catch (error) {
      throw new Error(`${url} returned invalid JSON.`);
    }
  } else {
    const fallback = response.ok ? "non-JSON content" : `HTTP ${response.status}`;
    throw new Error(`${url} returned ${fallback}.`);
  }
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

const buzzEventLabel = (value) => ({
  model_collection: "Model collection",
  model_reaction: "Model reaction",
  image_collection: "Image collection",
  image_reaction: "Image reaction",
  article_reaction: "Article reaction",
  comment_reaction: "Comment reaction",
  tip_received: "Tip received",
  tip_sent: "Tip sent",
  reward: "Reward",
  purchase: "Purchase",
  generation_spend: "Generation spend",
  training_spend: "Training spend",
  other_gain: "Other gain",
  other_spend: "Other spend",
  unknown: "Unknown",
}[value] || "Unknown");
const buzzAccountPill = (value) => `<span class="ct-buzz-account ct-buzz-${esc(String(value || "unknown").toLowerCase())}">${esc(value || "Unknown")}</span>`;
const buzzSource = (row) => row.source_label || row.model_name || (row.image_id ? `Image #${row.image_id}` : row.username || "Unknown source");
const buzzCategoryMatch = (row, filter) => filter === "all"
  || (filter === "model" && row.event_category.startsWith("model_"))
  || (filter === "image" && row.event_category.startsWith("image_"))
  || (filter === "article" && row.event_category.startsWith("article_"))
  || (filter === "comment" && row.event_category.startsWith("comment_"))
  || (filter === "tip" && row.event_category.startsWith("tip_"))
  || (filter === "reward" && row.event_category === "reward")
  || (filter === "spend" && ["purchase", "generation_spend", "training_spend", "other_spend"].includes(row.event_category))
  || (filter === "unknown" && row.event_category === "unknown");
const filterSummary = (values, labels) => values.length ? values.map((value) => labels[value] || value).join(", ") : "All";

function setChipGroupState(selector, datasetKey, values) {
  $$(`${selector} .ct-filter`).forEach((button) => {
    const value = button.dataset[datasetKey];
    const active = value === "all" ? !values.length : values.includes(value);
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}

function toggleChipValue(stateKey, selector, datasetKey, value) {
  if (value === "all") {
    state[stateKey] = [];
  } else {
    const current = state[stateKey] || [];
    state[stateKey] = current.includes(value)
      ? current.filter((item) => item !== value)
      : [...current, value];
  }
  setChipGroupState(selector, datasetKey, state[stateKey]);
}

function renderBuzzSettings() {
  const settings = state.buzzSettings;
  if (!settings) return;
  $("#buzzTrackingEnabled").checked = settings.enabled;
  $("#buzzTrackBlue").checked = settings.account_types.Blue;
  $("#buzzTrackYellow").checked = settings.account_types.Yellow;
  $("#buzzTrackGreen").checked = settings.account_types.Green;
  $("#buzzTransactionLimit").value = settings.transaction_limit;
}

function renderBuzz() {
  const summary = state.buzzStatus;
  const latest = summary?.latest_check;
  const available = summary?.endpoint_available;
  $("#buzzStatusPill").className = `ct-pill ${available === true ? "ct-pill-success" : available === false ? "ct-pill-warning" : "ct-pill-muted"}`;
  $("#buzzStatusPill").textContent = available === true
    ? (latest.quality_status === "partial" ? "Partial" : "Buzz API Ready")
    : available === false ? "Unavailable" : "Not checked";
  $("#buzzStatusHelp").textContent = summary?.warning
    || (latest ? `Last Buzz check ${dateFmt(latest.checked_at)}. ${fmt(summary.new_transaction_count)} new stored transaction${summary.new_transaction_count === 1 ? "" : "s"} found.` : "Enable Buzz tracking in Settings, then run a check.");
  const balances = Object.fromEntries((summary?.latest_balances || []).map((row) => [row.account_type, row]));
  const accountCards = (summary?.selected_account_types || []).map((accountType) => {
    const row = balances[accountType] || {};
    return `<article class="ct-card ct-metric">
      <span class="ct-metric-label">${esc(accountType)} Buzz balance</span>
      <strong class="ct-metric-value">${fmt(row.balance)}</strong>
      <span class="ct-metric-delta"><span class="ct-positive">+${fmt(row.gained_recent || 0)}</span> gained, <span class="ct-negative">-${fmt(row.spent_recent || 0)}</span> spent in fetched activity</span>
    </article>`;
  });
  accountCards.push(`<article class="ct-card ct-metric"><span class="ct-metric-label">New transactions</span><strong class="ct-metric-value">${fmt(summary?.new_transaction_count || 0)}</strong><span class="ct-metric-delta">Found in the latest Buzz check</span></article>`);
  $("#buzzMetricsGrid").innerHTML = accountCards.join("");
  renderBuzzTransactions();
}

function renderBuzzTransactions() {
  const query = $("#buzzSearch").value.trim().toLowerCase();
  const rows = state.buzzTransactions
    .filter((row) => state.buzzAccountFilter === "all" || row.account_type === state.buzzAccountFilter)
    .filter((row) => state.buzzDirectionFilter === "all" || row.direction === state.buzzDirectionFilter)
    .filter((row) => buzzCategoryMatch(row, state.buzzCategoryFilter))
    .filter((row) => !query || [row.description, row.model_name, row.image_id, row.article_id, row.comment_id, row.source_label, row.username].some((value) => String(value || "").toLowerCase().includes(query)));
  $("#buzzFilterSummary").textContent = `${fmt(rows.length)} of ${fmt(state.buzzTransactions.length)} transactions shown. Account: ${filterSummary(state.buzzAccountFilter === "all" ? [] : [state.buzzAccountFilter], buzzFilterLabels)}. Event: ${filterSummary(state.buzzCategoryFilter === "all" ? [] : [state.buzzCategoryFilter], buzzFilterLabels)}. Direction: ${filterSummary(state.buzzDirectionFilter === "all" ? [] : [state.buzzDirectionFilter], buzzFilterLabels)}.`;
  $("#buzzRows").innerHTML = rows.length ? rows.map((row) => {
    const link = row.source_url || row.model_url || row.image_page_url || row.image_url || row.article_url || row.comment_url;
    return `<tr data-buzz-id="${row.id}">
      <td>${esc(dateFmt(row.transaction_date || row.first_seen_at))}</td>
      <td><span class="ct-delta ${deltaClass(row.amount)}">${signed(row.amount)}</span></td>
      <td>${buzzAccountPill(row.account_type)}</td>
      <td>${esc(buzzEventLabel(row.event_category))}</td>
      <td>${esc(buzzSource(row))}</td>
      <td>${esc(row.description || row.title || "Unmatched Buzz event.")}</td>
      <td><span class="ct-status">${esc(qualityLabel(row.match_confidence))}</span></td>
      <td>${link ? `<a href="${esc(link)}" target="_blank" rel="noopener" onclick="event.stopPropagation()" aria-label="Open ${esc(buzzSource(row))} on CivitAI"><i class="bi bi-box-arrow-up-right"></i></a>` : "-"}</td>
    </tr>`;
  }).join("") : `<tr><td colspan="8" class="ct-table-empty">No stored Buzz activity matches these filters. Unknown events will appear here when CivitAI returns them.</td></tr>`;
  $$("#buzzRows tr[data-buzz-id]").forEach((row) => row.addEventListener("click", () => showBuzzDetail(row.dataset.buzzId)));
}

const metricSpec = [
  ["Downloads", "total_download_count", "Total model downloads"],
  ["Reactions", "total_reaction_count", "Combined reaction signals"],
  ["Collections", "total_collected_count", "Added to CivitAI collections"],
  ["Generations", "total_generation_count", "CivitAI on-site generations"],
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
      <td>${fmt(snapshot.total_generation_count)}</td>
      <td>${fmt(snapshot.total_comment_count)}</td>
      <td><span class="ct-row-actions"><button class="btn ct-btn-quiet js-quality-report" type="button" data-snapshot-id="${snapshot.id}"><i class="bi bi-clipboard-data"></i> Details</button><button class="btn ct-btn-danger js-delete-snapshot" type="button" data-snapshot-id="${snapshot.id}"><i class="bi bi-trash3"></i> Delete</button></span></td>
    </tr>`).join("") : `<tr><td colspan="13" class="ct-table-empty">Take your first snapshot to start tracking growth.</td></tr>`;
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
    generation_count: ["Generations", "total_generation_count"],
  };
  const [label, totalKey] = metricSpecs[metric];
  const total = Number(breakdown?.totals?.[totalKey] || 0);
  const sortDescription = state.breakdownSort === "metric"
    ? `Ranked by ${label.toLowerCase()}, with share of that total.`
    : `Sorted by ${state.breakdownSort} original date, with share of total ${label.toLowerCase()}.`;
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
        <td title="Last stored check with a download increase. Original date used for sort: ${esc(dateFmt(row.published_at))}">${esc(row.last_download_observed_at ? dateFmt(row.last_download_observed_at) : "Unknown")}</td>
        <td><span class="ct-delta">${fmt(row.download_count)}</span></td>
        <td><span class="ct-delta">${fmt(row.reaction_count)}</span></td>
        <td><span class="ct-delta">${fmt(row.collected_count)}</span></td>
        <td><span class="ct-delta">${fmt(row.generation_count)}</span></td>
        <td><span class="ct-share"><span class="ct-share-bar"><span class="ct-share-fill" style="width:${Math.min(100, share).toFixed(2)}%"></span></span><span class="ct-share-value">${share.toFixed(1)}%</span></span></td>
        <td>${esc(row.latest_version_name || "-")}</td>
        <td><a href="${esc(row.page_url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()" aria-label="Open ${esc(row.model_name)} on CivitAI"><i class="bi bi-box-arrow-up-right"></i></a></td>
      </tr>`;
  }).join("") : `<tr><td colspan="10" class="ct-table-empty">${breakdown?.snapshot ? `No models with ${label.toLowerCase()} in the latest snapshot.` : "Take a snapshot to see your current model totals."}</td></tr>`;
  $$("#breakdownRows tr[data-model-id]").forEach((row) => row.addEventListener("click", () => showHistory(row.dataset.modelId)));
}

const imageReactionCount = (row) => Number(row.like_count || 0) + Number(row.heart_count || 0) + Number(row.laugh_count || 0) + Number(row.cry_count || 0);
const cachedImageUrl = (imageId) => `/api/images/cache/${encodeURIComponent(imageId)}`;
const imageFallbackHandler = "if(this.dataset.fallback&&this.src!==this.dataset.fallback){this.src=this.dataset.fallback;this.removeAttribute('data-fallback')}else{this.closest('.ct-image-thumb')?.classList.add('ct-image-broken');this.hidden=true}";
const imageReactionSpecs = [
  ["Like", "bi-hand-thumbs-up-fill", "like_count"],
  ["Heart", "bi-heart-fill", "heart_count"],
  ["Laugh", "bi-emoji-laughing-fill", "laugh_count"],
  ["Cry", "bi-emoji-frown-fill", "cry_count"],
];
const commentReactionSpecs = [
  ["Like", "bi-hand-thumbs-up-fill"],
  ["Laugh", "bi-emoji-laughing-fill"],
  ["Cry", "bi-emoji-frown-fill"],
  ["Heart", "bi-heart-fill"],
];

async function loadReactionUsage() {
  state.reactionUsage = await api("/api/images/reaction-usage");
  return state.reactionUsage;
}

async function confirmReactionBonusLimit(isRemoving) {
  if (isRemoving) return true;
  let usage = state.reactionUsage;
  try {
    usage = await loadReactionUsage();
  } catch (_) {
    return true;
  }
  const limit = Number(usage?.warning_limit || 0);
  const count = Number(usage?.today_count || 0);
  if (!usage?.warning_enabled || !limit || count < limit) return true;
  return confirm(`You have already added ${fmt(count)} reaction${count === 1 ? "" : "s"} today. The blue Buzz reaction bonus may already be done for today. Continue reacting anyway?`);
}

function updateReactionUsage(result) {
  if (result?.reaction_usage) state.reactionUsage = result.reaction_usage;
}

function renderImageSummary() {
  const totals = state.imageStatus?.totals || {};
  const latest = state.imageStatus?.latest_sync;
  const cache = state.imageStatus?.cache || {};
  const hidden = state.imageStatus?.hidden || {};
  const blocked = state.imageStatus?.blocked || {};
  $("#imageSyncHelp").textContent = latest
    ? `Last image sync ${dateFmt(latest.checked_at)}. ${fmt(latest.new_image_count)} new image${latest.new_image_count === 1 ? "" : "s"} found. CivitAI-hidden images are excluded.`
    : "Take a model snapshot first, then sync public images.";
  $("#imageMetricsGrid").innerHTML = [
    ["Stored images", totals.image_count, "Public linked images in SQLite"],
    ["Linked models", totals.model_count, "Models represented in the gallery"],
    ["Linked versions", totals.version_count, "Model versions represented"],
    ["Latest remote image", totals.newest_image_at ? dateOnlyFmt(totals.newest_image_at) : "N/A", "Newest public image timestamp"],
    ["Hidden filtered", hidden.hidden_count || 0, hidden.hidden_checked_at ? `Synced ${dateFmt(hidden.hidden_checked_at)}` : "CivitAI hidden-image list"],
    ["Blocked users", blocked.blocked_user_count || 0, blocked.blocked_checked_at ? `Synced ${dateFmt(blocked.blocked_checked_at)}` : "CivitAI blocked-user list"],
    ["Thumbnail cache", byteFmt(cache.cache_bytes), `${fmt(cache.cache_file_count || 0)} local files, capped at ${byteFmt(cache.max_bytes)}`],
  ].map(([label, value, help]) => `<article class="ct-card ct-metric"><span class="ct-metric-label">${esc(label)}</span><strong class="ct-metric-value">${esc(value)}</strong><span class="ct-metric-delta">${esc(help)}</span></article>`).join("");
}

function renderImageFilters() {
  const selectedModel = $("#imageModelFilter").value;
  const selectedVersion = $("#imageVersionFilter").value;
  const modelQuery = $("#imageModelOptionSearch").value.trim().toLowerCase();
  const models = state.imageFilterOptions.models.filter((row) => String(row.model_id) === selectedModel || !modelQuery || row.model_name.toLowerCase().includes(modelQuery) || String(row.model_id).includes(modelQuery));
  $("#imageModelFilter").innerHTML = `<option value="">All models</option>${models.map((row) => `<option value="${row.model_id}">${esc(row.model_name)} (${fmt(row.image_count)})</option>`).join("")}`;
  $("#imageModelFilter").value = selectedModel;
  const versions = state.imageFilterOptions.versions.filter((row) => !selectedModel || String(row.model_id) === selectedModel);
  $("#imageVersionFilter").innerHTML = `<option value="">All versions</option>${versions.map((row) => `<option value="${row.model_version_id}">${esc(row.version_name || `Version ${row.model_version_id}`)} (${fmt(row.image_count)})</option>`).join("")}`;
  $("#imageVersionFilter").value = versions.some((row) => String(row.model_version_id) === selectedVersion) ? selectedVersion : "";
}

function imageFilterQueryString() {
  const params = new URLSearchParams();
  if (state.imageHideOwn) params.set("hide_own", "true");
  state.imageRatingFilters.forEach((rating) => params.append("rating", rating));
  return params.toString();
}

function imageQueryString(offset = state.imageOffset) {
  const params = new URLSearchParams({
    limit: "120",
    offset: String(offset),
    sort: $("#imageSort").value,
  });
  const search = $("#imageSearch").value.trim();
  const modelId = $("#imageModelFilter").value;
  const versionId = $("#imageVersionFilter").value;
  if (search) params.set("search", search);
  if (modelId) params.set("model_id", modelId);
  if (versionId) params.set("model_version_id", versionId);
  state.imageRatingFilters.forEach((rating) => params.append("rating", rating));
  if (state.imageHideOwn) params.set("hide_own", "true");
  return params.toString();
}

async function loadImages(reset = false) {
  if (state.imageLoading) return;
  state.imageLoading = true;
  if (reset) {
    state.images = [];
    state.imageOffset = 0;
    state.imageTotal = 0;
    state.imageHasMore = false;
    renderImageGallery();
  }
  try {
    const result = await api(`/api/images?${imageQueryString(reset ? 0 : state.imageOffset)}`);
    state.images = reset ? result.images : [...state.images, ...result.images];
    state.imageTotal = result.total;
    state.imageOffset = result.offset + result.images.length;
    state.imageHasMore = result.has_more;
    renderImageGallery();
  } catch (error) {
    toast(error.message, "error");
  } finally {
    state.imageLoading = false;
    renderImageGallery();
  }
}

async function loadImageStatus() {
  const filterQuery = imageFilterQueryString();
  const [status, filters] = await Promise.all([api("/api/images/status"), api(`/api/images/filters${filterQuery ? `?${filterQuery}` : ""}`)]);
  state.imageStatus = status;
  state.imageFilterOptions = filters;
  renderImageSummary();
  renderImageFilters();
}

async function ensureImagesPanelLoaded() {
  try {
    if (!state.imageStatus || !state.imageFilterOptions.models.length) {
      await loadImageStatus();
    }
    if (!state.images.length) {
      await loadImages(true);
    }
  } catch (error) {
    toast(error.message, "error");
  }
}

function resetImageGallery() {
  state.imageOffset = 0;
  state.imageHasMore = false;
  loadImages(true);
}

function updateImageVirtualMetrics() {
  const scroller = $("#imageScroller");
  if (!scroller) return;
  const width = Math.max(260, scroller.clientWidth - 24);
  const nextColumns = Math.max(1, Math.floor((width + state.imageVirtual.gap) / (236 + state.imageVirtual.gap)));
  state.imageVirtual.columns = nextColumns;
  state.imageVirtual.rowHeight = window.innerWidth <= 520 ? 322 : 344;
}

function imageCard(row) {
  const reactions = imageReactionCount(row);
  const ratio = row.width && row.height ? `${row.width}x${row.height}` : "Unknown size";
  const preview = cachedImageUrl(row.image_id);
  return `<article class="ct-image-card" data-image-id="${row.image_id}">
    <div class="ct-image-thumb">
      ${row.image_url ? `<img src="${esc(preview)}" data-fallback="${esc(row.image_url)}" alt="${esc(row.model_name)} public image" loading="lazy" decoding="async" referrerpolicy="no-referrer" onerror="${imageFallbackHandler}">` : ""}
      <span class="ct-image-badge">${esc(imageRatingLabel(row.nsfw_level, row.nsfw))}</span>
    </div>
    <div class="ct-image-meta">
      <strong>${esc(row.model_name)}</strong>
      <span>${esc(row.version_name || `Version ${row.model_version_id}`)} | ${esc(row.username || "Unknown creator")}</span>
      <span>${esc(dateFmt(row.published_at || row.first_seen_at))} | ${esc(ratio)}</span>
      <div class="ct-image-stats">
        <span><i class="bi bi-heart-fill"></i> ${fmt(reactions)}</span>
        <span><i class="bi bi-chat-left-text"></i> ${fmt(row.comment_count)}</span>
        ${row.local_reactions?.length ? `<span class="ct-image-reacted"><i class="bi bi-check2-circle"></i> Reacted</span>` : ""}
        <a href="${esc(row.image_page_url || row.image_url || "#")}" target="_blank" rel="noopener" onclick="event.stopPropagation()" aria-label="Open image on CivitAI"><i class="bi bi-box-arrow-up-right"></i></a>
      </div>
    </div>
  </article>`;
}

function renderImageGallery() {
  const scroller = $("#imageScroller");
  const grid = $("#imageGrid");
  const space = $("#imageVirtualSpace");
  if (!scroller || !grid || !space) return;
  updateImageVirtualMetrics();
  const { columns, rowHeight, overscanRows } = state.imageVirtual;
  const rowsLoaded = Math.ceil(state.images.length / columns);
  const totalHeight = Math.max(scroller.clientHeight - 2, rowsLoaded * rowHeight + (state.imageLoading || state.imageHasMore ? rowHeight : 0));
  space.style.height = `${totalHeight}px`;
  grid.style.gridTemplateColumns = `repeat(${columns}, minmax(0, 1fr))`;
  grid.style.gap = `${state.imageVirtual.gap}px`;

  if (!state.images.length) {
    grid.style.transform = "translateY(0)";
    grid.innerHTML = `<div class="ct-gallery-empty">${state.imageLoading ? "Loading public images." : "No stored public images match these filters. Run Sync Images to populate the gallery."}</div>`;
    $("#imageGalleryHelp").textContent = state.imageLoading ? "Loading stored images." : "Sync images to populate the local gallery.";
    return;
  }

  const startRow = Math.max(0, Math.floor(scroller.scrollTop / rowHeight) - overscanRows);
  const visibleRows = Math.ceil(scroller.clientHeight / rowHeight) + overscanRows * 2;
  const startIndex = startRow * columns;
  const endIndex = Math.min(state.images.length, (startRow + visibleRows) * columns);
  const visible = state.images.slice(startIndex, endIndex);
  grid.style.transform = `translateY(${startRow * rowHeight}px)`;
  grid.innerHTML = visible.map(imageCard).join("");
  $("#imageGalleryHelp").textContent = `${fmt(state.images.length)} of ${fmt(state.imageTotal)} stored image${state.imageTotal === 1 ? "" : "s"} loaded.${state.imageHasMore ? " Scroll near the bottom to load more." : ""}`;
}

function requestImageRender() {
  if (state.imageVirtual.frame) return;
  state.imageVirtual.frame = requestAnimationFrame(() => {
    state.imageVirtual.frame = null;
    renderImageGallery();
    maybeLoadMoreImages();
  });
}

function maybeLoadMoreImages() {
  const scroller = $("#imageScroller");
  if (!scroller || state.imageLoading || !state.imageHasMore) return;
  if (scroller.scrollTop + scroller.clientHeight > scroller.scrollHeight - state.imageVirtual.rowHeight * 3) {
    loadImages(false);
  }
}

function imageIndexById(imageId) {
  const id = Number(imageId);
  return state.images.findIndex((row) => Number(row.image_id) === id);
}

function scrollImageCardIntoView(imageId) {
  const scroller = $("#imageScroller");
  if (!scroller) return;
  const index = imageIndexById(imageId);
  if (index < 0) return;
  updateImageVirtualMetrics();
  const row = Math.floor(index / state.imageVirtual.columns);
  const top = row * state.imageVirtual.rowHeight;
  const bottom = top + state.imageVirtual.rowHeight;
  if (top < scroller.scrollTop || bottom > scroller.scrollTop + scroller.clientHeight) {
    scroller.scrollTo({
      top: Math.max(0, top - state.imageVirtual.rowHeight),
      behavior: "smooth",
    });
    requestImageRender();
  }
}

function imageModalVisible() {
  return $("#imageModal")?.classList.contains("show");
}

function isTextEntryTarget(target) {
  const tag = target?.tagName?.toLowerCase();
  return target?.isContentEditable || ["input", "textarea", "select"].includes(tag);
}

async function navigateImageDetail(direction) {
  if (state.imageDetailLoading || !state.images.length) return;
  const currentIndex = imageIndexById(state.currentImageId);
  if (currentIndex < 0) return;
  let nextIndex = currentIndex + direction;
  if (nextIndex < 0) return;
  if (nextIndex >= state.images.length) {
    if (direction <= 0 || !state.imageHasMore) return;
    await loadImages(false);
    nextIndex = currentIndex + direction;
  }
  const next = state.images[nextIndex];
  if (next) await showImageDetail(next.image_id);
}

function handleImageModalKeydown(event) {
  if (!imageModalVisible() || isTextEntryTarget(event.target) || event.altKey || event.ctrlKey || event.metaKey) return;
  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
  event.preventDefault();
  navigateImageDetail(event.key === "ArrowRight" ? 1 : -1);
}

async function runImageSync(event) {
  const buttons = $$(".js-image-sync");
  buttons.forEach((button) => busy(button, true, "Syncing images..."));
  try {
    const result = await api("/api/images/sync", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        pages_per_version: 1,
        with_meta: false,
        model_id: $("#imageModelFilter").value || null,
        model_version_id: $("#imageVersionFilter").value || null,
        max_versions: 12,
      }),
    });
    await Promise.all([loadImageStatus(), loadLogs()]);
    await loadImages(true);
    setView("images");
    toast(`Image sync saved. ${fmt(result.image_count)} linked public image${result.image_count === 1 ? "" : "s"} checked, ${fmt(result.new_image_count)} new.${result.warnings.length ? " Some versions were unavailable." : ""}`, result.warnings.length ? "warning" : "info");
  } catch (error) {
    toast(error.message, "error");
    await Promise.all([loadImageStatus().catch(() => {}), loadLogs()]);
  } finally {
    buttons.forEach((button) => busy(button, false));
  }
}

function articleRatingLabel(value) {
  const text = String(value || "").trim().toUpperCase();
  return text || "PG";
}

function articleQueryString() {
  const params = new URLSearchParams({
    limit: "500",
    offset: "0",
    sort: $("#articleSort").value,
  });
  const search = $("#articleSearch").value.trim();
  if (search) params.set("search", search);
  state.articleRatingFilters.forEach((rating) => params.append("rating", rating));
  return params.toString();
}

function articleMetricCell(row, key) {
  const delta = row[`${key}_delta`];
  const deltaMarkup = delta === null || delta === undefined
    ? `<small class="ct-article-delta">New baseline</small>`
    : `<small class="ct-article-delta ${deltaClass(delta)}">${signed(delta)} since sync</small>`;
  return `<span class="ct-article-metric">${fmt(row[key])}</span>${deltaMarkup}`;
}

function articleReactionBreakdown(row) {
  const parts = [
    ["bi-hand-thumbs-up-fill", "Like", row.like_count, row.like_count_delta],
    ["bi-heart-fill", "Heart", row.heart_count, row.heart_count_delta],
    ["bi-emoji-laughing-fill", "Laugh", row.laugh_count, row.laugh_count_delta],
    ["bi-cloud-rain-fill", "Cry", row.cry_count, row.cry_count_delta],
    ["bi-hand-thumbs-down-fill", "Dislike", row.dislike_count, row.dislike_count_delta],
  ];
  return `<div class="ct-reaction-breakdown">${parts.map(([icon, label, value, delta]) => `
    <span title="${esc(label)}${delta === null || delta === undefined ? "" : ` ${signed(delta)} since previous sync`}"><i class="bi ${icon}"></i>${fmt(value)}</span>
  `).join("")}</div>`;
}

function renderArticleSummary() {
  const totals = state.articleStatus?.totals || {};
  const latest = state.articleStatus?.latest_sync;
  $("#articleSyncHelp").textContent = latest
    ? `Last article sync ${dateFmt(latest.checked_at)}. ${fmt(latest.new_article_count)} new article${latest.new_article_count === 1 ? "" : "s"} found.`
    : "Sync articles to populate local progress.";
  $("#articleMetricsGrid").innerHTML = [
    ["Articles", totals.article_count || 0, "Creator articles stored locally"],
    ["Views", totals.total_view_count || 0, "All stored article views"],
    ["Collections", totals.total_collected_count || 0, "Article collection adds"],
    ["Reactions", totals.total_reaction_count || 0, "Like, heart, laugh, cry, dislike"],
    ["Comments", totals.total_comment_count || 0, "Stored CivitAI comment count"],
    ["Tipped Buzz", totals.total_tipped_amount_count || 0, "Total tips reported by CivitAI"],
    ["Newest article", totals.newest_article_at ? dateOnlyFmt(totals.newest_article_at) : "N/A", "Latest published timestamp"],
  ].map(([label, value, help]) => `<article class="ct-card ct-metric"><span class="ct-metric-label">${esc(label)}</span><strong class="ct-metric-value">${esc(value)}</strong><span class="ct-metric-delta">${esc(help)}</span></article>`).join("");
}

function renderArticles() {
  $("#articleTableHelp").textContent = state.articleLoading
    ? "Loading stored article progress."
    : `${fmt(state.articles.length)} of ${fmt(state.articleTotal)} article${state.articleTotal === 1 ? "" : "s"} shown. Deltas compare against the previous article sync.`;
  $("#articleRows").innerHTML = state.articles.length ? state.articles.map((row) => `
    <tr>
      <td>${esc(dateFmt(row.published_at || row.first_seen_at))}</td>
      <td>
        <strong>${esc(row.title)}</strong>
        <small class="ct-article-tags">${(row.tags || []).slice(0, 4).map((tag) => esc(tag)).join(", ") || esc(row.status || "Published")}</small>
      </td>
      <td><span class="ct-status">${esc(articleRatingLabel(row.rating_label))}</span></td>
      <td>${articleMetricCell(row, "view_count")}</td>
      <td>${articleMetricCell(row, "collected_count")}</td>
      <td>${articleMetricCell(row, "reaction_count")}</td>
      <td>${articleReactionBreakdown(row)}</td>
      <td>${articleMetricCell(row, "comment_count")}</td>
      <td>${articleMetricCell(row, "tipped_amount_count")}</td>
      <td><a href="${esc(row.article_url)}" target="_blank" rel="noopener" aria-label="Open ${esc(row.title)} on CivitAI"><i class="bi bi-box-arrow-up-right"></i></a></td>
    </tr>`).join("") : `<tr><td colspan="10" class="ct-table-empty">${state.articleLoading ? "Loading article progress." : "No stored articles match these filters. Run Sync Articles to populate this table."}</td></tr>`;
}

async function loadArticleStatus() {
  state.articleStatus = await api("/api/articles/status");
  renderArticleSummary();
}

async function loadArticles() {
  if (state.articleLoading) return;
  state.articleLoading = true;
  renderArticles();
  try {
    const result = await api(`/api/articles?${articleQueryString()}`);
    state.articles = result.articles;
    state.articleTotal = result.total;
  } catch (error) {
    toast(error.message, "error");
  } finally {
    state.articleLoading = false;
    renderArticles();
  }
}

async function ensureArticlesPanelLoaded() {
  try {
    if (!state.articleStatus) await loadArticleStatus();
    if (!state.articles.length) await loadArticles();
  } catch (error) {
    toast(error.message, "error");
  }
}

async function runArticleSync(event) {
  const buttons = $$(".js-article-sync");
  buttons.forEach((button) => busy(button, true, "Syncing articles..."));
  try {
    const result = await api("/api/articles/sync", { method: "POST" });
    await Promise.all([loadArticleStatus(), loadArticles(), loadLogs()]);
    setView("articles");
    toast(`Article sync saved. ${fmt(result.article_count)} article${result.article_count === 1 ? "" : "s"} checked, ${fmt(result.new_article_count)} new.${result.warnings.length ? " Some records were skipped." : ""}`, result.warnings.length ? "warning" : "info");
  } catch (error) {
    toast(error.message, "error");
    await Promise.all([loadArticleStatus().catch(() => {}), loadLogs()]);
  } finally {
    buttons.forEach((button) => busy(button, false));
  }
}

function rawMetricDelta(row, metric) { return row[`${metric}_delta`]; }
function metricDelta(row, metric) { return Number(rawMetricDelta(row, metric) || 0); }
function changed(row) { return ["download_count", "reaction_count", "collected_count", "generation_count"].some((key) => metricDelta(row, key) !== 0) || row.status !== "normal"; }
function deltaCell(value) { return value === null || value === undefined ? `<span class="ct-delta">N/A</span>` : `<span class="ct-delta ${deltaClass(value)}">${signed(value)}</span>`; }
function metricDeltaCell(row, metric) { return deltaCell(rawMetricDelta(row, metric)); }

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
      <td title="Last stored check with a download increase. Original date used for sort: ${esc(dateFmt(row.published_at))}">${esc(row.last_download_observed_at ? dateFmt(row.last_download_observed_at) : "Unknown")}</td>
      <td>${esc(row.model_type || "-")}</td>
      <td>${esc(row.base_model || "-")}</td>
      <td>${metricDeltaCell(row, "download_count")}</td>
      <td>${metricDeltaCell(row, "reaction_count")}</td>
      <td>${metricDeltaCell(row, "collected_count")}</td>
      <td>${metricDeltaCell(row, "generation_count")}</td>
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
      <td>${esc(row.base_model || "-")}</td><td>${metricDeltaCell(row, "download_count")}</td><td>${metricDeltaCell(row, "generation_count")}</td>
      <td>${row.version_contribution_percent === null ? "N/A" : `<span class="ct-contribution"><span class="ct-share-bar"><span class="ct-share-fill" style="width:${Math.min(100, Math.max(0, row.version_contribution_percent)).toFixed(1)}%"></span></span><strong>${fmt(row.version_contribution_percent)}%</strong></span>`}</td>
      <td><span class="ct-status">${esc(row.status.replaceAll("_", " "))}</span></td>
    </tr>`).join("") : `<tr><td colspan="8" class="ct-table-empty">No version data in this comparison.</td></tr>`;
  $("#showAllVersions").classList.toggle("d-none", allRows.length <= 20 || state.showAllVersions);
}

function renderInsight() {
  const comparison = state.currentComparison;
  $("#insightStrip").classList.toggle("d-none", !comparison);
  if (!comparison) return;
  const delta = comparison.summary.total_generation_count_delta ?? comparison.summary.total_download_count_delta;
  const movers = comparison.models.filter(changed);
  const metric = comparison.summary.total_generation_count_delta === null || comparison.summary.total_generation_count_delta === undefined ? "download_count" : "generation_count";
  const label = metric === "generation_count" ? "generations" : "downloads";
  const top = [...comparison.models].sort((a, b) => metricDelta(b, metric) - metricDelta(a, metric))[0];
  const context = [comparison.from_context, comparison.to_context]
    .filter((item) => item && (item.note || (item.note_type && item.note_type !== "normal_check")))
    .map((item) => `${noteTypeLabel(item.note_type)}${item.note ? `: ${item.note}` : ""}`);
  const growth = delta === 0 && !movers.length ? "No growth detected in this range." : `${label[0].toUpperCase()}${label.slice(1)} changed by ${signedOptional(delta)} across ${movers.length} model${movers.length === 1 ? "" : "s"}.${top && metricDelta(top, metric) > 0 ? ` Top mover: ${top.model_name} gained ${signed(metricDelta(top, metric))} ${label}.` : ""}`;
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
    ["Most generations gained", "generation_count", bestMover(models, "generation_count")],
    ["Most collections gained", "collected_count", bestMover(models, "collected_count")],
    ["Most reactions gained", "reaction_count", bestMover(models, "reaction_count")],
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
  const requests = {
    status: api("/api/status"),
    settings: api("/api/settings"),
    snapshots: api("/api/snapshots"),
    breakdown: api("/api/latest-breakdown"),
    logs: api("/api/logs"),
    alerts: api("/api/alerts"),
    alertSettings: api("/api/alert-settings"),
    articleStatus: api("/api/articles/status"),
    buzzStatus: api("/api/buzz/status"),
    buzzSettings: api("/api/buzz-settings"),
    buzzTransactions: api("/api/buzz/transactions"),
  };
  const names = Object.keys(requests);
  const results = await Promise.allSettled(Object.values(requests));
  const data = {};
  const failures = [];
  results.forEach((result, index) => {
    const name = names[index];
    if (result.status === "fulfilled") {
      data[name] = result.value;
    } else {
      failures.push(result.reason?.message || `${name} failed to load.`);
    }
  });

  if (data.status) {
    state.status = data.status;
    renderStatus();
  }
  if (data.settings) {
    state.settings = data.settings;
    renderSettings();
  }
  if (data.snapshots) {
    state.snapshots = data.snapshots.snapshots || [];
    renderSnapshots();
  }
  if (data.breakdown) {
    state.latestBreakdown = data.breakdown;
    renderBreakdown();
  }
  renderMetrics();
  if (data.logs) renderLogs(data.logs.logs || []);
  if (data.alerts) {
    state.alerts = data.alerts.alerts || [];
    state.unreadAlertCount = data.alerts.unread_count || 0;
    renderAlerts();
  }
  if (data.alertSettings) {
    state.alertSettings = data.alertSettings;
    renderAlertSettings();
  }
  if (data.articleStatus) {
    state.articleStatus = data.articleStatus;
    renderArticleSummary();
  }
  if (data.buzzStatus) state.buzzStatus = data.buzzStatus;
  if (data.buzzSettings) {
    state.buzzSettings = data.buzzSettings;
    renderBuzzSettings();
  }
  if (data.buzzTransactions) state.buzzTransactions = data.buzzTransactions.transactions || [];
  if (data.buzzStatus || data.buzzTransactions) renderBuzz();
  if (failures.length) toast(`Some panels did not load: ${failures.join(" ")}`, "warning");
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
    buzz_unavailable: "Buzz tracking unavailable",
    buzz_tip: "Buzz tip received",
    buzz_large_gain: "Large Buzz gain",
    buzz_large_spend: "Large Buzz spend",
  };
  $("#alertToggleGrid").innerHTML = Object.entries(labels).map(([key, label]) => `
    <label class="ct-toggle-row"><span>${esc(label)}</span><input type="checkbox" data-alert-toggle="${key}" ${settings.enabled[key] ? "checked" : ""}></label>`).join("");
  $("#alertMilestones").value = settings.download_milestones.join(",");
  $("#alertMinimumDownloads").value = settings.minimum_download_gain_alert;
  $("#alertMinimumCollections").value = settings.minimum_collection_gain_alert;
  $("#alertVelocityMultiplier").value = settings.velocity_spike_multiplier;
  $("#alertVelocityCurrent").value = settings.velocity_minimum_current_delta;
  $("#alertVelocityPrevious").value = settings.velocity_minimum_previous_delta;
  $("#alertBuzzLargeGain").value = settings.buzz_large_gain_threshold;
  $("#alertBuzzLargeSpend").value = settings.buzz_large_spend_threshold;
}

function openSnapshotModal() {
  $("#snapshotNote").value = "";
  $("#snapshotNoteType").value = "normal_check";
  $("#snapshotProgress").classList.add("d-none");
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
  $("#snapshotProgress").classList.remove("d-none");
  busy(button, true, "Fetching stats & generations...");
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
  finally { busy(button, false); $("#snapshotProgress").classList.add("d-none"); }
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
        buzz_large_gain_threshold: $("#alertBuzzLargeGain").value,
        buzz_large_spend_threshold: $("#alertBuzzLargeSpend").value,
      }),
    });
    state.alertSettings = result.settings;
    renderAlertSettings();
    toast("Alert preferences saved.");
  } catch (error) { toast(error.message, "error"); }
  finally { busy(button, false); }
}

async function runBuzzCheck(event) {
  const buttons = $$(".js-buzz-check");
  buttons.forEach((button) => busy(button, true, "Checking Buzz..."));
  try {
    const result = await api("/api/buzz/check", { method: "POST" });
    await refresh();
    setView("buzz");
    toast(`Buzz check saved. ${fmt(result.new_transaction_count)} new transaction${result.new_transaction_count === 1 ? "" : "s"} found.${result.warnings.length ? " Some data was unavailable." : ""}`, result.warnings.length ? "warning" : "info");
  } catch (error) {
    toast(error.message, "error");
    await Promise.all([loadBuzz(), loadLogs(), loadAlerts()]);
  } finally {
    buttons.forEach((button) => busy(button, false));
  }
}

async function saveBuzzSettings(event) {
  event.preventDefault();
  const button = $("#saveBuzzSettings");
  busy(button, true, "Saving...");
  try {
    const result = await api("/api/buzz-settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        enabled: $("#buzzTrackingEnabled").checked,
        account_types: {
          Blue: $("#buzzTrackBlue").checked,
          Yellow: $("#buzzTrackYellow").checked,
          Green: $("#buzzTrackGreen").checked,
        },
        transaction_limit: $("#buzzTransactionLimit").value,
      }),
    });
    state.buzzSettings = result.settings;
    await loadBuzz();
    renderBuzzSettings();
    toast("Buzz settings saved.");
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

async function loadBuzz() {
  const [status, transactions] = await Promise.all([api("/api/buzz/status"), api("/api/buzz/transactions")]);
  state.buzzStatus = status;
  state.buzzTransactions = transactions.transactions;
  renderBuzz();
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
      good: "This snapshot looks complete. CivitTrack loaded the available model stats, generation metrics, and extra collection/minor-model data without warnings.",
      partial: "This snapshot was saved successfully, but some extra CivitAI data was unavailable. Downloads and reactions are still usable, but collections, generations, or minor-model coverage may be incomplete.",
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
      ["Generation metrics", esc(quality.generation_metric_status || "Unavailable")],
      ["Generation metrics loaded", fmt(quality.generation_metric_count)],
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
      <p class="ct-history-summary"><strong>${signed(latest.download_count - first.download_count)}</strong> downloads${latest.generation_count !== null && first.generation_count !== null ? `, <strong>${signed(latest.generation_count - first.generation_count)}</strong> generations` : ""} across ${rows.length} stored snapshot${rows.length === 1 ? "" : "s"}.</p>
      <a class="btn ct-btn-secondary mb-3" href="${esc(latest.page_url)}" target="_blank" rel="noopener">Open on CivitAI <i class="bi bi-box-arrow-up-right"></i></a>
      <div class="table-responsive"><table class="table ct-table"><thead><tr><th>Checked at</th><th>Downloads</th><th>Reactions</th><th>Collections</th><th>Generations</th><th>Comments</th></tr></thead>
      <tbody>${rows.map((row) => `<tr><td>${esc(dateFmt(row.checked_at))}</td><td>${fmt(row.download_count)}</td><td>${fmt(row.reaction_count)}</td><td>${fmt(row.collected_count)}</td><td>${fmt(row.generation_count)}</td><td>${fmt(row.comment_count)}</td></tr>`).join("")}</tbody></table></div>`;
    bootstrap.Offcanvas.getOrCreateInstance($("#historyDrawer")).show();
  } catch (error) { toast(error.message, "error"); }
}

async function showBuzzDetail(transactionId) {
  try {
    const detail = await api(`/api/buzz/transaction-detail?id=${encodeURIComponent(transactionId)}`);
    const raw = JSON.stringify(detail.raw_json || {}, null, 2);
    let source = detail.model_id ? `
      ${detail.related_model?.cover_image_url ? `<img class="ct-history-cover" src="${esc(detail.related_model.cover_image_url)}" alt="${esc(detail.model_name || "Model")} cover image" loading="lazy" referrerpolicy="no-referrer" onerror="this.hidden=true">` : ""}
      <div class="ct-quality-detail">
        <div><span>Model</span><strong>${esc(detail.model_name || `Model #${detail.model_id}`)}</strong></div>
        <div><span>Model ID</span><strong>${fmt(detail.model_id)}</strong></div>
        <div><span>Latest version</span><strong>${esc(detail.related_model?.latest_version_name || "Unavailable")}</strong></div>
      </div>
      ${detail.model_url ? `<a class="btn ct-btn-secondary mb-3" href="${esc(detail.model_url)}" target="_blank" rel="noopener">Open model on CivitAI <i class="bi bi-box-arrow-up-right"></i></a>` : ""}`
      : detail.image_id ? `
      ${detail.image_url ? `<img class="ct-history-cover" src="${esc(detail.image_url)}" alt="Remote CivitAI image preview" loading="lazy" referrerpolicy="no-referrer" onerror="this.hidden=true">` : ""}
      <div class="ct-quality-detail">
        <div><span>Image ID</span><strong>${fmt(detail.image_id)}</strong></div>
        <div><span>Post ID</span><strong>${fmt(detail.post_id)}</strong></div>
      </div>
      ${detail.image_page_url || detail.image_url ? `<a class="btn ct-btn-secondary mb-3" href="${esc(detail.image_page_url || detail.image_url)}" target="_blank" rel="noopener">Open image on CivitAI <i class="bi bi-box-arrow-up-right"></i></a>` : ""}`
      : detail.article_id ? `
      <div class="ct-quality-detail">
        <div><span>Article</span><strong>Article #${fmt(detail.article_id)}</strong></div>
      </div>
      ${detail.article_url ? `<a class="btn ct-btn-secondary mb-3" href="${esc(detail.article_url)}" target="_blank" rel="noopener">Open article on CivitAI <i class="bi bi-box-arrow-up-right"></i></a>` : ""}`
      : detail.comment_id ? `
      <div class="ct-quality-detail">
        <div><span>Comment</span><strong>Comment #${fmt(detail.comment_id)}</strong></div>
      </div>
      ${detail.comment_url ? `<a class="btn ct-btn-secondary mb-3" href="${esc(detail.comment_url)}" target="_blank" rel="noopener">Open comment on CivitAI <i class="bi bi-box-arrow-up-right"></i></a>` : `<p class="ct-quality-summary">CivitAI did not include the parent article, model, or image for this comment reaction.</p>`}`
      : `<p class="ct-quality-summary">CivitTrack could not confidently match this Buzz event to a model, image, article, or comment. The raw description is still stored below.</p>`;
    $("#buzzDrawerBody").innerHTML = `
      <div class="ct-quality-grid">
        <div><span>Buzz amount</span><strong class="${deltaClass(detail.amount)}">${signed(detail.amount)}</strong></div>
        <div><span>Account</span><strong>${buzzAccountPill(detail.account_type)}</strong></div>
        <div><span>Date</span><strong>${esc(dateFmt(detail.transaction_date || detail.first_seen_at))}</strong></div>
        <div><span>Event</span><strong>${esc(buzzEventLabel(detail.event_category))}</strong></div>
        <div><span>Transaction type</span><strong>${esc(detail.transaction_type || "Unknown")}</strong></div>
        <div><span>Match confidence</span><strong>${esc(qualityLabel(detail.match_confidence))}</strong></div>
      </div>
      <p class="ct-quality-summary">${esc(detail.description || detail.title || "Unmatched Buzz event.")}</p>
      ${source}
      ${detail.username ? `<p class="ct-quality-summary"><strong>User:</strong> ${esc(detail.username)}</p>` : ""}
      <details class="ct-advanced"><summary>Raw sanitized details</summary><button id="copyBuzzRaw" class="btn ct-btn-quiet my-3" type="button"><i class="bi bi-copy"></i> Copy raw JSON</button><pre class="ct-raw-json">${esc(raw)}</pre></details>`;
    $("#copyBuzzRaw").addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(raw); toast("Raw Buzz JSON copied."); }
      catch (_) { toast("Could not copy raw JSON from this browser.", "warning"); }
    });
    bootstrap.Offcanvas.getOrCreateInstance($("#buzzDrawer")).show();
  } catch (error) { toast(error.message, "error"); }
}

async function showImageDetail(imageId) {
  if (state.imageDetailLoading) return;
  state.imageDetailLoading = true;
  state.currentImageId = Number(imageId);
  try {
    const detail = await api(`/api/images/detail?image_id=${encodeURIComponent(imageId)}`);
    state.currentImageId = Number(detail.image_id);
    state.images = state.images.map((row) => row.image_id === detail.image_id ? { ...row, ...detail } : row);
    renderImageGallery();
    scrollImageCardIntoView(detail.image_id);
    renderImageDetailModal(detail);
    bootstrap.Modal.getOrCreateInstance($("#imageModal")).show();
  } catch (error) { toast(error.message, "error"); }
  finally {
    state.imageDetailLoading = false;
  }
}

function imageCommentList(detail) {
  if (detail.comments_error) {
    return `<div class="ct-image-comment-empty">${esc(detail.comments_error)}</div>`;
  }
  const comments = detail.comments || [];
  if (!comments.length) {
    return `<div class="ct-image-comment-empty">No comments are stored on CivitAI for this image yet.</div>`;
  }
  return comments.map((comment) => {
    const counts = comment.reaction_counts || {};
    const active = comment.local_reactions || [];
    return `
    <article class="ct-image-comment" data-comment-id="${comment.id}" data-thread-id="${comment.threadId}">
      <div class="ct-image-comment-head">
        <strong>${esc(comment.user?.username || "CivitAI user")}</strong>
        <span>${esc(dateFmt(comment.createdAt || comment.created_at))}</span>
      </div>
      <p>${esc(htmlText(comment.content))}</p>
      <div class="ct-comment-reaction-bar">
        ${commentReactionSpecs.map(([reaction, icon]) => {
          const pressed = active.includes(reaction);
          return `<button class="ct-comment-reaction ${pressed ? "active" : ""}" type="button" data-comment-reaction="${reaction}" aria-pressed="${String(pressed)}">
            <i class="bi ${icon}"></i><span>${esc(reaction)}</span><strong>${fmt(counts[reaction] || 0)}</strong>
          </button>`;
        }).join("")}
      </div>
      <details class="ct-comment-reply">
        <summary>Reply</summary>
        <form class="ct-comment-reply-form" data-image-id="${detail.image_id}" data-comment-id="${comment.id}" data-parent-thread-id="${comment.threadId}">
          <textarea class="form-control" rows="2" maxlength="8000" placeholder="Write a reply on CivitAI"></textarea>
          <button class="btn ct-btn-secondary" type="submit"><i class="bi bi-reply"></i> Send Reply</button>
        </form>
      </details>
    </article>`;
  }).join("");
}

function renderImageDetailModal(detail) {
    const raw = JSON.stringify(detail.raw_json || {}, null, 2);
    const reactions = imageReactionCount(detail);
    const preview = cachedImageUrl(detail.image_id);
    const imageIndex = imageIndexById(detail.image_id);
    const hasPrevious = imageIndex > 0;
    const hasNext = imageIndex >= 0 && (imageIndex < state.images.length - 1 || state.imageHasMore);
    $("#imageModalTitle").textContent = `Image #${detail.image_id}`;
    $("#imageModalBody").innerHTML = `
      <div class="ct-image-modal-layout">
        <div class="ct-image-modal-visual">
          <div class="ct-image-modal-media">
            <button class="ct-image-nav ct-image-nav-prev" type="button" data-image-nav="-1" aria-label="Previous image" title="Previous image" ${hasPrevious ? "" : "disabled"}><i class="bi bi-chevron-left"></i></button>
            ${detail.image_url ? `<img src="${esc(preview)}" data-fallback="${esc(detail.image_url)}" alt="${esc(detail.model_name)} public image" loading="lazy" referrerpolicy="no-referrer" onerror="if(this.dataset.fallback&&this.src!==this.dataset.fallback){this.src=this.dataset.fallback;this.removeAttribute('data-fallback')}else{this.hidden=true}">` : ""}
            <button class="ct-image-nav ct-image-nav-next" type="button" data-image-nav="1" aria-label="Next image" title="Next image" ${hasNext ? "" : "disabled"}><i class="bi bi-chevron-right"></i></button>
          </div>
          <div class="ct-image-reaction-bar" data-image-id="${detail.image_id}">
            ${imageReactionSpecs.map(([reaction, icon, countKey]) => {
              const active = (detail.local_reactions || []).includes(reaction);
              return `<button class="ct-image-reaction ${active ? "active" : ""}" type="button" data-image-reaction="${reaction}" aria-pressed="${String(active)}">
                <i class="bi ${icon}"></i><span>${esc(reaction)}</span><strong>${fmt(detail[countKey])}</strong>
              </button>`;
            }).join("")}
          </div>
        </div>
        <aside class="ct-image-modal-details">
          <div class="ct-image-modal-title">
            <strong>${esc(detail.model_name)}</strong>
            <span>${esc(detail.version_name || `Version ${detail.model_version_id}`)}</span>
          </div>
          <div class="ct-quality-detail">
            <div><span>Image ID</span><strong>${fmt(detail.image_id)}</strong></div>
            <div><span>Post ID</span><strong>${fmt(detail.post_id)}</strong></div>
            <div><span>Creator</span><strong>${esc(detail.username || "Unknown")}</strong></div>
            <div><span>Published</span><strong>${esc(dateFmt(detail.published_at || detail.first_seen_at))}</strong></div>
            <div><span>Size</span><strong>${detail.width && detail.height ? `${fmt(detail.width)} x ${fmt(detail.height)}` : "Unknown"}</strong></div>
            <div><span>Rating</span><strong>${esc(imageRatingLabel(detail.nsfw_level, detail.nsfw))}</strong></div>
            <div><span>CivitAI reactions</span><strong>${fmt(reactions)}</strong></div>
            <div><span>Comments</span><strong>${fmt(detail.comment_count)}</strong></div>
          </div>
          <div class="ct-row-actions mb-3">
            ${detail.image_page_url ? `<a class="btn ct-btn-secondary" href="${esc(detail.image_page_url)}" target="_blank" rel="noopener">Open image <i class="bi bi-box-arrow-up-right"></i></a>` : ""}
            ${detail.model_page_url ? `<a class="btn ct-btn-secondary" href="${esc(detail.model_page_url)}" target="_blank" rel="noopener">Open model <i class="bi bi-box-arrow-up-right"></i></a>` : ""}
          </div>
          <section class="ct-image-comments">
            <div class="ct-image-comments-title"><h3>Comments</h3><span>${fmt(detail.comment_count)}</span></div>
            <div class="ct-image-comment-list">${imageCommentList(detail)}</div>
            <form id="imageCommentForm" class="ct-image-comment-form" data-image-id="${detail.image_id}">
              <textarea id="imageCommentText" class="form-control" rows="3" maxlength="8000" placeholder="Write a comment on CivitAI"></textarea>
              <button id="submitImageComment" class="btn ct-btn-primary" type="submit"><i class="bi bi-send"></i> Send Comment</button>
            </form>
          </section>
          <details class="ct-advanced"><summary>Raw stored image JSON</summary><button id="copyImageRaw" class="btn ct-btn-quiet my-3" type="button"><i class="bi bi-copy"></i> Copy raw JSON</button><pre class="ct-raw-json">${esc(raw)}</pre></details>
        </aside>
      </div>`;
    $("#copyImageRaw").addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(raw); toast("Raw image JSON copied."); }
      catch (_) { toast("Could not copy raw JSON from this browser.", "warning"); }
    });
    $$("#imageModalBody [data-image-reaction]").forEach((button) => button.addEventListener("click", toggleImageReaction));
    $$("#imageModalBody [data-image-nav]").forEach((button) => button.addEventListener("click", () => navigateImageDetail(Number(button.dataset.imageNav))));
    $$("#imageModalBody [data-comment-reaction]").forEach((button) => button.addEventListener("click", toggleCommentReaction));
    $$("#imageModalBody .ct-comment-reply-form").forEach((form) => form.addEventListener("submit", submitCommentReply));
    $("#imageCommentForm").addEventListener("submit", submitImageComment);
}

async function toggleImageReaction(event) {
  const button = event.currentTarget;
  const imageId = button.closest("[data-image-id]")?.dataset.imageId;
  const reaction = button.dataset.imageReaction;
  if (!imageId || !reaction) return;
  if (!await confirmReactionBonusLimit(button.classList.contains("active"))) return;
  $$("#imageModalBody [data-image-reaction]").forEach((item) => item.disabled = true);
  try {
    const result = await api("/api/images/reaction", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image_id: Number(imageId), reaction }),
    });
    updateReactionUsage(result);
    state.images = state.images.map((row) => row.image_id === result.image.image_id ? { ...row, ...result.image } : row);
    renderImageGallery();
    renderImageDetailModal(result.image);
    toast(`${result.is_active ? "Added" : "Removed"} ${reaction.toLowerCase()} reaction.`);
  } catch (error) {
    toast(error.message, "error");
    $$("#imageModalBody [data-image-reaction]").forEach((item) => item.disabled = false);
  }
}

async function submitImageComment(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const imageId = form.dataset.imageId;
  const content = $("#imageCommentText").value.trim();
  if (!imageId || !content) {
    toast("Write a comment before sending.", "warning");
    return;
  }
  const button = $("#submitImageComment");
  busy(button, true, "Sending...");
  try {
    const result = await api("/api/images/comment", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image_id: Number(imageId), content }),
    });
    state.images = state.images.map((row) => row.image_id === result.image.image_id ? { ...row, ...result.image } : row);
    renderImageGallery();
    renderImageDetailModal(result.image);
    toast("Comment sent to CivitAI.");
  } catch (error) {
    toast(error.message, "error");
  } finally {
    busy(button, false);
  }
}

async function submitCommentReply(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const textarea = form.querySelector("textarea");
  const content = textarea.value.trim();
  if (!content) {
    toast("Write a reply before sending.", "warning");
    return;
  }
  const button = form.querySelector("button[type='submit']");
  busy(button, true, "Sending...");
  try {
    const result = await api("/api/images/comment-reply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        image_id: Number(form.dataset.imageId),
        comment_id: Number(form.dataset.commentId),
        parent_thread_id: Number(form.dataset.parentThreadId),
        content,
      }),
    });
    state.images = state.images.map((row) => row.image_id === result.image.image_id ? { ...row, ...result.image } : row);
    renderImageGallery();
    renderImageDetailModal(result.image);
    toast("Reply sent to CivitAI.");
  } catch (error) {
    toast(error.message, "error");
  } finally {
    busy(button, false);
  }
}

async function toggleCommentReaction(event) {
  const button = event.currentTarget;
  const comment = button.closest("[data-comment-id]");
  const reaction = button.dataset.commentReaction;
  const imageId = $("#imageCommentForm")?.dataset.imageId;
  if (!comment || !reaction || !imageId) return;
  if (!await confirmReactionBonusLimit(button.classList.contains("active"))) return;
  const buttons = $$(`[data-comment-id="${comment.dataset.commentId}"] [data-comment-reaction]`);
  buttons.forEach((item) => item.disabled = true);
  try {
    const result = await api("/api/images/comment-reaction", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        image_id: Number(imageId),
        comment_id: Number(comment.dataset.commentId),
        reaction,
      }),
    });
    updateReactionUsage(result);
    state.images = state.images.map((row) => row.image_id === result.image.image_id ? { ...row, ...result.image } : row);
    renderImageGallery();
    renderImageDetailModal(result.image);
    toast(`${result.is_active ? "Added" : "Removed"} ${reaction.toLowerCase()} reaction on comment.`);
  } catch (error) {
    toast(error.message, "error");
    buttons.forEach((item) => item.disabled = false);
  }
}

async function clearImageCache(event) {
  if (!confirm("Clear local thumbnail cache files? This does not delete CivitAI images or local SQLite data.")) return;
  const button = event.currentTarget;
  busy(button, true, "Clearing...");
  try {
    const result = await api("/api/images/cache", { method: "DELETE" });
    await loadImageStatus();
    $("#imageCacheClearHelp").textContent = `Removed ${fmt(result.removed_files)} file${result.removed_files === 1 ? "" : "s"} (${byteFmt(result.bytes_removed)}).`;
    toast("Thumbnail cache cleared.");
  } catch (error) {
    toast(error.message, "error");
  } finally {
    busy(button, false);
  }
}

$$(".js-snapshot").forEach((button) => button.addEventListener("click", openSnapshotModal));
$$(".js-compare-latest").forEach((button) => button.addEventListener("click", (event) => compare("/api/compare-latest", event.currentTarget)));
$$(".js-compare-range").forEach((button) => button.addEventListener("click", compareRange));
$$(".ct-side-tab").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
$("#snapshotForm").addEventListener("submit", takeSnapshot);
$("#settingsForm").addEventListener("submit", saveSettings);
$("#alertSettingsForm").addEventListener("submit", saveAlertSettings);
$("#buzzSettingsForm").addEventListener("submit", saveBuzzSettings);
$("#restoreForm").addEventListener("submit", restoreDatabase);
$("#clearImageCache").addEventListener("click", clearImageCache);
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
$("#buzzSearch").addEventListener("input", renderBuzzTransactions);
$$(".js-buzz-check").forEach((button) => button.addEventListener("click", runBuzzCheck));
$$(".js-image-sync").forEach((button) => button.addEventListener("click", runImageSync));
$$(".js-article-sync").forEach((button) => button.addEventListener("click", runArticleSync));
$("#articleRefresh").addEventListener("click", async (event) => {
  busy(event.currentTarget, true, "Refreshing...");
  try {
    await loadArticleStatus();
    await loadArticles();
  } finally {
    busy(event.currentTarget, false);
  }
});
$("#articleSearch").addEventListener("input", () => {
  clearTimeout(state.articleSearchTimer);
  state.articleSearchTimer = setTimeout(loadArticles, 220);
});
$("#articleSort").addEventListener("change", loadArticles);
$("#articleRatingFilters").addEventListener("click", (event) => {
  const button = event.target.closest("[data-rating]");
  const value = button?.dataset.rating;
  if (!value) return;
  toggleChipValue("articleRatingFilters", "#articleRatingFilters", "rating", value);
  loadArticles();
});
$("#imageRefresh").addEventListener("click", async (event) => {
  busy(event.currentTarget, true, "Refreshing...");
  try {
    await loadImageStatus();
    await loadImages(true);
  } finally {
    busy(event.currentTarget, false);
  }
});
$("#imageSearch").addEventListener("input", () => {
  clearTimeout(state.imageSearchTimer);
  state.imageSearchTimer = setTimeout(resetImageGallery, 220);
});
$("#imageModelOptionSearch").addEventListener("input", renderImageFilters);
["#imageModelFilter", "#imageVersionFilter", "#imageSort"].forEach((selector) => $(selector).addEventListener("change", () => {
  if (selector === "#imageModelFilter") renderImageFilters();
  resetImageGallery();
}));
$("#imageRatingFilters").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-rating]");
  const value = button?.dataset.rating;
  if (!value) return;
  toggleChipValue("imageRatingFilters", "#imageRatingFilters", "rating", value);
  await loadImageStatus();
  resetImageGallery();
});
$("#imageHideOwn").addEventListener("change", async (event) => {
  state.imageHideOwn = event.target.checked;
  await loadImageStatus();
  resetImageGallery();
});
$("#imageScroller").addEventListener("scroll", requestImageRender, { passive: true });
$("#imageGrid").addEventListener("click", (event) => {
  const card = event.target.closest("[data-image-id]");
  if (card) showImageDetail(card.dataset.imageId);
});
document.addEventListener("keydown", handleImageModalKeydown);
$("#imageModal").addEventListener("hidden.bs.modal", () => {
  state.currentImageId = null;
  state.imageDetailLoading = false;
});
window.addEventListener("resize", () => {
  if (state.currentView !== "images") return;
  updateImageVirtualMetrics();
  requestImageRender();
});
$("#openBuzzSettings").addEventListener("click", () => {
  setView("settings");
  setTimeout(() => $("#buzzSettingsCard").scrollIntoView({ behavior: "smooth", block: "start" }), 80);
});
[
  ["#buzzAccountFilter", "buzzAccountFilter"],
  ["#buzzCategoryFilter", "buzzCategoryFilter"],
  ["#buzzDirectionFilter", "buzzDirectionFilter"],
].forEach(([selector, stateKey]) => $(selector).addEventListener("change", (event) => {
  state[stateKey] = event.target.value;
  renderBuzzTransactions();
}));
$("#clearBuzzFilters").addEventListener("click", () => {
  state.buzzAccountFilter = "all";
  state.buzzCategoryFilter = "all";
  state.buzzDirectionFilter = "all";
  $("#buzzAccountFilter").value = "all";
  $("#buzzCategoryFilter").value = "all";
  $("#buzzDirectionFilter").value = "all";
  renderBuzzTransactions();
});
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
$("#modelFilterSelect").addEventListener("change", (event) => {
  state.currentFilter = event.target.value;
  renderModels();
});
$("#modelSortSelect").addEventListener("change", (event) => {
  state.currentSort = event.target.value;
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
  return ["overview", "models", "images", "articles", "buzz", "snapshots", "alerts", "settings"].includes(hash) ? hash : "overview";
}

window.addEventListener("hashchange", () => setView(viewFromHash(), false));
setView(viewFromHash(), false);
refresh().catch((error) => toast(error.message, "error"));
