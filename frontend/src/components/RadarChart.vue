<template>
  <div ref="el" class="chart"></div>
</template>

<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps<{ dimensions: Array<{ name: string; score: number; max_score: number }> }>()
const el = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null

function render() {
  if (!el.value) return
  chart = chart || echarts.init(el.value)
  const dims = props.dimensions || []
  chart.setOption({
    tooltip: {
      trigger: 'item',
      backgroundColor: 'rgba(255,255,255,0.95)',
      borderColor: '#e8f5f1',
      borderWidth: 1,
      textStyle: { color: '#1a2e2a', fontSize: 13 }
    },
    radar: {
      indicator: dims.map(d => ({ name: `${d.name}\n${d.score}/${d.max_score}`, max: d.max_score })),
      radius: '62%',
      axisName: {
        color: '#5a7a72',
        fontSize: 12,
        fontWeight: 500
      },
      splitArea: {
        areaStyle: {
          color: ['#f0faf7', '#e8f5f1', '#ddf0eb', '#d0ebe4', '#c4e6dd']
        }
      },
      splitLine: {
        lineStyle: { color: 'rgba(26,107,92,0.1)' }
      },
      axisLine: {
        lineStyle: { color: 'rgba(26,107,92,0.15)' }
      }
    },
    series: [{
      type: 'radar',
      data: [{
        value: dims.map(d => d.score),
        name: '得分',
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: {
          color: '#1a6b5c',
          width: 2
        },
        itemStyle: {
          color: '#1a6b5c',
          borderColor: '#fff',
          borderWidth: 2
        },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(45,212,168,0.35)' },
            { offset: 1, color: 'rgba(26,107,92,0.08)' }
          ])
        }
      }],
      animationDuration: 800,
      animationEasing: 'cubicOut'
    }]
  })
}

onMounted(() => { render(); window.addEventListener('resize', render) })
onBeforeUnmount(() => { window.removeEventListener('resize', render); chart?.dispose() })
watch(() => props.dimensions, render, { deep: true })
</script>
