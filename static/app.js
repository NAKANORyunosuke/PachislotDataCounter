const KEYS = ["IN", "OUT", "BB", "RB"];
const counts = Object.fromEntries(KEYS.map((k) => [k, 0]));
const status = document.getElementById("status");

function render() {
  for (const k of KEYS) {
    document.getElementById(k).textContent = counts[k];
  }
}

const source = new EventSource("/api/events/stream");

source.addEventListener("snapshot", (e) => {
  const data = JSON.parse(e.data);
  for (const k of KEYS) counts[k] = data[k] ?? 0;
  render();
  status.textContent = "Connected";
});

source.addEventListener("event", (e) => {
  const { type } = JSON.parse(e.data);
  if (type in counts) {
    counts[type] += 1;
    render();
  }
});

source.onerror = () => {
  status.textContent = "Disconnected, retrying...";
};
