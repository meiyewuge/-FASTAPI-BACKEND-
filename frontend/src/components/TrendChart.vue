<template>
  <div ref="el" class="chart"></div>
</template>

<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps<{ months: string[]; seriesName: string; values: number[] }>()
const el = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null

function render() {
  if (!el.value) return
  chart = chart || echarts.init(el.value)
  chart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 40, right: 20, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: props.months },
    yAxis: { type: 'value' },
    series: [{ name: props.seriesName, type: 'line', smooth: true, data: props.values }]
  })
}

onMounted(() => { render(); window.addEventListener('resize', render) })
onBeforeUnmount(() => { window.removeEventListener('resize', render); chart?.dispose() })
watch(() => [props.months, props.values, props.seriesName], render, { deep: true })
</script>
