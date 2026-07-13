# Search Router P0.2 — Provenance & Corrections

## Origin
- **Source handoff commit**: `913d6e8ad09d8357d9fc9379e2f0bc541acc0407`
  (branch `feature/sr-p02-final-engineering-closure`, delivered as a Git bundle by the
  scheduling middle-platform)
- **Independent audit verdict**: `NEED_FIX` (see `CLAUDE_FINAL_AUDIT_REPORT_V1`)

The origin commit `913d6e8` was **not importable** as delivered and its
"1099/1099" claim was **not reproducible** in an independent environment. This
directory is a **corrected** version of that source. Commit `913d6e8` is retained
here only as provenance — the code below is a new, corrected commit, not `913d6e8`.

## Corrections applied on top of 913d6e8

1. **Restored two required runtime modules** that origin `.gitignore` excluded in error:
   - `search_router/cost_tracker.py` (imported by `search_router/router.py:47`)
   - `search_router/dual_review.py`  (imported by `search_router/router.py:49`)
   Both are hard runtime dependencies (instantiated as defaults in `SearchRouter`),
   contain no secrets, use in-memory SQLite, and do not touch the network.
2. **Corrected `.gitignore`** — removed the erroneous blacklist entries for the two
   modules above (they were listed twice).
3. **Removed hardcoded ECS absolute paths** in 4 test sites (was
   `/opt/wuge-labs/search-router-production-shadow/...`), replaced with a portable
   repo-relative `_REPO_ROOT` derived from `__file__`:
   - `tests/test_real_dns_resolver.py`
   - `tests/test_real_transport_b3a.py`
   - `tests/test_real_transport_td06_v2.py` (sys.path insert + AST source read)
4. **Guarded IPv6-only tests** with `skipif` on hosts without IPv6
   (`test_ipv6_addr_info`, `test_ipv6_real_peer`) — previously hard-failed with
   `OSError 97` in non-IPv6 environments.
5. **Added `requirements.txt`** — locked dependency manifest (was absent from the
   commit; only a full-host freeze shipped out-of-band). Notably includes
   `python-dotenv==1.0.1`, without which `config.from_env(env_file=...)` silently
   no-ops and a config test fails.

## Independent verification (post-fix)

- Package imports succeed; test collection is non-zero (1099 collected).
- `python3.11 -m pytest tests/` → **1097 passed, 2 skipped, 0 failed**
  (the 2 skips are the IPv6 tests; on an IPv6-capable host all 1099 pass).
- Sensitive scan: **0 real credentials**, no secret-bearing files.
- SHA-256 of all 101 origin files verified against the origin manifest before edits.

## Not changed
- No production deployment. No default-branch merge. No history rewrite.
- Origin engineering evidence files (bundle, manifests, audit reports) are retained
  out-of-band with the handoff package.
