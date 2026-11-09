<template>
  <main class="history-shell">
    <header class="history-header">
      <div>
        <p class="history-eyebrow">IIoT Security Monitor</p>
        <h1>Telemetry History</h1>
        <p class="history-subtitle">Query snapshots persisted in MySQL by receive date.</p>
      </div>
      <div class="history-actions">
        <el-button plain @click="router.push({ name: 'dashboard' })">Dashboard</el-button>
        <el-button type="danger" plain @click="logout">Logout</el-button>
      </div>
    </header>

    <section class="history-panel">
      <el-form inline @submit.prevent="loadHistory">
        <el-form-item label="Date range">
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            range-separator="To"
            start-placeholder="Start date"
            end-placeholder="End date"
            value-format="YYYY-MM-DD"
            clearable
          />
        </el-form-item>
        <el-form-item label="Device ID">
          <el-input v-model="deviceId" clearable placeholder="All devices" @keyup.enter="loadHistory" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="loadHistory">Search</el-button>
        </el-form-item>
      </el-form>
    </section>

    <section class="history-panel table-panel">
      <div class="table-heading">
        <div>
          <h2>Snapshot Records</h2>
          <span>{{ rows.length }} records</span>
        </div>
        <span v-if="lastQuery" class="query-label">{{ lastQuery }}</span>
      </div>

      <el-table v-loading="loading" :data="rows" stripe height="560">
        <el-table-column prop="receivedAt" label="Received At (UTC)" min-width="190" />
        <el-table-column prop="deviceId" label="Device ID" min-width="140" />
        <el-table-column prop="temperature" label="Temp (C)" min-width="100" />
        <el-table-column prop="humidity" label="Humidity (%)" min-width="115" />
        <el-table-column prop="rssi" label="RSSI" min-width="90" />
        <el-table-column prop="seq" label="Seq" min-width="80" />
        <el-table-column prop="uptimeMs" label="Uptime (ms)" min-width="120" />
        <el-table-column prop="source" label="Source" min-width="95" />
      </el-table>

      <el-empty v-if="!loading && rows.length === 0" description="No snapshot records found" />
    </section>
  </main>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { useRouter } from "vue-router";

import { fetchTelemetryHistory } from "../services/api";
import { useAuthStore } from "../stores/auth";

const router = useRouter();
const auth = useAuthStore();
const dateRange = ref([]);
const deviceId = ref("");
const rows = ref([]);
const loading = ref(false);
const lastQuery = ref("");

const dateLabel = computed(() => {
  if (!dateRange.value?.length) {
    return "All dates";
  }
  return `${dateRange.value[0]} to ${dateRange.value[1]}`;
});

async function loadHistory() {
  loading.value = true;
  try {
    const filters = {
      ...(dateRange.value?.[0] ? { startDate: dateRange.value[0] } : {}),
      ...(dateRange.value?.[1] ? { endDate: dateRange.value[1] } : {}),
      ...(deviceId.value.trim() ? { deviceId: deviceId.value.trim() } : {})
    };
    const result = await fetchTelemetryHistory(auth.token, filters);
    rows.value = result.items ?? [];
    lastQuery.value = `${dateLabel.value}${deviceId.value.trim() ? ` · ${deviceId.value.trim()}` : ""}`;
  } catch (error) {
    if (error.response?.status === 401) {
      auth.logout();
      await router.replace({ name: "login" });
      return;
    }
    ElMessage.error(error.response?.data?.detail ?? "Unable to load telemetry history.");
  } finally {
    loading.value = false;
  }
}

function logout() {
  auth.logout();
  router.replace({ name: "login" });
}

onMounted(loadHistory);
</script>

<style scoped>
.history-shell {
  min-height: 100vh;
  padding: 24px;
  background:
    linear-gradient(180deg, rgba(11, 18, 29, 0.76), rgba(11, 18, 29, 0.94)),
    transparent;
}

.history-header,
.table-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
}

.history-header {
  margin-bottom: 20px;
}

.history-eyebrow {
  margin: 0 0 8px;
  color: #12d2b7;
  font-size: 12px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

h1,
h2 {
  margin: 0;
}

h1 {
  font-size: clamp(28px, 4vw, 40px);
}

h2 {
  font-size: 18px;
}

.history-subtitle,
.table-heading span,
.query-label {
  color: #96a9b5;
  font-size: 13px;
}

.history-subtitle {
  margin: 10px 0 0;
}

.history-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.history-panel {
  margin-bottom: 16px;
  padding: 18px;
  border: 1px solid rgba(154, 174, 186, 0.14);
  border-radius: 10px;
  background: rgba(8, 18, 27, 0.82);
  backdrop-filter: blur(14px);
}

.table-panel {
  min-height: 650px;
}

.table-heading {
  align-items: center;
  margin-bottom: 16px;
}

.table-heading > div {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.query-label {
  text-align: right;
}

@media (max-width: 760px) {
  .history-shell {
    padding: 16px;
  }

  .history-header,
  .table-heading {
    flex-direction: column;
    align-items: stretch;
  }

  .query-label {
    text-align: left;
  }
}
</style>
