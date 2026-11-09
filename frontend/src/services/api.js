import axios from "axios";

export const apiClient = axios.create({
  baseURL: "http://127.0.0.1:8000/api",
  timeout: 5000
});

export async function loginRequest(credentials) {
  const { data } = await apiClient.post("/auth/login", credentials);
  return data;
}

export async function fetchDashboardSnapshot(token) {
  const { data } = await apiClient.get("/dashboard", {
    headers: token ? { Authorization: `Bearer ${token}` } : {}
  });
  return data;
}

export function getDashboardWebSocketUrl(token) {
  const query = token ? `?token=${encodeURIComponent(token)}` : "";
  return `ws://127.0.0.1:8000/ws${query}`;
}

export async function fetchTelemetryHistory(token, filters = {}) {
  const { data } = await apiClient.get("/telemetry/history", {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    params: filters
  });
  return data;
}
