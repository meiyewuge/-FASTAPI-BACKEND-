# API接口文档 MVP V0.1

## 创建首次诊断

POST `/api/diagnoses`

```json
{
  "store_info": {
    "store_name": "星光美容院",
    "city": "北京朝阳区",
    "contact_person": "张总",
    "contact_phone": "13800138000",
    "store_type": "美容院"
  },
  "form_data": {
    "monthly_revenue": 150000,
    "monthly_visits": 300,
    "average_ticket": 500,
    "repurchase_rate_3m": 35
  }
}
```

## 获取首次诊断

GET `/api/diagnoses/{diagnosis_id}`

## 创建月度体检

POST `/api/monthly-checkups`

```json
{
  "store_id": 1,
  "check_month": "2026-05",
  "form_data": {
    "revenue": 150000,
    "customer_visits": 300,
    "paying_customers": 150,
    "new_customers": 60,
    "old_customers": 90,
    "employee_count": 8,
    "marketing_cost": 12000
  }
}
```

## 获取月度体检

GET `/api/monthly-checkups/{checkup_id}`

## 趋势数据

GET `/api/monthly-checkups/store/{store_id}/trends?months=6`

## 后台接口

后台接口需请求头：

```text
X-Admin-Key: <ADMIN_KEY>
```

- GET `/api/admin/stores`
- GET `/api/admin/stores/{store_id}`
- GET `/api/admin/diagnoses`
- GET `/api/admin/monthly-checkups`
- POST `/api/admin/stores/{store_id}/followups`
