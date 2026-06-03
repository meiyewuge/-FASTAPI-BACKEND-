import axios from 'axios'

export const API_BASE = import.meta.env.VITE_API_BASE || ''

export const api = axios.create({
  baseURL: API_BASE,
  timeout: 120000
})

export function getAdminKey() {
  return localStorage.getItem('adminKey') || ''
}

export const adminApi = axios.create({
  baseURL: API_BASE,
  timeout: 120000
})

adminApi.interceptors.request.use(config => {
  config.headers = config.headers || {}
  config.headers['X-Admin-Key'] = getAdminKey()
  return config
})
