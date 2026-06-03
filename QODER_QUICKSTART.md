# QODER_QUICKSTART.md｜给阿里云 Qoder 的快速启动说明

## 一、先判断：当前项目是什么？

当前项目是：

```text
H5前端 + FastAPI后端 + PostgreSQL + Redis + Docker Compose
```

不是微信小程序原生项目。  
不是微信云开发项目。

当前目标是先让系统在服务器上跑起来，让用户通过网页/H5链接使用。

---

## 二、Qoder 第一次打开项目后，请先做这5件事

### 1. 阅读以下文件

```text
AI_INSTRUCTIONS.md
README.md
docs/DEPLOYMENT.md
docs/API.md
docs/SCORING.md
docs/LLM.md
```

### 2. 检查项目结构

确认存在：

```text
frontend/
backend/
docker-compose.yml
.env.example
```

### 3. 复制环境变量

```bash
cp .env.example .env
```

### 4. 启动服务

```bash
docker compose up -d --build
```

### 5. 打开服务

```text
前端：http://localhost:8080
后端接口文档：http://localhost:8000/docs
```

---

## 三、如果启动失败，优先检查

1. Docker 是否安装；
2. 端口 8080、8000、5432、6379 是否被占用；
3. PostgreSQL 容器是否正常；
4. backend 日志是否有依赖安装失败；
5. frontend 是否 npm 依赖安装失败。

常用命令：

```bash
docker compose ps
docker compose logs backend
docker compose logs frontend
docker compose logs postgres
```

---

## 四、Qoder 修复任务 Prompt

可以直接对 Qoder 说：

```text
请先不要重构项目。请读取 AI_INSTRUCTIONS.md 和 README.md，按 docker compose 启动项目。如果启动失败，请只修复启动问题，保持现有业务结构不变。修复后告诉我访问地址和测试步骤。
```

---

## 五、Qoder 页面美化任务 Prompt

启动成功后，再说：

```text
请在不改变接口和业务逻辑的前提下，优化 frontend 的移动端页面视觉。要求：适合美业门店老板使用，页面简洁、高级、按钮明显，表单易填写，结果页突出分数、风险和行动建议。
```

---

## 六、Qoder PDF优化任务 Prompt

```text
请优化 backend/app/templates 下的 PDF 报告模板。要求：A4纵向，美业经营诊断报告风格，突出综合得分、维度雷达图、核心问题、15天行动方案和下月经营建议。不要修改评分逻辑。
```

---

## 七、如果要改成微信小程序

不要直接在当前主项目里改。请新建分支或新建目录：

```text
mini-program/
```

然后基于当前API接口开发微信小程序前端。

推荐说法：

```text
请基于当前 backend API，新增一个微信小程序原生前端项目，放在 mini-program/ 目录下。不要删除现有 frontend/ H5项目。
```

