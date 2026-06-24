# api · 统一出口 /api/*

所有请求的唯一入口。负责路由、鉴权、参数校验、统一响应包。
不直接调用 a_engine / b_engine —— 经 services 编排。
