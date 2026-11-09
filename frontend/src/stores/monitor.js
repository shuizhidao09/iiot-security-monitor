import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { seedAlerts, seedDevices } from "../data/seed";
import { fetchDashboardSnapshot, getDashboardWebSocketUrl } from "../services/api";
import { useAuthStore } from "./auth";

const OFFLINE_THRESHOLD_MS = 15000;
// Must be kept in sync with the backend thresholds (TEMP_ALERT_THRESHOLD,
// HUMIDITY_ALERT_THRESHOLD); they are also drawn as lines in the trend chart.
export const TEMP_ALERT_THRESHOLD = 31;
export const HUMIDITY_ALERT_THRESHOLD = 65;
const ALERT_LEVELS = ["info", "low", "medium", "high"];

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function normalizeAlertLevel(level) {
  const normalized = String(level ?? "").trim().toLowerCase();
  if (ALERT_LEVELS.includes(normalized)) {
    return normalized;
  }

  // Accept legacy severities while keeping the data exposed to the UI in the
  // four-level format used by the backend and the dashboard.
  if (["critical", "error", "fatal", "danger"].includes(normalized)) {
    return "high";
  }
  if (["warning", "warn", "alert"].includes(normalized)) {
    return "medium";
  }
  if (["notice", "informational", "normal", "debug"].includes(normalized)) {
    return "info";
  }
  return "info";
}

function createAlert(level, title, deviceId, description) {
  const timestamp = Date.now();
  return {
    id: `ALT-${Date.now()}-${Math.floor(Math.random() * 1000)}`,
    level: normalizeAlertLevel(level),
    title,
    deviceId,
    description,
    timestamp,
    firstSeenMs: timestamp,
    lastSeenMs: timestamp,
    occurrenceCount: 1
  };
}

function englishDeviceName(device) {
  const id = device.deviceId ?? "unknown";
  const suffix = id.replace("esp32_", "") || id;
  if (!device.name || /[\u4e00-\u9fff]/.test(device.name)) {
    return `Environment Sensor Node ${suffix}`;
  }
  return device.name;
}

function englishAreaName(area) {
  if (!area || /[\u4e00-\u9fff]/.test(area)) {
    return "Lab Collection Area";
  }
  return area;
}

function normalizeDevice(device) {
  return {
    ...device,
    name: englishDeviceName(device),
    area: englishAreaName(device.area)
  };
}

function normalizeAlert(alert) {
  const fallbackByType = {
    new_device: {
      title: "New Device Connected",
      description: "The device reported telemetry via MQTT for the first time."
    },
    online: {
      title: "Device Back Online",
      description: "The offline device has resumed telemetry reporting."
    },
    frequency: {
      title: "Message Interval Anomaly",
      description: "The interval between two reports exceeded the normal period."
    },
    temperature: {
      title: "Temperature Anomaly",
      description: "The current temperature exceeds the configured threshold."
    },
    humidity: {
      title: "Humidity Anomaly",
      description: "The current humidity exceeds the configured threshold."
    },
    offline: {
      title: "Device Offline",
      description: "No telemetry has been received for more than 15 seconds."
    },
    format: {
      title: "Invalid Data Format",
      description: "The telemetry payload could not be parsed."
    },
    mqtt: {
      title: "MQTT Connection Failed",
      description: "The backend could not connect to the MQTT broker."
    },
    restart: {
      title: "Device Restarted",
      description: "The sequence and uptime counters indicate that the device restarted."
    },
    sequence: {
      title: "Suspicious Sequence",
      description: "The message was discarded because its sequence or uptime was inconsistent."
    },
    device_id_mismatch: {
      title: "Device ID Mismatch",
      description: "The payload device ID did not match the MQTT topic."
    }
  };
  const fallback = fallbackByType[alert.type] ?? {
    title: "System Alert",
    description: "Alert details are unavailable in English."
  };
  const title = alert.title && !/[\u4e00-\u9fff]/.test(alert.title) ? alert.title : fallback.title;
  const description =
    alert.description && !/[\u4e00-\u9fff]/.test(alert.description)
      ? alert.description
      : fallback.description;
  const timestamp = Number(
    alert.timestamp ?? alert.lastSeenMs ?? alert.last_seen_ms ?? alert.firstSeenMs ?? alert.first_seen_ms
  );
  const firstSeenMs = Number(alert.firstSeenMs ?? alert.first_seen_ms ?? timestamp);
  const lastSeenMs = Number(alert.lastSeenMs ?? alert.last_seen_ms ?? timestamp);
  const occurrenceCount = Number(alert.occurrenceCount ?? alert.occurrence_count ?? 1);

  return {
    ...alert,
    level: normalizeAlertLevel(alert.level),
    title,
    description,
    timestamp: Number.isFinite(timestamp) ? timestamp : Date.now(),
    firstSeenMs: Number.isFinite(firstSeenMs) ? firstSeenMs : Date.now(),
    lastSeenMs: Number.isFinite(lastSeenMs) ? lastSeenMs : Date.now(),
    occurrenceCount: Number.isFinite(occurrenceCount) ? occurrenceCount : 1
  };
}

