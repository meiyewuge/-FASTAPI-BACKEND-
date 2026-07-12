"""DedupManager — 跨任务历史去重。

SQLite 表: search_dedup
窗口: 7 天
- 同一 URL 7 天内标记 merged / duplicate
- 7 天后可重新出现，标注 continuation / 延续跟踪
- 30 天核心选题出现超过 3 次，降权或提示换角度

要求:
- 默认不写生产路径
- 测试必须使用 tmp_path 临时 SQLite
- 不写 ECS 真实库
- 不入正式知识库
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


# 去重状态
DEDUP_STATUS_MERGED = "merged"
DEDUP_STATUS_DUPLICATE = "duplicate"
DEDUP_STATUS_CONTINUATION = "continuation"
DEDUP_STATUS_NEW = "new"

# 窗口
WINDOW_7_DAYS = timedelta(days=7)
WINDOW_30_DAYS = timedelta(days=30)

# 核心选题降权阈值
CORE_TOPIC_THRESHOLD = 3


def _utcnow() -> datetime:
    """获取当前 UTC 时间。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _url_hash(url: str) -> str:
    """URL 的 MD5 哈希。"""
    return hashlib.md5(url.encode("utf-8")).hexdigest()


@dataclass
class DedupResult:
    """单条结果的去重判定。"""
    url: str
    status: str = DEDUP_STATUS_NEW
    seen_count: int = 0
    first_seen_at: str = ""
    last_seen_at: str = ""
    confidence_score: float = 0.0
    dedup_status: str = DEDUP_STATUS_NEW
    is_core_topic_overexposed: bool = False
    core_topic_count_30d: int = 0

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "status": self.status,
            "seen_count": self.seen_count,
            "first_seen_at": self.first_seen_at,
            "last_seen_at": self.last_seen_at,
            "confidence_score": self.confidence_score,
            "dedup_status": self.dedup_status,
            "is_core_topic_overexposed": self.is_core_topic_overexposed,
            "core_topic_count_30d": self.core_topic_count_30d,
        }


