# AI_INSTRUCTIONS.md｜给 Qoder / AI 编程助手看的项目说明

## 1. 项目基本信息

项目名称：门店经营陪跑系统 MVP V0.1  
项目类型：H5 Web 应用 + 自有后端服务 + PostgreSQL 数据库 + Docker Compose 部署  
当前版本定位：可跑通 MVP，不是最终商用精修版

本项目不是微信小程序原生项目，也不是微信云开发项目。当前版本采用 H5 方式，是为了先快速跑通“诊断表单 → 规则评分 → AI报告 → PDF报告 → 后台线索”的闭环。

如果后续需要微信小程序原生版，请在此项目跑通后另开 `mini-program` 分支，不要直接把当前项目改废。

---

## 2. 当前技术栈

### 前端

- Vue 3
- Vite
- TypeScript
- ECharts
- Nginx 静态托管

### 后端

- Python 3.11
- FastAPI
- SQLAlchemy
- PostgreSQL
- Redis
- Jinja2 HTML 模板
- WeasyPrint / PDF 生成依赖（如服务器不兼容，可替换为 Playwright）

### 部署

- Docker
- Docker Compose
- Nginx

---

## 3. 系统目标

帮助美业门店完成两类经营分析：

1. 首次经营诊断：判断门店当前经营短板。
2. 月度经营体检：每个月录入业绩、客流、人货场客财数数据，生成经营体检报告。

系统输出：

- 综合得分
- 维度得分
- MBA经营模型诊断
- AI经营建议
- PDF报告
- 后台线索

---

## 4. 核心原则

请 Qoder / AI 编程助手严格遵守：

1. 不要让大模型直接计算分数。
2. 分数必须由后端规则引擎计算。
3. 大模型只负责报告表达和建议生成。
4. 诊断结论必须能追溯到用户填写数据。
5. 不允许编造用户未填写的数据。
6. 不允许承诺医疗效果。
7. 不允许承诺“保证赚钱”。
8. 优先保证系统可运行，再做页面美化。

---

## 5. 已有核心模块

### 前端页面

- `/` 首页
- `/diagnosis` 首次诊断表单
- `/diagnosis/result/:id` 首次诊断结果页
- `/monthly` 月度体检表单
- `/monthly/result/:id` 月度体检结果页
- `/trends/:storeId` 趋势页
- `/admin` 简易后台

### 后端接口

- `POST /api/diagnoses` 创建首次诊断
- `GET /api/diagnoses/{id}` 获取诊断结果
- `POST /api/monthly-checkups` 创建月度体检
- `GET /api/monthly-checkups/{id}` 获取月度体检结果
- `GET /api/stores/{store_id}/trends` 获取趋势数据
- `GET /api/admin/stores` 后台门店列表
- `GET /api/admin/diagnoses` 后台诊断列表
- `GET /api/admin/monthly-checkups` 后台月度体检列表

---

## 6. Qoder 首次任务建议

请按以下顺序执行，不要一上来重构：

### 第一步：启动项目

```bash
cp .env.example .env
docker compose up -d --build
```

### 第二步：检查服务

- 前端：http://localhost:8080
- 后端：http://localhost:8000/docs

### 第三步：跑通一条首次诊断

在前端填写首次诊断表单，提交后确认：

- 后端能返回诊断ID
- 页面能显示分数
- 后台能看到记录

### 第四步：跑通一条月度体检

在前端填写月度体检表单，提交后确认：

- 后端能返回体检ID
- 页面能显示分数
- 趋势页能显示数据

### 第五步：再做优化

优先级：

1. 修复启动报错
2. 修复接口错误
3. 优化移动端页面
4. 优化PDF模板
5. 增加字段和评分规则
6. 增加后台权限

---

## 7. 环境变量说明

请复制 `.env.example` 为 `.env`，并配置：

```env
DATABASE_URL=postgresql://store_user:store_password@postgres:5432/store_coach
REDIS_URL=redis://redis:6379/0
LLM_PROVIDER=mock
LLM_API_KEY=
LLM_BASE_URL=
LLM_MODEL=
PUBLIC_BASE_URL=http://localhost:8080
```

如果暂时没有大模型 API Key，保持 `LLM_PROVIDER=mock`，系统会使用本地模板报告兜底。

---

## 8. 如果要部署到阿里云

推荐流程：

1. 购买 ECS：Ubuntu 22.04，最低 4核8G。
2. 安装 Docker 和 Docker Compose。
3. 上传本项目代码。
4. 配置 `.env`。
5. 执行 `docker compose up -d --build`。
6. 配置域名解析到服务器公网IP。
7. 配置 Nginx / 宝塔 / 阿里云证书，实现 HTTPS。
8. 修改 `PUBLIC_BASE_URL` 为正式域名。

---

## 9. 不建议 Qoder 直接做的事

1. 不要直接改成微信云开发。
2. 不要直接删除后端规则评分模块。
3. 不要把所有诊断逻辑塞给大模型。
4. 不要先做复杂UI，再修业务逻辑。
5. 不要忽略数据库持久化。

---

## 10. 后续可新建的分支

- `main`：当前 H5 + Docker 版本
- `wechat-miniapp`：微信小程序原生版本
- `admin-pro`：后台增强版本
- `pdf-pro`：报告视觉增强版本
- `scoring-v1.5`：评分规则增强版本

