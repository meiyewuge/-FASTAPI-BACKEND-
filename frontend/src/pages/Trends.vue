<template>
  <div class="page">
    <van-nav-bar title="趋势分析" left-text="返回" left-arrow @click-left="$router.back()" />
    <van-loading v-if="loading" vertical>读取趋势...</van-loading>
    <template v-else>
      <div class="card"><div class="section-title">业绩趋势</div><TrendChart :months="data.months" series-name="业绩" :values="data.revenue" /></div>
      <div class="card"><div class="section-title">体检分趋势</div><TrendChart :months="data.months" series-name="体检分" :values="data.scores" /></div>
      <div class="card"><div class="section-title">复购率趋势</div><TrendChart :months="data.months" series-name="复购率" :values="data.repurchase_rate" /></div>
    </template>
  </div>
</template>
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api'
import TrendChart from '../components/TrendChart.vue'
const route = useRoute(); const loading = ref(true); const data = ref<any>({ months: [], revenue: [], scores: [], repurchase_rate: [] })
onMounted(async () => { const res = await api.get(`/api/monthly-checkups/store/${route.params.storeId}/trends?months=6`); data.value = res.data.data; loading.value = false })
</script>
