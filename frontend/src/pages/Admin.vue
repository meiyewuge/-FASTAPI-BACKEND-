<template>
  <div class="page">
    <van-nav-bar title="后台线索管理" left-text="首页" left-arrow @click-left="$router.push('/')" />

    <div class="card" v-if="!authenticated">
      <div class="section-title">管理员验证</div>
      <van-field v-model="adminKey" label="Admin Key" placeholder="请输入后台密钥" type="password" />
      <div style="height: 12px;"></div>
      <van-button type="primary" block round @click="saveKey">验证并进入</van-button>
    </div>

    <template v-else>
      <van-tabs v-model:active="tab" @change="load" shrink sticky>
        <van-tab title="门店"></van-tab>
        <van-tab title="诊断"></van-tab>
        <van-tab title="月度"></van-tab>
      </van-tabs>

      <div style="height: 12px;"></div>

      <!-- Stores -->
      <div class="card" v-if="tab===0">
        <div class="section-title">门店列表</div>
        <van-empty v-if="!stores.length" description="暂无门店数据" />
        <div v-else class="store-list">
          <div class="store-item" v-for="s in stores" :key="s.id" @click="openStore(s.id)">
            <div class="store-name">{{ s.store_name }}</div>
            <div class="store-meta">
              <span>{{ s.city }}</span>
              <span>{{ s.contact_person }}</span>
            </div>
            <div class="store-scores">
              <van-tag v-if="s.diagnosis_score" type="primary" size="small">诊断: {{ s.diagnosis_score }}分</van-tag>
              <van-tag v-if="s.monthly_score" type="success" size="small">月度: {{ s.monthly_score }}分</van-tag>
            </div>
          </div>
        </div>
      </div>

      <!-- Diagnoses -->
      <div class="card" v-if="tab===1">
        <div class="section-title">诊断记录</div>
        <van-empty v-if="!diagnoses.length" description="暂无诊断记录" />
        <div v-else class="record-list">
          <div class="record-item" v-for="d in diagnoses" :key="d.id">
            <div class="record-header">
              <span class="record-name">{{ d.store_name }}</span>
              <van-tag type="primary" size="small">{{ d.rating }}</van-tag>
            </div>
            <div class="record-detail">
              得分: {{ d.total_score }}分
              <a v-if="d.report_url" :href="d.report_url" target="_blank" class="report-link">查看报告</a>
            </div>
          </div>
        </div>
      </div>

      <!-- Monthly -->
      <div class="card" v-if="tab===2">
        <div class="section-title">月度体检记录</div>
        <van-empty v-if="!monthly.length" description="暂无月度体检记录" />
        <div v-else class="record-list">
          <div class="record-item" v-for="m in monthly" :key="m.id">
            <div class="record-header">
              <span class="record-name">{{ m.store_name }}</span>
              <van-tag type="success" size="small">{{ m.check_month }}</van-tag>
            </div>
            <div class="record-detail">
              得分: {{ m.total_score }}分 | 业绩: {{ (m.revenue / 10000).toFixed(1) }}万
              <a v-if="m.report_url" :href="m.report_url" target="_blank" class="report-link">查看报告</a>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { showToast, showDialog } from 'vant'
import { adminApi } from '../api'

const adminKey = ref(localStorage.getItem('adminKey') || '')
const authenticated = ref(!!localStorage.getItem('adminKey'))
const tab = ref(0)
const stores = ref<any[]>([])
const diagnoses = ref<any[]>([])
const monthly = ref<any[]>([])

function saveKey() {
  if (!adminKey.value) {
    showToast('请输入密钥')
    return
  }
  localStorage.setItem('adminKey', adminKey.value)
  authenticated.value = true
  load()
}

async function load() {
  try {
    if (tab.value === 0) {
      const r = await adminApi.get('admin/stores')
      stores.value = r.data.data.items
    }
    if (tab.value === 1) {
      const r = await adminApi.get('admin/diagnoses')
      diagnoses.value = r.data.data.items
    }
    if (tab.value === 2) {
      const r = await adminApi.get('admin/monthly-checkups')
      monthly.value = r.data.data.items
    }
  } catch (e: any) {
    if (e?.response?.status === 403) {
      authenticated.value = false
      localStorage.removeItem('adminKey')
      showToast('密钥无效，请重新输入')
    } else {
      showToast(e?.response?.data?.detail || '读取失败')
    }
  }
}

async function openStore(id: number) {
  const r = await adminApi.get(`admin/stores/${id}`)
  const s = r.data.data.store
  showDialog({
    title: s.store_name,
    message: `联系人: ${s.contact_person}\n电话: ${s.contact_phone}\n城市: ${s.city}\n诊断记录: ${r.data.data.diagnoses.length} 次\n月度体检: ${r.data.data.monthly_checkups.length} 次`
  })
}

onMounted(() => {
  if (authenticated.value) load()
})
</script>

<style scoped>
.store-list, .record-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.store-item {
  padding: 14px;
  background: linear-gradient(135deg, #f8fcfb 0%, #f0faf7 100%);
  border-radius: 12px;
  border: 1px solid rgba(26,107,92,0.06);
  cursor: pointer;
  transition: transform 0.2s;
}
.store-item:active {
  transform: scale(0.98);
}
.store-name {
  font-size: 15px;
  font-weight: 700;
  color: var(--text);
  margin-bottom: 4px;
}
.store-meta {
  font-size: 12px;
  color: var(--text-muted);
  display: flex;
  gap: 12px;
  margin-bottom: 8px;
}
.store-scores {
  display: flex;
  gap: 6px;
}
.record-item {
  padding: 12px 14px;
  background: #f8fcfb;
  border-radius: 10px;
  border: 1px solid rgba(26,107,92,0.04);
}
.record-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}
.record-name {
  font-size: 14px;
  font-weight: 600;
}
.record-detail {
  font-size: 12px;
  color: var(--text-secondary);
}
.report-link {
  color: var(--brand);
  text-decoration: none;
  margin-left: 8px;
  font-weight: 500;
}
</style>
