#!/usr/bin/env python3
"""Main-backend -> Daily Loop S2S adapter (C1-B).

Feature-flagged OFF by default and NOT mounted on any main-backend router in this
stage. It only knows how to SIGN an outbound S2S request; it never holds
DM_CALLER_SIGNING_KEY and never mints CallerContext (identity is minted inside the
Daily Loop service).
"""
