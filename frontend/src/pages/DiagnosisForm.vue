<template>
  <div class="page">
    <van-nav-bar title="首次经营诊断" left-text="返回" left-arrow @click-left="$router.back()" />
    <div class="card">
      <van-steps :active="active" active-color="#0f766e">
        <van-step v-for="s in steps" :key="s.title">{{ s.title }}</van-step>
      </van-steps>
    </div>

    <van-form @submit="submit">
      <div class="card">
        <div class="section-title">{{ steps[active].title }}</div>
        <template v-for="field in steps[active].fields" :key="field.key">
          <van-field
            v-if="field.type !== 'select' && field.type !== 'checkbox' && field.type !== 'boolean'"
            v-model="form[field.key]"
            :name="field.key"
            :label="field.label"
            :placeholder="field.placeholder || '请输入'"
            :type="field.type === 'number' ? 'number' : 'text'"
            :rules="field.required ? [{ required: true, message: '请填写' + field.label }] : []"
          />
          <van-field v-else-if="field.type === 'select'" :label="field.label">
            <template #input>
              <van-checkbox-group v-model="form[field.key]" direction="horizontal">
                <van-checkbox v-for="op in field.options" :key="op" :name="op" shape="square">{{ op }}</van-checkbox>
              </van-checkbox-group>
            </template>
          </van-field>
          <van-field v-else-if="field.type === 'boolean'" :label="field.label">
            <template #input><van-switch v-model="form[field.key]" /></template>
          </van-field>
        </template>
      </div>

      <div class="btn-row">
        <van-button v-if="active > 0" block round @click="active--">上一步</van-button>
        <van-button v-if="active < steps.length - 1" block round type="primary" native-type="button" @click="next">下一步</van-button>
        <van-button v-else block round type="primary" native-type="submit" :loading="loading">生成诊断报告</van-button>
      </div>
    </van-form>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { showToast } from 'vant'
import { api } from '../api'

const router = useRouter()
const active = ref(0)
const loading = ref(false)

const form = reactive<any>({
  store_name: '', city: '', contact_person: '', contact_phone: '', store_type: '美容院',
  years_in_business: 5, store_area: 150, employee_count: 8, monthly_visits: 300, monthly_revenue: 150000, average_ticket: 500,
  monthly_rent: 20000, monthly_labor_cost: 40000, monthly_consumable_cost: 10000,
  total_members: 500, active_members_3m: 200, old_customer_ratio: 60, new_customer_ratio: 40, repurchase_rate_3m: 35,
  traffic_product_count: 3, traffic_product_avg_price: 99, traffic_product_revenue_ratio: 20,
  profit_product_count: 5, profit_product_avg_price: 399, profit_product_revenue_ratio: 60,
  premium_product_count: 2, premium_product_avg_price: 1299, premium_product_revenue_ratio: 20, main_product_gross_margin: 60,
  visit_conversion_rate: 50, new_customer_conversion_rate: 30, old_customer_conversion_rate: 70, champion_monthly_sales: 50000, staff_avg_monthly_sales: 18000,
  staff_avg_years: 2, staff_turnover_rate_3m: 15, has_sales_script: true, has_service_sop: true,
  douyin_rating: 4.8, meituan_rating: 4.5, negative_review_types: ['服务'], monthly_marketing_cost: 10000, main_marketing_channels: ['抖音', '美团'],
  douyin_cac: 200, meituan_cac: 150, referral_cac: 50, douyin_monthly_revenue: 30000, meituan_monthly_revenue: 40000, private_domain_monthly_revenue: 20000,
  has_crm: true, has_douyin_account: true, douyin_followers: 1500, douyin_monthly_views: 50000, has_douyin_local_life: false
})