class DedupManager:
    """跨任务历史去重管理器。"""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS search_dedup (
        url_hash TEXT PRIMARY KEY,
        url TEXT NOT NULL,
        title TEXT,
        task_id TEXT,
        provider TEXT,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        seen_count INTEGER DEFAULT 1,
        confidence_score REAL DEFAULT 0.0,
        dedup_status TEXT DEFAULT 'new'
    );
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._connect()

    def _connect(self) -> None:
        self._conn = sqlite3.connect(self._db_path)
        self._conn.execute(self.SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "DedupManager":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def check_url(
        self,
        url: str,
        title: str = "",
        task_id: str = "",
        provider: str = "",
        confidence_score: float = 0.0,
        now: datetime | None = None,
    ) -> DedupResult:
        if now is None:
            now = _utcnow()
        now_str = now.isoformat()
        url_h = _url_hash(url)

        assert self._conn is not None
        cursor = self._conn.cursor()

        cursor.execute(
            "SELECT first_seen_at, last_seen_at, seen_count, confidence_score, dedup_status "
            "FROM search_dedup WHERE url_hash = ?",
            (url_h,),
        )
        row = cursor.fetchone()

        if row is None:
            cursor.execute(
                "INSERT INTO search_dedup (url_hash, url, title, task_id, provider, "
                "first_seen_at, last_seen_at, seen_count, confidence_score, dedup_status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
                (url_h, url, title, task_id, provider, now_str, now_str, confidence_score, DEDUP_STATUS_NEW),
            )
            self._conn.commit()
            return DedupResult(
                url=url, status=DEDUP_STATUS_NEW, seen_count=1,
                first_seen_at=now_str, last_seen_at=now_str,
                confidence_score=confidence_score, dedup_status=DEDUP_STATUS_NEW,
            )

        first_seen_str, last_seen_str, seen_count, existing_confidence, existing_status = row
        first_seen = datetime.fromisoformat(first_seen_str)
        last_seen = datetime.fromisoformat(last_seen_str)

        age = now - last_seen
        in_7day_window = age < WINDOW_7_DAYS
        new_seen_count = seen_count + 1

        first_seen_age = now - first_seen
        in_30day_window = first_seen_age < WINDOW_30_DAYS
        core_topic_overexposed = in_30day_window and new_seen_count > CORE_TOPIC_THRESHOLD

        if in_7day_window:
            dedup_status = DEDUP_STATUS_MERGED
            status = DEDUP_STATUS_MERGED
        else:
            dedup_status = DEDUP_STATUS_CONTINUATION
            status = DEDUP_STATUS_CONTINUATION

        cursor.execute(
            "UPDATE search_dedup SET last_seen_at = ?, seen_count = ?, "
            "confidence_score = ?, dedup_status = ?, title = ?, task_id = ?, provider = ? "
            "WHERE url_hash = ?",
            (now_str, new_seen_count, max(confidence_score, existing_confidence),
             dedup_status, title or "", task_id, provider, url_h),
        )
        self._conn.commit()

        return DedupResult(
            url=url, status=status, seen_count=new_seen_count,
            first_seen_at=first_seen_str, last_seen_at=now_str,
            confidence_score=max(confidence_score, existing_confidence),
            dedup_status=dedup_status,
            is_core_topic_overexposed=core_topic_overexposed,
            core_topic_count_30d=new_seen_count if in_30day_window else 0,
        )

    def check_batch(
        self,
        urls: list[str],
        titles: list[str] | None = None,
        task_id: str = "",
        provider: str = "",
        now: datetime | None = None,
    ) -> list[DedupResult]:
        if now is None:
            now = _utcnow()
        results: list[DedupResult] = []
        for i, url in enumerate(urls):
            title = titles[i] if titles and i < len(titles) else ""
            results.append(self.check_url(url, title, task_id, provider, now=now))
        return results

    def get_core_topic_count(self, url: str, now: datetime | None = None) -> int:
        if now is None:
            now = _utcnow()
        url_h = _url_hash(url)
        assert self._conn is not None
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT first_seen_at, seen_count FROM search_dedup WHERE url_hash = ?",
            (url_h,),
        )
        row = cursor.fetchone()
        if row is None:
            return 0
        first_seen_str, seen_count = row
        first_seen = datetime.fromisoformat(first_seen_str)
        if (now - first_seen) < WINDOW_30_DAYS:
            return seen_count
        return 0


# -- Phase2 V1.1: Single-Run Dedup + Cross-Day Dedup + Quarantine --

_PHASE2_CROSS_DAY_DB_PATH = "/tmp/sr_p02_phase2_cross_day_dedup.db"

# Fix 3: SAFE_STRIP — only these are removed (tightened whitelist)
SAFE_STRIP_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_cid", "utm_reader", "utm_name", "utm_social", "utm_social-type",
    "utm_referrer", "utm_brand", "utm_keyword",
    "fbclid", "gclid", "dclid", "msclkid", "yclid", "twclid", "igshid",
    "mc_cid", "mc_eid",
})

# Fix 3: AMBIGUOUS_PRESERVE — these are preserved by default
AMBIGUOUS_PRESERVE_PARAMS = frozenset({
    "fb_action_ids", "fb_action_types", "fb_source", "fb_ref",
    "gclsrc", "_ga", "_gl", "_gid", "_gcl_au",
    "spm", "is_from_webapp", "share_token",
    "ref_src", "ref_url", "smid", "smtyp", "smchannel",
    "wt_mc", "wt_oid", "ns_mchannel", "ns_campaign",
    "bclid", "li_fat_id",
})

# Backward-compatible: TRACKING_PARAMS_DEDUP now only includes SAFE_STRIP
TRACKING_PARAMS_DEDUP = SAFE_STRIP_PARAMS


def _normalize_whitespace(text: str) -> str:
    """Fix 5: Normalize only clearly meaningless whitespace differences."""
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text).strip()


