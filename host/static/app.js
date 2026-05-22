const KEYS = ["IN", "OUT", "BB", "RB"];
const totals = Object.fromEntries(KEYS.map((k) => [k, 0]));
const sessionCounts = Object.fromEntries(KEYS.map((k) => [k, 0]));
const statusEl = document.getElementById("status");

const sessionPanel = document.getElementById("session-panel");
const registerPanel = document.getElementById("register-panel");
const userStatsPanel = document.getElementById("user-stats");
const historyPanel = document.getElementById("history-panel");
const chartPanel = document.getElementById("session-chart-panel");
const eventLogEl = document.getElementById("event-log");
const bonusOverlay = document.getElementById("bonus-overlay");
const slumpChartPanel = document.getElementById("slump-chart-panel");
const payoutChartPanel = document.getElementById("payout-panel");
const bonusResultEl = document.getElementById("bonus-result");
const historyDetailPanel = document.getElementById("history-detail-panel");
const historyDetailTitle = document.getElementById("history-detail-title");
const gameCountEl = document.getElementById("game-count");
const renchanZoneEl = document.getElementById("renchan-zone");
const renchanRemainingEl = document.getElementById("renchan-remaining");

// 直近ボーナスからこのゲーム数以内の当選が「連チャン」(host/app/game_counter.py と一致).
const RENCHAN_LIMIT = 100;

let activeSessionId = null;
let activeUserId = null;
let chart = null;
let slumpChart = null;
let slumpData = [];
let slumpBaseGames = null;   // セッション開始時点の累計ゲーム数(X 軸の原点)
let currentTotalGames = 0;   // バックエンドの total_games 最新値
let payoutChart = null;
let payoutLabels = [];
let payoutMedals = [];
let payoutBaseGames = null;  // セッション最初の払い出しのゲーム(ラベル原点)
let historySlumpChart = null;
let historyPayoutChart = null;

function renderTotals() {
  for (const k of KEYS) document.getElementById(k).textContent = totals[k];
}

function renderSessionCounts() {
  for (const k of KEYS) {
    const el = document.getElementById(`s-${k}`);
    if (el) el.textContent = sessionCounts[k];
  }
  const diff = sessionCounts.OUT - sessionCounts.IN;
  const diffEl = document.getElementById("s-diff");
  diffEl.textContent = diff > 0 ? `+${diff}` : `${diff}`;
  diffEl.classList.toggle("positive", diff > 0);
  diffEl.classList.toggle("negative", diff < 0);
}

function resetSessionCounts() {
  for (const k of KEYS) sessionCounts[k] = 0;
}

// 現在のゲーム数と連チャンゾーン(直近ボーナスから 100G 以内)を描画.
function renderGameInfo(count, inZone) {
  gameCountEl.textContent = count;
  renchanZoneEl.classList.toggle("hidden", !inZone);
  if (inZone) {
    renchanRemainingEl.textContent = `残り ${Math.max(0, RENCHAN_LIMIT - count)} G`;
  }
}

// --- 差枚スランプグラフ -------------------------------------------------
// X 軸はセッション内の累計ゲーム数(バックエンドの total_games の差分).
function resetSlump() {
  slumpBaseGames = null;
  slumpData = [{ x: 0, y: 0 }];
  renderSlumpChart();
}

function pushSlumpPoint() {
  if (slumpBaseGames === null) slumpBaseGames = currentTotalGames;
  slumpData.push({
    x: currentTotalGames - slumpBaseGames,
    y: sessionCounts.OUT - sessionCounts.IN,
  });
  renderSlumpChart();
}

// スランプグラフの軸範囲を slumpData から決める.
//  - 横軸(ゲーム数): 100 から 100 刻みで、ゲームが進んだら拡張(青天井)
//  - 縦軸(差枚): ±500 から 500 刻みで拡張. ただし下側は -1000 で打ち止め
function slumpBounds(data) {
  let maxX = 0;
  let maxY = 0;
  let minY = 0;
  for (const p of data) {
    if (p.x > maxX) maxX = p.x;
    if (p.y > maxY) maxY = p.y;
    if (p.y < minY) minY = p.y;
  }
  const lower = Math.min(1000, Math.max(500, Math.ceil(-minY / 500) * 500));
  return {
    xMax: Math.max(100, Math.ceil(maxX / 100) * 100),
    yMax: Math.max(500, Math.ceil(maxY / 500) * 500),
    yMin: -lower,
  };
}

