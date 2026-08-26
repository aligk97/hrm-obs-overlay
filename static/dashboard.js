const $ = (selector) => document.querySelector(selector);

const form = $("#settingsForm");
const deviceSelect = $("#deviceSelect");
const statusText = $("#statusText");
const errorText = $("#errorText");
const connectionPill = $("#connectionPill");
const connectionText = $("#connectionText");
const overlayUrl = $("#overlayUrl");
const sessionList = $("#sessionList");
const reportEmpty = $("#reportEmpty");
const reportContent = $("#reportContent");
const recordingWarning = $("#recordingWarning");
const startButton = $("#connectButton");
const stopButton = $("#disconnectButton");
const history = [];
const maxHistory = 90;
let settingsHydrated = false;
let selectedSessionId = "";
let activeRecording = false;
let knownDevice = null;

function formatKcalHour(value) {
  return `${Number(value || 0).toFixed(0)} kcal/saat`;
}

function formatDate(value) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("tr-TR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatMinutes(seconds) {
  const totalSeconds = Math.max(0, Number(seconds || 0));
  if (totalSeconds < 60) return `${Math.round(totalSeconds)} sn`;
  const minutes = totalSeconds / 60;
  if (minutes < 60) return `${minutes.toFixed(minutes >= 10 ? 0 : 1)} dk`;
  const hours = Math.floor(minutes / 60);
  const remainder = Math.round(minutes % 60);
  return `${hours} sa ${remainder} dk`;
}