def _content_sha256(content: str) -> str:
    """Fix 5: SHA256 of normalized full content (not MD5 of first 500 chars)."""
    if not content:
        return ""
    normalized = _normalize_whitespace(content)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def canonicalize_url_for_dedup(url: str) -> str:
    """Fix 3: URL canonicalization — only strips SAFE_STRIP params.
    Preserves: business query params, path, fragment, param value case,
    duplicate params, empty value params, and all AMBIGUOUS_PRESERVE params.
    """
    if not url:
        return ""
    try:
        from urllib.parse import urlparse as _urlparse, urlunparse as _urlunparse
        parsed = _urlparse(url)
        if not parsed.query:
            return url
        original_pairs = []
        for pair in parsed.query.split("&"):
            if "=" in pair:
                key = pair.split("=", 1)[0]
                if key.lower() not in SAFE_STRIP_PARAMS:
                    original_pairs.append(pair)
            else:
                if pair.lower() not in SAFE_STRIP_PARAMS:
                    original_pairs.append(pair)
        new_query = "&".join(original_pairs)
        return _urlunparse((
            parsed.scheme, parsed.netloc, parsed.path,
            parsed.params, new_query, parsed.fragment
        ))
    except Exception:
        return url


@dataclass
class SingleRunDedupResult:
    """Fix 4: Unified decision structure — no mixed states.
    Fields: decision / version_preserved / version_evidence / should_drop / quarantine_reason
    """
    url: str
    canonical_url: str
    decision: str = "new"          # new / duplicate / new_version / uncertain
    is_duplicate: bool = False
    duplicate_of: str = ""
    dedup_status: str = "new"
    version_preserved: bool = False
    version_evidence: str = ""
    should_drop: bool = False
    quarantine_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "canonical_url": self.canonical_url,
            "decision": self.decision,
            "is_duplicate": self.is_duplicate,
            "duplicate_of": self.duplicate_of,
            "dedup_status": self.dedup_status,
            "version_preserved": self.version_preserved,
            "version_evidence": self.version_evidence,
            "should_drop": self.should_drop,
            "quarantine_reason": self.quarantine_reason,
        }


@dataclass
class QuarantineItem:
    """去重隔离项 - 不确定重复项。"""
    url: str
    canonical_url: str
    reason: str = ""
    similar_to_url: str = ""
    similarity_type: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "canonical_url": self.canonical_url,
            "reason": self.reason,
            "similar_to_url": self.similar_to_url,
            "similarity_type": self.similarity_type,
            "metadata": self.metadata,
        }


