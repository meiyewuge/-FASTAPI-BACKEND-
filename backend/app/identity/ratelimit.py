"""In-process login rate limiting + one-time-code replay guard (W3-01 §4.1).

Both are per-process, time-based, and driven by an injectable clock so tests are
deterministic. They are defense-in-depth: WeChat login codes are already
single-use upstream, and this adds a short local replay window plus a per-IP login
throttle. A shared/distributed store would be required for a multi-instance
production fleet; that is called out in the migration/handoff notes and is out of
this round's scope.

Nothing here stores the raw code: only a salted sha256 of the code is kept, and
only until the short window elapses.
"""
from __future__ import annotations

import hashlib
import threading
import time
from collections import deque
from typing import Callable, Deque, Dict

_CODE_SALT = b"dsm_w3_01_code_replay_v1"


def _hash_code(code: str) -> str:
    return hashlib.sha256(_CODE_SALT + code.encode("utf-8")).hexdigest()


class LoginRateLimiter:
    """Sliding-window per-key attempt limiter."""

    def __init__(self, window_seconds: int, max_attempts: int,
                 clock: Callable[[], float] = time.monotonic):
        self._window = max(1, int(window_seconds))
        self._max = max(1, int(max_attempts))
        self._clock = clock
        self._hits: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self._clock()
        cutoff = now - self._window
        with self._lock:
            dq = self._hits.setdefault(key, deque())
            while dq and dq[0] <= cutoff:
                dq.popleft()
            if len(dq) >= self._max:
                return False
            dq.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


class CodeReplayGuard:
    """Rejects a login code seen again within the short replay window."""

    def __init__(self, window_seconds: int, clock: Callable[[], float] = time.monotonic):
        self._window = max(1, int(window_seconds))
        self._clock = clock
        self._seen: Dict[str, float] = {}
        self._lock = threading.Lock()

    def check_and_remember(self, code: str) -> bool:
        """Return True if this code is fresh (and remember it); False if it is a
        replay within the window."""
        now = self._clock()
        h = _hash_code(code)
        with self._lock:
            # opportunistic prune
            expired = [k for k, t in self._seen.items() if t <= now - self._window]
            for k in expired:
                self._seen.pop(k, None)
            prev = self._seen.get(h)
            if prev is not None and prev > now - self._window:
                return False
            self._seen[h] = now
            return True

    def reset(self) -> None:
        with self._lock:
            self._seen.clear()
