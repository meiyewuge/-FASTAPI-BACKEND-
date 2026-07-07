# V0.2.0 P0A 加固 — SQLite 备份方案

> 仅 P0A 止血使用，P0B 需迁移到 PostgreSQL。

## 数据库路径

```
/opt/meiye-wuyou-test/data/store_manager_workbench_test.db
```

## 备份脚本

路径：`/opt/scripts/backup_wuyou_db.sh`

```bash
#!/bin/bash
set -euo pipefail

DB_PATH="/opt/meiye-wuyou-test/data/store_manager_workbench_test.db"
BACKUP_DIR="/opt/backups/wuyou"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/wuyou_${DATE}.db"

mkdir -p "${BACKUP_DIR}"
sqlite3 "${DB_PATH}" ".backup '${BACKUP_FILE}'"
gzip "${BACKUP_FILE}"

find "${BACKUP_DIR}" -name "wuyou_*.db.gz" -mtime +14 -delete
echo "[backup] $(date): ${BACKUP_FILE}.gz created"
```

## 权限

```bash
chmod +x /opt/scripts/backup_wuyou_db.sh
```

## 定时任务

```bash
# 每日 03:00 自动备份
0 3 * * * /opt/scripts/backup_wuyou_db.sh >> /var/log/wuyou_backup.log 2>&1
```

## 保留策略

- 保留最近 14 天备份
- 超时自动清理（`find -mtime +14 -delete`）

## 验证

```bash
# 手动触发
/opt/scripts/backup_wuyou_db.sh

# 查看备份
ls -lh /opt/backups/wuyou/

# 验证备份完整性
sqlite3 /opt/backups/wuyou/wuyou_YYYYMMDD_HHMMSS.db ".tables"
# 应输出：alembic_version diagnoses monthly_checkups ai_reports followups stores

# 验证 cron
crontab -l | grep wuyou
```
