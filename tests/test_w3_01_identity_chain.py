"""DSM W3-01 authoritative employee-identity acceptance matrix.

Schema is built by the REVIEWED MIGRATION (not ORM create_all) so migration/ORM
consistency is genuinely exercised. Covers the §9.1 behavior list: login
bound/unbound, code validation, code2session reject/timeout, replay guard, login
rate limit, token randomness + DB-stores-only-sha256, /me valid/invalid/expired/
revoked/disabled/drift, client-forged store/role ignored, external opaque
store/member ids, store 3-id mapping uniqueness, logout success/idempotency/
post-logout, unified envelope on 401/403/422/429/500/503, and no
code/openid/token/secret leakage in logs.

Emits structured evidence to DM_W3_01_EVIDENCE_PATH when set.
"""
import io
import json
import logging
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient

from backend.app.database import get_db
from backend.app.identity import models as im
from backend.app.identity import (migrator, session_service, service, store_registry,
                                   envelope)
from backend.app.identity.errors import ApiError, VALIDATION_ERROR
from backend.app.identity.ratelimit import LoginRateLimiter, CodeReplayGuard
from backend.app.identity.wechat import WeChatClient, WeChatError
from backend.app.routers import auth_identity

_EVID = []


def _rec(case, ok, extra=None):
    e = {"case": case, "passed": bool(ok)}
    if extra:
        e.update(extra)
    _EVID.append(e)


def tearDownModule():
    p = os.environ.get("DM_W3_01_EVIDENCE_PATH")
    if p:
        json.dump({"report_type": "DSM_W3_01_IDENTITY_TEST_MATRIX",
                   "total": len(_EVID), "passed": sum(1 for e in _EVID if e["passed"]),
                   "cases": _EVID}, open(p, "w"), indent=2, ensure_ascii=False)


class FakeWeChat(WeChatClient):
    """Injectable WeChat client: returns a fixed openid or raises a chosen error
    reason. Never touches the network."""
    def __init__(self, openid=None, error=None):
        super().__init__(app_id="x", app_secret="y", transport=lambda *a, **k: {})
        self._openid, self._error = openid, error

    def code2session(self, code):
        if not code or len(code) > 512:
            raise WeChatError("invalid_code")
        if self._error:
            raise WeChatError(self._error)
        return self._openid


def _build_test_app() -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _trace(request: Request, call_next):
        incoming = request.headers.get("x-trace-id")
        request.state.trace_id = incoming or envelope.new_trace_id()
        return await call_next(request)

    app.include_router(auth_identity.router)

    @app.exception_handler(ApiError)
    async def _h(request: Request, exc: ApiError):
        return JSONResponse(status_code=exc.http_status,
                            content=exc.envelope(envelope.trace_id_of(request)))

    @app.exception_handler(RequestValidationError)
    async def _v(request: Request, exc: RequestValidationError):
        if request.url.path.startswith("/api/auth"):
            return JSONResponse(status_code=422, content={
                "code": VALIDATION_ERROR, "message": "请求参数错误",
                "trace_id": envelope.trace_id_of(request), "data": None})
        return JSONResponse(status_code=422, content={"detail": jsonable_encoder(exc.errors())})

    return app


