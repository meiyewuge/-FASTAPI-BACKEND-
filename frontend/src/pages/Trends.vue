<template>
  <div class="page">
    <van-nav-bar title="趋势分析" left-text="返回" left-arrow @click-left="$router.back()" />
    <van-loading v-if="loading" vertical>读取趋势...</van-loading>
    <!-- P0B-2: 401 无权访问提示 -->
    <div v-else-if="authError" style="padding: 80px 24px; text-align: center;">
      <van-icon name="warning-o" size="48" color="#e53e3e" />
      <p style="margin-top: 16px; font-size: 15px; color: var(--text-secondary);">
        {{ authError }}
      </p>
    </div>
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
const route = useRoute(); const loading = ref(true); const authError = ref(''); const data = ref<any>({ months: [], revenue: [], scores: [], repurchase_rate: [] })
onMounted(async () => {
  try {
    // P0B-2: 从 URL query 读取 token
    const token = route.query.token as string | undefined
    const params: Record<string, string> = { months: '6' }
    if (token) {
      params.token = token
    }
    const res = await api.get(`/api/monthly-checkups/store/${route.params.storeId}/trends`, { params })
    data.value = res.data.data
  } catch (e: any) {
    if (e?.response?.status === 401) {
      // P0B-2: 401 无权访问
      authError.value = '无权访问趋势数据，请从入口重新进入'
    } else {
      authError.value = e?.response?.data?.detail || '加载失败'
    }
  } finally {
    loading.value = false
  }
})
</script>
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
