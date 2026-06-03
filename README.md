# 门店经营陪跑系统 MVP V0.1

定位：美业门店首次经营诊断 + 月度经营体检 + 规则评分 + AI报告 + PDF下载 + 简易后台线索。

## 技术栈

- 前端：Vue3 + Vite + Vant + ECharts
- 后端：FastAPI + SQLAlchemy + PostgreSQL
- PDF：WeasyPrint
- 部署：Docker Compose + Nginx
- 大模型：OpenAI-compatible 接口，支持 DeepSeek / 通义千问兼容接口 / OpenAI 等

## MVP 功能

1. H5 首页
2. 首次经营诊断表单
3. 月度经营体检表单
4. 规则引擎评分
5. AI报告生成，未配置模型时自动使用本地模板报告
6. PDF报告生成和下载
7. 简易后台：门店、诊断、月度体检、跟进备注
8. Docker 一键启动

## 快速启动

```bash
cp .env.example .env
# 修改 .env 里的大模型配置、管理员KEY、域名等

docker compose up -d --build
```

默认访问：

- H5前端：http://localhost:8080
- 后端API：http://localhost:8000/docs
- 报告文件：http://localhost:8000/reports/xxx.pdf

## 本地开发

### 后端

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

## 管理后台

MVP 的后台是前端内置页面：

- `/admin`

后台接口使用 `X-Admin-Key`，默认值配置在 `.env` 的 `ADMIN_KEY`。

## 注意事项

1. 大模型只生成报告文案，不参与评分。
2. 分数由后端 `app/scoring.py` 统一计算。
3. 报告结论由结构化数据 + 规则标签 + AI表达组成。
4. 未配置 LLM_API_KEY 时，系统会使用本地模板生成可用报告。
5. 生产环境必须配置 HTTPS、强 ADMIN_KEY、数据库备份。

---

## 阿里云 Qoder 使用说明

如果你准备用阿里云 Qoder 部署或继续开发，请优先阅读：

1. `AI_INSTRUCTIONS.md`
2. `QODER_QUICKSTART.md`
3. `QODER_QUEST_PROMPT.md`
4. `PROJECT_MANIFEST.md`

当前项目是 H5 + FastAPI + PostgreSQL + Docker Compose 版本。  
它适合先部署成网页/H5，让用户通过链接使用。

如果后续要做微信小程序，不建议直接改掉当前 H5 项目。建议新增：

```text
mini-program/
```

并让小程序调用现有后端 API。

Qoder 首次任务建议：

```text
请先读取 AI_INSTRUCTIONS.md 和 QODER_QUICKSTART.md，不要重构项目，先用 docker compose 把服务跑起来。如果启动失败，只修复启动问题。
```
