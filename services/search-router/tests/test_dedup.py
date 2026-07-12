"""测试 DedupManager — 跨任务历史去重。V1.1 with Fix 4+6."""

import pytest
from datetime import datetime, timedelta, timezone
from search_router.dedup import (
    DedupManager,
    DedupResult,
    DEDUP_STATUS_NEW,
    DEDUP_STATUS_MERGED,
    DEDUP_STATUS_CONTINUATION,
    WINDOW_7_DAYS,
    WINDOW_30_DAYS,
    _url_hash,
    SingleRunDeduplicator,
    CrossDayDeduplicator,
    canonicalize_url_for_dedup,
    SAFE_STRIP_PARAMS,
    AMBIGUOUS_PRESERVE_PARAMS,
    _content_sha256,
)


class TestDedupManager:
    """DedupManager 测试。"""

    def test_new_url(self, tmp_path):
        db_path = str(tmp_path / "test_dedup.db")
        mgr = DedupManager(db_path=db_path)
        result = mgr.check_url("https://example.com/new", task_id="task1", provider="bocha")
        assert result.status == DEDUP_STATUS_NEW
        assert result.seen_count == 1
        mgr.close()

    def test_duplicate_within_7_days(self, tmp_path):
        db_path = str(tmp_path / "test_dedup.db")
        mgr = DedupManager(db_path=db_path)
        mgr.check_url("https://example.com/a", task_id="task1", provider="bocha")
        result = mgr.check_url("https://example.com/a", task_id="task2", provider="glm_search")
        assert result.status == DEDUP_STATUS_MERGED
        assert result.seen_count == 2
        mgr.close()

    def test_continuation_after_7_days(self, tmp_path):
        db_path = str(tmp_path / "test_dedup.db")
        mgr = DedupManager(db_path=db_path)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        mgr.check_url("https://example.com/a", task_id="task1", provider="bocha", now=now)
        later = now + timedelta(days=8)
        result = mgr.check_url("https://example.com/a", task_id="task2", provider="bocha", now=later)
        assert result.status == DEDUP_STATUS_CONTINUATION
        mgr.close()

    def test_still_merged_at_day_6(self, tmp_path):
        db_path = str(tmp_path / "test_dedup.db")
        mgr = DedupManager(db_path=db_path)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        mgr.check_url("https://example.com/a", task_id="task1", provider="bocha", now=now)
        later = now + timedelta(days=6)
        result = mgr.check_url("https://example.com/a", task_id="task2", provider="bocha", now=later)
        assert result.status == DEDUP_STATUS_MERGED
        mgr.close()

    def test_30_day_core_topic_downweight(self, tmp_path):
        db_path = str(tmp_path / "test_dedup.db")
        mgr = DedupManager(db_path=db_path)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        url = "https://example.com/core-topic"
        for i in range(4):
            mgr.check_url(url, task_id=f"task{i}", provider="bocha", now=now + timedelta(days=i * 5))
        count = mgr.get_core_topic_count(url, now=now + timedelta(days=20))
        assert count >= 4
        mgr.close()

    def test_uses_tmp_path_not_production(self, tmp_path):
        db_path = str(tmp_path / "test_dedup.db")
        mgr = DedupManager(db_path=db_path)
        assert mgr._db_path == db_path
        mgr.close()

    def test_memory_db(self):
        mgr = DedupManager(db_path=":memory:")
        result = mgr.check_url("https://example.com/test", task_id="task1")
        assert result.status == DEDUP_STATUS_NEW
        mgr.close()

    def test_batch_check(self, tmp_path):
        db_path = str(tmp_path / "test_dedup.db")
        mgr = DedupManager(db_path=db_path)
        urls = [
            "https://example.com/a",
            "https://example.com/b",
            "https://example.com/a",
        ]
        results = mgr.check_batch(urls, task_id="task1", provider="bocha")
        assert len(results) == 3
        assert results[0].status == DEDUP_STATUS_NEW
        assert results[1].status == DEDUP_STATUS_NEW
        assert results[2].status == DEDUP_STATUS_MERGED
        mgr.close()

    def test_different_urls_not_deduped(self, tmp_path):
        db_path = str(tmp_path / "test_dedup.db")
        mgr = DedupManager(db_path=db_path)
        r1 = mgr.check_url("https://example.com/a", task_id="task1")
        r2 = mgr.check_url("https://example.com/b", task_id="task1")
        assert r1.status == DEDUP_STATUS_NEW
        assert r2.status == DEDUP_STATUS_NEW
        mgr.close()

    def test_seen_count_increments(self, tmp_path):
        db_path = str(tmp_path / "test_dedup.db")
        mgr = DedupManager(db_path=db_path)
        url = "https://example.com/count"
        r1 = mgr.check_url(url, task_id="t1")
        r2 = mgr.check_url(url, task_id="t2")
        r3 = mgr.check_url(url, task_id="t3")
        assert r1.seen_count == 1
        assert r2.seen_count == 2
        assert r3.seen_count == 3
        mgr.close()

    def test_30_day_expires(self, tmp_path):
        db_path = str(tmp_path / "test_dedup.db")
        mgr = DedupManager(db_path=db_path)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        url = "https://example.com/expire"
        mgr.check_url(url, task_id="t1", provider="bocha", now=now)
        count = mgr.get_core_topic_count(url, now=now + timedelta(days=31))
        assert count == 0
        mgr.close()


