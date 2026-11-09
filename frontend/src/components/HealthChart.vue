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
      trigger: "item"
    },
    legend: {
      bottom: 0,
      textStyle: {
        color: "#c4d4de"
      }
    },
    series: [
      {
        type: "pie",
        radius: ["56%", "74%"],
        center: ["50%", "44%"],
        label: {
          color: "#d8e5ed",
          formatter: "{b}\n{c}"
        },
        itemStyle: {
          borderRadius: 6,
          borderColor: "#0f1720",
          borderWidth: 4
        },
        data: props.data.map((item) => ({
          ...item,
          itemStyle: {
            color:
              item.name === "Normal"
                ? "#12d2b7"
                : item.name === "Warning"
                  ? "#ffb44a"
                  : "#ff6a6a"
          }
        }))
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
