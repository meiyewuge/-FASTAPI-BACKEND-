#!/usr/bin/env bash
# 一键部署：前后端 + nginx 网关（docker compose）。
set -euo pipefail
cd "$(dirname "$0")"

# 首次部署自动从模板生成 .env（部署后按需填火山 key / 数据库）
if [ ! -f ../backend/.env ]; then
  cp ../backend/.env.example ../backend/.env
  echo "已从 .env.example 生成 backend/.env，请按需修改（火山 key / 数据库等）。"
fi

docker compose up -d --build
echo "deployed. 前端: http://localhost:8080  后端API: http://localhost:8080/api  文档: http://localhost:8080/api/docs"
