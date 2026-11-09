<template>
  <div class="dashboard-shell">
    <header class="topbar">
      <div class="topbar-title-group">
        <p class="topbar-eyebrow">IIoT Security Monitor</p>
        <h1 class="topbar-title">Industrial IoT Device Security Monitoring Dashboard</h1>
      </div>
      <div class="topbar-meta">
        <div class="meta-chip">
          <el-icon><Connection /></el-icon>
          <span>{{ store.brokerLabel }}</span>
        </div>
        <div class="meta-chip" :class="{ 'is-online': store.mqttConnected }">
          <span class="status-dot"></span>
          <span>{{ store.mqttConnected ? "MQTT Online" : "MQTT Offline" }}</span>
        </div>
        <div class="meta-chip" :class="{ 'is-online': store.backendConnected }">
          <span class="status-dot"></span>
          <span>{{ store.backendConnected ? "Backend Online" : "Demo Mode" }}</span>
        </div>
        <div class="meta-chip" :class="{ 'is-online': store.mysqlConnected }">
          <span class="status-dot"></span>
          <span>{{ store.mysqlConnected ? "MySQL Online" : "MySQL Offline" }}</span>
        </div>
        <el-button size="small" type="primary" plain @click="openHistory">History</el-button>
        <el-button size="small" type="danger" plain @click="logout">Logout</el-button>
        <div class="meta-clock">{{ currentTime }}</div>
      </div>
    </header>

    <section class="metric-strip">
      <article
        v-for="item in metricCards"
        :key="item.label"
        class="metric-card"
      >
        <div class="metric-icon" :class="item.tone">
          <el-icon><component :is="item.icon" /></el-icon>
        </div>
        <div class="metric-copy">
          <p>{{ item.label }}</p>
          <h2>{{ item.value }}</h2>
          <span>{{ item.hint }}</span>
        </div>
      </article>
    </section>

    <main class="dashboard-grid">
      <div class="dashboard-column left-column">
        <SectionPanel title="Device Access Overview" eyebrow="Device Status">
          <div class="device-list">
            <article
              v-for="device in store.devices"
              :key="device.deviceId"
              class="device-item"
            >
              <div class="device-main">
                <div>
                  <h4>{{ device.name }}</h4>
                  <p>{{ device.deviceId }} · {{ device.area }}</p>
                </div>
                <el-tag
                  :type="device.online ? 'success' : 'danger'"
                  effect="dark"
                  round
                >
                  {{ device.online ? "Online" : "Offline" }}
                </el-tag>
              </div>
              <div class="device-metrics">
                <span>Temp {{ device.temperature.toFixed(1) }}C</span>
                <span>Humidity {{ device.humidity.toFixed(1) }}%</span>
                <span>RSSI {{ device.rssi }} dBm</span>
              </div>
              <el-progress
                :percentage="signalToPercent(device.rssi)"
                :stroke-width="8"
                :show-text="false"
                :color="progressColor(device.rssi)"
              />
            </article>
          </div>
        </SectionPanel>

        <SectionPanel title="Alert List" eyebrow="Alerts">
          <div class="alert-list">
            <article
              v-for="alert in store.latestAlerts"
              :key="alert.id"
              class="alert-item"
            >
              <div class="alert-header">
                <el-tag :type="alertType(alert.level)" effect="light" round>
                  {{ alertLevelLabel(alert.level) }}
                </el-tag>
                <span>{{ formatTime(alert.lastSeenMs ?? alert.timestamp) }}</span>
              </div>
              <h4>{{ alert.title }}</h4>
              <p>{{ alert.deviceId }} · {{ alert.description }}</p>
            </article>
          </div>
        </SectionPanel>
      </div>

      <div class="dashboard-column center-column">
        <SectionPanel title="Realtime Temperature and Humidity Trend" eyebrow="Realtime Trend">
          <TrendChart :series="store.trendSeries" />
        </SectionPanel>

        <section class="status-band">
          <div class="status-card">
            <p>Active Rules</p>
            <h3>Device Offline / Threshold Breach / Message Frequency Anomaly</h3>
            <span>Offline threshold 15s, temperature threshold 31C, humidity threshold 65%</span>
          </div>
          <div class="status-card">
            <p>Data Pipeline</p>
            <h3>ESP32 -> MQTT -> Backend Service -> Vue Dashboard</h3>
            <span>{{ store.backendConnected ? "Receiving live backend data." : "Backend unavailable, using local simulation stream." }}</span>
          </div>
        </section>

        <SectionPanel title="Latest Telemetry Records" eyebrow="Telemetry Feed">
          <el-table :data="tableRows" height="260" class="telemetry-table">
            <el-table-column prop="deviceId" label="Device ID" min-width="120" />
            <el-table-column prop="temperature" label="Temp (C)" min-width="100" />
            <el-table-column prop="humidity" label="Humidity (%)" min-width="120" />
            <el-table-column prop="rssi" label="RSSI" min-width="90" />
            <el-table-column prop="seq" label="Seq" min-width="80" />
            <el-table-column prop="status" label="Status" min-width="90">
              <template #default="{ row }">
                <el-tag :type="row.online ? 'success' : 'danger'" effect="light" round>
                  {{ row.online ? "Online" : "Offline" }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
        </SectionPanel>
      </div>

      <div class="dashboard-column right-column">
        <SectionPanel title="Device Health Distribution" eyebrow="Health Score">
          <HealthChart :data="store.healthDistribution" />
        </SectionPanel>

        <SectionPanel title="Alert Severity Statistics" eyebrow="Alert Analytics">
          <AlertBarChart :data="store.alertTrend" />
        </SectionPanel>

        <SectionPanel title="Connection Control" eyebrow="Data Source">
          <div class="control-stack">
            <div class="control-row">
              <div>
                <h4>Simulated Live Data</h4>
                <p>Keep demonstrating telemetry and alert changes when the backend is unavailable.</p>
              </div>
              <el-switch
                v-model="store.mockStreaming"
                inline-prompt
                active-text="On"
                inactive-text="Off"
                @change="handleStreamToggle"
              />
            </div>
            <div class="control-row">
              <div>
                <h4>Backend API</h4>
                <p>http://127.0.0.1:8000/api/dashboard</p>
              </div>
              <el-button type="primary" plain @click="store.connectBackend">Reconnect</el-button>
            </div>
          </div>
        </SectionPanel>
      </div>
    </main>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import {
  Bell,
  Connection,
  DataAnalysis,
  Monitor,
  Opportunity,
  TrendCharts
} from "@element-plus/icons-vue";

import AlertBarChart from "../components/AlertBarChart.vue";
import HealthChart from "../components/HealthChart.vue";
import SectionPanel from "../components/SectionPanel.vue";
import TrendChart from "../components/TrendChart.vue";
import { useAuthStore } from "../stores/auth";
import { useMonitorStore } from "../stores/monitor";

const store = useMonitorStore();
const auth = useAuthStore();
const router = useRouter();
const currentTime = ref("");
let clockTimer;

const metricCards = computed(() => [
  {
    label: "Total Devices",
    value: store.summary.totalDevices,
    hint: "Managed devices",
    icon: Monitor,
    tone: "tone-cyan"
  },
  {
    label: "Online Devices",
    value: store.summary.onlineCount,
    hint: "Reported within 15s",
    icon: Connection,
    tone: "tone-green"
  },
  {
    label: "Active Alerts",
    value: store.summary.warningCount,
    hint: "Needs attention",
    icon: Bell,
    tone: "tone-red"
  },
  {
    label: "Avg Temperature",
    value: `${store.summary.avgTemperature}C`,
    hint: "Sensor node average",
    icon: TrendCharts,
    tone: "tone-amber"
  },
  {
    label: "Avg Humidity",
    value: `${store.summary.avgHumidity}%`,
    hint: "Environment average",
    icon: DataAnalysis,
    tone: "tone-blue"
  },
  {
    label: "Offline Devices",
    value: store.summary.offlineCount,
    hint: "Check connectivity",
    icon: Opportunity,
    tone: "tone-purple"
  }
]);

const tableRows = computed(() =>
  [...store.devices]
    .sort((a, b) => b.lastSeen - a.lastSeen)
    .map((device) => ({
      ...device,
      temperature: device.temperature.toFixed(1),
      humidity: device.humidity.toFixed(1)
    }))
);

function refreshTime() {
  currentTime.value = new Date().toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  });
}

