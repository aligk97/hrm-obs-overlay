const $ = (selector) => document.querySelector(selector);

const form = $("#settingsForm");
const deviceSelect = $("#deviceSelect");
const statusText = $("#statusText");
const errorText = $("#errorText");
const connectionPill = $("#connectionPill");
const connectionText = $("#connectionText");
const overlayUrl = $("#overlayUrl");
const history = [];
const maxHistory = 90;
let settingsHydrated = false;

function formatKcalHour(value) {
  return `${Number(value || 0).toFixed(0)} kcal/saat`;
}

function setError(message) {
  errorText.hidden = !message;
  errorText.textContent = message || "";
}

function request(path, options = {}) {
  return fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  }).then(async (response) => {
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || "İşlem tamamlanamadı");
    return data;
  });
}

function fillSettings(settings) {
  for (const [key, value] of Object.entries(settings)) {
    const field = form.elements[key];
    if (field) field.value = value;
  }
}

function readSettingsForm() {
  return {
    display_name: form.elements.display_name.value,
    height_cm: form.elements.height_cm.value,
    weight_kg: form.elements.weight_kg.value,
    age: form.elements.age.value,
    sex: form.elements.sex.value,
  };
}

function selectedDevice() {
  const option = deviceSelect.selectedOptions[0];
  return {
    address: deviceSelect.value,
    name: option?.dataset.name || "",
  };
}

function renderState(state) {
  const zoneColor = state.zone?.color || "#aeb9b2";
  const zoneSoft = state.zone?.soft || "rgba(174, 185, 178, 0.24)";

  document.documentElement.style.setProperty("--zone-color", zoneColor);
  document.documentElement.style.setProperty("--zone-soft", zoneSoft);

  $("#bpmValue").textContent = state.bpm ?? "--";
  $("#elapsedValue").textContent = state.elapsed || "00:00";
  $("#caloriesValue").textContent = Number(state.calories || 0).toFixed(1);
  $("#zoneValue").textContent = state.zone?.label || "Bekleniyor";
  $("#kcalHourValue").textContent = formatKcalHour(state.kcal_per_hour);
  statusText.textContent = state.error ? `${state.status}: ${state.error}` : state.status;
  setError(state.error || "");

  connectionPill.classList.toggle("connected", Boolean(state.connected));
  connectionPill.classList.toggle("connecting", Boolean(state.connecting));
  connectionText.textContent = state.demo
    ? "Demo"
    : state.connected
      ? "Bağlı"
      : state.connecting
        ? "Bağlanıyor"
        : "Hazır";

  if (state.settings && !settingsHydrated) {
    fillSettings(state.settings);
    settingsHydrated = true;
  }

  if (state.bpm) {
    history.push({ bpm: state.bpm, color: zoneColor });
    while (history.length > maxHistory) history.shift();
  }
  drawChart();
}

function drawChart() {
  const canvas = $("#pulseChart");
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);

  ctx.strokeStyle = "rgba(255,255,255,0.08)";
  ctx.lineWidth = 1;
  for (let i = 1; i < 4; i += 1) {
    const y = (height / 4) * i;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  }

  if (history.length < 2) return;

  const min = 50;
  const max = 190;
  const pointAt = (point, index) => {
    const x = (index / (maxHistory - 1)) * width;
    const pct = Math.max(0, Math.min(1, (point.bpm - min) / (max - min)));
    const y = height - pct * (height - 18) - 9;
    return { x, y };
  };

  ctx.lineWidth = 4;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";

  for (let index = 1; index < history.length; index += 1) {
    const previous = pointAt(history[index - 1], index - 1);
    const current = pointAt(history[index], index);
    ctx.strokeStyle = history[index].color || "#42df8b";
    ctx.beginPath();
    ctx.moveTo(previous.x, previous.y);
    ctx.lineTo(current.x, current.y);
    ctx.stroke();
  }
}

async function scanDevices() {
  setError("");
  statusText.textContent = "Bluetooth cihazları taranıyor...";
  const data = await request("/api/scan?timeout=6");
  deviceSelect.innerHTML = "";
  if (!data.devices?.length) {
    const option = new Option("Cihaz bulunamadı", "");
    deviceSelect.add(option);
    return;
  }

  for (const device of data.devices) {
    const prefix = device.is_hrm ? "★ " : "";
    const rssi = device.rssi ? ` (${device.rssi} dBm)` : "";
    const option = new Option(`${prefix}${device.name} - ${device.address}${rssi}`, device.address);
    option.dataset.name = device.name;
    deviceSelect.add(option);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const data = await request("/api/settings", {
      method: "POST",
      body: JSON.stringify(readSettingsForm()),
    });
    fillSettings(data.settings);
    statusText.textContent = "Ayarlar kaydedildi";
  } catch (error) {
    setError(error.message);
  }
});

$("#scanButton").addEventListener("click", async () => {
  try {
    await scanDevices();
  } catch (error) {
    setError(error.message);
  }
});

$("#connectButton").addEventListener("click", async () => {
  try {
    await request("/api/settings", {
      method: "POST",
      body: JSON.stringify(readSettingsForm()),
    });
    await request("/api/connect", {
      method: "POST",
      body: JSON.stringify(selectedDevice()),
    });
    statusText.textContent = "Bağlantı başlatıldı";
  } catch (error) {
    setError(error.message);
  }
});

$("#disconnectButton").addEventListener("click", async () => {
  try {
    await request("/api/disconnect", { method: "POST", body: "{}" });
  } catch (error) {
    setError(error.message);
  }
});

$("#demoButton").addEventListener("click", async () => {
  try {
    await request("/api/demo", { method: "POST", body: JSON.stringify({ enabled: true }) });
  } catch (error) {
    setError(error.message);
  }
});

$("#resetButton").addEventListener("click", async () => {
  try {
    history.length = 0;
    await request("/api/reset", { method: "POST", body: "{}" });
    drawChart();
  } catch (error) {
    setError(error.message);
  }
});

$("#copyOverlayButton").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(`${window.location.origin}/overlay`);
    statusText.textContent = "Overlay URL kopyalandı";
  } catch {
    statusText.textContent = "Overlay URL seçilip kopyalanabilir";
  }
});

overlayUrl.textContent = `${window.location.origin}/overlay`;

request("/api/state")
  .then(renderState)
  .catch((error) => setError(error.message));

const events = new EventSource("/events");
events.addEventListener("state", (event) => renderState(JSON.parse(event.data)));
events.onerror = () => {
  connectionText.textContent = "Bekliyor";
};
