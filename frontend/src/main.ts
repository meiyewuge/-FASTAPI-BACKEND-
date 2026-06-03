import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import Vant from 'vant'
import 'vant/lib/index.css'
import './styles/global.css'
import App from './App.vue'
import routes from './router'

const router = createRouter({
  history: createWebHistory(),
  routes
})

createApp(App).use(router).use(Vant).mount('#app')
