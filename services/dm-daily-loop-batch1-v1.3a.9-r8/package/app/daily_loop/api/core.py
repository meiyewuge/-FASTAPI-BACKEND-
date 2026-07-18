#!/usr/bin/env python3
"""Framework-agnostic core for the C1-B internal Daily Loop API.

This module has NO web-framework dependency: it dispatches a plain
(method, path, headers, query, body) into (status, body_dict). The FastAPI
runtime wrapper (fastapi_app.py) and the stdlib test-suite both drive this same
core, so the security semantics are proven without a running server.

Endpoints:
  GET /v1/dl/healthz                 liveness, fixed minimal body, no auth
  GET /v1/dl/readyz                  readiness, ops/loopback only, no auth, no detail
  GET /v1/dl/internal/tasks          S2S + identity, read-only, store-scoped
  GET /v1/dl/internal/appointments   S2S + identity, read-only, store-scoped

RECOVERY_HOLD: nothing here imports VaultRecoveryService / recovery roots.
IDENTITY_SOURCE_HOLD: business endpoints are integration-test only.
"""
from __future__ import annotations
import json, sqlite3
from datetime import datetime, timezone
from typing import Optional

from app.daily_loop.services.repository import AuthRepository
from app.daily_loop.services.caller_context import TrustedMemberProvider
from app.daily_loop.api.s2s import S2SVerifier
from app.daily_loop.api.identity_gateway import IdentityGateway
from app.daily_loop.api.serialization import serialize_task, serialize_appointment
from app.daily_loop.api.errors import ApiError, forbidden, not_found, unavailable

BASE_PATH = '/v1/dl'
READY_REQUIRED_TABLES = ('dl_store_member', 'dl_daily_customer_task', 'dl_appointment')
BUSINESS_ROLES = ('owner', 'manager', 'staff')


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