function formatBpm(value) {
  return value || value === 0 ? `${Number(value).toFixed(0)} bpm` : "-- bpm";
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
    if (!response.ok) throw new Error(data.error || data.message || "İşlem tamamlanamadı");
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

function deviceText(device) {
  const name = device.name || (device.is_saved ? "Kayıtlı nabız kemeri" : "Bilinmeyen cihaz");
  const type = device.is_saved ? "Kayıtlı cihaz" : device.is_hrm ? "Nabız kemeri" : "Bluetooth";
  const rssi = Number.isFinite(Number(device.rssi)) ? ` - ${device.rssi} dBm` : "";
  return `${type}: ${name} - ${device.address}${rssi}`;
}

function removeDevicePlaceholders() {
  for (const option of Array.from(deviceSelect.options)) {
    if (!option.value) option.remove();
  }
}

function addDeviceOption(device, { selected = false, prepend = false } = {}) {
  if (!device?.address) return null;

  removeDevicePlaceholders();
  const existing = Array.from(deviceSelect.options).find((option) => option.value === device.address);
  const option = existing || new Option("", device.address);
  option.textContent = deviceText(device);
  option.dataset.name = device.name || "";
  option.dataset.saved = device.is_saved ? "true" : "false";

  if (!existing) {
    if (prepend && deviceSelect.firstChild) {
      deviceSelect.insertBefore(option, deviceSelect.firstChild);
    } else {
      deviceSelect.add(option);
    }
  }
  if (selected) option.selected = true;
  return option;
}

function rememberDevice(address, name) {
  if (!address) return;
  knownDevice = {
    address,
    name: name || "Kayıtlı nabız kemeri",
    is_hrm: true,
    is_saved: true,
  };
  addDeviceOption(knownDevice, { selected: !deviceSelect.value, prepend: true });
}

function selectedDevice() {
  const option = deviceSelect.selectedOptions[0];
  const address = deviceSelect.value || knownDevice?.address || "";
  return {
    address,
    name: option?.dataset.name || knownDevice?.name || "",
  };
}

function renderState(state) {
  const zoneColor = state.zone?.color || "#7ddaff";
  const zoneSoft = state.zone?.soft || "rgba(125, 218, 255, 0.24)";

  document.documentElement.style.setProperty("--zone-color", zoneColor);
  document.documentElement.style.setProperty("--zone-soft", zoneSoft);

  $("#bpmValue").textContent = state.bpm ?? "--";
  $("#elapsedValue").textContent = state.elapsed || "00:00";
  $("#caloriesValue").textContent = Number(state.calories || 0).toFixed(1);
  $("#zoneValue").textContent = state.zone?.label || "Bekleniyor";
  $("#kcalHourValue").textContent = formatKcalHour(state.kcal_per_hour);
  statusText.textContent = state.error ? `${state.status}: ${state.error}` : state.status;
  if (state.bpm_stale && !state.error) {
    statusText.textContent = `${state.status} - son nabız değeri korunuyor`;
  }
  setError(state.error || "");
  const startPending = Boolean(state.start_pending);
  activeRecording = Boolean(state.recording_active);
  recordingWarning.hidden = !activeRecording;
  startButton.disabled = Boolean(state.connecting || startPending || activeRecording);
  stopButton.disabled =
    !activeRecording && !state.connected && !state.connecting && !state.demo && !startPending;

  connectionPill.classList.toggle("connected", Boolean(state.connected));
  connectionPill.classList.toggle("connecting", Boolean(state.connecting || startPending));
  connectionText.textContent = state.demo
    ? "Demo"
    : state.connected
      ? "Bağlı"
      : state.connecting || startPending
        ? activeRecording
          ? "Yeniden bağlanıyor"
          : "Bağlantı bekleniyor"
        : activeRecording
          ? "Kayıt açık"
          : "Hazır";

  if (state.settings && !settingsHydrated) {
    fillSettings(state.settings);
    rememberDevice(state.settings.device_address, state.settings.device_name);
    settingsHydrated = true;
  }
  rememberDevice(state.device_address, state.device_name);

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
  const previousSelection = deviceSelect.value || knownDevice?.address || "";
  deviceSelect.innerHTML = "";
  if (!data.devices?.length) {
    const option = new Option("Cihaz bulunamadı", "");
    deviceSelect.add(option);
    statusText.textContent = "Cihaz bulunamadı";
    return;
  }

  for (const device of data.devices) {
    addDeviceOption(device, { selected: device.address === previousSelection });
    if (device.is_saved) knownDevice = { ...device };
  }
  if (previousSelection && Array.from(deviceSelect.options).some((option) => option.value === previousSelection)) {
    deviceSelect.value = previousSelection;
  }

  const savedOnly = data.devices.length === 1 && data.devices[0].is_saved;
  if (data.warning) {
    setError(
      savedOnly
        ? "Tarama tamamlanamadı ama kayıtlı cihaz seçili. Kemer takılı/uyanıksa Başlat ile deneyin."
        : `Tarama uyarısı: ${data.warning}`
    );
  }
  if (savedOnly) {
    statusText.textContent = "Kayıtlı cihaz seçildi";
  } else {
    statusText.textContent = `${data.devices.length} cihaz bulundu`;
  }
}

function renderSessionList(sessions) {
  sessionList.replaceChildren();
  if (!sessions.length) {
    const empty = document.createElement("div");
    empty.className = "session-empty";
    empty.textContent = "Henüz kayıt yok";
    sessionList.append(empty);
    return;
  }

  const fragment = document.createDocumentFragment();
  for (const session of sessions) {
    const item = document.createElement("div");
    item.className = "session-item";
    item.dataset.sessionId = session.id;
    item.classList.toggle("selected", session.id === selectedSessionId);

    const selectButton = document.createElement("button");
    selectButton.type = "button";
    selectButton.className = "session-select";

    const title = document.createElement("strong");
    title.textContent = session.active ? `${session.title} · Aktif` : session.title;

    const meta = document.createElement("span");
    meta.textContent = `${formatDate(session.started_at)} · ${formatMinutes(session.duration_seconds)}`;

    const stats = document.createElement("small");
    stats.textContent = `${Number(session.calories || 0).toFixed(1)} kcal · ${formatBpm(session.avg_bpm)} ort.`;

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "session-delete";
    deleteButton.textContent = "Sil";
    deleteButton.disabled = Boolean(session.active);
    deleteButton.title = session.active ? "Aktif kayıt silinemez" : "Kaydı sil";
    deleteButton.addEventListener("click", () => deleteSession(session.id));

    selectButton.append(title, meta, stats);
    selectButton.addEventListener("click", () => selectSession(session.id));
    item.append(selectButton, deleteButton);
    fragment.append(item);
  }
  sessionList.append(fragment);
}

async function loadSessions({ refreshSelected = false } = {}) {
  const data = await request("/api/sessions");
  const sessions = data.sessions || [];
  const selectedStillExists = sessions.some((session) => session.id === selectedSessionId);
  if (!sessions.length) {
    selectedSessionId = "";
    renderSessionList(sessions);
    reportEmpty.hidden = false;
    reportContent.hidden = true;
    return;
  }
  if (!selectedSessionId || !selectedStillExists) selectedSessionId = sessions[0].id;
  renderSessionList(sessions);

  if (selectedSessionId && (refreshSelected || !reportContent || reportContent.hidden)) {
    await selectSession(selectedSessionId, { skipListUpdate: true });
  }
}

async function selectSession(sessionId, { skipListUpdate = false } = {}) {
  selectedSessionId = sessionId;
  if (!skipListUpdate) {
    for (const item of sessionList.querySelectorAll(".session-item")) {
      item.classList.toggle("selected", item.dataset.sessionId === sessionId);
    }
  }

  const data = await request(`/api/sessions/${encodeURIComponent(sessionId)}`);
  renderReport(data.session);
}

async function deleteSession(sessionId) {
  if (!sessionId) return;
  const approved = window.confirm("Bu kaydı silmek istiyor musunuz?");
  if (!approved) return;

  try {
    const data = await request(`/api/sessions/${encodeURIComponent(sessionId)}`, {
      method: "DELETE",
    });
    if (selectedSessionId === sessionId) {
      selectedSessionId = "";
      reportEmpty.hidden = false;
      reportContent.hidden = true;
    }
    statusText.textContent = data.message || "Kayıt silindi";
    await loadSessions({ refreshSelected: true });
  } catch (error) {
    setError(error.message);
  }
}

function renderReport(session) {
  const summary = session.summary || {};
  const samples = session.samples || [];

  reportEmpty.hidden = true;
  reportContent.hidden = false;

  $("#reportTitle").textContent = summary.active ? `${summary.title} · Aktif` : summary.title;
  $("#reportMeta").textContent = `${formatDate(summary.started_at)} · ${summary.sample_count || 0} örnek`;
  $("#reportCalories").textContent = Number(summary.calories || 0).toFixed(1);
  $("#reportDuration").textContent = summary.duration || "00:00";
  $("#reportAvgBpm").textContent = formatBpm(summary.avg_bpm);
  $("#reportMinBpm").textContent = formatBpm(summary.min_bpm);
  $("#reportMaxBpm").textContent = formatBpm(summary.max_bpm);

  drawReportHeartChart(samples);
  renderZoneBreakdown(summary.zones || []);
}

function drawReportHeartChart(samples) {
  const canvas = $("#reportHeartChart");
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);

  ctx.fillStyle = "rgba(255, 255, 255, 0.04)";
  ctx.fillRect(0, 0, width, height);

  const points = samples
    .filter((sample) => sample.bpm)
    .map((sample) => ({
      elapsed: Number(sample.elapsed_seconds || 0),
      bpm: Number(sample.bpm),
      color: sample.zone?.color || "#7ddaff",
    }));

  if (points.length < 2) {
    ctx.fillStyle = "#aab8af";
    ctx.font = "18px Segoe UI, sans-serif";
    ctx.fillText("Grafik için nabız verisi bekleniyor", 24, height / 2);
    return;
  }

  const minElapsed = points[0].elapsed;
  const maxElapsed = Math.max(points.at(-1).elapsed, minElapsed + 1);
  const bpmValues = points.map((point) => point.bpm);
  const minBpm = Math.max(40, Math.min(...bpmValues) - 10);
  const maxBpm = Math.min(210, Math.max(...bpmValues) + 10);
  const left = 42;
  const right = width - 16;
  const top = 18;
  const bottom = height - 28;

  ctx.strokeStyle = "rgba(255,255,255,0.08)";
  ctx.lineWidth = 1;
  for (let i = 0; i < 4; i += 1) {
    const y = top + ((bottom - top) / 3) * i;
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(right, y);
    ctx.stroke();
  }

  const mapPoint = (point) => {
    const x = left + ((point.elapsed - minElapsed) / (maxElapsed - minElapsed)) * (right - left);
    const y = bottom - ((point.bpm - minBpm) / (maxBpm - minBpm)) * (bottom - top);
    return { x, y };
  };

  ctx.lineWidth = 4;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  for (let index = 1; index < points.length; index += 1) {
    const previous = mapPoint(points[index - 1]);
    const current = mapPoint(points[index]);
    ctx.strokeStyle = points[index].color;
    ctx.beginPath();
    ctx.moveTo(previous.x, previous.y);
    ctx.lineTo(current.x, current.y);
    ctx.stroke();
  }

  ctx.fillStyle = "#aab8af";
  ctx.font = "14px Segoe UI, sans-serif";
  ctx.fillText(`${Math.round(maxBpm)} bpm`, 6, top + 4);
  ctx.fillText(`${Math.round(minBpm)} bpm`, 6, bottom);
}