export const useMonitorStore = defineStore("monitor", () => {
  const auth = useAuthStore();
  const devices = ref([]);
  const alerts = ref([]);
  const telemetryHistory = ref([]);
  const mqttConnected = ref(true);
  const backendConnected = ref(false);
  const mysqlConnected = ref(false);
  const mockStreaming = ref(false);
  const brokerLabel = ref("broker.emqx.io:1883");
  const streamTimer = ref(null);
  const socket = ref(null);
  const reconnectTimer = ref(null);
  const lastBackendReceivedAtMs = ref(null);
  const lastWebSocketLatencyMs = ref(null);
  const trendLength = 60;

  function initialize() {
    devices.value = seedDevices.map((item) => ({ ...item }));
    alerts.value = seedAlerts.map(normalizeAlert);
    telemetryHistory.value = seedDevices.map((item, index) => ({
      timeLabel: `${String(8 + index).padStart(2, "0")}:00`,
      timestamp: Date.now() - (seedDevices.length - index) * 5000,
      temperature: item.temperature,
      humidity: item.humidity,
      deviceId: item.deviceId
    }));
  }

  function applySnapshot(snapshot) {
    brokerLabel.value = snapshot.brokerLabel ?? brokerLabel.value;
    mqttConnected.value = Boolean(snapshot.mqttConnected);
    if ("mysqlConnected" in snapshot) {
      mysqlConnected.value = Boolean(snapshot.mysqlConnected);
    }
    devices.value = Array.isArray(snapshot.devices) ? snapshot.devices.map(normalizeDevice) : [];
    alerts.value = Array.isArray(snapshot.alerts) ? snapshot.alerts.map(normalizeAlert) : [];
    telemetryHistory.value = Array.isArray(snapshot.telemetryHistory)
      ? snapshot.telemetryHistory.slice(-trendLength)
      : [];
  }

  async function connectBackend() {
    clearReconnectTimer();

    try {
      const snapshot = await fetchDashboardSnapshot(auth.token);
      applySnapshot(snapshot);
      backendConnected.value = true;
      stopMockStream();
    } catch (error) {
      if (error.response?.status === 401) {
        auth.logout();
        window.location.replace("/login");
        return;
      }
      backendConnected.value = false;
      if (devices.value.length === 0) {
        initialize();
      }
      if (!mockStreaming.value) {
        startMockStream();
      }
      scheduleReconnect();
      return;
    }

    connectWebSocket();
  }

  function connectWebSocket() {
    closeWebSocket();

    const ws = new WebSocket(getDashboardWebSocketUrl(auth.token));
    socket.value = ws;

    ws.onopen = () => {
      backendConnected.value = true;
      stopMockStream();
    };

    ws.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        const receivedAtMs = message.backendReceivedAtMs;
        if (typeof receivedAtMs === "number" && Number.isFinite(receivedAtMs)) {
          lastBackendReceivedAtMs.value = receivedAtMs;
          lastWebSocketLatencyMs.value = Date.now() - receivedAtMs;
        }
        if (message.event === "snapshot") {
          applySnapshot(message.payload);
        }
        if (message.event === "telemetry") {
          applySnapshot(message.payload.snapshot);
        }
      } catch (error) {
        console.warn("Invalid dashboard websocket message", error);
      }
    };

    ws.onclose = (event) => {
      if (event.code === 1008) {
        auth.logout();
        window.location.replace("/login");
        return;
      }
      backendConnected.value = false;
      socket.value = null;
      scheduleReconnect();
      if (!mockStreaming.value && devices.value.length === 0) {
        initialize();
        startMockStream();
      }
    };

    ws.onerror = () => {
      backendConnected.value = false;
      ws.close();
    };
  }

  function scheduleReconnect() {
    clearReconnectTimer();
    reconnectTimer.value = window.setTimeout(() => {
      connectBackend();
    }, 3000);
  }

  function clearReconnectTimer() {
    if (reconnectTimer.value) {
      window.clearTimeout(reconnectTimer.value);
      reconnectTimer.value = null;
    }
  }

  function closeWebSocket() {
    if (socket.value) {
      const currentSocket = socket.value;
      socket.value = null;
      currentSocket.onclose = null;
      currentSocket.onerror = null;
      currentSocket.close();
    }
  }

  function disconnectBackend() {
    clearReconnectTimer();
    closeWebSocket();
    backendConnected.value = false;
  }

  function ingestTelemetry(payload) {
    const existing = devices.value.find((item) => item.deviceId === payload.deviceId);
    const now = Date.now();
    const nextState = {
      deviceId: payload.deviceId,
      name: existing?.name ?? payload.deviceId,
      area: existing?.area ?? "Unassigned Area",
      online: true,
      temperature: Number(payload.temperature ?? existing?.temperature ?? 0),
      humidity: Number(payload.humidity ?? existing?.humidity ?? 0),
      rssi: Number(payload.rssi ?? existing?.rssi ?? 0),
      seq: Number(payload.seq ?? existing?.seq ?? 0),
      uptimeMs: Number(payload.uptimeMs ?? existing?.uptimeMs ?? 0),
      status: "normal",
      lastSeen: now
    };

    if (!existing) {
      devices.value.unshift(nextState);
      alerts.value.unshift(
        createAlert("info", "New Device Detected", payload.deviceId, "The device connected to the monitoring platform for the first time.")
      );
    } else {
      Object.assign(existing, nextState);
    }

    const target = existing ?? devices.value[0];

    if (target.temperature >= TEMP_ALERT_THRESHOLD) {
      target.status = "warning";
      alerts.value.unshift(
        createAlert(
          "high",
          "Temperature Anomaly",
          target.deviceId,
          `Current temperature ${target.temperature.toFixed(1)}C exceeds the ${TEMP_ALERT_THRESHOLD}C threshold.`
        )
      );
    }

    if (target.humidity >= HUMIDITY_ALERT_THRESHOLD) {
      target.status = "warning";
      alerts.value.unshift(
        createAlert(
          "medium",
          "Humidity Anomaly",
          target.deviceId,
          `Current humidity ${target.humidity.toFixed(1)}% exceeds the ${HUMIDITY_ALERT_THRESHOLD}% threshold.`
        )
      );
    }

    telemetryHistory.value.push({
      timeLabel: new Date(now).toLocaleTimeString("en-US", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit"
      }),
      timestamp: now,
      temperature: target.temperature,
      humidity: target.humidity,
      deviceId: target.deviceId
    });

    if (telemetryHistory.value.length > trendLength) {
      telemetryHistory.value.splice(0, telemetryHistory.value.length - trendLength);
    }

    if (alerts.value.length > 20) {
      alerts.value.splice(20);
    }
  }

  function evaluateOnlineState() {
    const now = Date.now();
    devices.value.forEach((device) => {
      const shouldBeOnline = now - device.lastSeen <= OFFLINE_THRESHOLD_MS;
      if (device.online && !shouldBeOnline) {
        device.online = false;
        device.status = "offline";
        alerts.value.unshift(
          createAlert("high", "Device Offline", device.deviceId, "No telemetry has been received for more than 15 seconds.")
        );
      }
      if (!device.online && shouldBeOnline) {
        device.online = true;
        device.status = "normal";
      }
    });

    if (alerts.value.length > 20) {
      alerts.value.splice(20);
    }
  }

  function startMockStream() {
    stopMockStream();
    if (devices.value.length === 0) {
      initialize();
    }
    mockStreaming.value = true;

    streamTimer.value = window.setInterval(() => {
      const source = devices.value[0];
      if (!source) {
        return;
      }
      const nextTemperature = clamp(source.temperature + (Math.random() - 0.5) * 1.4, 24, 34);
      const nextHumidity = clamp(source.humidity + (Math.random() - 0.5) * 3.2, 42, 72);
      const nextRssi = clamp(source.rssi + Math.round((Math.random() - 0.5) * 6), -70, -28);

      ingestTelemetry({
        deviceId: source.deviceId,
        seq: source.seq + 1,
        temperature: Number(nextTemperature.toFixed(1)),
        humidity: Number(nextHumidity.toFixed(1)),
        rssi: nextRssi,
        uptimeMs: source.uptimeMs + 5000
      });

      if (devices.value[1] && Math.random() > 0.4) {
        const backup = devices.value[1];
        ingestTelemetry({
          deviceId: backup.deviceId,
          seq: backup.seq + 1,
          temperature: Number(clamp(backup.temperature + (Math.random() - 0.5), 23, 31).toFixed(1)),
          humidity: Number(clamp(backup.humidity + (Math.random() - 0.5) * 2.4, 38, 68).toFixed(1)),
          rssi: clamp(backup.rssi + Math.round((Math.random() - 0.5) * 4), -68, -30),
          uptimeMs: backup.uptimeMs + 5000
        });
      }

      evaluateOnlineState();
    }, 5000);
  }

  function stopMockStream() {
    if (streamTimer.value) {
      window.clearInterval(streamTimer.value);
      streamTimer.value = null;
    }
    mockStreaming.value = false;
  }

  const summary = computed(() => {
    const onlineCount = devices.value.filter((item) => item.online).length;
    const offlineCount = devices.value.length - onlineCount;
    const warningCount = alerts.value.filter((item) => ["medium", "high"].includes(item.level)).length;
    const avgTemperature =
      devices.value.length > 0
        ? devices.value.reduce((sum, item) => sum + item.temperature, 0) / devices.value.length
        : 0;
    const avgHumidity =
      devices.value.length > 0
        ? devices.value.reduce((sum, item) => sum + item.humidity, 0) / devices.value.length
        : 0;

    return {
      totalDevices: devices.value.length,
      onlineCount,
      offlineCount,
      warningCount,
      avgTemperature: avgTemperature.toFixed(1),
      avgHumidity: avgHumidity.toFixed(1)
    };
  });

  const latestAlerts = computed(() => alerts.value.slice(0, 6));

  // One series per device, sorted by device ID; each point is placed on a
  // time axis using the backend reception timestamp.
  const trendSeries = computed(() => {
    const byDevice = new Map();
    for (const item of telemetryHistory.value) {
      const deviceId = item.deviceId || "unknown";
      if (!byDevice.has(deviceId)) {
        byDevice.set(deviceId, []);
      }
      byDevice.get(deviceId).push({
        timestamp: Number(item.timestamp) || 0,
        temperature: Number(item.temperature),
        humidity: Number(item.humidity)
      });
    }
    return [...byDevice.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([deviceId, points]) => ({
        deviceId,
        points: points.sort((a, b) => a.timestamp - b.timestamp)
      }));
  });

  const healthDistribution = computed(() => {
    const normal = devices.value.filter((item) => item.online && item.status === "normal").length;
    const warning = devices.value.filter((item) => item.status === "warning").length;
    const offline = devices.value.filter((item) => !item.online).length;

    return [
      { name: "Normal", value: normal },
      { name: "Warning", value: warning },
      { name: "Offline", value: offline }
    ];
  });

  const alertTrend = computed(() => {
    const levelCount = {
      info: 0,
      low: 0,
      medium: 0,
      high: 0
    };

    alerts.value.forEach((item) => {
      levelCount[item.level] = (levelCount[item.level] ?? 0) + 1;
    });

    return [
      { level: "info", label: "Info", value: levelCount.info },
      { level: "low", label: "Low", value: levelCount.low },
      { level: "medium", label: "Medium", value: levelCount.medium },
      { level: "high", label: "High", value: levelCount.high }
    ];
  });

  return {
    devices,
    alerts,
    brokerLabel,
    mqttConnected,
    backendConnected,
    mysqlConnected,
    lastBackendReceivedAtMs,
    lastWebSocketLatencyMs,
    mockStreaming,
    summary,
    latestAlerts,
    trendSeries,
    healthDistribution,
    alertTrend,
    initialize,
    connectBackend,
    disconnectBackend,
    applySnapshot,
    ingestTelemetry,
    evaluateOnlineState,
    startMockStream,
    stopMockStream
  };
});
