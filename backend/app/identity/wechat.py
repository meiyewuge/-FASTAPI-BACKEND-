"""Real server-side WeChat code2session — injectable transport, no mock fallback.

The HTTP transport is injectable so tests never touch the public internet, while
production performs a genuine call to WeChat. Configuration (app id / secret) is
read from the single Settings source (backend .env or environment) — not a second
os.environ path — so it cannot drift from the startup config gate.

The WeChat code2session protocol REQUIRES WECHAT_APP_SECRET to be sent to WeChat
as an HTTPS query parameter (api.weixin.qq.com over TLS); that transmission is
unavoidable. Our guarantee is narrower: the secret never enters the FRONTEND, our
business LOGS, EXCEPTION messages, the DATABASE, or GIT, and is read only from
Settings. The raw code, session_key and full openid are never logged.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from ..config import settings as _settings

logger = logging.getLogger("identity_wechat")

WECHAT_CODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"


class WeChatError(Exception):
    """Structured WeChat failure. Carries a SAFE reason tag only (never the raw
    errcode/errmsg/secret)."""
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class WeChatClient:
    def __init__(self, app_id: Optional[str] = None, app_secret: Optional[str] = None,
                 transport: Optional[Callable[[str, dict, float], dict]] = None,
                 timeout: Optional[float] = None):
        # single Settings source (no os.environ drift); tests still inject explicitly
        self._app_id = app_id if app_id is not None else _settings.wechat_app_id
        self._app_secret = app_secret if app_secret is not None else _settings.wechat_app_secret
        self._transport = transport or self._http_get_json
        self._timeout = timeout if timeout is not None else _settings.wechat_timeout_seconds

    def _http_get_json(self, url: str, params: dict, timeout: float) -> dict:
        import httpx  # imported lazily so tests with an injected transport need no network stack
        resp = httpx.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    def code2session(self, code: str) -> str:
        """Exchange a one-time login code for an openid. Returns the raw openid on
        success; raises WeChatError (fail-closed) on any error. NEVER returns a
        mock openid."""
        if not code or not isinstance(code, str) or len(code) > 512:
            raise WeChatError("invalid_code")
        if not self._app_id or not self._app_secret:
            # misconfiguration must fail closed, not fall back to a mock
            raise WeChatError("not_configured")
        params = {
            "appid": self._app_id,
            "secret": self._app_secret,
            "js_code": code,
            "grant_type": "authorization_code",
        }
        try:
            data = self._transport(WECHAT_CODE2SESSION_URL, params, self._timeout)
        except WeChatError:
            raise
        except Exception:
            # timeouts / connection errors / malformed responses -> fail closed.
            # Do NOT include the exception text (could carry the request URL w/ secret).
            logger.warning("wechat code2session transport failure")
            raise WeChatError("transport_error")
        if not isinstance(data, dict):
            raise WeChatError("bad_response")
        errcode = data.get("errcode", 0)
        if errcode and errcode != 0:
            # log only the class of failure, never errmsg/openid/session_key
            logger.warning("wechat code2session non-zero errcode")
            raise WeChatError("wechat_rejected")
        openid = data.get("openid")
        if not openid or not isinstance(openid, str):
            raise WeChatError("no_openid")
        return openid
