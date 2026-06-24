# 部署清单 · deployment.md（V4.0 可部署稳定版）

## 1. 依赖
后端（`backend/requirements.txt`）：
```
fastapi · uvicorn[standard] · pydantic · pydantic-settings · SQLAlchemy · httpx · python-dotenv
```
- SQLite 内置，零额外依赖即可跑。
- 用 PostgreSQL 时额外装驱动：`pip install "psycopg[binary]"`，并把 `DATABASE_URL` 改为
  `postgresql+psycopg://user:pass@host:5432/meiye_v4`（代码无需改，SQLAlchemy 自动适配）。

前端（`frontend/`）：Node 20，`npm install && npm run build`（Vite）。

## 2. 启动方式

### 本地开发（dev）
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --reload          # http://127.0.0.1:8000/docs
# 前端：cd frontend && npm install && npm run dev（vite 代理 /api → :8000）
```

### 生产（prod）
```bash
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
# 或用下方 Docker 一键
```

## 3. 环境变量（`backend/.env`，模板见 `.env.example`）
| 变量 | 说明 | 默认 |
| --- | --- | --- |
| `APP_ENV` / `APP_PORT` | 环境 / 端口 | dev / 8000 |
| `DATABASE_URL` | 数据库（sqlite/postgres）| `sqlite:///./meiye_v4.db` |
| `DEFAULT_TENANT` | 默认租户 | default |
| `JWT_SECRET` | 鉴权密钥（占位）| change_me |
| `VIDEO_PROVIDER` | `mock` / `volcano_seedance` / `volcano_legacy` | mock |
| `VIDEO_FALLBACK` / `PROVIDER_RETRIES` | 失败回退 / 重试次数 | true / 3 |
| `VIDEO_API_BASE` / `VIDEO_API_KEY` | 火山 Ark 地址 / Bearer Key | - |
| `VOLC_MODEL` | 模型 | doubao-seedance-2.0-260128 |
| `VOLC_AK` / `VOLC_SK` / `VOLC_REGION` / `VOLC_SERVICE` | legacy AK/SK 签名 | - |
| `PROVIDER_TIMEOUT` / `POLL_INTERVAL` | 任务超时 / 轮询间隔（秒）| 120 / 3 |
| `COST_PER_MOTHER` / `COST_PER_CLIP` | 计价单价 | 1.0 / 0.1 |

provider 切换：`VIDEO_PROVIDER=mock`（默认，零依赖跑通）↔ `volcano_seedance`（真实，需 `VIDEO_API_KEY`）。

## 4. Docker 部署
```bash
cd infra
./deploy.sh            # 首次自动生成 backend/.env，再 docker compose up -d --build
```
- `infra/docker-compose.yml`：backend(8000) + frontend(80) + nginx 网关(8080)
- `infra/nginx.conf`：`/api/*` 反代后端，`/` 给前端静态资源
- 访问：前端 `http://<host>:8080`，API `http://<host>:8080/api`，文档 `/api/docs`
- 生产建议：把 SQLite 换 PostgreSQL（compose 可加 db 服务），并配置 HTTPS。

## 5. 健康检查
- `GET /health` → `{"status":"ok"}`
- `GET /api/info` → 当前 provider / env

## 6. 阿里云部署要点
- 镜像构建后推到 ACR，用 ACK/ECS 跑 compose 或 K8s。
- `.env` 走密钥管理（火山 key 不入镜像/仓库）。
- 数据库用 RDS PostgreSQL，改 `DATABASE_URL` 即可。
- 视频产物 URL 来自 provider（火山 CDN）；如需自管存储，在 provider 层落 OSS（属 provider 优化，不影响上层）。
