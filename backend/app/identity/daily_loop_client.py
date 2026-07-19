"""HTTP transport from the main-backend Facade to the Daily Loop internal API.

Injectable so tests never need a running Daily Loop service. Any transport
failure (connection refused, timeout, non-2xx, malformed body) surfaces as
DailyLoopUnavailable, which the Facade turns into a structured 503 with NO
internal URL / table / SQL / path / stack leaked.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from ..config import settings

logger = logging.getLogger("identity_daily_loop_client")

DEFAULT_BASE_URL = "http://127.0.0.1:18090"


class DailyLoopUnavailable(Exception):
    """The Daily Loop service could not be reached or returned an error."""


class DailyLoopClient:
    def __init__(self, base_url: Optional[str] = None,
                 transport: Optional[Callable[[str, str, dict, dict, float], tuple]] = None,
                 timeout: float = 5.0):
        # R1c: base URL from the single Settings source (not a second os.environ path);
        # explicit base_url still wins for tests.
        self._base_url = (base_url or settings.dm_daily_loop_base_url or DEFAULT_BASE_URL).rstrip("/")
        self._transport = transport or self._http
        self._timeout = timeout

    def _http(self, method: str, url: str, params: dict, headers: dict, timeout: float) -> tuple:
        import httpx
        resp = httpx.request(method, url, params=params, headers=headers, timeout=timeout)
        return resp.status_code, resp.json()

    def get(self, path: str, params: dict, headers: dict) -> dict:
        """Return the parsed JSON body on a 2xx; raise DailyLoopUnavailable otherwise."""
        url = f"{self._base_url}{path}"
        try:
            status, body = self._transport("GET", url, params, headers, self._timeout)
        except Exception:
            logger.warning("daily loop transport failure")
            raise DailyLoopUnavailable()
        if status != 200 or not isinstance(body, dict):
            logger.warning("daily loop non-200 or malformed body")
            raise DailyLoopUnavailable()
        return body