function renderSlumpChart() {
  if (typeof Chart === "undefined") return;
  slumpChartPanel.classList.toggle("hidden", slumpData.length <= 1);
  const bounds = slumpBounds(slumpData);
  if (!slumpChart) {
    const ctx = document.getElementById("slump-chart").getContext("2d");
    slumpChart = new Chart(ctx, {
      type: "line",
      data: {
        datasets: [
          {
            label: "差枚",
            data: slumpData,
            borderColor: "#ffca28",
            fill: false,
            pointRadius: 0,
            borderWidth: 2,
            tension: 0,
          },
        ],
      },
      options: {
        animation: false,
        parsing: false,
        plugins: { legend: { display: false } },
        scales: {
          x: {
            type: "linear",
            min: 0,
            max: bounds.xMax,
            title: { display: true, text: "ゲーム数", color: "#aaa" },
            // ゲーム数は整数なので目盛りも整数だけにする(2.5 等を出さない).
            ticks: { color: "#aaa", precision: 0 },
            grid: { color: "#2a2a2a" },
          },
          y: {
            min: bounds.yMin,
            max: bounds.yMax,
            ticks: { color: "#aaa", stepSize: 500 },
            grid: {
              color: (c) => (c.tick.value === 0 ? "#666" : "#2a2a2a"),
            },
          },
        },
      },
    });
  } else {
    slumpChart.data.datasets[0].data = slumpData;
    slumpChart.options.scales.x.max = bounds.xMax;
    slumpChart.options.scales.y.min = bounds.yMin;
    slumpChart.options.scales.y.max = bounds.yMax;
    slumpChart.update("none");
  }
}

// --- 払い出し(1ゲームごとの払い出し枚数とボーナス合計)-----------------
function resetPayout() {
  payoutLabels = [];
  payoutMedals = [];
  payoutBaseGames = null;
  bonusResultEl.textContent = "-";
  renderPayoutChart();
}

function addPayout(payload) {
  if (payoutBaseGames === null) payoutBaseGames = payload.game;
  payoutLabels.push(`${payload.game - payoutBaseGames + 1}G`);
  payoutMedals.push(payload.medals);
  renderPayoutChart();
}

function showBonusResult(payload) {
  bonusResultEl.textContent = `直近ボーナス: ${payload.bonus} ${payload.medals} 枚`;
}

function renderPayoutChart() {
  if (typeof Chart === "undefined") return;
  payoutChartPanel.classList.toggle("hidden", payoutMedals.length === 0);
  if (!payoutChart) {
    const ctx = document.getElementById("payout-chart").getContext("2d");
    payoutChart = new Chart(ctx, {
      type: "bar",
      data: {
        labels: payoutLabels,
        datasets: [
          {
            label: "払い出し",
            data: payoutMedals,
            backgroundColor: "rgba(102,187,106,0.75)",
          },
        ],
      },
      options: {
        animation: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { color: "#aaa" }, grid: { color: "#2a2a2a" } },
          y: {
            beginAtZero: true,
            ticks: { color: "#aaa" },
            grid: { color: "#2a2a2a" },
          },
        },
      },
    });
  } else {
    payoutChart.data.labels = payoutLabels;
    payoutChart.data.datasets[0].data = payoutMedals;
    payoutChart.update("none");
  }
}

function fmtTs(iso) {
  if (!iso) return "-";
  const d = new Date(iso);
  return d.toLocaleString();
}

function appendEventLog({ type, ts, session_id }) {
  const li = document.createElement("li");
  const t = document.createElement("span");
  t.className = "ts";
  t.textContent = new Date(ts).toLocaleTimeString();
  const ty = document.createElement("span");
  ty.className = `type ${type}`;
  ty.textContent = type;
  const sid = document.createElement("span");
  sid.className = "muted small";
  sid.textContent = session_id ? `#${session_id}` : "(no session)";
  li.append(t, ty, sid);
  eventLogEl.prepend(li);
  while (eventLogEl.children.length > 100) {
    eventLogEl.removeChild(eventLogEl.lastChild);
  }
}

