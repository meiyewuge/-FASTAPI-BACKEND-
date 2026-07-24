"""DSM W3-01 authoritative employee-identity chain.

WeChat authoritative login, opaque 24h sessions, user/role/store-binding
resolution, and the authoritative store registry (DR-01=A). Gated behind
IDENTITY_I1_ENABLED; identity tables come only from the reviewed migration.
"""

# Importing the identity package installs the process-wide SQLite
# `PRAGMA foreign_keys=ON` connect listener (defined in backend.app.database),
# so foreign-key integrity is enforced on EVERY sqlite connection that touches
# identity data — the app, the tests, and any standalone migrator/tool — not only
# when the main app engine module happens to be imported first (R1 P0-4).
from .. import database as _database  # noqa: F401