class DailyLoopApi:
    """Wires S2S + identity + read repositories. One instance per worker."""

    def __init__(self, auth_db_path: str, provider: TrustedMemberProvider,
                 s2s: S2SVerifier):
        self._auth_db_path = auth_db_path
        self._provider = provider
        self._s2s = s2s
        self._identity = IdentityGateway(provider)

    # ---- helpers ---------------------------------------------------------

    def _reject_actor_spoof(self, query: dict, body: bytes) -> None:
        """body/query must NOT carry an actor member_id (operator is ctx.member_id)."""
        if query and 'member_id' in query:
            raise forbidden('E-ACTOR', 'actor member_id not permitted')
        if body:
            try:
                parsed = json.loads(body.decode('utf-8'))
                if isinstance(parsed, dict) and 'member_id' in parsed:
                    raise forbidden('E-ACTOR', 'actor member_id not permitted')
            except (ValueError, UnicodeDecodeError):
                pass  # non-JSON body carries no actor claim

    def _reject_cross_store(self, query: dict, ctx_store_id: str) -> None:
        """An explicit store_id that differs from the verified context is a
        cross-store attempt -> 403 E-SCOPE, with no existence disclosure."""
        if query and 'store_id' in query and query['store_id'] != ctx_store_id:
            raise forbidden('E-SCOPE', 'cross-store access denied')

    def _authenticated_ctx(self, method: str, path: str, headers: dict, query: dict, body: bytes):
        # 1) S2S v2 first (adapter authenticity + identity/query binding). 401 on
        #    failure — identity headers and query are now inside the HMAC, so a
        #    signed request cannot be re-pointed at another user/store/date.
        self._s2s.verify(method, path, headers, query, body)
        # 2) identity resolution -> internally minted, verified CallerContext. 401.
        ctx = self._identity.resolve(headers)
        # 3) actor-spoof + cross-store (authz-level). 403. Done BEFORE any resource read.
        self._reject_actor_spoof(query, body)
        self._reject_cross_store(query, ctx.store_id)
        if ctx.role not in BUSINESS_ROLES:
            raise forbidden('E-ROLE', 'role not permitted for this endpoint')
        return ctx

    # ---- endpoints -------------------------------------------------------

    def healthz(self) -> tuple:
        return 200, {'status': 'ok'}

    def readyz(self) -> tuple:
        """Fail-closed readiness. No secrets / provider names / schema detail."""
        conn = None
        try:
            conn = sqlite3.connect(self._auth_db_path)
            names = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            ok = all(t in names for t in READY_REQUIRED_TABLES)
        except sqlite3.Error:
            ok = False
        finally:
            if conn is not None:
                conn.close()
        if not ok:
            raise unavailable('E-NOT-READY', 'dependency not ready')
        return 200, {'ready': True, 'migrations_applied': True}

    def _with_repo(self, fn):
        """Open the repo, run fn(repo), always close. Convert ONLY explicit
        dependency failures (sqlite3.Error / OSError) into a structured 503
        E-DEPENDENCY with NO table name / path / SQL / stack. Programming errors
        are NOT swallowed — they propagate so they surface in tests."""
        try:
            repo = AuthRepository(self._auth_db_path)
        except (sqlite3.Error, OSError):
            raise unavailable('E-DEPENDENCY', 'dependency not ready')
        try:
            return fn(repo)
        except (sqlite3.Error, OSError):
            raise unavailable('E-DEPENDENCY', 'dependency not ready')
        finally:
            try:
                repo.close()
            except (sqlite3.Error, OSError):
                pass

    def list_tasks_internal(self, headers: dict, query: dict, body: bytes = b'') -> tuple:
        ctx = self._authenticated_ctx('GET', f'{BASE_PATH}/internal/tasks', headers, query, body)
        task_date = (query or {}).get('task_date') or _today_utc()

        def _read(repo):
            if ctx.role == 'staff':
                return repo.list_tasks(ctx.store_id, task_date=task_date, member_id=ctx.member_id)
            return repo.list_tasks(ctx.store_id, task_date=task_date)  # owner/manager: whole store
        rows = self._with_repo(_read)
        return 200, {'task_date': task_date, 'store_id': ctx.store_id,
                     'items': [serialize_task(t) for t in rows]}

    def list_appointments_internal(self, headers: dict, query: dict, body: bytes = b'') -> tuple:
        ctx = self._authenticated_ctx('GET', f'{BASE_PATH}/internal/appointments', headers, query, body)
        date = (query or {}).get('date') or _today_utc()
        rows = self._with_repo(lambda repo: repo.list_appointments(ctx.store_id, date=date))
        return 200, {'date': date, 'store_id': ctx.store_id,
                     'items': [serialize_appointment(a) for a in rows]}

    # ---- dispatch --------------------------------------------------------

    def dispatch(self, method: str, path: str, headers: Optional[dict] = None,
                 query: Optional[dict] = None, body: bytes = b'') -> tuple:
        """Route a request. Returns (status, body_dict). Never raises ApiError."""
        headers = headers or {}
        query = query or {}
        method = (method or 'GET').upper()
        try:
            if method != 'GET':
                raise ApiError(405, 'E-METHOD', 'method not allowed')
            if path == f'{BASE_PATH}/healthz':
                return self.healthz()
            if path == f'{BASE_PATH}/readyz':
                return self.readyz()
            if path == f'{BASE_PATH}/internal/tasks':
                return self.list_tasks_internal(headers, query, body)
            if path == f'{BASE_PATH}/internal/appointments':
                return self.list_appointments_internal(headers, query, body)
            raise not_found('E-NOT-FOUND', 'unknown route')
        except ApiError as e:
            return e.status, e.to_body()
        except (sqlite3.Error, OSError):
            # P1-1: an explicit dependency failure anywhere in the request path
            # (identity DB lookup, provider query, repo read) becomes a structured
            # 503 with NO table name / path / SQL / stack. Programming errors
            # (TypeError/KeyError/...) are deliberately NOT caught here.
            return 503, {'error_code': 'E-DEPENDENCY', 'message': 'dependency not ready'}