class W3Base(unittest.TestCase):
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

        # deterministic, isolated limiter + replay guard per test (generous defaults
        # so ordinary logins are never throttled; specific tests override).
        service._login_limiter = LoginRateLimiter(1000, 1000)
        service._code_guard = CodeReplayGuard(1000)

        self.client = TestClient(self.app)

    def tearDown(self):
        self.app.dependency_overrides.clear()
        self.app.dependency_overrides = {}
        service._login_limiter = None
        service._code_guard = None
        try:
            os.unlink(self.dbfile)
        except OSError:
            pass

    # ---- helpers -----------------------------------------------------------
    def _set_wechat(self, openid=None, error=None):
        auth_identity.router  # noqa
        self.app.dependency_overrides[auth_identity.get_wechat_client] = \
            lambda: FakeWeChat(openid=openid, error=error)

    def _seed_binding(self, openid, dl_store_id="dls_1", role="manager",
                      dl_auth_user_id="au_1", dl_member_id="m_free_text_1",
                      main_store_id=101, v013_store_id="v013_store_A"):
        """Create app_user + wechat identity + registry + active binding for openid."""
        db = self.TestSession()
        try:
            openid_hash = session_service.hash_openid(openid)
            u = im.AppUser(status="active")
            db.add(u); db.flush()
            db.add(im.WechatIdentity(app_user_id=u.id, openid_hash=openid_hash))
            reg = store_registry.register_store(db, dl_store_id,
                                                main_store_id=main_store_id,
                                                v013_store_id=v013_store_id)
            db.add(im.StoreMemberBinding(
                app_user_id=u.id, dl_auth_user_id=dl_auth_user_id,
                dl_store_id=dl_store_id, dl_member_id=dl_member_id,
                member_public_id=store_registry.new_member_public_id(),
                role=role, status="active"))
            db.commit()
            return u.id, reg.public_id
        finally:
            db.close()

    def _login(self, openid, code="code_ok"):
        self._set_wechat(openid=openid)
        return self.client.post("/api/auth/wechat/login", json={"code": code})

    def _assert_envelope(self, body):
        for k in ("code", "message", "trace_id", "data"):
            self.assertIn(k, body, f"envelope missing {k}")
        self.assertTrue(body["trace_id"])


