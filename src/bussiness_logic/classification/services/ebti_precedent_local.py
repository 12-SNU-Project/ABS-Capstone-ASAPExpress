"""EBTI precedent evidence lookup from runtime database tables.

FindSimilarCases is display evidence only and never selects a code or replaces
GRI 3(b). Candidate rows are fetched narrowly from bti_case_evidence,
bti_case, or bti_case_full when those tables exist.
"""
from __future__ import annotations

import os
import re
from collections.abc import Iterable
from typing import Any

from bussiness_logic.core.runtime_asset_repository import LoadBtiCasesForCode


_TOKEN = re.compile(r"[a-z]+")


def _stem(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("es") and not token.endswith(("ses", "oes")):
        return token[:-2] if token.endswith(("ches", "shes", "xes")) else token[:-1]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _tokens(text: str) -> frozenset[str]:
    return frozenset(_stem(t) for t in _TOKEN.findall(str(text or "").lower()) if len(t) >= 3)


def _BuildEntry(row: dict[str, Any]) -> dict[str, Any] | None:
    if str(row.get("quality_status") or "").strip().lower() in {
        "rejected",
        "invalid",
    }:
        return None
    if str(row.get("status") or "").strip().upper() not in {"", "VALID"}:
        return None
    cn8 = re.sub(r"\D", "", str(row.get("cn8") or ""))[:8]
    terms = _tokens(
        " ".join(
            str(row.get(field) or "")
            for field in (
                "bti_keyword_terms",
                "feature_composition",
                "feature_function",
                "feature_form",
                "keywords",
            )
        )
    )
    if not cn8 or not terms:
        return None
    summary = (
        str(row.get("bti_case_summary_ko") or "").strip()
        or str(row.get("bti_case_summary") or "").strip()
    )
    if not summary:
        summary = f"판례 키워드: {str(row.get('keywords') or '').lower()}"
    return {
        "ref": str(
            row.get("bti_reference")
            or row.get("reference")
            or ""
        )[:40],
        "code": str(
            row.get("assigned_code")
            or row.get("nomenclature_code")
            or cn8
        ),
        "cn8": cn8,
        "country": str(row.get("issuing_country") or ""),
        "terms": terms,
        "summary": summary[:800],
    }


def FindSimilarCases(
    cn8: str,
    identity_text: str,
    *,
    limit: int = 2,
    preloaded_rows: Iterable[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """선택된 cn8에 대한 유사 판례 (표시 전용 payload, UI 계약 키).

    같은 cn8 판례 → 같은 hs6 → 같은 hs4 순으로 좁은 층부터 찾고,
    제품 identity 어휘와의 겹침이 있는 판례만 유사도순으로 반환한다.
    """
    if (os.environ.get("ASAP_EBTI_EVIDENCE", "1") or "1").strip() == "0":
        return []
    code = re.sub(r"\D", "", str(cn8 or ""))[:8]
    if len(code) < 4:
        return []
    product_terms = _tokens(identity_text)
    if not product_terms:
        return []
    sourceRows = (
        preloaded_rows
        if preloaded_rows is not None
        else LoadBtiCasesForCode(code)
    )
    entries = [
        entry
        for row in sourceRows
        if (entry := _BuildEntry(row)) is not None
    ]
    for level, key in (("cn8", code), ("hs6", code[:6]), ("hs4", code[:4])):
        pool = [
            entry
            for entry in entries
            if (
                entry["cn8"] == key
                if level == "cn8"
                else entry["cn8"].startswith(key)
            )
        ]
        scored = sorted(
            ((len(entry["terms"] & product_terms), entry) for entry in pool),
            key=lambda pair: -pair[0],
        )
        picked = [(score, entry) for score, entry in scored[:limit] if score >= 1]
        if picked:
            return [
                {
                    "evidence_ref": f"{entry['ref']} ({entry['country']}, {level}={key})",
                    "similarity_comment": (
                        "판례-제품 공유 어휘: "
                        + ", ".join(sorted(entry["terms"] & product_terms)[:6])
                    )[:260],
                    # 판례 내용은 공유 어휘와 분리된 별도 필드 (요약 or 키워드 나열)
                    "case_summary": str(entry["summary"] or "")[:800],
                    "difference_comment": (
                        "" if entry["cn8"] == code
                        else f"판례 코드 {entry['code']} ≠ 선택 {code} (동일 {level} 계열)"
                    ),
                }
                for _score, entry in picked
            ]
    return []
