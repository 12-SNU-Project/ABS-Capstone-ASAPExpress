"""EBTI 판례 근거 조회 (로컬 CSV, 표시 전용 — 선택 영향 0).

설계자 결정: EBTI는 코드를 '선택'하는 데 쓰지 않는다 — 판례는 특정 코드에
편향이 있어 선택기로 쓰면 그 편향을 수입한다. 용도는 원용도 하나뿐이다:
이미 선택된 코드에 대해 "이런 판례가 있었다"를 근거로 보여주는 것.
따라서 이 모듈의 출력은 어떤 점수·순위·판정에도 들어가지 않고
ClassificationCandidate.similar_ebti_cases(기존 UI 계약)로만 나간다.

데이터: bti_case_evidence.csv (정제본 9k, 현재 food16_21 중심) — DB 테이블이
아직 없어 임시로 로컬 파일을 읽는다. 파일 부재/오류 = 빈 목록(no-op).

  ASAP_EBTI_EVIDENCE=0        끄기 (기본 1)
  ASAP_EBTI_LOCAL_PATH=...    CSV 경로 오버라이드
"""
from __future__ import annotations

import csv
import os
import re
from pathlib import Path
from typing import Any

_DEFAULT_PATH = Path.home() / "ASAP_A" / "data" / "processed" / "bti_for_upload" / "bti_case_evidence.csv"
_TOKEN = re.compile(r"[a-z]+")
_index_cache: list[dict[str, Any]] = []


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


def _load_index() -> dict[str, Any]:
    """{'cn8': {code: [row]}, 'hs6': {...}, 'hs4': {...}} — 1회 로드 캐시."""
    if _index_cache:
        return _index_cache[0]
    index: dict[str, Any] = {"cn8": {}, "hs6": {}, "hs4": {}}
    path = Path(os.environ.get("ASAP_EBTI_LOCAL_PATH") or _DEFAULT_PATH)
    try:
        with open(path, encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if str(row.get("quality_status") or "").strip().lower() in ("rejected", "invalid"):
                    continue
                cn8 = re.sub(r"\D", "", str(row.get("cn8") or ""))[:8]
                hs6 = re.sub(r"\D", "", str(row.get("hs6") or ""))[:6] or cn8[:6]
                if not (cn8 or hs6):
                    continue
                terms = _tokens(" ".join(
                    str(row.get(field) or "")
                    for field in ("bti_keyword_terms", "feature_composition",
                                  "feature_function", "feature_form")
                ))
                if not terms:
                    continue
                entry = {
                    "ref": str(row.get("bti_reference") or "")[:40],
                    "code": str(row.get("assigned_code") or cn8),
                    "cn8": cn8,
                    "country": str(row.get("issuing_country") or ""),
                    "terms": terms,
                    "summary": str(row.get("bti_case_summary") or "")[:200],
                }
                if cn8:
                    index["cn8"].setdefault(cn8, []).append(entry)
                if hs6:
                    index["hs6"].setdefault(hs6, []).append(entry)
                    index["hs4"].setdefault(hs6[:4], []).append(entry)
    except Exception:  # noqa: BLE001 — 판례 부재는 결함이 아니라 근거 없음
        index = {"cn8": {}, "hs6": {}, "hs4": {}}
    _index_cache.append(index)
    return index


def FindSimilarCases(
    cn8: str,
    identity_text: str,
    *,
    limit: int = 2,
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
    index = _load_index()
    for level, key in (("cn8", code), ("hs6", code[:6]), ("hs4", code[:4])):
        pool = index.get(level, {}).get(key) or []
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
                        + (f" — {entry['summary']}" if entry["summary"] else "")
                    )[:260],
                    "difference_comment": (
                        "" if entry["cn8"] == code
                        else f"판례 코드 {entry['code']} ≠ 선택 {code} (동일 {level} 계열)"
                    ),
                }
                for _score, entry in picked
            ]
    return []
