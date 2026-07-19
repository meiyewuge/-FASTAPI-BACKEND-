#!/usr/bin/env python3
"""Runtime import smoke — runnable INSIDE the runtime image by the deployer.

Proves the vendored dm_customer_holdings runtime package is importable as a
top-level module and that the production services that depend on it import
cleanly, WITHOUT the whole vendor/ tree and WITHOUT a broad PYTHONPATH hack.

Usage (inside the container):
    python tools/runtime_import_smoke.py   # exits 0 on success, 1 on failure
"""
import sys


def main() -> int:
    try:
        import dm_customer_holdings  # top-level package present in the image
        from dm_customer_holdings.store import HoldingsStore          # noqa: F401
        from dm_customer_holdings.contract import CONTRACT_VERSION    # noqa: F401
        from dm_customer_holdings.api import LedgerEntry, TransactionType  # noqa: F401
        from dm_customer_holdings import balance                      # noqa: F401
        # the production services that import the vendored package
        from app.daily_loop.services import repository                # noqa: F401
        from app.daily_loop.services import holdings_bridge           # noqa: F401
        # the API/server entrypoints
        from app.daily_loop.api import core                           # noqa: F401
    except Exception as e:  # pragma: no cover - smoke failure path
        sys.stderr.write(f'RUNTIME_IMPORT_SMOKE_FAIL: {type(e).__name__}: {e}\n')
        return 1
    print('RUNTIME_IMPORT_SMOKE_OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
