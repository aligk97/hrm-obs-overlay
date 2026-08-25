const displayName = document.querySelector("#displayName");
const bpmValue = document.querySelector("#bpmValue");
const elapsedValue = document.querySelector("#elapsedValue");
const caloriesValue = document.querySelector("#caloriesValue");
const zoneValue = document.querySelector("#zoneValue");
const zoneSubtitle = document.querySelector("#zoneSubtitle");
const zoneRange = document.querySelector("#zoneRange");
const statusDot = document.querySelector("#statusDot");
const pulseRing = document.querySelector(".pulse-ring");

function render(state) {
  const zoneColor = state.zone?.color || "#7ddaff";
  const zoneSoft = state.zone?.soft || "rgba(125, 218, 255, 0.22)";

  document.documentElement.style.setProperty("--zone-color", zoneColor);
  document.documentElement.style.setProperty("--zone-soft", zoneSoft);

  displayName.textContent = state.settings?.display_name || "Canlı Nabız";
  bpmValue.textContent = state.bpm ?? "--";
  elapsedValue.textContent = state.elapsed || "00:00";
  caloriesValue.textContent = `${Number(state.calories || 0).toFixed(1)} kcal`;
  zoneValue.textContent = state.zone?.label || "Bekleniyor";
  zoneSubtitle.textContent = state.zone?.subtitle || "Nabız aranıyor";
  zoneRange.textContent = state.zone?.range ? `${state.zone.range} MAX HR` : "Bölge";

  statusDot.classList.toggle("connected", Boolean(state.connected || state.demo));
  statusDot.classList.toggle("connecting", Boolean(state.connecting));

  const bpm = Number(state.bpm || 0);
  if (bpm > 0) {
    const duration = Math.max(0.42, Math.min(1.5, 60 / bpm));
    pulseRing.style.animationDuration = `${duration}s`;
  } else {
    pulseRing.style.animationDuration = "1.4s";
  }
}

fetch("/api/state")
  .then((response) => response.json())
  .then(render)
  .catch(() => {});

const events = new EventSource("/events");
events.addEventListener("state", (event) => render(JSON.parse(event.data)));
