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

let activeSessionId = null;
let activeUserId = null;
let chart = null;

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
  sessionPanel.classList.remove("hidden");
  const name = payload.user.name || "(未登録カード)";
  document.getElementById("session-user").textContent = name;
  document.getElementById("session-started").textContent = `開始 ${fmtTs(payload.started_at)}`;
  if (payload.user.registered) hideRegisterPanel();
  loadUserHistory(payload.user.id);
}

function handleSessionEnd(payload) {
  activeSessionId = null;
  sessionPanel.classList.add("hidden");
  resetSessionCounts();
}

const BONUS_SUB = { BB: "BIG BONUS", RB: "REGULAR BONUS" };
let bonusTimer = null;

function playBonus(type) {
  bonusOverlay.className = `bonus-overlay ${type.toLowerCase()}`;
  bonusOverlay.innerHTML =
    `<div class="bonus-text">${type}</div>` +
    `<div class="bonus-sub">${BONUS_SUB[type]}</div>`;
  // クラス再付与だけではアニメーションが再生されないため reflow で強制リスタート
  void bonusOverlay.offsetWidth;
  bonusOverlay.classList.add("show");
  clearTimeout(bonusTimer);
  bonusTimer = setTimeout(() => bonusOverlay.classList.remove("show"), 3600);
}

function handleEvent(payload) {
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
  }
  if (payload.type === "BB" || payload.type === "RB") {
    playBonus(payload.type);
  }
  appendEventLog(payload);
}

const source = new EventSource("/api/events/stream");

source.addEventListener("snapshot", (e) => {
  const data = JSON.parse(e.data);
  for (const k of KEYS) totals[k] = data[k] ?? 0;
  renderTotals();
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
  }
});

source.onerror = () => {
  statusEl.textContent = "Disconnected, retrying...";
};
