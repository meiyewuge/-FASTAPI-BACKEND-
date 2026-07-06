"""webview-token H5 域名回归测试（V0.1.3）。

覆盖工单要求：
- 默认配置返回 wuyou 子域；
- 设置 H5_BASE_URL（settings.h5_base_url）后按配置读取（非硬编码）；
- 返回 URL 不含 https://beautypeaceai.com/diagnosis（旧根域硬编码反向断言）；
- 返回 URL 不跳 www；
- ticket 参数仍存在；
- 不影响 /health；
- 不影响已有路由导入。
"""
from fastapi.testclient import TestClient

from app.main import app
from app.config import settings

client = TestClient(app)

WEBVIEW_URL = "/api/coach/webview-token"


def _post(target="diagnosis"):
    resp = client.post(WEBVIEW_URL, json={"target": target})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    return data["url"], data["ticket"]


def test_default_returns_wuyou():
    """默认配置：diagnosis → wuyou 子域 + /diagnosis/form?ticket= 开头。"""
    url, ticket = _post("diagnosis")
    assert url.startswith("https://wuyou.beautypeaceai.com/diagnosis/form?ticket="), url
    assert ticket and ticket in url


def test_monthly_returns_form():
    """monthly → /monthly/form（H5 实际存在的路由）。"""
    url, _ = _post("monthly")
    assert url.startswith("https://wuyou.beautypeaceai.com/monthly/form?ticket="), url


def test_history_safe_landing():
    """history：H5 暂无通用历史页 → 安全落地首页 /，不伪造未验证路由。"""
    url, _ = _post("history")
    assert url.startswith("https://wuyou.beautypeaceai.com/?ticket="), url


def test_unknown_target_defaults_to_form():
    """未知 target → 默认落 /diagnosis/form（默认兜底也不得是 /diagnosis/start）。"""
    url, _ = _post("something_unknown")
    assert url.startswith("https://wuyou.beautypeaceai.com/diagnosis/form?ticket="), url


def test_no_legacy_start_paths():
    """反向断言：任何 target 都不得再出现 /diagnosis/start 或 /monthly/start。"""
    for t in ("diagnosis", "monthly", "history", "zzz"):
        url, _ = _post(t)
        assert "/diagnosis/start" not in url, url
        assert "/monthly/start" not in url, url


def test_reads_config_not_hardcoded(monkeypatch):
    """设置 settings.h5_base_url 后，返回 URL 按配置走（证明读配置而非硬编码）。"""
    monkeypatch.setattr(settings, "h5_base_url", "https://custom-h5.example.com")
    url, _ = _post("diagnosis")
    assert url.startswith("https://custom-h5.example.com/diagnosis/form?ticket="), url


def test_rstrip_trailing_slash(monkeypatch):
    """配置带尾斜杠时 rstrip 生效，不产生双斜杠。"""
    monkeypatch.setattr(settings, "h5_base_url", "https://wuyou.beautypeaceai.com/")
    url, _ = _post("diagnosis")
    assert url.startswith("https://wuyou.beautypeaceai.com/diagnosis/form?ticket="), url
    assert "beautypeaceai.com//diagnosis" not in url, url


def test_no_root_domain_diagnosis():
    """反向断言：不得再出现旧根域 https://beautypeaceai.com/diagnosis。"""
    url, _ = _post("diagnosis")
    assert "https://beautypeaceai.com/diagnosis" not in url, url


def test_no_www():
    """不得跳 www 根域。"""
    url, _ = _post("diagnosis")
    assert "www.beautypeaceai.com" not in url, url


def test_ticket_param_present():
    """ticket 查询参数仍在，且与返回的 ticket 一致。"""
    url, ticket = _post("diagnosis")
    assert "ticket=" in url
    assert f"ticket={ticket}" in url


def test_health_unaffected():
    """/health 不受影响。"""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json().get("status") == "ok"


def test_routes_import_intact():
    """已有路由导入完好：webview-token 路径已注册，路由数量正常。"""
    paths = {getattr(r, "path", None) for r in app.routes}
    assert WEBVIEW_URL in paths
    assert "/health" in paths
    assert len(app.routes) > 10
