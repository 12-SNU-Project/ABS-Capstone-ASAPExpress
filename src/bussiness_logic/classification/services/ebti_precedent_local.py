"""EBTI 판례 근거 조회 (로컬 CSV, 표시 전용 — 선택 영향 0).

설계자 결정: EBTI는 코드를 '선택'하는 데 쓰지 않는다 — 판례는 특정 코드에
편향이 있어 선택기로 쓰면 그 편향을 수입한다. 용도는 원용도 하나뿐이다:
이미 선택된 코드에 대해 "이런 판례가 있었다"를 근거로 보여주는 것.
따라서 이 모듈의 출력은 어떤 점수·순위·판정에도 들어가지 않고
ClassificationCandidate.similar_ebti_cases(기존 UI 계약)로만 나간다.

데이터 2층 (둘 다 로컬 CSV, 부재/오류 = 빈 목록 no-op):
  1) bti_case_evidence.csv — 정제본 9k (food16_21+ch33). 영어 keyword_terms
     + feature 분해 + 요약까지 있어 매칭 신호가 풍부. 우선 소스.
  2) bti_case_full.csv — 전 챕터(1~99류) VALID ~117k. keywords 컬럼은 발급국
     언어와 무관하게 영어 표준 용어라(실측) 키워드 매칭이 성립한다. 신호는
     얇지만(키워드만, 요약 없음) evidence가 못 덮는 챕터의 커버리지 폴백.
     evidence와 겹치는 판례는 bti_reference로 중복 제거.
     첫 로드 시 150MB 파싱(수 초) + 메모리 ~수십MB — 프로세스당 1회 캐시.

  ASAP_EBTI_EVIDENCE=0         끄기 (기본 1)
  ASAP_EBTI_LOCAL_PATH=...     evidence CSV 경로 오버라이드
  ASAP_EBTI_FULL=0             full(1~99류) 폴백 끄기 (기본 1)
  ASAP_EBTI_FULL_PATH=...      full CSV 경로 오버라이드
"""
from __future__ import annotations

import csv
import os
import re
from pathlib import Path
from typing import Any

_DEFAULT_PATH = Path.home() / "ASAP_A" / "data" / "processed" / "bti_for_upload" / "bti_case_evidence.csv"
_DEFAULT_FULL_PATH = Path.home() / "ASAP_A" / "data" / "processed" / "bti_for_upload" / "bti_case_full.csv"
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


def _add_entry(index: dict[str, Any], entry: dict[str, Any], cn8: str, hs6: str) -> None:
    if cn8:
        index["cn8"].setdefault(cn8, []).append(entry)
    if hs6:
        index["hs6"].setdefault(hs6, []).append(entry)
        index["hs4"].setdefault(hs6[:4], []).append(entry)


def _load_evidence(index: dict[str, Any], seen_refs: set[str]) -> None:
    """정제본(우선 소스): 키워드+feature 어휘, 요약 포함."""
    path = Path(os.environ.get("ASAP_EBTI_LOCAL_PATH") or _DEFAULT_PATH)
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
            ref = str(row.get("bti_reference") or "")[:40]
            seen_refs.add(ref)
            _add_entry(index, {
                "ref": ref,
                "code": str(row.get("assigned_code") or cn8),
                "cn8": cn8,
                "country": str(row.get("issuing_country") or ""),
                "terms": terms,
                # 표시 요약: 한글 번역본(bti_case_summary_ko, 배치 번역 산출)이
                # 있으면 우선 — 없으면 기존 키워드 템플릿 폴백. 표시 전용·선택 무관여.
                "summary": (
                    str(row.get("bti_case_summary_ko") or "").strip()
                    or str(row.get("bti_case_summary") or "").strip()
                )[:800],
            }, cn8, hs6)


def _load_full(index: dict[str, Any], seen_refs: set[str]) -> None:
    """전 챕터(1~99류) 폴백: keywords(영어 표준 용어)만으로 매칭.

    설명문은 원어(다국어)라 어휘 신호도 아니고 UI에 노출할 것도 아니므로
    사용하지 않는다. evidence에 이미 있는 판례는 건너뛴다.
    """
    if (os.environ.get("ASAP_EBTI_FULL", "1") or "1").strip() == "0":
        return
    path = Path(os.environ.get("ASAP_EBTI_FULL_PATH") or _DEFAULT_FULL_PATH)
    with open(path, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("status") or "").strip().upper() not in ("", "VALID"):
                continue
            ref = str(row.get("bti_reference") or "")[:40]
            if not ref or ref in seen_refs:
                continue
            cn8 = re.sub(r"\D", "", str(row.get("cn8") or ""))[:8]
            hs6 = re.sub(r"\D", "", str(row.get("hs6") or ""))[:6] or cn8[:6]
            if not (cn8 or hs6):
                continue
            keywords = str(row.get("keywords") or "")
            terms = _tokens(keywords)
            if not terms:
                continue
            _add_entry(index, {
                "ref": ref,
                "code": str(row.get("nomenclature_code") or cn8),
                "cn8": cn8,
                "country": str(row.get("issuing_country") or ""),
                "terms": terms,
                # full에는 영어 요약이 없다 — 표준 키워드 나열이 곧 판례 내용
                "summary": f"판례 키워드: {keywords.lower()}"[:500],
            }, cn8, hs6)


def _load_index() -> dict[str, Any]:
    """{'cn8': {code: [row]}, 'hs6': {...}, 'hs4': {...}} — 1회 로드 캐시."""
    if _index_cache:
        return _index_cache[0]
    index: dict[str, Any] = {"cn8": {}, "hs6": {}, "hs4": {}}
    seen_refs: set[str] = set()
    try:
        _load_evidence(index, seen_refs)
    except Exception:  # noqa: BLE001 — 판례 부재는 결함이 아니라 근거 없음
        pass
    try:
        _load_full(index, seen_refs)
    except Exception:  # noqa: BLE001 — full 부재 시 evidence만으로 동작
        pass
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