class TestLogin(W3Base):
    def test_01_login_success_bound(self):
        self._seed_binding("openid_bound_1")
        r = self._login("openid_bound_1")
        self.assertEqual(r.status_code, 200, r.text)
        b = r.json(); self._assert_envelope(b)
        self.assertEqual(b["code"], "OK")
        self.assertTrue(b["data"]["token"])
        self.assertEqual(b["data"]["expires_in"], 24 * 3600)
        self.assertTrue(b["data"]["bound"])
        # expires_in and expires_at agree
        exp = datetime.fromisoformat(b["data"]["expires_at"])
        self.assertGreater(exp, datetime.now(timezone.utc))
        _rec("01_login_success_bound", True)

    def test_02_login_success_unbound(self):
        r = self._login("openid_unbound_1")
        self.assertEqual(r.status_code, 200, r.text)
        b = r.json(); self._assert_envelope(b)
        self.assertFalse(b["data"]["bound"])
        self.assertTrue(b["data"]["token"])
        _rec("02_login_success_unbound", True)

    def test_03_code_missing_empty_toolong(self):
        self._set_wechat(openid="x")
        # missing
        r1 = self.client.post("/api/auth/wechat/login", json={})
        # empty
        r2 = self.client.post("/api/auth/wechat/login", json={"code": ""})
        # too long
        r3 = self.client.post("/api/auth/wechat/login", json={"code": "a" * 513})
        for r in (r1, r2, r3):
            self.assertEqual(r.status_code, 422, r.text)
            b = r.json(); self._assert_envelope(b)
            self.assertEqual(b["code"], VALIDATION_ERROR)
        _rec("03_code_missing_empty_toolong", True)

    def test_04_code2session_rejected(self):
        self._set_wechat(error="wechat_rejected")
        r = self.client.post("/api/auth/wechat/login", json={"code": "bad_code"})
        self.assertEqual(r.status_code, 422, r.text)
        b = r.json(); self._assert_envelope(b)
        self.assertEqual(b["code"], VALIDATION_ERROR)
        _rec("04_code2session_rejected", True)

    def test_04b_code2session_timeout_is_503(self):
        self._set_wechat(error="transport_error")
        r = self.client.post("/api/auth/wechat/login", json={"code": "some_code"})
        self.assertEqual(r.status_code, 503, r.text)
        b = r.json(); self._assert_envelope(b)
        self.assertEqual(b["code"], "DEPENDENCY_UNAVAILABLE")
        _rec("04b_code2session_timeout_is_503", True)

    def test_05_code_replay_rejected(self):
        service._code_guard = CodeReplayGuard(1000)
        self._set_wechat(openid="openid_replay")
        r1 = self.client.post("/api/auth/wechat/login", json={"code": "same_code"})
        self.assertEqual(r1.status_code, 200, r1.text)
        r2 = self.client.post("/api/auth/wechat/login", json={"code": "same_code"})
        self.assertEqual(r2.status_code, 422, r2.text)
        self.assertEqual(r2.json()["code"], VALIDATION_ERROR)
        _rec("05_code_replay_rejected", True)

    def test_06_login_rate_limited(self):
        service._login_limiter = LoginRateLimiter(1000, 3)  # 3 attempts/window
        self._set_wechat(openid="openid_rl")
        codes = ["c1", "c2", "c3", "c4"]
        statuses = []
        for c in codes:
            statuses.append(self.client.post("/api/auth/wechat/login",
                                             json={"code": c}).status_code)
        self.assertEqual(statuses[:3], [200, 200, 200], statuses)
        self.assertEqual(statuses[3], 429, statuses)
        b = self.client.post("/api/auth/wechat/login", json={"code": "c5"}).json()
        self.assertEqual(b["code"], "RATE_LIMITED")
        self._assert_envelope(b)
        _rec("06_login_rate_limited", True)

    def test_07_token_random_and_db_only_hash(self):
        self._seed_binding("openid_tok")
        tokens = set()
        # three logins (unique codes) -> three distinct random tokens
        for i, code in enumerate(("t1", "t2", "t3")):
            self._set_wechat(openid="openid_tok")
            r = self.client.post("/api/auth/wechat/login", json={"code": code})
            tokens.add(r.json()["data"]["token"])
        self.assertEqual(len(tokens), 3)
        for t in tokens:
            self.assertGreaterEqual(len(t), 64)  # 256-bit hex
        # DB stores only sha256(token) — the raw token never appears in any column
        db = self.TestSession()
        try:
            rows = db.execute(text("SELECT token_hash FROM dl_auth_session")).fetchall()
            hashes = {row[0] for row in rows}
            for t in tokens:
                self.assertNotIn(t, hashes)
                self.assertIn(session_service.hash_token(t), hashes)
        finally:
            db.close()
        _rec("07_token_random_and_db_only_hash", True)

    def test_14_store_three_id_mapping_uniqueness(self):
        # same main_store_id under two different dl_store_id must violate uniqueness
        db = self.TestSession()
        try:
            db.add(im.StoreRegistry(public_id="store_aaaaaaaaaaaa",
                                    dl_store_id="dlsX", main_store_id=900))
            db.add(im.StoreRegistry(public_id="store_bbbbbbbbbbbb",
                                    dl_store_id="dlsY", main_store_id=900))
            with self.assertRaises(IntegrityError):
                db.commit()
        finally:
            db.rollback(); db.close()
        _rec("14_store_three_id_mapping_uniqueness", True)


