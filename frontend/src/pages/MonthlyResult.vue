<template>
  <div class="page">
    <van-nav-bar title="月度体检结果" left-text="首页" left-arrow @click-left="$router.push('/')" />
    <van-loading v-if="loading" vertical style="padding-top: 80px;">正在读取报告...</van-loading>
    <template v-else-if="data">
      <!-- Score Card -->
      <div class="card card-elevated" style="text-align: center;">
        <div class="subtle" style="margin-bottom: 8px;">{{ data.store.store_name }} | {{ data.check_month }}</div>
        <div class="score">{{ data.total_score }}<span> 分</span></div>
        <van-tag size="large" type="success" style="margin: 12px 0;">评级 {{ data.rating }}</van-tag>
        <p style="font-size: 14px; color: var(--text-secondary); line-height: 1.8; margin-top: 12px;">
          {{ data.ai_report.monthly_summary }}
        </p>
        <div style="margin-top: 16px;" v-if="data.report_url">
          <van-button type="primary" block round :url="data.report_url" size="small">下载报告</van-button>
        </div>
      </div>

      <!-- Radar Chart -->
      <div class="card">
        <div class="section-title">人货场客财数雷达图</div>
        <RadarChart :dimensions="data.dimensions" />
      </div>

      <!-- Core Problems -->
      <div class="card report-text">
        <div class="section-title">本月核心问题</div>
        <div v-for="item in data.ai_report.top_three_problems" :key="item.problem" class="problem-item">
          <h3>{{ item.problem }}</h3>
          <p>{{ item.impact_next_month }}</p>
          <van-tag v-if="item.priority === 'high'" type="danger" size="small">优先处理</van-tag>
          <van-tag v-else type="warning" size="small">建议关注</van-tag>
        </div>
      </div>

      <!-- Next Month Plan -->
      <div class="card">
        <div class="section-title">下月行动计划</div>
        <div class="action-list">
          <div class="action-item" v-for="item in data.ai_report.next_month_action_plan" :key="item.week">
            <div class="action-period">{{ item.week }}</div>
            <div class="action-content">{{ item.action }}</div>
            <div class="action-goal">{{ item.target }}</div>
          </div>
        </div>
      </div>

      <!-- Boss Advice -->
      <div class="card" v-if="data.ai_report.boss_decision_advice">
        <div class="section-title">老板决策建议</div>
        <p style="font-size: 14px; color: var(--text-secondary); line-height: 1.8;">
          {{ data.ai_report.boss_decision_advice }}
        </p>
      </div>

      <!-- Next Steps -->
      <div class="btn-row">
        <van-button block round type="success" :to="`/monthly/trends/${data.store.id}`">查看趋势</van-button>
      </div>
      <div class="btn-row">
        <van-button block round plain to="/monthly/form" style="color: var(--text-secondary); border-color: rgba(26,107,92,0.15);">
          下月继续体检
        </van-button>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api'
import RadarChart from '../components/RadarChart.vue'

const route = useRoute()
const loading = ref(true)
const data = ref<any>(null)

onMounted(async () => {
  const res = await api.get(`/api/monthly-checkups/${route.params.id}`)
  data.value = res.data.data
  loading.value = false
})
</script>

<style scoped>
.problem-item {
  padding: 12px 0;
  border-bottom: 1px solid rgba(26,107,92,0.06);
}
.problem-item:last-child {
  border-bottom: none;
}
.problem-item h3 {
  font-size: 15px;
  color: var(--brand);
  margin-bottom: 4px;
}
.problem-item p {
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 8px;
}
.action-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.action-item {
  background: linear-gradient(135deg, #f0faf7 0%, #e8f5f1 100%);
  border-radius: 12px;
  padding: 14px 16px;
  border-left: 3px solid var(--brand);
}
.action-period {
  font-size: 13px;
  font-weight: 700;
  color: var(--brand);
  margin-bottom: 4px;
}
.action-content {
  font-size: 14px;
  color: var(--text);
  line-height: 1.6;
  margin-bottom: 4px;
}
.action-goal {
  font-size: 12px;
  color: var(--text-muted);
}
</style>
