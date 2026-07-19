#!/usr/bin/env python3
"""DM Daily Loop network/service entrypoint layer (C1-B).

This package is the ONLY place fastapi/uvicorn are imported. It lives OUTSIDE the
`app/` production package so the zero-connection invariant on `app/` (no network
libraries) stays intact: the business logic and API core in `app/` are
framework-agnostic and network-free; only this thin server wrapper touches the
network boundary.
"""
