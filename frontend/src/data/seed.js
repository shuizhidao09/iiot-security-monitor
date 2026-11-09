export const seedDevices = [
  {
    deviceId: "esp32_001",
    name: "Workshop Environment Node A",
    area: "Collection Zone 1",
    online: true,
    temperature: 29.2,
    humidity: 60.4,
    rssi: -37,
    seq: 3,
    uptimeMs: 15006,
    status: "normal",
    lastSeen: Date.now()
  },
  {
    deviceId: "esp32_002",
    name: "Workshop Environment Node B",
    area: "Collection Zone 2",
    online: true,
    temperature: 27.6,
    humidity: 55.1,
    rssi: -42,
    seq: 8,
    uptimeMs: 43112,
    status: "normal",
    lastSeen: Date.now() - 5000
  }
];

export const seedAlerts = [
  {
    id: "ALT-1001",
    level: "info",
    title: "Device Back Online",
    deviceId: "esp32_002",
    description: "The device was briefly offline and has resumed reporting.",
    timestamp: Date.now() - 1000 * 60 * 18
  },
  {
    id: "ALT-1002",
    level: "medium",
    title: "Humidity Near Threshold",
    deviceId: "esp32_001",
    description: "Humidity is approaching 65%; continued observation is recommended.",
    timestamp: Date.now() - 1000 * 60 * 6
  }
];
