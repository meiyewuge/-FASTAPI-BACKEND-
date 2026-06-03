<template>
  <div class="page">
    <van-nav-bar title="月度经营体检" left-text="返回" left-arrow @click-left="$router.back()" />
    <div class="card"><van-steps :active="active" active-color="#0f766e"><van-step v-for="s in steps" :key="s.title">{{ s.title }}</van-step></van-steps></div>
    <van-form @submit="submit">
      <div class="card">
        <div class="section-title">{{ steps[active].title }}</div>
        <van-field v-if="active===0" v-model="storeId" label="已有门店ID" placeholder="已有门店可填，不填则新建" type="number" />
        <template v-if="active===0 && !storeId">
          <van-field v-model="store.store_name" label="门店名称" :rules="[{required: true, message: '请填写门店名称'}]" />
          <van-field v-model="store.city" label="城市区域" :rules="[{required: true, message: '请填写城市'}]" />
          <van-field v-model="store.contact_person" label="联系人" :rules="[{required: true, message: '请填写联系人'}]" />
          <van-field v-model="store.contact_phone" label="联系电话" :rules="[{required: true, message: '请填写手机号'}]" />
        </template>
        <van-field v-for="field in steps[active].fields" :key="field.key" v-model="form[field.key]" :label="field.label" :type="field.type === 'number' ? 'number' : 'text'" :rules="field.required ? [{required: true, message: '请填写' + field.label}] : []" />
      </div>
      <div class="btn-row">
        <van-button v-if="active>0" block round @click="active--">上一步</van-button>
        <van-button v-if="active<steps.length-1" block round type="primary" native-type="button" @click="active++">下一步</van-button>
        <van-button v-else block round type="primary" native-type="submit" :loading="loading">生成月度报告</van-button>
      </div>
    </van-form>
  </div>
</template>
<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { showToast } from 'vant'
import { api } from '../api'
const router = useRouter(); const active = ref(0); const loading = ref(false); const storeId = ref(localStorage.getItem('lastStoreId') || '')
const store = reactive<any>({ store_name: '', city: '', contact_person: '', contact_phone: '', store_type: '美容院', source_channel: 'H5月度体检' })
const form = reactive<any>({
  check_month: new Date().toISOString().slice(0,7), revenue: 150000, customer_visits: 300, paying_customers: 150, new_customers: 60, old_customers: 90, average_ticket: 1000, recharge_amount: 50000, consumed_amount: 90000, refund_amount: 0,
  employee_count: 8, resigned_count: 0, champion_sales: 50000, staff_avg_sales: 18000, training_count: 2, complaint_count: 1,
  main_project_name: '颈脑项目', main_project_orders: 30, main_project_revenue: 45000, traffic_project_revenue: 30000, profit_project_revenue: 90000, premium_project_revenue: 30000, consumable_cost: 12000, inventory_backlog_amount: 8000,
  satisfaction_score: 8, meituan_rating: 4.7, douyin_groupbuy_rating: 4.8, bad_review_count: 1, followup_customer_count: 100,
  active_members: 200, repurchase_customers: 55, reactivated_members: 12, referral_customers: 6, private_domain_customers: 20, churn_risk_members: 30,
  douyin_new_followers: 300, douyin_views: 80000, douyin_orders: 35, meituan_orders: 40, private_domain_new_contacts: 80, live_sessions: 8, short_video_count: 20, marketing_cost: 12000,
  rent_cost: 20000, labor_cost: 40000, platform_commission: 5000, water_electric_cost: 3000, gross_margin_rate: 60
})
const steps = [
  { title: '经营', fields: [{key:'check_month',label:'体检月份',required:true},{key:'revenue',label:'本月总业绩',type:'number',required:true},{key:'customer_visits',label:'本月到店人次',type:'number',required:true},{key:'paying_customers',label:'本月成交人数',type:'number',required:true},{key:'new_customers',label:'本月新客数',type:'number',required:true},{key:'old_customers',label:'本月老客数',type:'number',required:true}] },
  { title: '人', fields: [{key:'employee_count',label:'员工人数',type:'number',required:true},{key:'resigned_count',label:'离职人数',type:'number'},{key:'champion_sales',label:'销售冠军业绩',type:'number'},{key:'training_count',label:'培训次数',type:'number'},{key:'complaint_count',label:'投诉数',type:'number'}] },
  { title: '货', fields: [{key:'main_project_name',label:'本月主推项目'},{key:'main_project_orders',label:'主推项目单数',type:'number'},{key:'main_project_revenue',label:'主推项目业绩',type:'number'},{key:'traffic_project_revenue',label:'引流项目业绩',type:'number'},{key:'profit_project_revenue',label:'利润项目业绩',type:'number'},{key:'premium_project_revenue',label:'高端项目业绩',type:'number'}] },
  { title: '场客', fields: [{key:'satisfaction_score',label:'满意度1-10',type:'number'},{key:'meituan_rating',label:'美团评分',type:'number'},{key:'bad_review_count',label:'差评数量',type:'number'},{key:'followup_customer_count',label:'回访客户数',type:'number'},{key:'repurchase_customers',label:'复购客户数',type:'number'},{key:'referral_customers',label:'老带新人数',type:'number'}] },
  { title: '数财', fields: [{key:'douyin_views',label:'抖音播放量',type:'number'},{key:'douyin_orders',label:'抖音团购订单',type:'number'},{key:'private_domain_new_contacts',label:'私域新增好友',type:'number'},{key:'live_sessions',label:'直播场次',type:'number'},{key:'short_video_count',label:'短视频条数',type:'number'},{key:'marketing_cost',label:'营销投入',type:'number',required:true},{key:'rent_cost',label:'房租',type:'number'},{key:'labor_cost',label:'人工成本',type:'number'},{key:'gross_margin_rate',label:'毛利率%',type:'number'}] }
]
const saved = localStorage.getItem('monthlyForm'); if (saved) Object.assign(form, JSON.parse(saved))
watch(form, () => localStorage.setItem('monthlyForm', JSON.stringify(form)), { deep: true })
async function submit() {
  loading.value = true
  try {
    const { check_month, ...form_data } = form
    const payload: any = { check_month, form_data }
    if (storeId.value) payload.store_id = Number(storeId.value); else payload.store_info = store
    const res = await api.post('/api/monthly-checkups', payload)
    localStorage.setItem('lastStoreId', String(res.data.data.store_id))
    showToast('月度报告已生成')
    router.push(`/monthly/result/${res.data.data.checkup_id}`)
  } catch(e:any) { showToast(e?.response?.data?.detail || '提交失败') } finally { loading.value = false }
}
</script>