const steps = [
  { title: '基础', fields: [
    { key: 'store_name', label: '门店名称', required: true }, { key: 'city', label: '城市区域', required: true }, { key: 'contact_person', label: '联系人', required: true }, { key: 'contact_phone', label: '联系电话', required: true }, { key: 'store_type', label: '门店类型' }
  ]},
  { title: '经营', fields: [
    { key: 'years_in_business', label: '经营年限', type: 'number', required: true }, { key: 'store_area', label: '门店面积㎡', type: 'number', required: true }, { key: 'employee_count', label: '员工人数', type: 'number', required: true }, { key: 'monthly_visits', label: '月均到店客流', type: 'number', required: true }, { key: 'monthly_revenue', label: '月均业绩', type: 'number', required: true }, { key: 'average_ticket', label: '月均客单价', type: 'number', required: true }
  ]},
  { title: '客户', fields: [
    { key: 'total_members', label: '总会员数', type: 'number', required: true }, { key: 'active_members_3m', label: '3个月活跃会员', type: 'number', required: true }, { key: 'old_customer_ratio', label: '老客占比%', type: 'number', required: true }, { key: 'new_customer_ratio', label: '新客占比%', type: 'number', required: true }, { key: 'repurchase_rate_3m', label: '3个月复购率%', type: 'number', required: true }
  ]},
  { title: '品项', fields: [
    { key: 'traffic_product_revenue_ratio', label: '引流款业绩占比%', type: 'number', required: true }, { key: 'profit_product_revenue_ratio', label: '利润款业绩占比%', type: 'number', required: true }, { key: 'premium_product_revenue_ratio', label: '高端款业绩占比%', type: 'number', required: true }, { key: 'premium_product_count', label: '高端款项目数量', type: 'number', required: true }, { key: 'main_product_gross_margin', label: '主推项目毛利率%', type: 'number' }
  ]},
  { title: '转化', fields: [
    { key: 'visit_conversion_rate', label: '到店转化率%', type: 'number', required: true }, { key: 'new_customer_conversion_rate', label: '新客转化率%', type: 'number', required: true }, { key: 'old_customer_conversion_rate', label: '老客转化率%', type: 'number' }, { key: 'champion_monthly_sales', label: '销售冠军月业绩', type: 'number', required: true }, { key: 'staff_avg_monthly_sales', label: '员工平均月业绩', type: 'number', required: true }
  ]},
  { title: '团队', fields: [
    { key: 'staff_avg_years', label: '员工平均从业年限', type: 'number' }, { key: 'staff_turnover_rate_3m', label: '3个月员工流失率%', type: 'number' }, { key: 'has_sales_script', label: '是否有标准话术', type: 'boolean' }, { key: 'has_service_sop', label: '是否有服务SOP', type: 'boolean' }
  ]},
  { title: '评价', fields: [
    { key: 'douyin_rating', label: '抖音评分', type: 'number', required: true }, { key: 'meituan_rating', label: '美团/点评评分', type: 'number', required: true }, { key: 'negative_review_types', label: '主要差评类型', type: 'select', options: ['服务', '技术', '效果', '环境', '价格'], required: true }
  ]},
  { title: '营销', fields: [
    { key: 'monthly_marketing_cost', label: '月均营销投入', type: 'number', required: true }, { key: 'main_marketing_channels', label: '主要营销渠道', type: 'select', options: ['抖音', '美团', '小红书', '私域', '老带新', '其他'], required: true }, { key: 'douyin_monthly_revenue', label: '抖音月成交额', type: 'number' }, { key: 'meituan_monthly_revenue', label: '美团月成交额', type: 'number' }, { key: 'private_domain_monthly_revenue', label: '私域月成交额', type: 'number' }
  ]},
  { title: '数字化', fields: [
    { key: 'has_crm', label: '是否有CRM', type: 'boolean', required: true }, { key: 'has_douyin_account', label: '是否有抖音账号', type: 'boolean', required: true }, { key: 'douyin_followers', label: '抖音粉丝数', type: 'number' }, { key: 'douyin_monthly_views', label: '抖音月均播放量', type: 'number' }, { key: 'has_douyin_local_life', label: '是否接入抖音来客', type: 'boolean' }
  ]}
]

const saved = localStorage.getItem('diagnosisForm')
if (saved) Object.assign(form, JSON.parse(saved))
watch(form, () => localStorage.setItem('diagnosisForm', JSON.stringify(form)), { deep: true })

function next() { active.value++ }

async function submit() {
  loading.value = true
  try {
    const { store_name, city, contact_person, contact_phone, store_type } = form
    const store_info = { store_name, city, contact_person, contact_phone, store_type, source_channel: 'H5诊断' }
    const form_data = { ...form }
    delete form_data.store_name; delete form_data.city; delete form_data.contact_person; delete form_data.contact_phone; delete form_data.store_type
    const res = await api.post('/api/diagnoses', { store_info, form_data })
    const id = res.data.data.diagnosis_id
    // P0B-2: 读取 access_token
    const accessToken = res.data.data.access_token
    localStorage.setItem('lastStoreId', String(res.data.data.store_id))
    if (!accessToken) {
      // P0B-2: access_token 缺失，不裸跳结果页
      showToast('报告生成成功，但访问凭证缺失，请联系工作人员')
      return
    }
    // P0B-2: 跳转携带 token（encodeURIComponent 防止特殊字符）
    showToast('诊断报告已生成')
    router.push(`/diagnosis/result/${id}?token=${encodeURIComponent(accessToken)}`)
  } catch (e: any) {
    showToast(e?.response?.data?.detail || '提交失败')
  } finally { loading.value = false }
}
</script>