async function loadUserHistory(userId) {
  activeUserId = userId;
  const res = await fetch(`/api/users/${userId}/history`);
  if (!res.ok) return;
  const data = await res.json();
  const name = data.user.name || "(未登録)";
  document.getElementById("user-stats-title").textContent = `${name} 累計`;
  for (const k of KEYS) {
    document.getElementById(`u-${k}`).textContent = data.totals[k] ?? 0;
  }
  userStatsPanel.classList.remove("hidden");
  renderHistory(data.sessions);
  renderChart(data.sessions);
}

function renderHistory(sessions) {
  const body = document.getElementById("history-body");
  body.innerHTML = "";
  for (const s of sessions) {
    const tr = document.createElement("tr");
    tr.className = "clickable";
    tr.addEventListener("click", () => loadSessionSeries(s));
    const diff = (s.out_count || 0) - (s.in_count || 0);
    tr.innerHTML = `
      <td>${fmtTs(s.started_at)}</td>
      <td>${fmtTs(s.ended_at)}</td>
      <td>${s.in_count || 0}</td>
      <td>${s.out_count || 0}</td>
      <td>${s.bb_count || 0}</td>
      <td>${s.rb_count || 0}</td>
      <td>${diff > 0 ? "+" + diff : diff}</td>`;
    body.appendChild(tr);
  }
  historyPanel.classList.toggle("hidden", sessions.length === 0);
}

// --- 過去セッションのグラフ再描画(履歴の行クリックで表示)---------------
async function loadSessionSeries(session) {
  const res = await fetch(`/api/sessions/${session.id}/series`);
  if (!res.ok) return;
  const series = await res.json();
  historyDetailTitle.textContent = `セッション詳細  ${fmtTs(session.started_at)}`;
  renderHistorySlump(series.slump || []);
  renderHistoryPayout(series.payout || []);
  historyDetailPanel.classList.remove("hidden");
}

function renderHistorySlump(slump) {
  if (typeof Chart === "undefined") return;
  const b = slumpBounds(slump);
  if (historySlumpChart) historySlumpChart.destroy();
  const ctx = document.getElementById("history-slump-chart").getContext("2d");
  historySlumpChart = new Chart(ctx, {
    type: "line",
    data: {
      datasets: [
        {
          label: "差枚",
          data: slump,
          borderColor: "#ffca28",
          fill: false,
          pointRadius: 0,
          borderWidth: 2,
          tension: 0,
        },
      ],
    },
    options: {
      animation: false,
      parsing: false,
      plugins: { legend: { display: false } },
      scales: {
        x: {
          type: "linear",
          min: 0,
          max: b.xMax,
          title: { display: true, text: "ゲーム数", color: "#aaa" },
          ticks: { color: "#aaa", precision: 0 },
          grid: { color: "#2a2a2a" },
        },
        y: {
          min: b.yMin,
          max: b.yMax,
          ticks: { color: "#aaa", stepSize: 500 },
          grid: { color: (c) => (c.tick.value === 0 ? "#666" : "#2a2a2a") },
        },
      },
    },
  });
}

function renderHistoryPayout(payout) {
  if (typeof Chart === "undefined") return;
  if (historyPayoutChart) historyPayoutChart.destroy();
  const ctx = document.getElementById("history-payout-chart").getContext("2d");
  historyPayoutChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels: payout.map((p) => `${p.game}G`),
      datasets: [
        {
          label: "払い出し",
          data: payout.map((p) => p.medals),
          backgroundColor: "rgba(102,187,106,0.75)",
        },
      ],
    },
    options: {
      animation: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: "#aaa" }, grid: { color: "#2a2a2a" } },
        y: { beginAtZero: true, ticks: { color: "#aaa" }, grid: { color: "#2a2a2a" } },
      },
    },
  });
}

