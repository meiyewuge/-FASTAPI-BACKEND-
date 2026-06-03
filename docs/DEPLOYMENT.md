# 部署说明

## 1. 准备服务器

推荐 Ubuntu 20.04+，安装 Docker 和 Docker Compose。

## 2. 上传代码

```bash
scp -r store-coach-mvp-v0.1 root@your-server:/opt/store-coach
cd /opt/store-coach
```

## 3. 配置环境变量

```bash
cp .env.example .env
vim .env
```

必须修改：

- `ADMIN_KEY`
- `PUBLIC_BASE_URL`
- `LLM_API_KEY`，没有也能跑，本地模板报告会兜底
- `LLM_BASE_URL`
- `LLM_MODEL`

## 4. 启动

```bash
docker compose up -d --build
```

## 5. 验证

```bash
curl http://localhost:8000/health
```

浏览器访问：

```text
http://服务器IP:8080
http://服务器IP:8000/docs
```

## 6. 配置域名和HTTPS

正式上线建议由运维配置 Nginx：

- 前端域名：`https://你的域名`
- 后端API：`https://api.你的域名`
- PDF报告：后端 `/reports` 路径

## 7. 数据备份

PostgreSQL 数据卷为 `postgres_data`，建议每天自动备份。