function renderZoneBreakdown(zones) {
  const root = $("#zoneBreakdown");
  root.replaceChildren();
  for (const zone of zones) {
    const row = document.createElement("div");
    row.className = "zone-row";

    const head = document.createElement("div");
    head.className = "zone-row-head";

    const name = document.createElement("strong");
    name.textContent = zone.label;
    name.style.color = zone.color;

    const time = document.createElement("span");
    time.textContent = `${formatMinutes(zone.seconds)} · %${Number(zone.percent || 0).toFixed(1)}`;

    const bar = document.createElement("div");
    bar.className = "zone-row-bar";
    const fill = document.createElement("span");
    fill.style.background = zone.color;
    fill.style.width = `${Math.max(zone.seconds > 0 ? 3 : 0, Number(zone.percent || 0))}%`;
    bar.append(fill);

    head.append(name, time);
    row.append(head, bar);
    root.append(row);
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
    await loadSessions({ refreshSelected: true });
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

startButton.addEventListener("click", async () => {
  try {
    startButton.disabled = true;
    await request("/api/settings", {
      method: "POST",
      body: JSON.stringify(readSettingsForm()),
    });
    const data = await request("/api/connect", {
      method: "POST",
      body: JSON.stringify(selectedDevice()),
    });
    statusText.textContent = data.recording_pending
      ? "Bluetooth bağlantısı deneniyor. Kayıt bağlantıdan sonra başlayacak."
      : "Kayıt başladı";
    await loadSessions({ refreshSelected: true });
  } catch (error) {
    startButton.disabled = false;
    setError(error.message);
  }
});

stopButton.addEventListener("click", async () => {
  try {
    stopButton.disabled = true;
    await request("/api/disconnect", { method: "POST", body: "{}" });
    activeRecording = false;
    recordingWarning.hidden = true;
    statusText.textContent = "Durduruldu, kayıt kaydedildi";
    await loadSessions({ refreshSelected: true });
  } catch (error) {
    stopButton.disabled = false;
    setError(error.message);
  }
});

$("#demoButton").addEventListener("click", async () => {
  try {
    await request("/api/demo", { method: "POST", body: JSON.stringify({ enabled: true }) });
    await loadSessions({ refreshSelected: true });
  } catch (error) {
    setError(error.message);
  }
});

$("#resetButton").addEventListener("click", async () => {
  try {
    history.length = 0;
    await request("/api/reset", { method: "POST", body: "{}" });
    selectedSessionId = "";
    drawChart();
    await loadSessions({ refreshSelected: true });
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

$("#refreshSessionsButton").addEventListener("click", async () => {
  try {
    await loadSessions({ refreshSelected: true });
  } catch (error) {
    setError(error.message);
  }
});

overlayUrl.textContent = `${window.location.origin}/overlay`;

request("/api/state")
  .then(renderState)
  .catch((error) => setError(error.message));

loadSessions().catch((error) => setError(error.message));
setInterval(() => loadSessions({ refreshSelected: true }).catch(() => {}), 15000);

window.addEventListener("beforeunload", (event) => {
  if (!activeRecording) return;
  event.preventDefault();
  event.returnValue = "Aktif yayın kaydı var. Önce Durdur ile kaydedin.";
});

const events = new EventSource("/events");
events.addEventListener("state", (event) => renderState(JSON.parse(event.data)));
events.onerror = () => {
  connectionText.textContent = "Bekliyor";
};