class SingleRunDeduplicator:
    """V1.1: Unified decision structure.
    Fix 4 rules:
    1. Same URL + same date + same content → decision=duplicate, should_drop=true
    2. Same URL + different date → decision=new_version, version_preserved=true, should_drop=false
    3. Same URL + content changed → decision=new_version, version_preserved=true, should_drop=false
    4. No content + no date → decision=uncertain, should_drop=false → quarantine
    """

    def __init__(self) -> None:
        self._seen_canonical: dict[str, dict] = {}
        self._quarantine: list[QuarantineItem] = []
        self._results: list[SingleRunDedupResult] = []

    def check_url(self, url: str, content: str = "", publish_time: str = "", title: str = "") -> SingleRunDedupResult:
        canonical = canonicalize_url_for_dedup(url)
        content_hash = _content_sha256(content)

        if canonical not in self._seen_canonical:
            self._seen_canonical[canonical] = {
                "url": url, "content_hash": content_hash,
                "publish_time": publish_time, "title": title,
            }
            result = SingleRunDedupResult(
                url=url, canonical_url=canonical,
                decision="new", dedup_status="new", is_duplicate=False,
                should_drop=False,
            )
            self._results.append(result)
            return result

        existing = self._seen_canonical[canonical]
        same_content = (content_hash == existing["content_hash"]) if content_hash and existing["content_hash"] else None
        same_date = (publish_time == existing["publish_time"]) if publish_time and existing["publish_time"] else None

        # Fix 4 Rule 1: same URL + same date + same content → duplicate
        if same_content is True and same_date is not False:
            result = SingleRunDedupResult(
                url=url, canonical_url=canonical,
                decision="duplicate", is_duplicate=True, dedup_status="duplicate",
                duplicate_of=existing["url"],
                version_evidence="same_content_same_date",
                should_drop=True,
            )
            self._results.append(result)
            return result

        # Fix 4 Rule 2: same URL + different date → new_version
        if same_date is False:
            result = SingleRunDedupResult(
                url=url, canonical_url=canonical,
                decision="new_version", is_duplicate=False, dedup_status="new",
                version_preserved=True,
                version_evidence=f"different_date:existing={existing['publish_time']},new={publish_time}",
                should_drop=False,
            )
            self._results.append(result)
            return result

        # Fix 4 Rule 3: same URL + content changed → new_version
        if same_content is False:
            result = SingleRunDedupResult(
                url=url, canonical_url=canonical,
                decision="new_version", is_duplicate=False, dedup_status="new",
                version_preserved=True,
                version_evidence="different_content",
                should_drop=False,
            )
            self._results.append(result)
            return result

        # Fix 4 Rule 4: uncertain
        qi = QuarantineItem(
            url=url, canonical_url=canonical,
            reason="Cannot determine if duplicate: insufficient content or date info",
            similar_to_url=existing["url"],
            similarity_type="canonical_match",
            metadata={
                "existing_publish_time": existing["publish_time"],
                "new_publish_time": publish_time,
                "existing_content_hash": existing["content_hash"],
                "new_content_hash": content_hash,
            },
        )
        self._quarantine.append(qi)
        result = SingleRunDedupResult(
            url=url, canonical_url=canonical,
            decision="uncertain", is_duplicate=False, dedup_status="uncertain",
            quarantine_reason="dedup_review_quarantine: cannot determine if duplicate",
            should_drop=False,
        )
        self._results.append(result)
        return result

    def check_batch(self, urls: list[str], contents: list[str] | None = None,
                    publish_times: list[str] | None = None, titles: list[str] | None = None) -> list[SingleRunDedupResult]:
        results_list = []
        for i, url in enumerate(urls):
            content = contents[i] if contents and i < len(contents) else ""
            pt = publish_times[i] if publish_times and i < len(publish_times) else ""
            title = titles[i] if titles and i < len(titles) else ""
            results_list.append(self.check_url(url, content, pt, title))
        return results_list

    @property
    def quarantine(self) -> list[QuarantineItem]:
        return list(self._quarantine)

    @property
    def results(self) -> list[SingleRunDedupResult]:
        return list(self._results)

    def stats(self) -> dict[str, int]:
        total = len(self._results)
        new = sum(1 for r in self._results if r.decision == "new")
        dup = sum(1 for r in self._results if r.decision == "duplicate")
        nv = sum(1 for r in self._results if r.decision == "new_version")
        unc = sum(1 for r in self._results if r.decision == "uncertain")
        vp = sum(1 for r in self._results if r.version_preserved)
        sd = sum(1 for r in self._results if r.should_drop)
        return {"total": total, "new": new, "duplicate": dup, "new_version": nv,
                "uncertain": unc, "version_preserved": vp, "should_drop": sd,
                "quarantine": len(self._quarantine)}


