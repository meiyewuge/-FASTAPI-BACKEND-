import Home from '../pages/Home.vue'
import DiagnosisForm from '../pages/DiagnosisForm.vue'
import DiagnosisResult from '../pages/DiagnosisResult.vue'
import MonthlyForm from '../pages/MonthlyForm.vue'
import MonthlyResult from '../pages/MonthlyResult.vue'
import Trends from '../pages/Trends.vue'
import Admin from '../pages/Admin.vue'

export default [
  { path: '/', component: Home },
  { path: '/diagnosis/form', component: DiagnosisForm },
  { path: '/diagnosis/result/:id', component: DiagnosisResult },
  { path: '/monthly/form', component: MonthlyForm },
  { path: '/monthly/result/:id', component: MonthlyResult },
  { path: '/monthly/trends/:storeId', component: Trends },
  { path: '/admin', component: Admin }
]
