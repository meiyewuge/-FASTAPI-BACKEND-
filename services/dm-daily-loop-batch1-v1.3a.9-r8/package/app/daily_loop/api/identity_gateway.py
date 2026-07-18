#!/usr/bin/env python3
"""Identity gateway for the C1-B internal API.

After S2S authenticates the *adapter*, the request carries the caller's claimed
personnel identity as test-only headers:

    X-DM-Auth-User-Id     the authenticated end-user id (test mapping)
    X-DM-Target-Store-Id  the store the caller intends to act within

The Daily Loop service mints its OWN CallerContext INTERNALLY via
TrustedMemberProvider.create(auth_user_id, target_store_id). The main backend
never holds DM_CALLER_SIGNING_KEY. The freshly minted context is then verified.

IDENTITY_SOURCE_HOLD: these headers are a test mapping, not a production
personnel-identity authority. Business endpoints are not exposed to the
mini-program until a real source lands.

Fail-closed: no mapping, inactive/left member, or a context that fails verify()
yields 401 (identity could not be established). Authorization (role / store) is a
separate 403 decided by the route handler.
"""
from __future__ import annotations
from app.daily_loop.services.caller_context import CallerContext, TrustedMemberProvider
from app.daily_loop.api.errors import unauthorized


class IdentityGateway:
    def __init__(self, provider: TrustedMemberProvider):
        self._provider = provider
        # audience is pinned to the frozen production constant, never hardcoded here
        self.audience = TrustedMemberProvider.AUDIENCE

    def resolve(self, headers: dict) -> CallerContext:
        """Return a verified CallerContext or raise ApiError(401)."""
        h = {k.lower(): v for k, v in (headers or {}).items()}
        auth_user_id = h.get('x-dm-auth-user-id')
        target_store_id = h.get('x-dm-target-store-id')
        if not auth_user_id or not target_store_id:
            raise unauthorized('E-IDENTITY-MISSING', 'identity headers missing')
        ctx = self._provider.create(auth_user_id, target_store_id)
        # create() returns an empty ctx (no token) for no mapping / inactive / left
        if not ctx.token or not ctx.token_id:
            raise unauthorized('E-IDENTITY-NO-MAPPING', 'no active membership')
        # defence in depth: audience must match the frozen production constant
        if ctx.audience != self.audience:
            raise unauthorized('E-IDENTITY-AUDIENCE', 'audience mismatch')
        if not self._provider.verify(ctx):
            # expired / disabled / left / role or store drift since minting
            raise unauthorized('E-IDENTITY-INVALID', 'identity not verifiable')
        return ctx
