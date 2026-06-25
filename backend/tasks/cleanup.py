"""到期文件清理入口（V4 P0）。

供 systemd timer / cron 每日调用：
    cd /opt/v4-video-engine/backend && python -m tasks.cleanup

扫描 expires_at < now 的视频/上传，删服务器文件并置 storage_status=expired（保留 DB 记录）。
"""

from __future__ import annotations

from db import SessionLocal
from services import storage_service


def run() -> dict:
    db = SessionLocal()
    try:
        return storage_service.run_cleanup(db)
    finally:
        db.close()


if __name__ == "__main__":
    result = run()
    print(f"[cleanup] videos_expired={result['videos_expired']} uploads_expired={result['uploads_expired']}")
