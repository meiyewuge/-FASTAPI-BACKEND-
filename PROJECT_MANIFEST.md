# PROJECT_MANIFEST.md｜项目文件清单

## 根目录

- `README.md`：项目说明
- `AI_INSTRUCTIONS.md`：给 Qoder / AI 编程助手看的总说明
- `QODER_QUICKSTART.md`：Qoder 快速启动指南
- `QODER_QUEST_PROMPT.md`：可复制给 Qoder 的任务指令
- `.env.example`：环境变量模板
- `docker-compose.yml`：一键启动配置

## 前端目录 frontend/

- `src/pages/Home.vue`：首页
- `src/pages/DiagnosisForm.vue`：首次诊断表单
- `src/pages/DiagnosisResult.vue`：首次诊断结果
- `src/pages/MonthlyForm.vue`：月度体检表单
- `src/pages/MonthlyResult.vue`：月度体检结果
- `src/pages/Trends.vue`：趋势页
- `src/pages/Admin.vue`：简易后台
- `src/components/RadarChart.vue`：雷达图组件
- `src/components/TrendChart.vue`：趋势图组件
- `src/api.ts`：前端API封装

## 后端目录 backend/

- `app/main.py`：FastAPI入口
- `app/models.py`：数据库模型
- `app/schemas.py`：接口数据结构
- `app/scoring.py`：评分规则引擎
- `app/mba_models.py`：MBA模型诊断
- `app/ai.py`：AI报告生成
- `app/report.py`：PDF报告生成
- `app/routers/diagnoses.py`：首次诊断接口
- `app/routers/monthly.py`：月度体检接口
- `app/routers/admin.py`：后台接口
- `app/templates/`：HTML/PDF报告模板

## 文档目录 docs/

- `API.md`：接口文档
- `DEPLOYMENT.md`：部署说明
- `SCORING.md`：评分说明
- `LLM.md`：大模型配置说明

