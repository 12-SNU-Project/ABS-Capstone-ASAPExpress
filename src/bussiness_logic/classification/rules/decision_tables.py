"""치환 스프린트 선언 테이블 + 표 해석 집계기 (phase 1: 섀도 전용).

도면: docs/substitution_sprint_design.md §B. 예외 7·8·9(상태 단독 금지·
typed 자격·서열 가드)를 개별 if가 아니라 두 테이블의 합성식으로 재현한다:

  violated  := ∃false
  confirmed := all-true ∧ ∃(true, grade=1, authority=confirm) ∧ ¬전원강등
  undecided := 그 외

phase 1a에서는 구 평가기(branch_decision_evaluator.EvaluateCodeDecision)가
판정을 소유하고, 이 집계기는 같은 detail을 다시 읽어 status를 재산출 —
불일치만 artifacts/decision_shadow_diff.jsonl에 기록한다 (선택 무영향).
diff 0(골든 22 + 22캐시) 확인 후에만 소유권을 넘긴다(on 전환).

테이블 셀에 제품·코드명은 절대 넣지 않는다 (하드코딩 금지 원칙).
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Mapping

from bussiness_logic.classification.rules.branch_predicate_evaluator import (
    _dig,
    _stem,
)

_TOKEN = re.compile(r"[a-z]+")

# ── 질문 축 계열 (cond_type 16축 → 4계열) ─────────────────────────────
Q_STATE = frozenset({
    "processing_method", "preservation_state",
    "physical_form", "condition_quality",
})
# (Q_IDENTITY/Q_QUANT/Q_EXCLUDE는 집계식에서 '상태가 아닌 것'으로만
#  소비된다 — 명시 나열은 도면 §B-2, 코드는 여집합으로 충분)

# ── 증거등급표 (§B-1) ────────────────────────────────────────────────
GRADE_DIRECT = 1    # 확정(+50) 자격
GRADE_DERIVED = 2   # 지지·위반 가능, 확정 자격 없음
# 3급(잔차)은 phase 2 강화 후보 — 설계자 결정으로 이번 스프린트에서는
# 폴백 명사도 2급과 동일 대우(확정 자격 유지 경로는 자격쌍이 결정).

# 자격쌍 hand 폴백(binding_v1.json 부재 시)의 등급 1 leaf 집합.
# phase 1a 동안은 구 평가기의 _TYPED_LEAVES가 원본이고 여기는 사본 —
# on 전환 시 소유권이 이 테이블로 넘어온다.
HAND_QUALIFYING_LEAVES = frozenset({
    "food_form", "processing_state",
    "principal_ingredient", "contains_wrapper_or_dough",
})

# ── 축권한표 (§B-2) — 집계 층이 소비하는 셀만 (조건 층 셀은 phase 1b) ──
AXIS_AUTHORITY = {
    ("state_field", "Q_IDENTITY"): "support",   # 예외7: 상태 단독 확정 금지
    ("state_field", "Q_STATE"): "confirm",
    ("accessory_rank", "Q_IDENTITY"): "demote",  # 예외9: 부수성분만이면 강등
}

# 구 평가기가 undecided 경로에서 why에 덧붙이는 차단 마커 — 섀도가
# detail을 나중에 읽으므로 파싱 전에 벗겨낸다 (서명에는 미포함).
_BLOCK_SUFFIX = re.compile(
    r";(?:state_alone_blocked|typed_gate_blocked|accessory_only_blocked"
    r"|order_weight_blocked|order_w=[0-9.]+)")


def _clean_why(why: str) -> str:
    return _BLOCK_SUFFIX.sub("", str(why or ""))


def _hit_leaves(d: Mapping[str, Any]) -> list[str]:
    why = _clean_why(d.get("why"))
    if not why.startswith("field_hit:"):
        return []
    return [leaf for leaf in why.removeprefix("field_hit:").split(",") if leaf]


def _grade(d: Mapping[str, Any], binding: Mapping[str, Any]) -> int:
    """증거등급표 해석: 이 true 판정은 몇 급 증거인가."""
    if d.get("op") == "quant_gate" and d.get("verdict") == "true":
        return GRADE_DIRECT  # quant_satisfied (미파싱은 조건 층이 무판정 처리)
    leaves = _hit_leaves(d)
    if not leaves:
        return GRADE_DERIVED  # alias_hit / union / 폴백 — 파생 증거
    cond = str(d.get("cond") or "")
    if binding:
        # 자격쌍 실측본이 등급 1 판별을 소유 (권한 행렬을 데이터가 정의)
        if any(f"{cond}|{leaf}" in binding for leaf in leaves):
            return GRADE_DIRECT
        return GRADE_DERIVED
    # hand 폴백: 정체 계열 질문의 typed leaf 직접 매치만 등급 1
    if AXIS_AUTHORITY.get(("state_field", "Q_IDENTITY")) == "support" \
            and cond in Q_STATE:
        return GRADE_DERIVED
    if any(leaf in HAND_QUALIFYING_LEAVES for leaf in leaves):
        return GRADE_DIRECT
    return GRADE_DERIVED


def _value_toks(d: Mapping[str, Any]) -> set[str]:
    try:
        vals = json.loads(str(d.get("value") or "null")) or []
    except Exception:  # noqa: BLE001
        return set()
    return {_stem(w) for v in vals
            for w in _TOKEN.findall(str(v).lower()) if len(w) >= 3}


def _rank_pools(product_facts: Mapping[str, Any] | None) -> tuple[set, set]:
    """(주성분 토큰, 부수성분 토큰) — 서열 강등 셀의 입력."""
    principal: set = set()
    accessory: set = set()
    if not product_facts:
        return principal, accessory
    from bussiness_logic.classification.rules.branch_predicate_evaluator import (
        _field_tokens,
    )
    entries = _dig(product_facts, "composition_facts.ingredient_entries") or []
    for e in entries:
        if not isinstance(e, dict):
            continue
        toks = {_stem(w) for w in _TOKEN.findall(
            str(e.get("ingredient_name") or "").lower()) if len(w) >= 3}
        if int(e.get("order_index") or 99) == 1:
            principal |= toks
        else:
            accessory |= toks
    for extra in ("identity_hints.principal_ingredient_guess",
                  "composition_facts.principal_ingredient"):
        principal |= _field_tokens(product_facts, extra)
    for a in _dig(product_facts, "identity_hints.accessory_ingredients") or []:
        accessory |= {_stem(w) for w in _TOKEN.findall(str(a).lower())
                      if len(w) >= 3}
    accessory -= principal
    return principal, accessory


def AggregatePrincipled(
    detail: list[Mapping[str, Any]],
    product_facts: Mapping[str, Any] | None,
    binding: Mapping[str, Any],
) -> str:
    """표 해석 집계: detail(조건 층 산출)에서 status를 재산출."""
    answers = [str(d.get("verdict") or "") for d in detail]
    if "false" in answers:
        return "violated"
    if not answers or not all(a == "true" for a in answers):
        return "undecided"
    # 예외7 재현 (권한 셀이 등급보다 우선): 정체 질문에 상태 축만 답한
    # 조건 집합은 자격쌍과 무관하게 confirm 불가 — 구 평가기의
    # state_alone 차단과 동일 시맨틱.
    cond_types = {str(d.get("cond") or "") for d in detail}
    if cond_types and cond_types <= Q_STATE:
        return "undecided"
    # 예외8 재현 (증거등급표): 등급 1 증거가 하나는 있어야 확정.
    if GRADE_DIRECT not in (_grade(d, binding) for d in detail):
        return "undecided"
    # 예외9 재현 (demote 셀): 정체 계열 true의 근거 어휘가 전부 부수성분
    # 풀에만 있으면 확정 강등. 주성분 무관 어휘(양쪽 다 없음)는 강등 아님.
    if AXIS_AUTHORITY.get(("accessory_rank", "Q_IDENTITY")) == "demote":
        principal, accessory = _rank_pools(product_facts)
        id_trues = [d for d in detail
                    if str(d.get("verdict")) == "true"
                    and str(d.get("cond") or "") not in Q_STATE]
        if id_trues and accessory:
            def _accessory_only(d: Mapping[str, Any]) -> bool:
                vt = _value_toks(d)
                return bool(vt) and not (vt & principal) and bool(vt & accessory)
            if all(_accessory_only(d) for d in id_trues):
                return "undecided"
    return "confirmed"


def ShadowCompare(
    legacy_status: str,
    detail: list[Mapping[str, Any]],
    product_facts: Mapping[str, Any] | None,
    *,
    level: str,
    code: str,
) -> None:
    """섀도 모드 훅: 불일치만 jsonl로 축적. 어떤 예외도 밖으로 안 새운다."""
    try:
        from bussiness_logic.classification.rules.branch_decision_evaluator import (
            _binding_table,
        )
        binding = _binding_table() if (os.environ.get(
            "ASAP_BINDING_V1", "1") or "1").strip() != "0" else {}
        shadow_status = AggregatePrincipled(detail, product_facts, binding)
        if shadow_status == legacy_status:
            return
        import pathlib
        out = pathlib.Path(__file__).resolve().parents[4] / "artifacts" \
            / "decision_shadow_diff.jsonl"
        with open(out, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "level": level, "code": code,
                "legacy": legacy_status, "principled": shadow_status,
                "detail": [{k: str(v)[:80] for k, v in d.items()}
                           for d in detail],
            }, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 — 섀도는 절대 본선을 흔들지 않는다
        pass
