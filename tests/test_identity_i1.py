"""Stage I1-R1 identity + Facade acceptance matrix.

Schema is built by the REVIEWED MIGRATION (not ORM create_all) so migration/ORM
consistency (P0-1) is genuinely exercised. Covers the R1 negative matrix incl.
AppUser status enforcement, snapshot-based identity drift (no manual version
bump), Facade fail-closed, startup gating (real backend.app.main via subprocess),
concurrent first login, and PostgreSQL DDL contract (static; runtime NOT executed).

Emits structured evidence to DM_I1_EVIDENCE_PATH when set.
"""
import os
import sys
import json
import logging
import tempfile
import subprocess
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("DM_ADAPTER_SHARED_SECRET", "test_adapter_shared_secret_16c")

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from backend.app.config import settings
from backend.app.database import get_db
from backend.app.identity import models as im
from backend.app.identity import session_service, migrator
from backend.app.identity.errors import ApiError
from backend.app.routers import auth_identity, daily_loop_facade
from backend.app.routers import weapp as legacy_weapp
from backend.app.identity.wechat import WeChatClient
from backend.app.identity.daily_loop_client import DailyLoopClient, DailyLoopUnavailable
from backend.app.adapters import daily_loop_adapter

_EVID = []


def _rec(case, ok, extra=None):
    e = {"case": case, "passed": bool(ok)}
    if extra:
        e.update(extra)
    _EVID.append(e)


def tearDownModule():
    p = os.environ.get("DM_I1_EVIDENCE_PATH")
    if p:
        json.dump({"report_type": "IDENTITY_I1_R1_TEST_MATRIX",
                   "total": len(_EVID), "passed": sum(1 for e in _EVID if e["passed"]),
                   "cases": _EVID}, open(p, "w"), indent=2, ensure_ascii=False)


def _build_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_identity.router)
    app.include_router(daily_loop_facade.router)
    app.include_router(legacy_weapp.router, prefix="/api")

    @app.exception_handler(ApiError)
    async def _h(request: Request, exc: ApiError):
        return JSONResponse(status_code=exc.http_status, content=exc.envelope())
    return app


class FakeWeChat(WeChatClient):
    def __init__(self, openid=None, error=None):
        super().__init__(app_id="x", app_secret="y", transport=lambda *a, **k: {})
        self._openid, self._error = openid, error

    def code2session(self, code):
        from backend.app.identity.wechat import WeChatError
        if self._error:
            raise WeChatError(self._error)
        return self._openid


class FakeDailyLoop(DailyLoopClient):
    def __init__(self, items=None, unavailable=False, raw=None):
        super().__init__(base_url="http://unused", transport=lambda *a, **k: (200, {}))
        self._items, self._unavailable, self._raw = items, unavailable, raw
        self.last_headers = None

    def get(self, path, params, headers):
        self.last_headers = headers
        if self._unavailable:
            raise DailyLoopUnavailable()
        if self._raw is not None:
            return self._raw
        return {"items": list(self._items or [])}


class I1Base(unittest.TestCase):
    def setUp(self):
        fd, self.dbfile = tempfile.mkstemp(suffix=".db"); os.close(fd)
        self.engine = create_engine(f"sqlite:///{self.dbfile}",
                                    connect_args={"check_same_thread": False})
        migrator.apply_forward(self.engine)  # schema from MIGRATION, not create_all
        self.TestSession = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.app = _build_test_app()

        def _override_db():
            db = self.TestSession()
            try:
                yield db
            finally:
                db.close()
        self.app.dependency_overrides[get_db] = _override_db
        # R1c: the real Facade → Adapter → Client chain now reads its config from the
        # single Settings source. Drive enablement/secret/base_url via settings (NOT a
        # second os.environ path). main_backend=False so this combined test process is
        # not treated as a real main backend (root isolation is exercised end-to-end in
        # the .env-only subprocess tests instead).
        self._saved_settings = {
            "dm_daily_loop_adapter_enabled": settings.dm_daily_loop_adapter_enabled,
            "dm_adapter_shared_secret": settings.dm_adapter_shared_secret,
            "dm_main_backend": settings.dm_main_backend,
            "dm_daily_loop_base_url": settings.dm_daily_loop_base_url,
        }
        settings.dm_daily_loop_adapter_enabled = True
        settings.dm_adapter_shared_secret = "test_adapter_shared_secret_16c"
        settings.dm_main_backend = False
        self.client = TestClient(self.app)

    def tearDown(self):
        self.app.dependency_overrides.clear()
        for k, v in getattr(self, "_saved_settings", {}).items():
            setattr(settings, k, v)
        try:
            os.unlink(self.dbfile)
        except OSError:
            pass

    def _set_wechat(self, openid=None, error=None):
        self.app.dependency_overrides[auth_identity.get_wechat_client] = \
            lambda: FakeWeChat(openid=openid, error=error)

    def _set_daily_loop(self, items=None, unavailable=False, raw=None):
        fake = FakeDailyLoop(items=items, unavailable=unavailable, raw=raw)
        self.app.dependency_overrides[daily_loop_facade.get_daily_loop_client] = lambda: fake
        return fake

    def _login(self, openid):
        self._set_wechat(openid=openid)
        return self.client.post("/api/auth/wechat/login", json={"code": "real_code_123"})

    def _uid_for(self, openid):
        db = self.TestSession()
        row = db.query(im.WechatIdentity).filter_by(
            openid_hash=session_service.hash_openid(openid)).first()
        uid = row.app_user_id
        db.close()
        return uid

    def _bind(self, app_user_id, dl_auth="U001", store="S001", member="M-001",
              role="owner", status="active", version=1):
        db = self.TestSession()
        db.add(im.StoreMemberBinding(app_user_id=app_user_id, dl_auth_user_id=dl_auth,
               dl_store_id=store, dl_member_id=member, role=role, status=status,
               identity_version=version)); db.commit(); db.close()

    def _set_user_status(self, uid, status):
        db = self.TestSession()
        db.get(im.AppUser, uid).status = status; db.commit(); db.close()

    def _auth(self, tok):
        return {"Authorization": f"Bearer {tok}"}

    def _session_count(self):
        db = self.TestSession()
        n = db.query(im.AuthSession).count(); db.close()
        return n