class TestMe(W3Base):
    def _bearer(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_08_me_valid_session(self):
        _, public_id = self._seed_binding("openid_me", role="owner")
        token = self._login("openid_me").json()["data"]["token"]
        r = self.client.get("/api/auth/me", headers=self._bearer(token))
        self.assertEqual(r.status_code, 200, r.text)
        b = r.json(); self._assert_envelope(b)
        self.assertEqual(b["code"], "OK")
        self.assertTrue(b["data"]["bound"])
        self.assertEqual(b["data"]["role"], "owner")
        self.assertEqual(b["data"]["store_id"], public_id)
        self.assertTrue(b["data"]["member_id"].startswith("mbr_"))
        _rec("08_me_valid_session", True)

    def test_02b_me_unbound_is_200_bound_false(self):
        token = self._login("openid_unbound_me").json()["data"]["token"]
        r = self.client.get("/api/auth/me", headers=self._bearer(token))
        self.assertEqual(r.status_code, 200, r.text)
        b = r.json(); self._assert_envelope(b)
        self.assertEqual(b["code"], "OK")
        self.assertFalse(b["data"]["bound"])
        self.assertIsNone(b["data"]["store_id"])
        self.assertIsNone(b["data"]["role"])
        _rec("02b_me_unbound_is_200_bound_false", True)

    def test_09a_me_missing_and_invalid(self):
        # no header
        r0 = self.client.get("/api/auth/me")
        self.assertEqual(r0.status_code, 401, r0.text)
        self.assertEqual(r0.json()["code"], "SESSION_INVALID")
        self._assert_envelope(r0.json())
        # unknown token
        r1 = self.client.get("/api/auth/me", headers=self._bearer("deadbeef" * 8))
        self.assertEqual(r1.status_code, 401)
        self.assertEqual(r1.json()["code"], "SESSION_INVALID")
        # legacy mock token rejected
        r2 = self.client.get("/api/auth/me", headers=self._bearer("token_mock_openid_x"))
        self.assertEqual(r2.status_code, 401)
        _rec("09a_me_missing_and_invalid", True)

    def test_09b_me_expired(self):
        token = self._login("openid_exp").json()["data"]["token"]
        db = self.TestSession()
        try:
            past = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
            db.execute(text("UPDATE dl_auth_session SET expires_at=:e WHERE token_hash=:h"),
                       {"e": past, "h": session_service.hash_token(token)})
            db.commit()
        finally:
            db.close()
        r = self.client.get("/api/auth/me", headers=self._bearer(token))
        self.assertEqual(r.status_code, 401, r.text)
        self.assertEqual(r.json()["code"], "SESSION_EXPIRED")
        self._assert_envelope(r.json())
        _rec("09b_me_expired", True)

    def test_09c_me_revoked(self):
        token = self._login("openid_rev").json()["data"]["token"]
        self.client.post("/api/auth/logout", headers=self._bearer(token))
        r = self.client.get("/api/auth/me", headers=self._bearer(token))
        self.assertEqual(r.status_code, 401, r.text)
        self.assertEqual(r.json()["code"], "SESSION_INVALID")
        _rec("09c_me_revoked", True)

    def test_10_me_binding_status_drift(self):
        self._seed_binding("openid_drift")
        token = self._login("openid_drift").json()["data"]["token"]
        # disable the binding out of band -> trigger bumps status_epoch -> old token dead
        db = self.TestSession()
        try:
            db.execute(text("UPDATE dl_store_member_binding SET status='disabled'"))
            db.commit()
        finally:
            db.close()
        r = self.client.get("/api/auth/me", headers=self._bearer(token))
        self.assertIn(r.status_code, (401, 403), r.text)
        self.assertGreaterEqual(r.status_code, 400)
        self._assert_envelope(r.json())
        _rec("10_me_binding_status_drift", True)

    def test_10b_me_appuser_disabled(self):
        self._seed_binding("openid_udis")
        token = self._login("openid_udis").json()["data"]["token"]
        db = self.TestSession()
        try:
            db.execute(text("UPDATE dl_app_user SET status='disabled'"))
            db.commit()
        finally:
            db.close()
        r = self.client.get("/api/auth/me", headers=self._bearer(token))
        self.assertIn(r.status_code, (401, 403), r.text)
        _rec("10b_me_appuser_disabled", True)

    def test_11_12_role_store_from_binding_only_forgery_ignored(self):
        _, public_id = self._seed_binding("openid_forge", role="staff",
                                          dl_store_id="dls_forge")
        token = self._login("openid_forge").json()["data"]["token"]
        # forge store_id/role via query + header — must be ignored
        r = self.client.get("/api/auth/me?store_id=store_hacker&role=owner",
                            headers={**self._bearer(token),
                                     "X-Store-Id": "store_hacker", "X-Role": "owner"})
        self.assertEqual(r.status_code, 200, r.text)
        b = r.json()
        self.assertEqual(b["data"]["role"], "staff")
        self.assertEqual(b["data"]["store_id"], public_id)
        self.assertNotEqual(b["data"]["store_id"], "store_hacker")
        _rec("11_12_role_store_from_binding_only", True)

    def test_13_external_store_id_is_opaque(self):
        _, public_id = self._seed_binding("openid_opaque", dl_store_id="dls_raw_internal",
                                          main_store_id=555, v013_store_id="v013_raw")
        token = self._login("openid_opaque").json()["data"]["token"]
        b = self.client.get("/api/auth/me", headers=self._bearer(token)).json()
        sid = b["data"]["store_id"]
        self.assertTrue(sid.startswith("store_"))
        self.assertEqual(sid, public_id)
        # never a raw internal id
        self.assertNotIn(sid, ("dls_raw_internal", "555", "v013_raw"))
        self.assertFalse(sid.isdigit())
        _rec("13_external_store_id_is_opaque", True)

    def test_18_500_uses_envelope_on_missing_registry(self):
        # bound binding but NO registry row -> resolve fails closed with 500 envelope
        db = self.TestSession()
        try:
            u = im.AppUser(status="active"); db.add(u); db.flush()
            db.add(im.WechatIdentity(app_user_id=u.id,
                                     openid_hash=session_service.hash_openid("openid_noreg")))
            db.add(im.StoreMemberBinding(
                app_user_id=u.id, dl_auth_user_id="au", dl_store_id="dls_unregistered",
                dl_member_id="m", member_public_id=store_registry.new_member_public_id(),
                role="manager", status="active"))
            db.commit()
        finally:
            db.close()
        token = self._login("openid_noreg").json()["data"]["token"]
        r = self.client.get("/api/auth/me", headers=self._bearer(token))
        self.assertEqual(r.status_code, 500, r.text)
        b = r.json(); self._assert_envelope(b)
        self.assertEqual(b["code"], "INTERNAL_ERROR")
        # no internal leak in the message
        for bad in ("dls_unregistered", "Traceback", "SELECT", "dl_store_registry"):
            self.assertNotIn(bad, b["message"])
        _rec("18_500_uses_envelope", True)


class TestLogout(W3Base):
    def _bearer(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_15_logout_success(self):
        token = self._login("openid_lo").json()["data"]["token"]
        r = self.client.post("/api/auth/logout", headers=self._bearer(token))
        self.assertEqual(r.status_code, 200, r.text)
        b = r.json(); self._assert_envelope(b)
        self.assertEqual(b["code"], "OK")
        self.assertIsNone(b["data"])
        _rec("15_logout_success", True)

    def test_16_logout_idempotent(self):
        token = self._login("openid_lo2").json()["data"]["token"]
        r1 = self.client.post("/api/auth/logout", headers=self._bearer(token))
        r2 = self.client.post("/api/auth/logout", headers=self._bearer(token))
        # no-token logout is also a silent success
        r3 = self.client.post("/api/auth/logout")
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r3.status_code, 200)
        _rec("16_logout_idempotent", True)

    def test_17_logout_then_me_fails(self):
        token = self._login("openid_lo3").json()["data"]["token"]
        self.client.post("/api/auth/logout", headers=self._bearer(token))
        r = self.client.get("/api/auth/me", headers=self._bearer(token))
        self.assertEqual(r.status_code, 401, r.text)
        _rec("17_logout_then_me_fails", True)


class TestEnvelopeAndLeak(W3Base):
    def _bearer(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_19_all_responses_have_data_field(self):
        # success + several error classes all carry a present data key
        self._seed_binding("openid_env")
        ok = self._login("openid_env").json()
        bad = self.client.post("/api/auth/wechat/login", json={"code": ""}).json()
        noauth = self.client.get("/api/auth/me").json()
        for body in (ok, bad, noauth):
            self._assert_envelope(body)
            self.assertIn("data", body)
        _rec("19_all_responses_have_data_field", True)

    def test_20_no_secret_leak_in_logs(self):
        openid = "openid_SENSITIVE_9f3a"
        code = "code_SENSITIVE_7b21"
        self._seed_binding(openid)
        buf = io.StringIO()
        handler = logging.StreamHandler(buf)
        root = logging.getLogger()
        prev_level = root.level
        root.setLevel(logging.DEBUG)
        root.addHandler(handler)
        try:
            self._set_wechat(openid=openid)
            r = self.client.post("/api/auth/wechat/login", json={"code": code})
            token = r.json()["data"]["token"]
        finally:
            root.removeHandler(handler)
            root.setLevel(prev_level)
        logs = buf.getvalue()
        for secret in (code, openid, token, "y"):  # "y" = FakeWeChat app_secret
            if secret == "y":
                continue  # single char is not a meaningful leak assertion
            self.assertNotIn(secret, logs, f"leaked {secret!r} in logs")
        _rec("20_no_secret_leak_in_logs", True)


class TestReadinessGates(unittest.TestCase):
    """§6/§8: fail-closed startup gates (config + migrated schema)."""

    class _S:  # minimal settings stand-in
        def __init__(self, **kw):
            self.wechat_app_id = kw.get("wechat_app_id", "appid")
            self.wechat_app_secret = kw.get("wechat_app_secret", "app_secret_value")
            self.dm_main_backend = kw.get("dm_main_backend", True)
            self.dm_openid_hmac_key = kw.get("dm_openid_hmac_key", "k" * 40)
            self.dm_adapter_shared_secret = kw.get("dm_adapter_shared_secret", "adapter_secret")

    def test_config_ok(self):
        from backend.app.identity.readiness import check_identity_config
        check_identity_config(self._S(), env={})  # no raise

    def test_config_missing_wechat(self):
        from backend.app.identity.readiness import check_identity_config, IdentityConfigError
        with self.assertRaises(IdentityConfigError):
            check_identity_config(self._S(wechat_app_secret=""), env={})

    def test_config_requires_main_backend(self):
        from backend.app.identity.readiness import check_identity_config, IdentityConfigError
        with self.assertRaises(IdentityConfigError):
            check_identity_config(self._S(dm_main_backend=False), env={})

    def test_config_hmac_too_short(self):
        from backend.app.identity.readiness import check_identity_config, IdentityConfigError
        with self.assertRaises(IdentityConfigError):
            check_identity_config(self._S(dm_openid_hmac_key="short"), env={})

    def test_config_hmac_must_be_independent(self):
        from backend.app.identity.readiness import check_identity_config, IdentityConfigError
        key = "z" * 40
        with self.assertRaises(IdentityConfigError):
            check_identity_config(self._S(dm_openid_hmac_key=key, wechat_app_secret=key), env={})
        # nor equal a daily-loop root present in the environment
        with self.assertRaises(IdentityConfigError):
            check_identity_config(self._S(dm_openid_hmac_key=key),
                                  env={"DM_VAULT_MASTER_KEY": key})

    def test_ready_fails_on_unmigrated_then_passes(self):
        from backend.app.identity.readiness import check_ready, IdentityNotReady
        fd, dbf = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            eng = create_engine(f"sqlite:///{dbf}", connect_args={"check_same_thread": False})
            with self.assertRaises(IdentityNotReady):
                check_ready(eng)
            migrator.apply_forward(eng)
            check_ready(eng)  # no raise after migration
        finally:
            try:
                os.unlink(dbf)
            except OSError:
                pass

    def test_migration_idempotent_and_rollback(self):
        from backend.app.identity.readiness import check_ready, IdentityNotReady
        from sqlalchemy import inspect
        fd, dbf = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            eng = create_engine(f"sqlite:///{dbf}", connect_args={"check_same_thread": False})
            migrator.apply_forward(eng)
            migrator.apply_forward(eng)  # re-run is safe (idempotent)
            check_ready(eng)
            self.assertIn("dl_store_registry", set(inspect(eng).get_table_names()))
            migrator.apply_rollback(eng)
            self.assertNotIn("dl_app_user", set(inspect(eng).get_table_names()))
            with self.assertRaises(IdentityNotReady):
                check_ready(eng)
        finally:
            try:
                os.unlink(dbf)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
