#!/usr/bin/env python3
"""DM Daily Loop internal API layer (C1-B).

Framework-agnostic core (core.py) + thin FastAPI runtime wrapper (fastapi_app.py).
Business endpoints are for integration tests only and are NOT exposed to the
mini-program until a real personnel-identity authority lands (IDENTITY_SOURCE_HOLD).
Recovery is NOT imported or exposed here (RECOVERY_HOLD).
"""
