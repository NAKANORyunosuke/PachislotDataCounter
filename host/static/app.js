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
const payoutChartPanel = document.getElementById("payout-panel");
const bonusResultEl = document.getElementById("bonus-result");
const hitHistoryPanel = document.getElementById("hit-history-panel");
const hitListEl = document.getElementById("hit-list");
const hitDotsEl = document.getElementById("hit-dots");
const historyDetailPanel = document.getElementById("history-detail-panel");
const historyDetailTitle = document.getElementById("history-detail-title");
const historyHitListEl = document.getElementById("history-hit-list");
const scopeSelectEl = document.getElementById("scope-select");
const probEls = {
  BB: document.getElementById("s-pbb"),
  RB: document.getElementById("s-prb"),
  ALL: document.getElementById("s-pall"),
};
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
let historyHitChart = null;
// historyPayoutChart は廃止(過去セッション詳細は差枚 + 当たりG数)
let hitChart = null;
let hitGames = [];   // セッション中の当たりまでのゲーム数 [{type, game}]
// 確率メトリクス用. スコープ別カウント(分母の回転数 + BB/RB).
const PROB_SCOPE_KEY = "pdc-prob-scope";
let probScope = localStorage.getItem(PROB_SCOPE_KEY) || "session";
let sessionGameBase = 0;     // セッション開始時点の total_games
let todayStats = { BB: 0, RB: 0, games: 0 };
let bootStats = { BB: 0, RB: 0, games: 0 };

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
//  - 横軸(ゲーム数): 200 から 200 刻みで、ゲームが進んだら拡張(青天井)
//  - 縦軸(差枚): ±250 から 250 刻みで拡張. ただし下側は -1000 で打ち止め
function slumpBounds(data) {
  let maxX = 0;
  let maxY = 0;
  let minY = 0;
  for (const p of data) {
    if (p.x > maxX) maxX = p.x;
    if (p.y > maxY) maxY = p.y;
    if (p.y < minY) minY = p.y;
  }
  const lower = Math.min(1000, Math.max(250, Math.ceil(-minY / 250) * 250));
  return {
    xMax: Math.max(200, Math.ceil(maxX / 200) * 200),
    yMax: Math.max(250, Math.ceil(maxY / 250) * 250),
    yMin: -lower,
  };
}