class TestI1R1(I1Base):

    # P0-1: migration-built schema supports the full live flow incl. issued_at
    def test_00_migration_live_flow(self):
        r = self._login("wx_alpha")
        self.assertEqual(r.status_code, 200)
        tok = r.json()["data"]["token"]
        self.assertEqual(len(tok), 64)
        # issued_at was auto-written by the migration default (no IntegrityError)
        db = self.TestSession()
        s = db.query(im.AuthSession).first()
        self.assertIsNotNone(s.issued_at)
        db.close()
        # logout works
        self.assertEqual(self.client.post("/api/auth/logout", headers=self._auth(tok)).status_code, 200)
        _rec("00_migration_live_flow", True)

    def test_01_no_auth_401(self):
        r = self.client.get("/api/daily-loop/v1/tasks?date=2026-07-17")
        self.assertEqual(r.status_code, 401)
        _rec("01_no_auth_401", r.status_code == 401)

    def test_02_demo_user_rejected(self):
        for bad in ("demo_user", "token_mock_openid_x", "token_abc"):
            r = self.client.get("/api/daily-loop/v1/tasks?date=2026-07-17", headers=self._auth(bad))
            self.assertEqual(r.status_code, 401, bad)
        r = self.client.get("/api/daily-loop/v1/tasks?date=2026-07-17", headers={"Authorization": "demo_user"})
        self.assertEqual(r.status_code, 401)
        _rec("02_demo_user_rejected", True)

    def test_03_unknown_expired_revoked_401(self):
        r = self.client.get("/api/daily-loop/v1/tasks?date=2026-07-17", headers=self._auth("deadbeef" * 8))
        self.assertEqual(r.status_code, 401)
        # revoked
        rr = self._login("wx_rev"); tok = rr.json()["data"]["token"]
        self._uid_for("wx_rev")
        self.client.post("/api/auth/logout", headers=self._auth(tok))
        self._bind(self._uid_for("wx_rev"))
        r2 = self.client.get("/api/daily-loop/v1/tasks?date=2026-07-17", headers=self._auth(tok))
        self.assertEqual(r2.status_code, 401)
        # expired
        rr = self._login("wx_exp"); tok = rr.json()["data"]["token"]
        db = self.TestSession()
        s = db.query(im.AuthSession).filter_by(token_hash=session_service.hash_token(tok)).first()
        from datetime import datetime, timedelta, timezone
        s.expires_at = datetime.now(timezone.utc) - timedelta(hours=1); db.commit(); db.close()
        r3 = self.client.get("/api/daily-loop/v1/tasks?date=2026-07-17", headers=self._auth(tok))
        self.assertEqual(r3.status_code, 401)
        _rec("03_unknown_expired_revoked", True)

    # P1-1: unbound -> 403 (me + facade)
    def test_04_unbound_403(self):
        r = self._login("wx_unbound"); tok = r.json()["data"]["token"]
        me = self.client.get("/api/auth/me", headers=self._auth(tok))
        self.assertEqual(me.status_code, 403)
        self.assertIn("尚未绑定", me.json()["msg"])
        self._set_daily_loop(items=[])
        fac = self.client.get("/api/daily-loop/v1/tasks?date=2026-07-17", headers=self._auth(tok))
        self.assertEqual(fac.status_code, 403)
        _rec("04_unbound_403", True)

    # P0-3: AppUser disabled -> new login 403 + no session row; old token 403
    def test_05_appuser_disabled_new_login_403_no_session(self):
        r = self._login("wx_dis"); uid = self._uid_for("wx_dis")
        self._bind(uid)
        self._set_user_status(uid, "disabled")
        before = self._session_count()
        r2 = self._login("wx_dis")
        self.assertEqual(r2.status_code, 403)
        self.assertEqual(self._session_count(), before)  # no new session
        _rec("05_appuser_disabled_login", r2.status_code == 403)

    def test_05b_appuser_disabled_old_token_403(self):
        r = self._login("wx_dis2"); uid = self._uid_for("wx_dis2"); self._bind(uid)
        r = self._login("wx_dis2"); tok = r.json()["data"]["token"]
        self._set_daily_loop(items=[])
        ok = self.client.get("/api/daily-loop/v1/tasks?date=2026-07-17", headers=self._auth(tok))
        self.assertEqual(ok.status_code, 200)
        self._set_user_status(uid, "disabled")  # disable AFTER token issued
        r2 = self.client.get("/api/daily-loop/v1/tasks?date=2026-07-17", headers=self._auth(tok))
        self.assertEqual(r2.status_code, 403)
        _rec("05b_appuser_disabled_old_token", r2.status_code == 403)

    # binding disabled/left
    def test_06_binding_disabled_left_rejected(self):
        for st in ("disabled", "left"):
            r = self._login(f"wxb_{st}"); uid = self._uid_for(f"wxb_{st}")
            self._bind(uid, status=st)
            r = self._login(f"wxb_{st}"); tok = r.json()["data"]["token"]
            self._set_daily_loop(items=[])
            fac = self.client.get("/api/daily-loop/v1/tasks?date=2026-07-17", headers=self._auth(tok))
            self.assertIn(fac.status_code, (401, 403), st)
        _rec("06_binding_disabled_left", True)

    # P0-4: drift WITHOUT manual version bump -> old token 401 (snapshot enforced)
    def test_07_drift_without_version_bump_401(self):
        for field, mutate in [
            ("role", lambda b: setattr(b, "role", "staff")),
            ("store", lambda b: setattr(b, "dl_store_id", "S999")),
            ("member", lambda b: setattr(b, "dl_member_id", "M-999")),
            ("auth_user", lambda b: setattr(b, "dl_auth_user_id", "U999")),
        ]:
            oid = f"wx_drift_{field}"
            r = self._login(oid); uid = self._uid_for(oid); self._bind(uid, version=1)
            r = self._login(oid); tok = r.json()["data"]["token"]
            self._set_daily_loop(items=[])
            self.assertEqual(self.client.get("/api/daily-loop/v1/tasks?date=2026-07-17",
                             headers=self._auth(tok)).status_code, 200, field)
            db = self.TestSession()
            b = db.query(im.StoreMemberBinding).filter_by(app_user_id=uid).first()
            mutate(b)  # identity_version deliberately left at 1
            db.commit(); db.close()
            r2 = self.client.get("/api/daily-loop/v1/tasks?date=2026-07-17", headers=self._auth(tok))
            self.assertEqual(r2.status_code, 401, f"{field} drift should 401")
        _rec("07_drift_without_version_bump", True)

    # 7: forged identity params -> 400
    def test_08_forged_params_400(self):
        oid = "wx_forge"; r = self._login(oid); self._bind(self._uid_for(oid))
        r = self._login(oid); tok = r.json()["data"]["token"]; self._set_daily_loop(items=[])
        for p in ("store_id=S9", "member_id=M9", "role=owner", "auth_user_id=U9", "target_store_id=S9"):
            self.assertEqual(self.client.get(f"/api/daily-loop/v1/tasks?date=2026-07-17&{p}",
                             headers=self._auth(tok)).status_code, 400, p)
        _rec("08_forged_params_400", True)

    # 8: store only from binding
    def test_09_store_from_binding(self):
        oid = "wx_store"; r = self._login(oid); self._bind(self._uid_for(oid), dl_auth="U777", store="S777")
        r = self._login(oid); tok = r.json()["data"]["token"]
        fake = self._set_daily_loop(items=[{"task_id": "T-1"}])
        fac = self.client.get("/api/daily-loop/v1/tasks?date=2026-07-17", headers=self._auth(tok))
        self.assertEqual(fac.status_code, 200)
        self.assertEqual(fake.last_headers["X-DM-Target-Store-Id"], "S777")
        self.assertEqual(fake.last_headers["X-DM-Auth-User-Id"], "U777")
        _rec("09_store_from_binding", True)

    # R1-5: Facade fail-closed on malformed upstream
    def test_10_facade_failclosed_malformed(self):
        oid = "wx_mal"; r = self._login(oid); self._bind(self._uid_for(oid))
        r = self._login(oid); tok = r.json()["data"]["token"]
        for raw in ({"items": "notalist"}, {"nope": 1}, [1, 2, 3], {"items": [1, 2]}):
            self._set_daily_loop(raw=raw)
            fac = self.client.get("/api/daily-loop/v1/tasks?date=2026-07-17", headers=self._auth(tok))
            self.assertEqual(fac.status_code, 503, raw)
            blob = json.dumps(fac.json())
            for leak in ("18090", "127.0.0.1", "sqlite", "Traceback", "SELECT", "/v1/dl"):
                self.assertNotIn(leak, blob)
        _rec("10_facade_failclosed_malformed", True)

    # 11: daily loop unavailable -> 503; adapter disabled -> 503
    def test_11_unavailable_503(self):
        oid = "wx_503"; r = self._login(oid); self._bind(self._uid_for(oid))
        r = self._login(oid); tok = r.json()["data"]["token"]
        self._set_daily_loop(unavailable=True)
        self.assertEqual(self.client.get("/api/daily-loop/v1/tasks?date=2026-07-17",
                         headers=self._auth(tok)).status_code, 503)
        settings.dm_daily_loop_adapter_enabled = False  # feature flag OFF (Settings source)
        self._set_daily_loop(items=[])
        self.assertEqual(self.client.get("/api/daily-loop/v1/tasks?date=2026-07-17",
                         headers=self._auth(tok)).status_code, 503)
        _rec("11_unavailable_503", True)

    # 12: wechat error / no openid -> fail closed, no mock
    def test_12_wechat_fail_closed(self):
        for err in ("wechat_rejected", "transport_error", "no_openid", "not_configured"):
            self._set_wechat(error=err)
            r = self.client.post("/api/auth/wechat/login", json={"code": "bad"})
            self.assertEqual(r.status_code, 400, err)
            self.assertNotIn("mock", json.dumps(r.json()))
        _rec("12_wechat_fail_closed", True)

    # 13: secrets not logged
    def test_13_no_secret_in_logs(self):
        buf = []
        class H(logging.Handler):
            def emit(self, rec): buf.append(self.format(rec))
        root = logging.getLogger(); h = H(); h.setFormatter(logging.Formatter("%(message)s"))
        root.addHandler(h); old = root.level; root.setLevel(logging.DEBUG)
        try:
            oid = "wx_secret_openid_zzz"; r = self._login(oid); tok = r.json()["data"]["token"]
            self._bind(self._uid_for(oid)); self._set_daily_loop(items=[])
            self.client.get("/api/daily-loop/v1/tasks?date=2026-07-17", headers=self._auth(tok))
            self.client.post("/api/auth/wechat/login", json={"code": "supersecretcode999"})
        finally:
            root.removeHandler(h); root.setLevel(old)
        logs = "\n".join(buf)
        for leak in ("wx_secret_openid_zzz", tok, "supersecretcode999"):
            self.assertNotIn(leak, logs)
        _rec("13_no_secret_in_logs", True)

    # 14: legacy route unaffected
    def test_14_legacy_unaffected(self):
        r = self.client.post("/api/auth/wechat-login", json={"code": "abc123"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("token", r.json().get("data", {}))
        _rec("14_legacy_unaffected", True)

    # 15: facade <=100 stable
    def test_15_facade_cap_stable(self):
        oid = "wx_cap"; r = self._login(oid); self._bind(self._uid_for(oid))
        r = self._login(oid); tok = r.json()["data"]["token"]
        self._set_daily_loop(items=[{"task_id": f"T-{i:03d}"} for i in range(150)])
        fac = self.client.get("/api/daily-loop/v1/tasks?date=2026-07-17", headers=self._auth(tok))
        got = fac.json()["data"]["items"]
        self.assertEqual(len(got), 100)
        self.assertEqual(got[0]["task_id"], "T-000")
        _rec("15_facade_cap_stable", True)

    # 16: invalid date -> 400
    def test_16_invalid_date_400(self):
        oid = "wx_date"; r = self._login(oid); self._bind(self._uid_for(oid))
        r = self._login(oid); tok = r.json()["data"]["token"]; self._set_daily_loop(items=[])
        for bad in ("2026-13-40", "not-a-date", "20260717", ""):
            self.assertEqual(self.client.get(f"/api/daily-loop/v1/appointments?date={bad}",
                             headers=self._auth(tok)).status_code, 400, bad)
        _rec("16_invalid_date_400", True)

    # P1-3: concurrent first login same openid -> one identity/user, no 500
    def test_17_concurrent_first_login(self):
        results = []
        def worker():
            self._set_wechat(openid="wx_concurrent")  # shared override
            c = TestClient(self.app)
            results.append(c.post("/api/auth/wechat/login", json={"code": "c"}).status_code)
        threads = [threading.Thread(target=worker) for _ in range(6)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertTrue(all(s == 200 for s in results), results)
        db = self.TestSession()
        n_ident = db.query(im.WechatIdentity).filter_by(
            openid_hash=session_service.hash_openid("wx_concurrent")).count()
        n_user = db.query(im.AppUser).count()
        db.close()
        self.assertEqual(n_ident, 1)  # exactly one identity despite the race
        self.assertEqual(n_user, 1)
        _rec("17_concurrent_first_login", True, {"identities": n_ident, "users": n_user})

    def _raw_sql(self, sql):
        from sqlalchemy import text
        with self.engine.begin() as c:
            c.execute(text(sql))

    # P0-3: AppUser active->disabled->active permanently invalidates old token
    def test_17b_appuser_reactivation_invalidates(self):
        oid = "wx_reactiv_u"; r = self._login(oid); uid = self._uid_for(oid); self._bind(uid)
        r = self._login(oid); tok = r.json()["data"]["token"]; self._set_daily_loop(items=[])
        self.assertEqual(self.client.get("/api/daily-loop/v1/tasks?date=2026-07-17",
                         headers=self._auth(tok)).status_code, 200)
        # out-of-band raw SQL toggle active->disabled->active (trigger bumps epoch twice)
        self._raw_sql(f"UPDATE dl_app_user SET status='disabled' WHERE id={uid}")
        self._raw_sql(f"UPDATE dl_app_user SET status='active' WHERE id={uid}")
        r2 = self.client.get("/api/daily-loop/v1/tasks?date=2026-07-17", headers=self._auth(tok))
        self.assertEqual(r2.status_code, 401)  # old token stays dead after reactivation
        # a fresh login works again
        r3 = self._login(oid); tok3 = r3.json()["data"]["token"]
        self.assertEqual(self.client.get("/api/daily-loop/v1/tasks?date=2026-07-17",
                         headers=self._auth(tok3)).status_code, 200)
        _rec("17b_appuser_reactivation", True)

    def test_17c_binding_reactivation_invalidates(self):
        oid = "wx_reactiv_b"; r = self._login(oid); uid = self._uid_for(oid); self._bind(uid)
        r = self._login(oid); tok = r.json()["data"]["token"]; self._set_daily_loop(items=[])
        self.assertEqual(self.client.get("/api/daily-loop/v1/tasks?date=2026-07-17",
                         headers=self._auth(tok)).status_code, 200)
        self._raw_sql(f"UPDATE dl_store_member_binding SET status='disabled' WHERE app_user_id={uid}")
        self._raw_sql(f"UPDATE dl_store_member_binding SET status='active' WHERE app_user_id={uid}")
        r2 = self.client.get("/api/daily-loop/v1/tasks?date=2026-07-17", headers=self._auth(tok))
        self.assertEqual(r2.status_code, 401)
        r3 = self._login(oid); tok3 = r3.json()["data"]["token"]
        self.assertEqual(self.client.get("/api/daily-loop/v1/tasks?date=2026-07-17",
                         headers=self._auth(tok3)).status_code, 200)
        _rec("17c_binding_reactivation", True)

    # P0-3 #3: status change with NO request passing through still invalidates
    def test_17d_epoch_bumped_without_request(self):
        oid = "wx_noreq"; r = self._login(oid); uid = self._uid_for(oid); self._bind(uid)
        r = self._login(oid); tok = r.json()["data"]["token"]
        # NO API call between mint and the out-of-band status change
        self._raw_sql(f"UPDATE dl_app_user SET status='disabled' WHERE id={uid}")
        self._raw_sql(f"UPDATE dl_app_user SET status='active' WHERE id={uid}")
        db = self.TestSession()
        epoch = db.get(im.AppUser, uid).status_epoch; db.close()
        self.assertEqual(epoch, 2)  # trigger fired at UPDATE time, not at request time
        self._set_daily_loop(items=[])
        self.assertEqual(self.client.get("/api/daily-loop/v1/tasks?date=2026-07-17",
                         headers=self._auth(tok)).status_code, 401)
        _rec("17d_epoch_without_request", True, {"epoch": epoch})

    # P1-2: DB CHECK constraints + unique wechat->user
    def test_18b_db_constraints(self):
        from sqlalchemy.exc import IntegrityError
        db = self.TestSession()
        db.add(im.AppUser(status="active")); db.commit()
        uid = db.query(im.AppUser).first().id
        # invalid role rejected by CHECK
        with self.assertRaises(IntegrityError):
            db.add(im.StoreMemberBinding(app_user_id=uid, dl_auth_user_id="U", dl_store_id="S",
                   dl_member_id="M", role="superadmin", status="active")); db.commit()
        db.rollback()
        # invalid status rejected by CHECK
        with self.assertRaises(IntegrityError):
            db.add(im.AppUser(status="zombie")); db.commit()
        db.rollback()
        # one wechat identity per user (unique app_user_id)
        db.add(im.WechatIdentity(app_user_id=uid, openid_hash="h1")); db.commit()
        with self.assertRaises(IntegrityError):
            db.add(im.WechatIdentity(app_user_id=uid, openid_hash="h2")); db.commit()
        db.rollback(); db.close()
        _rec("18b_db_constraints", True)

    # P0-1 PG DDL contract (static; runtime NOT executed here)
    def test_18_postgres_ddl_contract_static(self):
        pg = (ROOT / "backend/migrations/i1_identity_forward_postgres.sql").read_text()
        self.assertIn("GENERATED ALWAYS AS IDENTITY", pg)
        self.assertIn("BOOLEAN NOT NULL DEFAULT FALSE", pg)
        self.assertIn("DEFAULT now()", pg)
        self.assertIn("BIGINT", pg)
        # R1a additions must be present in the PG DDL too
        self.assertIn("dl_bump_status_epoch", pg)          # status epoch trigger fn
        self.assertIn("CHECK (role in ('owner','manager','staff'))", pg)
        self.assertIn("uq_dl_wechat_app_user", pg)          # one wechat per user
        self.assertIn("dl_identity_schema_meta", pg)        # machine version
        self.assertIn("i1-r1a", pg)
        _rec("18_postgres_ddl_contract", True, {"postgres_runtime": "NOT_EXECUTED"})


class TestI1RealMainStartupGate(unittest.TestCase):
    """R1-2 / §6.4 / §6.5 / §6.12: real backend.app.main startup gating via
    subprocess (env is read at import time, so a fresh process is the honest test)."""

    def _run(self, env_extra, script):
        env = dict(os.environ, **env_extra)
        env["PYTHONPATH"] = str(ROOT)
        return subprocess.run([sys.executable, "-c", script], cwd=str(ROOT),
                              capture_output=True, text=True, env=env)

    def _tmpdb(self, migrated: bool):
        fd, db = tempfile.mkstemp(suffix=".db"); os.close(fd)
        if migrated:
            eng = create_engine(f"sqlite:///{db}")
            migrator.apply_forward(eng)
            eng.dispose()
        return db

    def test_19_disabled_routes_absent_legacy_ok(self):
        db = self._tmpdb(migrated=False)
        script = (
            "from backend.app.main import app\n"
            "paths=[r.path for r in app.routes]\n"
            "assert '/api/daily-loop/v1/tasks' not in paths, 'facade must NOT mount when disabled'\n"
            "assert '/health' in paths\n"
            "print('DISABLED_OK')\n"
        )
        r = self._run({"IDENTITY_I1_ENABLED": "0", "DATABASE_URL": f"sqlite:///{db}"}, script)
        os.unlink(db)
        self.assertIn("DISABLED_OK", r.stdout, r.stderr)
        _rec("19_disabled_routes_absent", "DISABLED_OK" in r.stdout)

    _GOOD_CFG = {
        "WECHAT_APP_ID": "wx_app_id_demo",
        "WECHAT_APP_SECRET": "wx_app_secret_demo_value",
        "DM_OPENID_HMAC_KEY": "openid_hmac_key_least_32_chars_long_xx",
        "DM_ADAPTER_SHARED_SECRET": "test_adapter_shared_secret_16c",
        "DM_MAIN_BACKEND": "1",
    }

    def _run_in_dir(self, cwd, env_extra, script):
        # env does NOT carry identity keys; they must be read from cwd/.env only
        env = {"PYTHONPATH": str(ROOT), "PATH": os.environ.get("PATH", "")}
        env.update(env_extra)
        return subprocess.run([sys.executable, "-c", script], cwd=cwd,
                              capture_output=True, text=True, env=env)

    def test_20_enabled_migrated_configured_routes_present(self):
        db = self._tmpdb(migrated=True)
        script = (
            "from backend.app.main import app\n"
            "paths=[r.path for r in app.routes]\n"
            "assert '/api/daily-loop/v1/tasks' in paths\n"
            "assert '/api/auth/wechat/login' in paths\n"
            "print('ENABLED_OK')\n"
        )
        env = {"IDENTITY_I1_ENABLED": "1", "DATABASE_URL": f"sqlite:///{db}", **self._GOOD_CFG}
        r = self._run(env, script)
        os.unlink(db)
        self.assertIn("ENABLED_OK", r.stdout, r.stderr)
        _rec("20_enabled_migrated_configured", "ENABLED_OK" in r.stdout)

    def test_22_enabled_missing_config_fail_closed(self):
        # migrated + enabled but the 3 config keys are EMPTY -> must fail closed
        db = self._tmpdb(migrated=True)
        script = ("try:\n import backend.app.main\n print('NO_FAIL')\n"
                  "except Exception as e:\n print('FAILCLOSED:'+type(e).__name__)\n")
        r = self._run({"IDENTITY_I1_ENABLED": "1", "DATABASE_URL": f"sqlite:///{db}",
                       "WECHAT_APP_ID": "", "WECHAT_APP_SECRET": "", "DM_OPENID_HMAC_KEY": ""}, script)
        os.unlink(db)
        self.assertIn("FAILCLOSED", r.stdout, r.stderr)
        self.assertNotIn("NO_FAIL", r.stdout)
        _rec("22_enabled_missing_config", "FAILCLOSED" in r.stdout)

    def test_23_enabled_short_hmac_fail_closed(self):
        db = self._tmpdb(migrated=True)
        env = {"IDENTITY_I1_ENABLED": "1", "DATABASE_URL": f"sqlite:///{db}", **self._GOOD_CFG,
               "DM_OPENID_HMAC_KEY": "too_short"}
        script = ("try:\n import backend.app.main\n print('NO_FAIL')\n"
                  "except Exception as e:\n print('FAILCLOSED:'+type(e).__name__)\n")
        r = self._run(env, script)
        os.unlink(db)
        self.assertIn("FAILCLOSED", r.stdout, r.stderr)
        _rec("23_enabled_short_hmac", "FAILCLOSED" in r.stdout)

    def test_24_enabled_reused_hmac_fail_closed(self):
        db = self._tmpdb(migrated=True)
        reused = "reused_secret_least_32_chars_long_abc"
        env = {"IDENTITY_I1_ENABLED": "1", "DATABASE_URL": f"sqlite:///{db}", **self._GOOD_CFG,
               "DM_OPENID_HMAC_KEY": reused, "WECHAT_APP_SECRET": reused}  # reuse wechat secret
        script = ("try:\n import backend.app.main\n print('NO_FAIL')\n"
                  "except Exception as e:\n print('FAILCLOSED:'+type(e).__name__+':'+str(e))\n")
        r = self._run(env, script)
        os.unlink(db)
        self.assertIn("FAILCLOSED", r.stdout, r.stderr)
        self.assertNotIn(reused, r.stdout)  # secret value not echoed
        _rec("24_enabled_reused_hmac", "FAILCLOSED" in r.stdout)

    def test_26_dm_main_backend_missing_fail_closed(self):
        db = self._tmpdb(migrated=True)
        env = {"IDENTITY_I1_ENABLED": "1", "DATABASE_URL": f"sqlite:///{db}", **self._GOOD_CFG}
        env.pop("DM_MAIN_BACKEND")  # everything else complete
        script = ("try:\n import backend.app.main\n print('NO_FAIL')\n"
                  "except Exception as e:\n print('FAILCLOSED:'+type(e).__name__)\n")
        r = self._run(env, script)
        os.unlink(db)
        self.assertIn("FAILCLOSED", r.stdout, r.stderr)
        self.assertNotIn("NO_FAIL", r.stdout)
        _rec("26_dm_main_backend_missing", "FAILCLOSED" in r.stdout)

    def test_27_env_file_only_startup(self):
        # P0-1: config ONLY in a temp .env (never exported); real main must start.
        d = tempfile.mkdtemp(); db = os.path.join(d, "app.db")
        eng = create_engine(f"sqlite:///{db}"); migrator.apply_forward(eng); eng.dispose()
        env_lines = {
            "IDENTITY_I1_ENABLED": "1", "DM_MAIN_BACKEND": "1",
            "DATABASE_URL": f"sqlite:///{db}",
            "WECHAT_APP_ID": "wx_env_id", "WECHAT_APP_SECRET": "wx_env_secret_value",
            "DM_OPENID_HMAC_KEY": "env_only_hmac_key_at_least_32_chars_xx",
            "DM_ADAPTER_SHARED_SECRET": "env_only_adapter_secret_16c",
        }
        with open(os.path.join(d, ".env"), "w") as f:
            for k, v in env_lines.items():
                f.write(f"{k}={v}\n")
        script = ("from backend.app.main import app\n"
                  "paths=[r.path for r in app.routes]\n"
                  "assert '/api/daily-loop/v1/tasks' in paths\n"
                  "print('ENV_ONLY_OK')\n")
        r = self._run_in_dir(d, {}, script)  # NO identity keys in the process env
        import shutil; shutil.rmtree(d, ignore_errors=True)
        self.assertIn("ENV_ONLY_OK", r.stdout, r.stderr)
        _rec("27_env_file_only_startup", "ENV_ONLY_OK" in r.stdout)

    def test_28_env_only_wechat_hash_same_source(self):
        # P0-1 req 2: WeChatClient default + hash_openid use the same Settings values
        d = tempfile.mkdtemp()
        env_lines = {
            "WECHAT_APP_ID": "wx_same_id", "WECHAT_APP_SECRET": "wx_same_secret_value",
            "DM_OPENID_HMAC_KEY": "same_source_hmac_key_at_least_32_chars",
        }
        with open(os.path.join(d, ".env"), "w") as f:
            for k, v in env_lines.items():
                f.write(f"{k}={v}\n")
        script = (
            "import hmac, hashlib\n"
            "from backend.app.config import settings\n"
            "from backend.app.identity.wechat import WeChatClient\n"
            "from backend.app.identity import session_service as ss\n"
            "c=WeChatClient()\n"
            "assert c._app_id==settings.wechat_app_id=='wx_same_id'\n"
            "assert c._app_secret==settings.wechat_app_secret\n"
            "exp=hmac.new(settings.dm_openid_hmac_key.encode(), b'oid', hashlib.sha256).hexdigest()\n"
            "assert ss.hash_openid('oid')==exp\n"  # HMAC from same Settings key
            "print('SAME_SOURCE_OK')\n")
        r = self._run_in_dir(d, {}, script)
        import shutil; shutil.rmtree(d, ignore_errors=True)
        self.assertIn("SAME_SOURCE_OK", r.stdout, r.stderr)
        _rec("28_env_only_same_source", "SAME_SOURCE_OK" in r.stdout)

    def test_29_rollback_dialect_contract(self):
        sqlite_rb = (ROOT / "backend/migrations/i1_identity_rollback_sqlite.sql").read_text()
        pg_rb = (ROOT / "backend/migrations/i1_identity_rollback_postgres.sql").read_text()
        # PG rollback cleans the function; SQLite rollback has no PG-only statement
        self.assertIn("DROP FUNCTION IF EXISTS dl_bump_status_epoch()", pg_rb)
        self.assertNotIn("DROP FUNCTION", sqlite_rb)
        self.assertNotIn("plpgsql", sqlite_rb)
        _rec("29_rollback_dialect_contract", True)

    # R1c P0: the SAME Settings/.env config must carry through the REAL
    # Facade -> Adapter -> Daily Loop Client chain. Everything (identity + adapter
    # enable flag + shared secret + base URL) lives ONLY in a temp .env (never
    # exported). A real authenticated request must return 200 with a genuine
    # dm-s2s-v2 signed upstream call. Only the upstream HTTP transport is injected;
    # the adapter, signer and identity dependency are all real.
    def test_30_env_only_facade_e2e_request_signed(self):
        d = tempfile.mkdtemp(); db = os.path.join(d, "app.db")
        eng = create_engine(f"sqlite:///{db}"); migrator.apply_forward(eng); eng.dispose()
        env_lines = {
            "IDENTITY_I1_ENABLED": "1", "DM_MAIN_BACKEND": "1",
            "DATABASE_URL": f"sqlite:///{db}",
            "WECHAT_APP_ID": "wx_e2e_id", "WECHAT_APP_SECRET": "wx_e2e_secret_value",
            "DM_OPENID_HMAC_KEY": "e2e_openid_hmac_key_at_least_32_chars_x",
            "DM_ADAPTER_SHARED_SECRET": "e2e_adapter_shared_secret_16c",
            "DM_DAILY_LOOP_ADAPTER_ENABLED": "1",
            "DM_DAILY_LOOP_BASE_URL": "http://daily-loop.internal:18090",
        }
        with open(os.path.join(d, ".env"), "w") as f:
            for k, v in env_lines.items():
                f.write(f"{k}={v}\n")
        script = r'''
import hmac
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.database import SessionLocal
from backend.app.identity import models as im, session_service as ss
from backend.app.identity.daily_loop_client import DailyLoopClient
from backend.app.adapters import daily_loop_adapter as ad
from backend.app.config import settings

# real active user + active binding + minted session (no dependency replaced)
db = SessionLocal()
u = im.AppUser(status="active"); db.add(u); db.commit()
db.add(im.WechatIdentity(app_user_id=u.id, openid_hash=ss.hash_openid("wx_e2e")))
b = im.StoreMemberBinding(app_user_id=u.id, dl_auth_user_id="U-E2E", dl_store_id="S-E2E",
    dl_member_id="M-E2E", role="owner", status="active", identity_version=1)
db.add(b); db.commit()
token, _ = ss.mint_session(db, u, b); db.close()

# inject ONLY the upstream HTTP transport (class-level); adapter/signer/identity real
captured = {}
def _capture(self, method, url, params, headers, timeout):
    captured.update(method=method, url=url,
                    params=dict(params or {}), headers=dict(headers or {}))
    return 200, {"items": [{"task_id": "T-1"}]}
DailyLoopClient._http = _capture

c = TestClient(app)
r = c.get("/api/daily-loop/v1/tasks?date=2026-07-19",
          headers={"Authorization": "Bearer " + token})
assert r.status_code == 200, (r.status_code, r.text)
assert r.json()["data"]["items"] == [{"task_id": "T-1"}], r.text

h = captured["headers"]
assert h["X-DM-S2S-Version"] == "dm-s2s-v2", h
assert h["X-DM-Auth-User-Id"] == "U-E2E", h            # identity from authoritative binding
assert h["X-DM-Target-Store-Id"] == "S-E2E", h
assert captured["params"] == {"task_date": "2026-07-19"}, captured["params"]
assert captured["url"].startswith("http://daily-loop.internal:18090"), captured["url"]  # base URL from Settings/.env

# independent verify: recompute the dm-s2s-v2 signature from the SAME Settings shared
# secret using the golden-pinned canonicalization; it must match the captured header.
key = ad._derive_key(settings.dm_adapter_shared_secret)
exp = ad.canonical_signature(key, "GET", "/v1/dl/internal/tasks", b"",
      h["X-DM-S2S-Timestamp"], h["X-DM-S2S-Nonce"], {"task_date": "2026-07-19"}, "U-E2E", "S-E2E")
assert hmac.compare_digest(exp, h["X-DM-S2S-Signature"]), "signature must verify under golden canonicalization"
print("E2E_SIGNED_OK")
'''
        r = self._run_in_dir(d, {}, script)  # NO identity/adapter keys in the process env
        import shutil; shutil.rmtree(d, ignore_errors=True)
        self.assertIn("E2E_SIGNED_OK", r.stdout, r.stderr)
        _rec("30_env_only_facade_e2e_signed", "E2E_SIGNED_OK" in r.stdout)

    # R1c acceptance #7: with DM_MAIN_BACKEND=1 (Settings) and a forbidden secret
    # root injected into the process env, constructing the real adapter must fail
    # closed; the error names the offending KEY but never leaks its VALUE.
    def test_31_adapter_key_isolation_fail_closed(self):
        d = tempfile.mkdtemp()
        env_lines = {
            "WECHAT_APP_ID": "x", "WECHAT_APP_SECRET": "y",
            "DM_OPENID_HMAC_KEY": "iso_openid_hmac_key_at_least_32_chars_x",
            "DM_MAIN_BACKEND": "1", "DM_ADAPTER_SHARED_SECRET": "iso_adapter_shared_secret_16c",
        }
        with open(os.path.join(d, ".env"), "w") as f:
            for k, v in env_lines.items():
                f.write(f"{k}={v}\n")
        forbidden_val = "forbidden_vault_root_value_do_not_leak"
        script = (
            "from backend.app.adapters import daily_loop_adapter as ad\n"
            "from backend.app.config import settings\n"
            "assert settings.dm_main_backend is True\n"
            "try:\n"
            "    ad.DailyLoopAdapter(shared_secret=settings.dm_adapter_shared_secret,\n"
            "                        main_backend=settings.dm_main_backend,\n"
            "                        enabled=settings.dm_daily_loop_adapter_enabled)\n"
            "    print('NO_FAIL')\n"
            "except ad.MainBackendKeyIsolationError as e:\n"
            "    assert 'DM_VAULT_MASTER_KEY' in str(e), str(e)\n"
            "    assert %r not in str(e), 'secret value leaked'\n"
            "    print('ISO_FAILCLOSED_OK')\n"
        ) % forbidden_val
        r = self._run_in_dir(d, {"DM_VAULT_MASTER_KEY": forbidden_val}, script)
        import shutil; shutil.rmtree(d, ignore_errors=True)
        self.assertIn("ISO_FAILCLOSED_OK", r.stdout, r.stderr)
        self.assertNotIn("NO_FAIL", r.stdout)
        self.assertNotIn(forbidden_val, r.stdout + r.stderr)  # value never echoed
        _rec("31_adapter_key_isolation_fail_closed", "ISO_FAILCLOSED_OK" in r.stdout)

    # R1c acceptance #8: a missing/short S2S shared secret still fails closed when
    # the real adapter is constructed (AdapterConfigError, no secret value).
    def test_32_adapter_short_secret_fail_closed(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, ".env"), "w") as f:
            f.write("DM_MAIN_BACKEND=0\nDM_ADAPTER_SHARED_SECRET=s3cr3t7\n")  # 7 chars < 16
        script = (
            "from backend.app.adapters import daily_loop_adapter as ad\n"
            "from backend.app.config import settings\n"
            "assert settings.dm_adapter_shared_secret == 's3cr3t7'\n"
            "try:\n"
            "    ad.DailyLoopAdapter(shared_secret=settings.dm_adapter_shared_secret,\n"
            "                        main_backend=settings.dm_main_backend, enabled=True)\n"
            "    print('NO_FAIL')\n"
            "except ad.AdapterConfigError as e:\n"
            "    assert 's3cr3t7' not in str(e), 'secret value leaked'\n"
            "    print('SECRET_FAILCLOSED_OK')\n"
        )
        r = self._run_in_dir(d, {}, script)
        import shutil; shutil.rmtree(d, ignore_errors=True)
        self.assertIn("SECRET_FAILCLOSED_OK", r.stdout, r.stderr)
        self.assertNotIn("NO_FAIL", r.stdout)
        _rec("32_adapter_short_secret_fail_closed", "SECRET_FAILCLOSED_OK" in r.stdout)

    def test_25_schema_version_missing_fail_closed(self):
        # migrated then delete the machine version row -> readiness must fail
        db = self._tmpdb(migrated=True)
        eng = create_engine(f"sqlite:///{db}")
        with eng.begin() as c:
            from sqlalchemy import text
            c.execute(text("DELETE FROM dl_identity_schema_meta"))
        eng.dispose()
        env = {"IDENTITY_I1_ENABLED": "1", "DATABASE_URL": f"sqlite:///{db}", **self._GOOD_CFG}
        script = ("try:\n import backend.app.main\n print('NO_FAIL')\n"
                  "except Exception as e:\n print('FAILCLOSED:'+type(e).__name__)\n")
        r = self._run(env, script)
        os.unlink(db)
        self.assertIn("FAILCLOSED", r.stdout, r.stderr)
        _rec("25_schema_version_missing", "FAILCLOSED" in r.stdout)

    def test_21_enabled_unmigrated_fail_closed(self):
        db = self._tmpdb(migrated=False)  # enabled but NOT migrated
        script = (
            "try:\n"
            "    import backend.app.main\n"
            "    print('NO_FAIL')\n"
            "except Exception as e:\n"
            "    print('FAILCLOSED:' + type(e).__name__)\n"
        )
        r = self._run({"IDENTITY_I1_ENABLED": "1", "DATABASE_URL": f"sqlite:///{db}",
                       "DM_ADAPTER_SHARED_SECRET": "test_adapter_shared_secret_16c"}, script)
        os.unlink(db)
        self.assertIn("FAILCLOSED", r.stdout, r.stderr)
        self.assertNotIn("NO_FAIL", r.stdout)
        _rec("21_enabled_unmigrated_fail_closed", "FAILCLOSED" in r.stdout)


if __name__ == "__main__":
    unittest.main()
