"""ResultMerger — 跨 Provider 4 层去重合并 (Phase2 V1.2).

4 层去重:
1. URL 精确去重 (V1.2: version-protected — same URL different version kept)
2. URL safe_normalize_url去重: host小写/默认端口规范化/尾斜杠/安全跟踪参数删除
3. 标题相似度去重: 字符级 2-gram Jaccard > 0.8 视为重复
4. 内容指纹去重: 完整正文 SHA256

V1.2 Changes (Layer1 only):
- Layer1 now considers publish_time and content SHA256 for version protection
- 7 rules ensure same-URL different-version results are preserved
- should_drop=True only from confirmed duplicate
- quarantine for uncertain cases (no date, no content)
- Layer1 does NOT bypass unified decision structure
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse, urlunparse, parse_qs

from search_router.models.search_response import SearchResult


_SOURCE_RANK: dict[str, int] = {
    "mock": 1,
    "tavily": 2,
    "bocha": 3,
    "glm_search": 4,
    "codeact": 5,
}

_TITLE_JACCARD_THRESHOLD = 0.8

SAFE_STRIP_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_cid", "utm_reader", "utm_name", "utm_social", "utm_social-type",
    "utm_referrer", "utm_brand", "utm_keyword",
    "fbclid", "gclid", "dclid", "msclkid", "yclid", "twclid", "igshid",
    "mc_cid", "mc_eid",
})

AMBIGUOUS_PRESERVE_PARAMS = frozenset({
    "fb_action_ids", "fb_action_types", "fb_source", "fb_ref",
    "gclsrc", "_ga", "_gl", "_gid", "_gcl_au",
    "spm", "is_from_webapp", "share_token",
    "ref_src", "ref_url", "smid", "smtyp", "smchannel",
    "wt_mc", "wt_oid", "ns_mchannel", "ns_campaign",
    "bclid", "li_fat_id",
})

TRACKING_PARAMS = SAFE_STRIP_PARAMS


def _normalize_url(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        path = parsed.path.rstrip("/") if parsed.path else ""
        normalized = urlunparse(("", parsed.netloc, path, "", "", ""))
        return normalized.lstrip("/")
    except Exception:
        return url


def safe_normalize_url(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        if netloc.endswith(":80") and parsed.scheme == "http":
            netloc = netloc[:-3]
        elif netloc.endswith(":443") and parsed.scheme == "https":
            netloc = netloc[:-4]
        path = parsed.path.rstrip("/") if parsed.path else ""
        if parsed.query:
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
        else:
            new_query = ""
        return urlunparse((
            parsed.scheme, netloc, path,
            parsed.params, new_query, parsed.fragment
        ))
    except Exception:
        return url


def canonicalize_url(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url)
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
        canonicalized = urlunparse((
            parsed.scheme, parsed.netloc, parsed.path,
            parsed.params, new_query, parsed.fragment
        ))
        return canonicalized
    except Exception:
        return url


def _text_2grams(text: str) -> set[str]:
    if not text or len(text) < 2:
        return set()
    return {text[i:i+2] for i in range(len(text) - 1)}


def _jaccard_similarity(text_a: str, text_b: str) -> float:
    grams_a = _text_2grams(text_a)
    grams_b = _text_2grams(text_b)
    if not grams_a or not grams_b:
        return 0.0
    intersection = grams_a & grams_b
    union = grams_a | grams_b
    return len(intersection) / len(union) if union else 0.0


def _normalize_whitespace(text: str) -> str:
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text).strip()


def _content_fingerprint(text: str) -> str:
    if not text:
        return ""
    normalized = _normalize_whitespace(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _source_rank(provider: str) -> int:
    return _SOURCE_RANK.get(provider, 0)


def _get_merged_from(result: SearchResult) -> list[str]:
    return list(result.raw.get("merged_from", []))


def _set_merged_from(result: SearchResult, merged_from: list[str]) -> None:
    result.raw["merged_from"] = merged_from


def _add_merged_from(existing: SearchResult, provider: str) -> None:
    merged_from = existing.raw.get("merged_from", [])
    if provider not in merged_from:
        merged_from.append(provider)
    existing.raw["merged_from"] = merged_from


@dataclass
class MergeResult:
    results: list[SearchResult] = field(default_factory=list)
    merged_count: int = 0
    merge_log: list[dict[str, Any]] = field(default_factory=list)
    quarantine: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "results": [r.to_dict() for r in self.results],
            "merged_count": self.merged_count,
            "merge_log": list(self.merge_log),
            "quarantine": list(self.quarantine),
        }


class ResultMerger:
    """跨 Provider 结果去重合并器 (V1.2: Layer1 version-protected)."""

    def merge(self, results: list[SearchResult]) -> MergeResult:
        if not results:
            return MergeResult()

        merged: list[SearchResult] = []
        merge_log: list[dict[str, Any]] = []
        merged_count = 0
        quarantine: list[dict[str, Any]] = []

        seen_urls_exact: dict[str, int] = {}
        seen_urls_safe_norm: dict[str, int] = {}
        seen_fingerprints: dict[str, int] = {}

        for result in results:
            replaced = False
            replaced_index = -1
            merge_reason = ""

            url = result.url or ""

            # 层 1: URL 精确去重 (V1.2: version-protected)
            if url and url in seen_urls_exact:
                existing_idx = seen_urls_exact[url]
                existing = merged[existing_idx]

                decision = self._layer1_decide(existing, result)
                action = decision["action"]

                if action == "merge":
                    if self._should_replace(existing, result):
                        merged_from = _get_merged_from(existing)
                        merged_from.append(existing.provider)
                        _set_merged_from(result, merged_from)
                        merged[existing_idx] = result
                        replaced_index = existing_idx
                        replaced = True
                        merge_reason = decision["reason"]
                    else:
                        _add_merged_from(existing, result.provider)
                    merged_count += 1
                    merge_log.append({
                        "layer": "url_exact",
                        "action": "merge",
                        "reason": decision["reason"],
                        "url": url,
                        "kept_provider": existing.provider if not replaced else result.provider,
                        "dropped_provider": result.provider if not replaced else existing.provider,
                        "should_drop": decision["should_drop"],
                    })
                    continue

                elif action == "keep_both":
                    merged_count += 1
                    merge_log.append({
                        "layer": "url_exact",
                        "action": "keep_both",
                        "reason": decision["reason"],
                        "url": url,
                        "version_preserved": True,
                        "should_drop": False,
                    })
                    # Fall through — don't continue, let this result be added

                elif action == "quarantine":
                    quarantine.append({
                        "url": url,
                        "reason": decision["reason"],
                        "existing_title": existing.title[:80],
                        "candidate_title": result.title[:80],
                        "should_drop": False,
                    })
                    merge_log.append({
                        "layer": "url_exact",
                        "action": "quarantine",
                        "reason": decision["reason"],
                        "url": url,
                        "should_drop": False,
                    })
                    # Fall through — don't delete

            # 层 2: safe_normalize_url
            if not replaced and url and url not in seen_urls_exact:
                safe_url = safe_normalize_url(url)
                if safe_url and safe_url in seen_urls_safe_norm:
                    existing_idx = seen_urls_safe_norm[safe_url]
                    existing = merged[existing_idx]
                    if self._should_replace(existing, result):
                        merged_from = _get_merged_from(existing)
                        merged_from.append(existing.provider)
                        _set_merged_from(result, merged_from)
                        merged[existing_idx] = result
                        replaced_index = existing_idx
                        replaced = True
                        merge_reason = "url_safe_normalized"
                    else:
                        _add_merged_from(existing, result.provider)
                        merged_count += 1
                        merge_log.append({
                            "layer": "url_safe_normalized",
                            "url": url,
                            "safe_normalized": safe_url,
                            "kept_provider": existing.provider,
                            "dropped_provider": result.provider,
                        })
                        continue

            # 层 3: 标题相似度去重
            if not replaced:
                title = result.title or ""
                if title:
                    for i, existing in enumerate(merged):
                        sim = _jaccard_similarity(title, existing.title or "")
                        if sim > _TITLE_JACCARD_THRESHOLD:
                            if self._should_replace(existing, result):
                                merged_from = _get_merged_from(existing)
                                merged_from.append(existing.provider)
                                _set_merged_from(result, merged_from)
                                merged[i] = result
                                replaced_index = i
                                replaced = True
                                merge_reason = "title_jaccard"
                                if url:
                                    seen_urls_exact[url] = i
                                safe_url = safe_normalize_url(url)
                                if safe_url:
                                    seen_urls_safe_norm[safe_url] = i
                            else:
                                _add_merged_from(existing, result.provider)
                                merged_count += 1
                                merge_log.append({
                                    "layer": "title_jaccard",
                                    "similarity": round(sim, 3),
                                    "title": title,
                                    "kept_provider": existing.provider,
                                    "dropped_provider": result.provider,
                                })
                            break

            # 层 4: 内容指纹去重
            if not replaced:
                fp = _content_fingerprint(result.summary or "")
                if fp and fp in seen_fingerprints:
                    existing_idx = seen_fingerprints[fp]
                    existing = merged[existing_idx]
                    if self._should_replace(existing, result):
                        merged_from = _get_merged_from(existing)
                        merged_from.append(existing.provider)
                        _set_merged_from(result, merged_from)
                        merged[existing_idx] = result
                        replaced_index = existing_idx
                        replaced = True
                        merge_reason = "content_fingerprint"
                    else:
                        _add_merged_from(existing, result.provider)
                        merged_count += 1
                        merge_log.append({
                            "layer": "content_fingerprint",
                            "fingerprint": fp[:8] + "...",
                            "kept_provider": existing.provider,
                            "dropped_provider": result.provider,
                        })
                    continue

            if replaced:
                if url:
                    seen_urls_exact[url] = replaced_index
                safe_url = safe_normalize_url(url)
                if safe_url:
                    seen_urls_safe_norm[safe_url] = replaced_index
                fp = _content_fingerprint(result.summary or "")
                if fp:
                    seen_fingerprints[fp] = replaced_index
                merged_count += 1
                merge_log.append({
                    "layer": merge_reason,
                    "url": url,
                    "replaced_provider": result.provider,
                    "replaced_at": replaced_index,
                })
            else:
                if url:
                    seen_urls_exact[url] = len(merged)
                safe_url = safe_normalize_url(url)
                if safe_url:
                    seen_urls_safe_norm[safe_url] = len(merged)
                fp = _content_fingerprint(result.summary or "")
                if fp:
                    seen_fingerprints[fp] = len(merged)
                merged.append(result)

        return MergeResult(
            results=merged,
            merged_count=merged_count,
            merge_log=merge_log,
            quarantine=quarantine,
        )

    def _layer1_decide(self, existing: SearchResult, candidate: SearchResult) -> dict:
        """V1.2: 7 rules for version-protected URL dedup."""
        ex_date = existing.publish_time or ""
        ca_date = candidate.publish_time or ""
        ex_fp = _content_fingerprint(existing.summary or "")
        ca_fp = _content_fingerprint(candidate.summary or "")
        has_date = bool(ex_date) or bool(ca_date)
        has_content = bool(ex_fp) or bool(ca_fp)

        # Rule 1: Same URL, same date, same content -> merge
        if ex_date and ca_date and ex_date == ca_date and ex_fp and ca_fp and ex_fp == ca_fp:
            return {"action": "merge", "reason": "same_url_same_date_same_content",
                    "should_drop": True, "version_preserved": False}

        # Rule 2: Same URL, different date -> keep both
        if ex_date and ca_date and ex_date != ca_date:
            return {"action": "keep_both", "reason": "same_url_different_date",
                    "should_drop": False, "version_preserved": True}

        # Rule 3: Same URL, same date, different content -> keep both
        if ex_date and ca_date and ex_date == ca_date and ex_fp and ca_fp and ex_fp != ca_fp:
            return {"action": "keep_both", "reason": "same_url_same_date_different_content",
                    "should_drop": False, "version_preserved": True}

        # Rule 4: Same URL, date missing but content different -> keep both
        if (not ex_date or not ca_date) and ex_fp and ca_fp and ex_fp != ca_fp:
            return {"action": "keep_both", "reason": "same_url_missing_date_different_content",
                    "should_drop": False, "version_preserved": True}

        # Rule 5: Same URL, both date and content missing -> quarantine
        if not has_date and not has_content:
            return {"action": "quarantine", "reason": "same_url_no_date_no_content",
                    "should_drop": False, "version_preserved": False}

        # Rule 6: Same URL, same content (dates uncertain) -> merge
        if ex_fp and ca_fp and ex_fp == ca_fp:
            return {"action": "merge", "reason": "same_url_same_content_uncertain_date",
                    "should_drop": True, "version_preserved": False}

        # Rule 7: Same URL, partial info -> keep both (conservative)
        return {"action": "keep_both", "reason": "same_url_insufficient_info_for_merge",
                "should_drop": False, "version_preserved": True}

    def _should_replace(self, existing: SearchResult, candidate: SearchResult) -> bool:
        rank_existing = _source_rank(existing.provider)
        rank_candidate = _source_rank(candidate.provider)
        if rank_candidate > rank_existing:
            return True
        if rank_candidate < rank_existing:
            return False
        return candidate.confidence_score > existing.confidence_score