class TestSingleRunDeduplicatorV11:
    """Fix 4+6: SingleRunDeduplicator V1.1 — unified decision."""

    def test_new_decision(self):
        d = SingleRunDeduplicator()
        r = d.check_url("https://example.com/new", content="test", publish_time="2026-07-01")
        assert r.decision == "new"
        assert r.should_drop is False

    def test_duplicate_decision(self):
        d = SingleRunDeduplicator()
        d.check_url("https://example.com/a", content="same", publish_time="2026-07-01")
        r = d.check_url("https://example.com/a", content="same", publish_time="2026-07-01")
        assert r.decision == "duplicate"
        assert r.should_drop is True

    def test_new_version_diff_date(self):
        d = SingleRunDeduplicator()
        d.check_url("https://example.com/a", content="c1", publish_time="2026-07-01")
        r = d.check_url("https://example.com/a", content="c2", publish_time="2026-07-10")
        assert r.decision == "new_version"
        assert r.version_preserved is True
        assert r.should_drop is False

    def test_new_version_diff_content(self):
        d = SingleRunDeduplicator()
        d.check_url("https://example.com/a", content="cA", publish_time="2026-07-01")
        r = d.check_url("https://example.com/a", content="cB", publish_time="2026-07-01")
        assert r.decision == "new_version"
        assert r.version_preserved is True
        assert r.should_drop is False

    def test_uncertain_strong(self):
        """Fix 6: decision must be 'uncertain', not 'uncertain or duplicate'."""
        d = SingleRunDeduplicator()
        d.check_url("https://example.com/a", content="", publish_time="")
        r = d.check_url("https://example.com/a", content="", publish_time="")
        assert r.decision == "uncertain"
        assert r.should_drop is False
        assert len(d.quarantine) == 1


class TestCrossDayDeduplicatorV11:
    """Fix 4+6: CrossDayDeduplicator V1.1 — unified decision, no mixed state."""

    def test_no_duplicate_version_preserved(self, tmp_path):
        """Fix 4: Must never return 'duplicate_version_preserved'."""
        db = str(tmp_path / "test_cd_no_mix.db")
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with CrossDayDeduplicator(db_path=db) as dd:
            dd.check_url("https://example.com/a", content="v1", publish_time="2026-07-01", now=now)
            r = dd.check_url("https://example.com/a", content="v1", publish_time="2026-07-10", now=now + timedelta(days=3))
            assert r["decision"] != "duplicate_version_preserved"
            assert r["decision"] in ("new_version", "duplicate")

    def test_quarantine_uncertain_strong(self, tmp_path):
        """Fix 6: uncertain → decision=uncertain, should_drop=false, quarantine +1, resolved=0."""
        db = str(tmp_path / "test_cd_q_strong.db")
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with CrossDayDeduplicator(db_path=db) as dd:
            dd.check_url("https://example.com/a", content="", publish_time="", now=now)
            r = dd.check_url("https://example.com/a", content="", publish_time="", now=now)
            assert r["decision"] == "uncertain"
            assert r["should_drop"] is False
            q_items = dd.get_quarantine_items(resolved=0)
            assert len(q_items) == 1
            # resolved=0 is guaranteed by filter resolved=0


class TestTrackingParamsV11:
    """Fix 3: Tracking param whitelist split."""

    def test_safe_strip_only(self):
        url = "https://example.com/page?utm_source=g&id=1"
        result = canonicalize_url_for_dedup(url)
        assert "utm_source" not in result
        assert "id=1" in result

    def test_ambiguous_preserved(self):
        url = "https://example.com/page?share_token=abc&id=1"
        result = canonicalize_url_for_dedup(url)
        assert "share_token=abc" in result
        assert "id=1" in result


class TestContentSha256:
    """Fix 5: SHA256 of full content."""

    def test_full_content_detected(self):
        long_a = "A" * 600 + "B" * 100
        long_b = "A" * 600 + "C" * 100
        assert _content_sha256(long_a) != _content_sha256(long_b)

    def test_empty_content(self):
        assert _content_sha256("") == ""

    def test_whitespace_normalized(self):
        t1 = "Hello  World\n\nTest"
        t2 = "Hello World Test"
        assert _content_sha256(t1) == _content_sha256(t2)