class CrossDayDeduplicator:
    """V1.1: Cross-day fingerprint dedup with unified decision, SHA256 fingerprints.
    Uses /tmp SQLite, never touches production DB.
    No mixed state "duplicate_version_preserved".
    """

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS cross_day_fingerprints (
        fingerprint TEXT PRIMARY KEY,
        canonical_url TEXT NOT NULL,
        original_url TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        publish_time TEXT,
        title TEXT,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        seen_count INTEGER DEFAULT 1,
        dedup_status TEXT DEFAULT 'new',
        version_evidence TEXT DEFAULT ''
    );
    """

    QUARANTINE_SCHEMA = """
    CREATE TABLE IF NOT EXISTS dedup_review_quarantine (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT NOT NULL,
        canonical_url TEXT NOT NULL,
        reason TEXT NOT NULL,
        similar_to_url TEXT NOT NULL,
        similarity_type TEXT NOT NULL,
        metadata TEXT DEFAULT '{}',
        created_at TEXT NOT NULL,
        resolved INTEGER DEFAULT 0
    );
    """

    def __init__(self, db_path: str = _PHASE2_CROSS_DAY_DB_PATH) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._connect()

    def _connect(self) -> None:
        self._conn = sqlite3.connect(self._db_path)
        self._conn.execute(self.SCHEMA)
        self._conn.execute(self.QUARANTINE_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    @staticmethod
    def _make_fingerprint(canonical_url: str, content_hash: str) -> str:
        """Fix 5: fingerprint uses SHA256 (not MD5)."""
        return hashlib.sha256(f"{canonical_url}|{content_hash}".encode("utf-8")).hexdigest()

    def check_url(self, url: str, content: str = "", publish_time: str = "",
                  title: str = "", now: datetime | None = None) -> dict:
        if now is None:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
        now_str = now.isoformat()
        canonical = canonicalize_url_for_dedup(url)
        content_hash = _content_sha256(content)
        fp = self._make_fingerprint(canonical, content_hash)

        assert self._conn is not None
        cursor = self._conn.cursor()

        cursor.execute(
            "SELECT canonical_url, original_url, content_hash, publish_time, "
            "first_seen_at, last_seen_at, seen_count, dedup_status, version_evidence "
            "FROM cross_day_fingerprints WHERE fingerprint = ?", (fp,))
        row = cursor.fetchone()

        if row is None:
            cursor.execute(
                "SELECT fingerprint, original_url, content_hash, publish_time "
                "FROM cross_day_fingerprints WHERE canonical_url = ?", (canonical,))
            version_rows = cursor.fetchall()

            if version_rows:
                has_different_date = any(r[3] != publish_time for r in version_rows if r[3] and publish_time)
                has_different_content = any(r[2] != content_hash for r in version_rows if content_hash)

                if has_different_date or has_different_content:
                    version_evidence = f"different_version:publish_time={publish_time}"
                    if has_different_content:
                        version_evidence += ";content_changed"
                    cursor.execute(
                        "INSERT INTO cross_day_fingerprints "
                        "(fingerprint, canonical_url, original_url, content_hash, publish_time, "
                        "title, first_seen_at, last_seen_at, seen_count, dedup_status, version_evidence) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 'new', ?)",
                        (fp, canonical, url, content_hash, publish_time, title, now_str, now_str, version_evidence))
                    self._conn.commit()
                    return {
                        "url": url, "canonical_url": canonical,
                        "decision": "new_version",
                        "version_preserved": True,
                        "should_drop": False,
                        "version_evidence": version_evidence,
                        "quarantine_reason": "",
                    }
                else:
                    similar_url = version_rows[0][1]
                    self._add_to_quarantine(url, canonical,
                        "Cross-day uncertain duplicate: same canonical, no clear version diff",
                        similar_url, "canonical_match",
                        {"existing_fp": version_rows[0][0], "new_fp": fp}, now_str)
                    cursor.execute(
                        "INSERT INTO cross_day_fingerprints "
                        "(fingerprint, canonical_url, original_url, content_hash, publish_time, "
                        "title, first_seen_at, last_seen_at, seen_count, dedup_status, version_evidence) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 'uncertain', ?)",
                        (fp, canonical, url, content_hash, publish_time, title, now_str, now_str, "quarantined"))
                    self._conn.commit()
                    return {
                        "url": url, "canonical_url": canonical,
                        "decision": "uncertain",
                        "version_preserved": False,
                        "should_drop": False,
                        "version_evidence": "",
                        "quarantine_reason": "dedup_review_quarantine",
                    }

            cursor.execute(
                "INSERT INTO cross_day_fingerprints "
                "(fingerprint, canonical_url, original_url, content_hash, publish_time, "
                "title, first_seen_at, last_seen_at, seen_count, dedup_status, version_evidence) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 'new', '')",
                (fp, canonical, url, content_hash, publish_time, title, now_str, now_str))
            self._conn.commit()
            return {
                "url": url, "canonical_url": canonical,
                "decision": "new",
                "version_preserved": False,
                "should_drop": False,
                "version_evidence": "",
                "quarantine_reason": "",
            }

        (existing_canonical, existing_url, existing_content_hash,
         existing_publish_time, first_seen_at, last_seen_at,
         seen_count, existing_status, version_evidence) = row

        last_seen = datetime.fromisoformat(last_seen_at)
        age_days = (now - last_seen).days
        new_seen_count = seen_count + 1

        if age_days < 7:
            # Fix 4 Rule 4: If content is empty and no dates, cannot confirm duplicate → uncertain/quarantine
            if not content_hash and not existing_content_hash and not publish_time and not existing_publish_time:
                self._add_to_quarantine(url, canonical,
                    "Cross-day uncertain: same canonical, no content and no date to confirm",
                    existing_url, "canonical_match",
                    {"existing_fp": fp, "new_content_hash": content_hash,
                     "existing_content_hash": existing_content_hash}, now_str)
                cursor.execute(
                    "UPDATE cross_day_fingerprints SET last_seen_at = ?, seen_count = ?, dedup_status = 'uncertain' WHERE fingerprint = ?",
                    (now_str, new_seen_count, fp))
                self._conn.commit()
                return {
                    "url": url, "canonical_url": canonical,
                    "decision": "uncertain",
                    "version_preserved": False,
                    "should_drop": False,
                    "version_evidence": "",
                    "quarantine_reason": "dedup_review_quarantine",
                }

            if publish_time and existing_publish_time and publish_time != existing_publish_time:
                new_ve = f"{version_evidence};version_at={publish_time}" if version_evidence else f"version_at={publish_time}"
                cursor.execute(
                    "UPDATE cross_day_fingerprints SET last_seen_at = ?, seen_count = ?, version_evidence = ? WHERE fingerprint = ?",
                    (now_str, new_seen_count, new_ve, fp))
                self._conn.commit()
                return {
                    "url": url, "canonical_url": canonical,
                    "decision": "new_version",
                    "version_preserved": True,
                    "should_drop": False,
                    "version_evidence": new_ve,
                    "quarantine_reason": "",
                }

            cursor.execute(
                "UPDATE cross_day_fingerprints SET last_seen_at = ?, seen_count = ?, dedup_status = 'duplicate' WHERE fingerprint = ?",
                (now_str, new_seen_count, fp))
            self._conn.commit()
            return {
                "url": url, "canonical_url": canonical,
                "decision": "duplicate",
                "version_preserved": False,
                "should_drop": True,
                "version_evidence": version_evidence or "same_content_same_date",
                "quarantine_reason": "",
            }

        cursor.execute(
            "UPDATE cross_day_fingerprints SET last_seen_at = ?, seen_count = ?, dedup_status = 'continuation' WHERE fingerprint = ?",
            (now_str, new_seen_count, fp))
        self._conn.commit()
        return {
            "url": url, "canonical_url": canonical,
            "decision": "continuation",
            "version_preserved": False,
            "should_drop": False,
            "version_evidence": version_evidence,
            "quarantine_reason": "",
        }

    def _add_to_quarantine(self, url, canonical_url, reason, similar_to_url, similarity_type, metadata, created_at):
        assert self._conn is not None
        self._conn.execute(
            "INSERT INTO dedup_review_quarantine (url, canonical_url, reason, similar_to_url, similarity_type, metadata, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (url, canonical_url, reason, similar_to_url, similarity_type,
             json.dumps(metadata, ensure_ascii=False), created_at))
        self._conn.commit()

    def get_quarantine_items(self, resolved: int = 0) -> list[dict]:
        assert self._conn is not None
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT id, url, canonical_url, reason, similar_to_url, similarity_type, metadata, created_at "
            "FROM dedup_review_quarantine WHERE resolved = ?", (resolved,))
        items = []
        for row in cursor.fetchall():
            items.append({
                "id": row[0], "url": row[1], "canonical_url": row[2],
                "reason": row[3], "similar_to_url": row[4], "similarity_type": row[5],
                "metadata": json.loads(row[6]) if row[6] else {}, "created_at": row[7],
            })
        return items

    def stats(self) -> dict:
        assert self._conn is not None
        cursor = self._conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM cross_day_fingerprints")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT dedup_status, COUNT(*) FROM cross_day_fingerprints GROUP BY dedup_status")
        by_status = dict(cursor.fetchall())
        cursor.execute("SELECT COUNT(*) FROM dedup_review_quarantine WHERE resolved = 0")
        quarantine_count = cursor.fetchone()[0]
        return {"total_fingerprints": total, "by_status": by_status, "unresolved_quarantine": quarantine_count}
