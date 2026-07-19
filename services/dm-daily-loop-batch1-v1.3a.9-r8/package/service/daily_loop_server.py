#!/usr/bin/env python3
"""Thin FastAPI runtime wrapper over the framework-agnostic DailyLoopApi core.

Lives OUTSIDE app/ so the app/ zero-connection invariant (no fastapi/uvicorn/
socket) holds. Imported ONLY at runtime inside the runtime Docker image.

Runtime posture (C1-A-R2): the container binds 0.0.0.0:18090 with a single
worker; compose publishes only 127.0.0.1:18090:18090 on the host.

RECOVERY_HOLD: no recovery/vault/holdings routes are registered.
"""
from __future__ import annotations
import os


def build_core():
    from app.daily_loop.services.caller_context import TrustedMemberProvider
    from app.daily_loop.api.s2s import S2SVerifier
    from app.daily_loop.api.core import DailyLoopApi
    auth_db_path = os.environ['DM_DAILY_LOOP_AUTH_DB']
    provider = TrustedMemberProvider.from_env(auth_db_path)
    s2s = S2SVerifier.from_env()
    return DailyLoopApi(auth_db_path, provider, s2s)


def create_app():
    from fastapi import FastAPI
    from starlette.requests import Request
    from starlette.responses import Response
    import json as _json

    core = build_core()
    app = FastAPI(title='DM Daily Loop Internal API', docs_url=None, redoc_url=None, openapi_url=None)

    async def _handle(request: Request) -> Response:
        body = await request.body()
        status, payload = core.dispatch(
            request.method, request.url.path,
            headers=dict(request.headers),
            query=dict(request.query_params),
            body=body or b'',
        )
        return Response(content=_json.dumps(payload), status_code=status,
                        media_type='application/json')

    # Starlette-level routes: the raw Request is passed straight through, so the
    # DailyLoopApi core owns ALL validation/authz (no FastAPI body/param coercion).
    for _p in ('/v1/dl/healthz', '/v1/dl/readyz',
               '/v1/dl/internal/tasks', '/v1/dl/internal/appointments'):
        app.add_route(_p, _handle, methods=['GET'])

    # NOTE: no recovery / vault / holdings routes are registered (RECOVERY_HOLD).
    return app


# uvicorn factory entrypoint (env is read at factory call, not import):
#   uvicorn service.daily_loop_server:create_app --factory \
#           --host 0.0.0.0 --port 18090 --workers 1
