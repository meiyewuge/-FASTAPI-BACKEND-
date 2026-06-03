<template>
  <div class="page">
    <div class="hero">
      <span class="brand-tag">美业无忧 AI 经营系统</span>
      <h1>门店经营陪跑系统</h1>
      <p>不是让门店做一次测试，而是让门店每个月做一次经营体检，持续跟踪改善。</p>
    </div>

    <div class="card">
      <div class="section-title">系统核心能力</div>
      <div class="feature-grid">
        <div class="feature-item">
          <span class="feature-icon">&#x1F50D;</span>
          <div class="feature-title">首次诊断</div>
          <div class="feature-desc">看清门店现在卡在哪里</div>
        </div>
        <div class="feature-item">
          <span class="feature-icon">&#x1F4CA;</span>
          <div class="feature-title">月度体检</div>
          <div class="feature-desc">每月检视人货场客财数</div>
        </div>
        <div class="feature-item">
          <span class="feature-icon">&#x1F916;</span>
          <div class="feature-title">AI 报告</div>
          <div class="feature-desc">自动生成行动方案</div>
        </div>
        <div class="feature-item">
          <span class="feature-icon">&#x1F4C8;</span>
          <div class="feature-title">趋势追踪</div>
          <div class="feature-desc">多月数据环比分析</div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="section-title">七大维度评分体系</div>
      <div class="dimension-list">
        <div class="dimension-item" v-for="d in dimensions" :key="d.key">
          <div class="dimension-bar">
            <span class="dimension-name">{{ d.name }}</span>
            <span class="dimension-weight">{{ d.weight }}分</span>
          </div>
          <div class="dimension-progress">
            <div class="dimension-fill" :style="{ width: d.weight + '%' }"></div>
          </div>
        </div>
      </div>
    </div>

    <div class="btn-row">
      <van-button type="primary" block round size="large" to="/diagnosis/form">
        开始首次诊断
      </van-button>
    </div>
    <div class="btn-row">
      <van-button type="success" block round size="large" to="/monthly/form">
        做本月经营体检
      </van-button>
    </div>

    <div style="height: 12px"></div>
    <van-button block plain round to="/admin" style="color: var(--text-secondary); border-color: rgba(26,107,92,0.15);">
      进入后台管理
    </van-button>

    <div class="footer-info">
      <p>美业吴哥 · 门店经营陪跑系统 V0.1</p>
      <p class="subtle">用数据说话，用规则打分，用AI写报告</p>
    </div>
  </div>
</template>

<script setup lang="ts">
const dimensions = [
  { key: 'traffic', name: '流量力', weight: 15 },
  { key: 'conversion', name: '转化力', weight: 15 },
  { key: 'ticket', name: '客单力', weight: 15 },
  { key: 'retention', name: '复购力', weight: 20 },
  { key: 'team', name: '团队力', weight: 10 },
  { key: 'product', name: '产品力', weight: 15 },
  { key: 'digital', name: '数字化力', weight: 10 },
]
</script>

<style scoped>
.dimension-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.dimension-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.dimension-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.dimension-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}
.dimension-weight {
  font-size: 12px;
  color: var(--text-muted);
}
.dimension-progress {
  height: 6px;
  background: #e8f5f1;
  border-radius: 3px;
  overflow: hidden;
}
.dimension-fill {
  height: 100%;
  background: var(--brand-gradient);
  border-radius: 3px;
  transition: width 0.6s ease;
}
.footer-info {
  text-align: center;
  margin-top: 32px;
  padding: 16px 0;
}
.footer-info p {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 0;
}
.footer-info .subtle {
  font-size: 12px;
  margin-top: 4px;
}
</style>
