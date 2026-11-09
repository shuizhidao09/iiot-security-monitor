<template>
  <div ref="chartRef" class="chart"></div>
</template>

<script setup>
import * as echarts from "echarts";
import { onBeforeUnmount, onMounted, ref, watch } from "vue";

const props = defineProps({
  data: {
    type: Array,
    default: () => []
  }
});

const chartRef = ref(null);
let chart;

function renderChart() {
  if (!chart) {
    return;
  }

  chart.setOption({
    tooltip: {
      trigger: "axis",
      axisPointer: {
        type: "shadow"
      }
    },
    grid: {
      top: 12,
      left: 12,
      right: 12,
      bottom: 18,
      containLabel: true
    },
    xAxis: {
      type: "category",
      data: props.data.map((item) => item.label),
      axisLabel: {
        color: "#96a9b5"
      },
      axisLine: {
        lineStyle: {
          color: "rgba(196, 212, 222, 0.22)"
        }
      }
    },
    yAxis: {
      type: "value",
      axisLabel: {
        color: "#96a9b5"
      },
      splitLine: {
        lineStyle: {
          color: "rgba(196, 212, 222, 0.12)"
        }
      }
    },
    series: [
      {
        type: "bar",
        data: props.data.map((item) => ({
          value: item.value,
          itemStyle: {
            color:
              item.level === "high" || item.label === "High"
                ? "#ff6a6a"
                : item.level === "medium" || item.label === "Medium"
                  ? "#ffb44a"
                  : item.level === "low" || item.label === "Low"
                    ? "#12d2b7"
                    : "#72b5ff"
          }
        })),
        barWidth: 28,
        borderRadius: [8, 8, 0, 0]
      }
    ]
  });
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
  () => props.data,
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
