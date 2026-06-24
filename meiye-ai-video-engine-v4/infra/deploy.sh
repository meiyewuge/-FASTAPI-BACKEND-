#!/usr/bin/env bash
# 一键部署（skeleton）。
set -euo pipefail
cd "$(dirname "$0")"
docker compose up -d --build
echo "deployed. 前端: http://localhost:8080  后端: http://localhost:8080/api"
