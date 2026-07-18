#!/usr/bin/env python3
"""Main backend adapters.

This is the REAL main-backend code domain (`backend/app/...`), separate from the
Daily Loop package. Nothing here imports the Daily Loop top-level `app` package,
so the two `app` namespaces never collide and the main-backend runtime image
(which only COPYs `backend/app`) contains a usable adapter.
"""
