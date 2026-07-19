"""Stage I1: authoritative WeChat identity backend + Daily Loop Facade.

This package adds real WeChat code2session login, opaque 24h sessions, and
authoritative member/role/store binding to the main backend. It is isolated from
the legacy weapp/auth routers, whose behaviour is unchanged. New Daily Loop
routes forbid the demo_user / bare-header fallbacks.
"""