function renderChart(sessions) {
  if (!sessions.length || typeof Chart === "undefined") {
    chartPanel.classList.add("hidden");
    return;
  }
  chartPanel.classList.remove("hidden");
  const sorted = [...sessions].reverse();
  const labels = sorted.map((s) => fmtTs(s.started_at));
  const diffs = sorted.map((s) => (s.out_count || 0) - (s.in_count || 0));
  if (chart) chart.destroy();
  const ctx = document.getElementById("session-chart").getContext("2d");
  chart = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "差枚",
          data: diffs,
          backgroundColor: diffs.map((v) =>
            v >= 0 ? "rgba(76,175,80,0.7)" : "rgba(239,83,80,0.7)"
          ),
        },
      ],
    },
    options: {
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: "#aaa" } },
        y: { ticks: { color: "#aaa" }, grid: { color: "#2a2a2a" } },
      },
    },
  });
}

function showRegisterPanel(payload) {
  registerPanel.classList.remove("hidden");
  const qr = document.getElementById("register-qr");
  qr.src = `/api/qr?token=${encodeURIComponent(payload.token)}`;
  const link = document.getElementById("register-link");
  link.href = payload.register_url || `/register?token=${payload.token}`;
  link.textContent = link.href;
}

function hideRegisterPanel() {
  registerPanel.classList.add("hidden");
}

function handleSessionStart(payload) {
  activeSessionId = payload.session_id;
  resetSessionCounts();
  renderSessionCounts();
  resetSlump();
  resetPayout();
  sessionPanel.classList.remove("hidden");
  const name = payload.user.name || "(未登録カード)";
  document.getElementById("session-user").textContent = name;
  document.getElementById("session-started").textContent = `開始 ${fmtTs(payload.started_at)}`;
  if (payload.user.registered) hideRegisterPanel();
  applyUserProfile(payload.user.display_settings);
  const qr = document.getElementById("session-settings-qr");
  if (qr) qr.src = `/api/qr?user=${payload.user.id}`;
  const link = document.getElementById("session-settings-link");
  if (link) {
    link.href = `${location.origin}/settings?user=${payload.user.id}`;
    link.textContent = link.href;
  }
  loadUserHistory(payload.user.id);
}

function handleSessionEnd(payload) {
  activeSessionId = null;
  sessionPanel.classList.add("hidden");
  slumpChartPanel.classList.add("hidden");
  payoutChartPanel.classList.add("hidden");
  resetSessionCounts();
  applyDefaultLayout();
}

// 演出などの言葉遣いは host/static/labels.json で差し替えられる.
// 取得失敗・キー欠落時は DEFAULT_LABELS にフォールバックする.
const DEFAULT_LABELS = {
  bb: "BB",
  rb: "RB",
  bbSub: "BIG BONUS",
  rbSub: "REGULAR BONUS",
  renchan: "連チャン!!",
  renchanZone: "連チャンゾーン",
  gameCount: "現在のゲーム数",
};
let labels = { ...DEFAULT_LABELS };

async function loadLabels() {
  try {
    const res = await fetch("/labels.json", { cache: "no-store" });
    if (res.ok) labels = { ...DEFAULT_LABELS, ...(await res.json()) };
  } catch {
    // 取得失敗時はデフォルトの言葉遣いのまま
  }
  document.getElementById("game-count-label").textContent = labels.gameCount;
  document.getElementById("renchan-zone-label").textContent = labels.renchanZone;
}

let bonusTimer = null;

function playBonus(type, renchan = false, winGames = null) {
  bonusOverlay.className = renchan
    ? `bonus-overlay ${type.toLowerCase()} renchan`
    : `bonus-overlay ${type.toLowerCase()}`;
  let html = "";
  if (renchan) {
    html += `<div class="renchan-banner">${
      winGames != null ? `${winGames}G ` : ""
    }${labels.renchan}</div>`;
  }
  html += `<div class="bonus-text">${type === "BB" ? labels.bb : labels.rb}</div>`;
  html += `<div class="bonus-sub">${type === "BB" ? labels.bbSub : labels.rbSub}</div>`;
  bonusOverlay.innerHTML = html;
  // クラス再付与だけではアニメーションが再生されないため reflow で強制リスタート
  void bonusOverlay.offsetWidth;
  bonusOverlay.classList.add("show");
  clearTimeout(bonusTimer);
  bonusTimer = setTimeout(() => bonusOverlay.classList.remove("show"), 3600);
}

