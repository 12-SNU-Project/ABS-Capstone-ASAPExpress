"""[12회차 §2-4] uncooked 결정론 도출 — LLM 무접촉 PU 후처리.

설계자 확정(07-19, LLM 완화 기각): 교대 질문(0710 `uncooked ∨
steaming`)에 DTO가 답하지 못하는 원인은 라벨이 '생것'을 명시하지 않는
것이다. 프롬프트 완화는 3급 추정을 확정 사다리에 올리므로 금지 —
대신 **발동 3조건 전부 이산**인 결정론 후처리로 processing_state를
보강한다(_TranscribeFoodTypeFact 계보·데모 _axes_from_name 검증분의
본선 이식).

발동 3조건(전부 성립 시에만):
  ① 조리 어휘 0건 — 지각 블롭(상품명·NTD·identity_terms·distilled)에
     조리 상태 어휘(영문 검증분 + taxonomy state_lexicon의 조리계
     한글 대응)가 전무하고, 기존 processing_state도 조리 계열이 아님
  ② 백과 강/중 승선 문서가 원물 서술 — graded 승선 항목 텍스트가
     조제 직격 어휘 0
  ③ 라우터 선두가 원물 챕터 — 관세율표 1~2부(01~14) 경계 선언
     (수기 어휘가 아니라 법정 구조 경계 — 대원칙의 '경계 선언' 허용범위)

산출: processing_state가 비어 있으면 'uncooked' 보강 + 서명
`derived_state:uncooked(<근거>)`. **2급 파생 등급** — 교대 응답·지지
참여만 하고 단독 확정 인장은 불가(평가기의 상태 단독 확정 금지
게이트가 구조적으로 보장 — 카나리아로 상설 확인).
"""
from __future__ import annotations

from typing import Any

from bussiness_logic.core.runtime_asset_repository import LoadSingletonAsset

# 데모 _axes_from_name 검증분(영문) — 조리 상태·조리 형태 어휘.
_COOK_EN = (
    "cooked", "prepared", "instant", "grilled", "fried", "stir-fried",
    "steamed", "roasted", "baked", "smoked", "boiled", "blanched",
    "seasoned", "marinated", "braised", "preserved",
)
_RAW_CHAPTERS = {f"{n:02d}" for n in range(1, 15)}   # 관세율표 1~2부 경계

_state_lex_cache: list[tuple[str, tuple[str, ...]]] = []


def _cook_lexicon_ko() -> list[tuple[str, tuple[str, ...]]]:
    """taxonomy state_lexicon에서 '조리계' 한글 키만 — 대응 영문에 조리
    어휘가 들어 있는 항목(기계 도출·수기 목록 0)."""
    if _state_lex_cache:
        return _state_lex_cache
    tax = LoadSingletonAsset("commodity_taxonomy")
    for ko, ens in (tax.get("state_lexicon") or {}).items():
        ens_t = tuple(str(e).lower() for e in (ens or []))
        # 정확 일치 비교 — 부분문자열이면 'uncooked'가 'cooked'에 걸려
        # '생(fresh/uncooked/raw)' 항목이 조리계로 오탐된다(실측).
        if any(e in _COOK_EN for e in ens_t):
            _state_lex_cache.append((str(ko), ens_t))
    return _state_lex_cache


def DeriveUncookedState(
    product_facts: dict[str, Any],
    routing_context: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    """3조건 성립 시 (보강된 product_facts 사본, 서명) — 아니면 (원본, "")."""
    ih = dict(product_facts.get("identity_hints") or {})
    existing = str(ih.get("processing_state") or "").strip().lower()
    # frozen/chilled는 보존 상태지 조리 상태가 아니다 — 0710 조문 자체가
    # frozen ∧ (uncooked ∨ …) 구조(냉동 생것이 이 장치의 원 표적).
    if existing not in ("", "unknown", "raw", "fresh", "uncooked",
                        "frozen", "chilled"):
        return product_facts, ""

    # 판정 원천 = **정제 서술만**(NTD·identity_terms·distilled) — 상품명
    # 원문은 마케팅 수식('간편'→taxonomy prepared 대응)이 섞여 원물에
    # 조리 신호를 오탐시킨다(청양고추 실측). 데모 검증분이 상품명을 쓴
    # 것은 데모 입력이 합성 정제명이었기 때문 — 본선 등가 지점은 지각이
    # 정제한 관세 서술이다.
    blob = " ".join([
        str(ih.get("normalized_tariff_description") or ""),
        " ".join(str(x) for x in (ih.get("identity_terms") or [])),
        str((product_facts.get("distilled_identity") or {})
            .get("normalizedDescription") or ""),
    ]).lower()
    # ① 조리 어휘 0건
    if any(w in blob for w in _COOK_EN):
        return product_facts, ""
    for ko, _ens in _cook_lexicon_ko():
        if ko in blob:
            return product_facts, ""

    # ② 백과 강/중 승선 문서가 원물 서술(조제 직격 0)
    ency = product_facts.get("encyclopedia_evidence") or {}
    entries = [e for e in (ency.get("entries") or []) if isinstance(e, dict)]
    boarded = [e for e in entries
               if str(e.get("grade") or "").lower() in ("strong", "medium")]
    if not boarded:
        return product_facts, ""
    ency_text = " ".join(
        f"{e.get('title') or ''} {e.get('summary') or e.get('text') or ''}"
        for e in boarded).lower()
    if any(w in ency_text for w in _COOK_EN):
        return product_facts, ""

    # ③ 라우터 선두가 원물 챕터
    details = [d for d in (routing_context.get("candidate_chapter_details")
                           or []) if isinstance(d, dict)]
    if not details:
        return product_facts, ""
    top_ch = max(details, key=lambda d: float(d.get("score") or 0.0))
    top_chapter = str(top_ch.get("chapter") or "").zfill(2)
    if top_chapter not in _RAW_CHAPTERS:
        return product_facts, ""

    signature = (f"derived_state:uncooked(no_cook_lex,ency_raw,"
                 f"router_raw_ch{top_chapter})")
    out = dict(product_facts)
    ih["processing_state"] = "uncooked"
    ih["derived_state"] = signature      # 2급 파생 서명(관측·감사 실물)
    out["identity_hints"] = ih
    cf = dict(out.get("composition_facts") or {})
    if not str(cf.get("processing_state") or "").strip():
        cf["processing_state"] = "uncooked"
        out["composition_facts"] = cf
    return out, signature