function signalToPercent(rssi) {
  if (rssi >= -45) return 92;
  if (rssi >= -55) return 78;
  if (rssi >= -65) return 55;
  return 34;
}

function progressColor(rssi) {
  if (rssi >= -50) return "#12d2b7";
  if (rssi >= -60) return "#ffb44a";
  return "#ff6a6a";
}

function alertLevelLabel(level) {
  if (level === "high") return "High";
  if (level === "medium") return "Medium";
  if (level === "low") return "Low";
  return "Info";
}

function alertType(level) {
  if (level === "high") return "danger";
  if (level === "medium") return "warning";
  if (level === "low") return "success";
  return "info";
}

function formatTime(timestamp) {
  return new Date(timestamp).toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  });
}

function handleStreamToggle(enabled) {
  if (enabled) {
    store.startMockStream();
    return;
  }
  store.stopMockStream();
}

function openHistory() {
  router.push({ name: "history" });
}

function logout() {
  auth.logout();
  router.replace({ name: "login" });
}

onMounted(() => {
  store.connectBackend();
  refreshTime();
  clockTimer = window.setInterval(() => {
    refreshTime();
    store.evaluateOnlineState();
  }, 1000);
});

onBeforeUnmount(() => {
  if (clockTimer) {
    window.clearInterval(clockTimer);
  }
  store.disconnectBackend();
  store.stopMockStream();
});
</script>
