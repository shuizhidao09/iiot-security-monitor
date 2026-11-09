<template>
  <div ref="chartRef" class="chart"></div>
</template>

<script setup>
import * as echarts from "echarts";
import { onBeforeUnmount, onMounted, ref, watch } from "vue";

import { HUMIDITY_ALERT_THRESHOLD, TEMP_ALERT_THRESHOLD } from "../stores/monitor";

const props = defineProps({
  // [{ deviceId, points: [{ timestamp, temperature, humidity }] }]
  series: {
    type: Array,
    default: () => []
  }
});

const DEVICE_COLORS = ["#12d2b7", "#72b5ff", "#ff8a65", "#b48cff", "#f4d35e", "#ff6a9a"];

const chartRef = ref(null);
let chart;

function buildSeries() {
  const result = [];

  props.series.forEach((device, index) => {
    const color = DEVICE_COLORS[index % DEVICE_COLORS.length];

    result.push({
      id: `${device.deviceId}-temp`,
      name: `${device.deviceId} Temp (C)`,
      type: "line",
      smooth: 0.3,
      smoothMonotone: "x",
      showSymbol: false,
      yAxisIndex: 0,
      data: device.points.map((point) => [point.timestamp, point.temperature]),
      lineStyle: { color, width: 3 },
      itemStyle: { color }
    });

    result.push({
      id: `${device.deviceId}-humidity`,
      name: `${device.deviceId} Humidity (%)`,
      type: "line",
      smooth: 0.3,
      smoothMonotone: "x",
      showSymbol: false,
      yAxisIndex: 1,
      data: device.points.map((point) => [point.timestamp, point.humidity]),
      lineStyle: { color, width: 2, type: "dashed", opacity: 0.85 },
      itemStyle: { color }
    });
  });

  result.push(
    thresholdSeries(
      `Temp threshold (${TEMP_ALERT_THRESHOLD} C)`,
      0,
      TEMP_ALERT_THRESHOLD,
      "#ff6a6a",
      `${TEMP_ALERT_THRESHOLD} C`
    )
  );
  result.push(
    thresholdSeries(
      `Humidity threshold (${HUMIDITY_ALERT_THRESHOLD} %)`,
      1,
      HUMIDITY_ALERT_THRESHOLD,
      "#ffb44a",
      `${HUMIDITY_ALERT_THRESHOLD} %`
    )
  );

  return result;
}

// An empty series that only draws a dashed horizontal threshold line,
// so that the threshold also gets its own legend entry.
function thresholdSeries(name, yAxisIndex, value, color, label) {
  return {
    id: `threshold-${yAxisIndex}`,
    name,
    type: "line",
    yAxisIndex,
    data: [],
    itemStyle: { color },
    lineStyle: { color, type: "dashed" },
    markLine: {
      silent: true,
      symbol: "none",
      lineStyle: { color, type: "dashed", width: 2 },
      label: { formatter: label, position: "insideEndTop", color },
      data: [{ yAxis: value }]
    }
  };
}

// Keep the threshold visible even when all values are far below it.
function axisRange(threshold, padding) {
  return {
    min: (value) => Math.floor(Math.min(value.min, threshold) - padding),
    max: (value) => Math.ceil(Math.max(value.max, threshold) + padding)
  };
}

function formatAxisTime(timestamp) {
  return new Date(timestamp).toLocaleTimeString("en-GB", { hour12: false });
}

function renderChart() {
  if (!chart) {
    return;
  }

  chart.setOption(
    {
      backgroundColor: "transparent",
      animation: false,
      tooltip: {
        trigger: "axis",
        valueFormatter: (value) => (typeof value === "number" ? value.toFixed(1) : value)
      },
      legend: {
        top: 0,
        type: "plain",
        textStyle: { color: "#c4d4de" },
        pageTextStyle: { color: "#c4d4de" }
      },
      grid: {
        top: 84,
        left: 20,
        right: 24,
        bottom: 18,
        containLabel: true
      },
      xAxis: {
        type: "time",
        axisLine: { lineStyle: { color: "rgba(196, 212, 222, 0.22)" } },
        axisLabel: { color: "#96a9b5", formatter: formatAxisTime, hideOverlap: true },
        splitLine: { show: false }
      },
      yAxis: [
        {
          type: "value",
          name: "Temperature (C)",
          ...axisRange(TEMP_ALERT_THRESHOLD, 2),
          nameTextStyle: { color: "#96a9b5", align: "left" },
          axisLabel: { color: "#96a9b5" },
          splitLine: { lineStyle: { color: "rgba(196, 212, 222, 0.12)" } }
        },
        {
          type: "value",
          name: "Humidity (%)",
          ...axisRange(HUMIDITY_ALERT_THRESHOLD, 5),
          nameTextStyle: { color: "#96a9b5", align: "right" },
          axisLabel: { color: "#96a9b5" },
          splitLine: { show: false }
        }
      ],
      series: buildSeries()
    },
    { replaceMerge: ["series"] }
  );
}

function handleResize() {
  chart?.resize();
}

onMounted(() => {
  chart = echarts.init(chartRef.value);
  renderChart();
  window.addEventListener("resize", handleResize);
});

watch(
  () => props.series,
  () => {
    renderChart();
  },
  { deep: true }
);

onBeforeUnmount(() => {
  window.removeEventListener("resize", handleResize);
  chart?.dispose();
});
</script>