function renderSlumpChart() {
  if (typeof Chart === "undefined") return;
  const bounds = slumpBounds(slumpData);
  if (!slumpChart) {
    const ctx = document.getElementById("slump-chart").getContext("2d");
    const grad = ctx.createLinearGradient(0, 0, 0, 240);
    grad.addColorStop(0, "rgba(95,228,255,0.28)");
    grad.addColorStop(1, "rgba(95,228,255,0.02)");
    slumpChart = new Chart(ctx, {
      type: "line",
      data: {
        datasets: [
          {
            label: "差枚",
            data: slumpData,
            borderColor: "#5fe4ff",
            backgroundColor: grad,
            fill: true,
            pointRadius: 0,
            pointHitRadius: 8,
            borderWidth: 1.6,
            tension: 0.25,
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
            title: { display: true, text: "ゲーム数", color: "#5a6678" },
            // ゲーム数は整数なので目盛りも整数だけにする(2.5 等を出さない).
            ticks: { color: "#5a6678", precision: 0, stepSize: 200 },
            grid: { color: "#1a2030" },
          },
          y: {
            min: bounds.yMin,
            max: bounds.yMax,
            ticks: { color: "#5a6678", stepSize: 250 },
            grid: {
              color: (c) => (c.tick.value === 0 ? "#3a4456" : "#1a2030"),
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
            backgroundColor: "rgba(56,227,104,0.85)",
            borderRadius: 4,
            maxBarThickness: 28,
          },
        ],
      },
      options: {
        animation: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { color: "#5a6678" }, grid: { color: "#1a2030" } },
          y: {
            beginAtZero: true,
            ticks: { color: "#5a6678" },
            grid: { color: "#1a2030" },
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

// --- 当たりまでのゲーム数(BB/RB ごとの当選ゲーム数)-----------------------
function hitBarConfig(hits) {
  return {
    type: "bar",
    data: {
      labels: hits.map((_, i) => `${i + 1}`),
      datasets: [
        {
          label: "当たりG数",
          data: hits.map((h) => h.game),
          backgroundColor: hits.map((h) =>
            h.type === "BB" ? "#ff3a3a" : "#4ab5ff"
          ),
          borderRadius: 4,
          maxBarThickness: 28,
        },
      ],
    },
    options: {
      animation: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: "#5a6678" }, grid: { color: "#1a2030" } },
        y: { beginAtZero: true, ticks: { color: "#5a6678" }, grid: { color: "#1a2030" } },
      },
    },
  };
}

function renderHitList(el, hits) {
  el.innerHTML = "";
  for (let i = hits.length - 1; i >= 0; i--) {  // 新しい当たりを上に
    const li = document.createElement("li");
    li.className = `type-${hits[i].type}`;
    const ty = document.createElement("span");
    ty.className = "hit-type";
    ty.textContent = hits[i].type;
    const g = document.createElement("span");
    g.className = "hit-game";
    g.textContent = `${hits[i].game} G`;
    li.append(ty, g);
    el.appendChild(li);
  }
}

// 当たり履歴ドット行: 直近16ヒットを古→新の並びで色付きドット表示(店舗カウンタ風)
function renderHitDots(hits) {
  if (!hitDotsEl) return;
  hitDotsEl.innerHTML = "";
  const recent = hits.slice(-16);
  for (const h of recent) {
    const d = document.createElement("span");
    d.className = `dot ${h.type === "BB" ? "bb" : "rb"}`;
    d.title = `${h.type} @ ${h.game} G`;
    hitDotsEl.appendChild(d);
  }
}

function resetHits() {
  hitGames = [];
  renderHitChart();
}

function addHit(type, games) {
  hitGames.push({ type, game: games == null ? 0 : games });
  renderHitChart();
}

function renderHitChart() {
  hitHistoryPanel.classList.toggle("hidden", hitGames.length === 0);
  renderHitList(hitListEl, hitGames);
  renderHitDots(hitGames);
  if (typeof Chart === "undefined") return;
  if (!hitChart) {
    hitChart = new Chart(
      document.getElementById("hit-chart").getContext("2d"),
      hitBarConfig(hitGames)
    );
  } else {
    hitChart.data = hitBarConfig(hitGames).data;
    hitChart.update("none");
  }
}

// --- 確率メトリクス(BB/RB/合成 を 1/N 表記、スコープ session/today/boot) -----
function fmtProb(games, count) {
  if (!games || !count) return "—";
  return `1/${(games / count).toFixed(1)}`;
}

function renderProbabilities() {
  let bb;
  let rb;
  let games;
  if (probScope === "session") {
    bb = sessionCounts.BB;
    rb = sessionCounts.RB;
    games = Math.max(0, currentTotalGames - sessionGameBase);
  } else if (probScope === "today") {
    bb = todayStats.BB;
    rb = todayStats.RB;
    games = todayStats.games;
  } else {
    bb = bootStats.BB;
    rb = bootStats.RB;
    games = bootStats.games;
  }
  probEls.BB.textContent = fmtProb(games, bb);
  probEls.RB.textContent = fmtProb(games, rb);
  probEls.ALL.textContent = fmtProb(games, bb + rb);
}

async function fetchStats() {
  try {
    const res = await fetch("/api/stats", { cache: "no-store" });
    if (!res.ok) return;
    const d = await res.json();
    if (d.today) todayStats = d.today;
    if (d.boot) bootStats = d.boot;
    renderProbabilities();
  } catch {
    // ネットワーク失敗時はスキップして次のポーリングに任せる
  }
}

function setScope(scope) {
  if (!["session", "today", "boot"].includes(scope)) return;
  probScope = scope;
  localStorage.setItem(PROB_SCOPE_KEY, scope);
  if (scopeSelectEl) {
    for (const btn of scopeSelectEl.querySelectorAll("button[data-scope]")) {
      btn.classList.toggle("active", btn.dataset.scope === scope);
    }
  }
  renderProbabilities();
}

function renderHistoryHits(hits) {
  renderHitList(historyHitListEl, hits);
  if (typeof Chart === "undefined") return;
  if (historyHitChart) historyHitChart.destroy();
  historyHitChart = new Chart(
    document.getElementById("history-hit-chart").getContext("2d"),
    hitBarConfig(hits)
  );
}

function fmtTs(iso) {
  if (!iso) return "-";
  const d = new Date(iso);
  return d.toLocaleString();
}

function appendEventLog({ type, ts, session_id }) {
  const li = document.createElement("li");
  li.className = `log-${type.toLowerCase()}`;
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
  renderHistoryHits(series.hits || []);
  historyDetailPanel.classList.remove("hidden");
}

function renderHistorySlump(slump) {
  if (typeof Chart === "undefined") return;
  const b = slumpBounds(slump);
  if (historySlumpChart) historySlumpChart.destroy();
  const ctx = document.getElementById("history-slump-chart").getContext("2d");
  const hgrad = ctx.createLinearGradient(0, 0, 0, 220);
  hgrad.addColorStop(0, "rgba(95,228,255,0.28)");
  hgrad.addColorStop(1, "rgba(95,228,255,0.02)");
  historySlumpChart = new Chart(ctx, {
    type: "line",
    data: {
      datasets: [
        {
          label: "差枚",
          data: slump,
          borderColor: "#5fe4ff",
          backgroundColor: hgrad,
          fill: true,
          pointRadius: 0,
          pointHitRadius: 8,
          borderWidth: 1.6,
          tension: 0.25,
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
          title: { display: true, text: "ゲーム数", color: "#5a6678" },
          ticks: { color: "#5a6678", precision: 0, stepSize: 200 },
          grid: { color: "#1a2030" },
        },
        y: {
          min: b.yMin,
          max: b.yMax,
          ticks: { color: "#5a6678", stepSize: 250 },
          grid: { color: (c) => (c.tick.value === 0 ? "#3a4456" : "#1a2030") },
        },
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
            v >= 0 ? "rgba(56,227,104,0.75)" : "rgba(255,45,45,0.75)"
          ),
          borderRadius: 4,
          maxBarThickness: 28,
        },
      ],
    },
    options: {
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: "#5a6678" } },
        y: { ticks: { color: "#5a6678" }, grid: { color: "#1a2030" } },
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
  resetHits();
  sessionGameBase = currentTotalGames;  // 確率「セッション中」スコープの分母原点
  renderProbabilities();
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

// ページ再読込時に snapshot へ同梱されたアクティブセッション情報を使い、
// セッションパネル/スランプ/履歴/払い出しを復元する.
async function restoreActiveSession(active, totalGames) {
  activeSessionId = active.session_id;
  resetSessionCounts();
  for (const k of KEYS) sessionCounts[k] = active.session_counts?.[k] ?? 0;
  renderSessionCounts();

  sessionGameBase = Math.max(0, totalGames - (active.session_game_count ?? 0));
  resetSlump();
  resetPayout();
  resetHits();
  renderProbabilities();

  sessionPanel.classList.remove("hidden");
  const name = active.user.name || "(未登録カード)";
  document.getElementById("session-user").textContent = name;
  document.getElementById("session-started").textContent = `開始 ${fmtTs(active.started_at)}`;
  if (active.user.registered) hideRegisterPanel();
  applyUserProfile(active.user.display_settings);
  const qr = document.getElementById("session-settings-qr");
  if (qr) qr.src = `/api/qr?user=${active.user.id}`;
  const link = document.getElementById("session-settings-link");
  if (link) {
    link.href = `${location.origin}/settings?user=${active.user.id}`;
    link.textContent = link.href;
  }
  loadUserHistory(active.user.id);

  try {
    const res = await fetch(`/api/sessions/${active.session_id}/series`);
    if (!res.ok) return;
    const series = await res.json();
    if (Array.isArray(series.slump) && series.slump.length > 0) {
      slumpData = series.slump.slice();
      renderSlumpChart();
    }
    if (Array.isArray(series.hits)) {
      hitGames = series.hits.map((h) => ({ type: h.type, game: h.game }));
      renderHitChart();
    }
    if (Array.isArray(series.payout)) {
      resetPayout();
      for (const p of series.payout) addPayout(p);
    }
  } catch (e) {
    /* シリーズ取得失敗時は静かに諦める. ライブ更新で徐々に埋まる */
  }
}

function handleSessionEnd(payload) {
  activeSessionId = null;
  sessionPanel.classList.add("hidden");
  payoutChartPanel.classList.add("hidden");
  hitHistoryPanel.classList.add("hidden");
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
    renderProbabilities();   // セッションスコープなら毎イベントで更新
  }
  if ("game_count" in payload) {
    renderGameInfo(payload.game_count, payload.in_renchan_zone);
  }
  if (payload.type === "BB" || payload.type === "RB") {
    playBonus(payload.type, payload.renchan, payload.win_game_count);
    if (activeSessionId !== null) addHit(payload.type, payload.win_game_count);
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
  if (data.active_session) {
    restoreActiveSession(data.active_session, currentTotalGames);
  }
  renderProbabilities();
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

// localStorage 未設定(初回)のときデフォルトで隠すパネル / カード.
// セッションパネルの BB/RB/IN/OUT カウントは規定で非表示、確率カードは表示.
const DEFAULT_HIDDEN = [
  "payout-panel",
  "m-s-bb",
  "m-s-rb",
  "m-s-in",
  "m-s-out",
];

function readDefaultHidden() {
  try {
    const saved = JSON.parse(localStorage.getItem(HIDDEN_PANELS_KEY));
    return Array.isArray(saved) ? saved : [...DEFAULT_HIDDEN];
  } catch {
    return [...DEFAULT_HIDDEN];
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

// 確率スコープのセレクタ + /api/stats のポーリング.
if (scopeSelectEl) {
  scopeSelectEl.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-scope]");
    if (btn) setScope(btn.dataset.scope);
  });
}
setScope(probScope);     // localStorage の永続値を反映してハイライト
fetchStats();
setInterval(fetchStats, 5000);