function handleEvent(payload) {
  if ("total_games" in payload) currentTotalGames = payload.total_games;
  if (payload.type in totals) {
    totals[payload.type] += 1;
    renderTotals();
  }
  if (
    payload.session_id &&
    payload.session_id === activeSessionId &&
    payload.type in sessionCounts
  ) {
    sessionCounts[payload.type] += 1;
    renderSessionCounts();
    if (payload.type === "IN" || payload.type === "OUT") pushSlumpPoint();
  }
  if ("game_count" in payload) {
    renderGameInfo(payload.game_count, payload.in_renchan_zone);
  }
  if (payload.type === "BB" || payload.type === "RB") {
    playBonus(payload.type, payload.renchan, payload.win_game_count);
  }
  appendEventLog(payload);
}

const source = new EventSource("/api/events/stream");

source.addEventListener("snapshot", (e) => {
  const data = JSON.parse(e.data);
  for (const k of KEYS) totals[k] = data[k] ?? 0;
  renderTotals();
  renderGameInfo(data.game_count ?? 0, data.in_renchan_zone ?? false);
  currentTotalGames = data.total_games ?? 0;
  statusEl.textContent = "Connected";
});

source.addEventListener("event", (e) => {
  const msg = JSON.parse(e.data);
  switch (msg.kind) {
    case "event":
      handleEvent(msg);
      break;
    case "session_start":
      handleSessionStart(msg);
      break;
    case "session_end":
      handleSessionEnd(msg);
      break;
    case "register_required":
      showRegisterPanel(msg);
      break;
    case "user_registered":
      hideRegisterPanel();
      if (activeUserId === msg.user_id) {
        document.getElementById("session-user").textContent = msg.name;
        loadUserHistory(msg.user_id);
      }
      break;
    case "settings_updated":
      if (msg.user_id === activeUserId) applyUserProfile(msg.display_settings);
      break;
    case "payout":
      if (activeSessionId !== null) addPayout(msg);
      break;
    case "bonus_result":
      if (activeSessionId !== null) showBonusResult(msg);
      break;
  }
});

source.onerror = () => {
  statusEl.textContent = "Disconnected, retrying...";
};

// --- 表示設定 -----------------------------------------------------------
// レイアウトは 2 層:
//   デフォルト(アイドル時) … この画面の「表示設定」パネル, localStorage 保存
//   ユーザープロファイル    … カードのユーザーに紐づく設定, セッション中だけ反映
// .user-off はデータ都合の .hidden とは独立に効く(両方無いときだけ表示).
const HIDDEN_PANELS_KEY = "pdc-hidden-panels";
const settingsToggles = document.getElementById("settings-toggles");
const PANEL_IDS = [...settingsToggles.querySelectorAll("input[data-panel]")].map(
  (i) => i.dataset.panel
);

function readDefaultHidden() {
  try {
    return JSON.parse(localStorage.getItem(HIDDEN_PANELS_KEY)) || [];
  } catch {
    return [];
  }
}

function applyHiddenPanels(hidden) {
  for (const id of PANEL_IDS) {
    document.getElementById(id)?.classList.toggle("user-off", hidden.includes(id));
  }
}

// デフォルト(アイドル時)レイアウトを反映し、設定パネルのチェック状態も同期.
function applyDefaultLayout() {
  const hidden = readDefaultHidden();
  applyHiddenPanels(hidden);
  for (const input of settingsToggles.querySelectorAll("input[data-panel]")) {
    input.checked = !hidden.includes(input.dataset.panel);
  }
}

// セッション中: ユーザープロファイルがあればそれを、無ければデフォルトを反映.
function applyUserProfile(settings) {
  const hidden =
    settings && Array.isArray(settings.hidden_panels)
      ? settings.hidden_panels
      : readDefaultHidden();
  applyHiddenPanels(hidden);
}

settingsToggles.addEventListener("change", () => {
  const hidden = [...settingsToggles.querySelectorAll("input[data-panel]")]
    .filter((i) => !i.checked)
    .map((i) => i.dataset.panel);
  localStorage.setItem(HIDDEN_PANELS_KEY, JSON.stringify(hidden));
  applyHiddenPanels(hidden);
});

applyDefaultLayout();
loadLabels();
