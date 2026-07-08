# V0.2.0 P0A 加固 — Nginx 限流配置片段

> 配置片段，需合并到 `/etc/nginx/nginx.conf` 的 `http {}` 块内。

## 限流声明（http 块顶部）

```nginx
# 美业无忧 POST 限流：同 IP 每分钟最多 20 次诊断/月度提交
limit_req_zone $binary_remote_addr zone=wuyou_post:10m rate=20r/m;
```

## 精确匹配（server 块内）

> ⚠️ 必须用 `location =`（精确匹配），避免影响 GET /admin /reports /weapp。

```nginx
# POST /api/diagnoses
location = /api/diagnoses {
    limit_req zone=wuyou_post burst=10 nodelay;
    limit_req_status 429;
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

# POST /api/monthly-checkups
location = /api/monthly-checkups {
    limit_req zone=wuyou_post burst=10 nodelay;
    limit_req_status 429;
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

## 验证

```bash
nginx -t && systemctl reload nginx

# 正常请求
curl -X POST https://api.beautypeaceai.com/api/diagnoses -H 'Content-Type: application/json' -d '{}'
# 应返回 200/422

# 超频请求（>20次/分钟）
for i in $(seq 1 35); do curl -s -o /dev/null -w "%{http_code}\n" -X POST https://api.beautypeaceai.com/api/diagnoses -H 'Content-Type: application/json' -d '{}'; done
# 部分应返回 429

# GET 不误伤
curl -s -o /dev/null -w "%{http_code}" https://api.beautypeaceai.com/api/admin/stores
# 应返回 200/401
```
