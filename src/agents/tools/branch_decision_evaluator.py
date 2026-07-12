"""Decision-table evaluator (runtime, no LLM).

Implements the designer model: at a branching point, check each sibling's
compiled CONDITIONS against the bound ProductUnderstandingFacts fields.

  confirmed   every condition of the code answered true  -> that code wins
  violated    any condition answered false               -> code is out
  undecided   conditions unanswerable (missing data)     -> lexical fallback

Confirmation requires the BOUND FIELD to answer (alias-expanded for
species/contains) — a broad-pool match is not enough to confirm (precision:
a stray OCR token must not certify a code). Violation uses the broad pool
(recall: an exclusion must be caught wherever the token lives) with
whole-phrase semantics ("common wheat flour" needs every content word).

Degrades to {} on any DB failure; the sidecar's absence turns the whole
layer off.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Mapping

from agents.tools.branch_predicate_evaluator import _aliases, _dig, _field_tokens, _stem

_TOKEN = re.compile(r"[a-z]+")
# 확정(confirmed) 자격을 줄 수 있는 typed 경로(단수·저오염 필드).
# NTD·identity_terms 같은 자유서술 다토큰 필드는 부수 요소('soup' 등)가
# 섞여 확정 정밀도 17%(정 7/오 33) 실측 — 이들 '단독' 히트는 확정 불가.
# ingredient_class는 제외: 'cereal' 같은 류(class) 값은 1901~1905 전부에
# 해당해 확정 근거로 판별력이 없다 — 오발동 6건 중 5건이 이 경로 실측.
# 점수 경쟁(+3)에는 계속 참여하고 확정(+50) 자격만 없다.
_TYPED_LEAVES = frozenset({
    "food_form", "processing_state",
    "principal_ingredient", "contains_wrapper_or_dough",
    "contains_sauce_or_broth",
})
_ALIAS_AXES = frozenset({
    "species", "contains",  # 구세대 명칭 호환
    "species_source", "material_composition", "product_identity",
})


def LoadBranchDecisions(
    level: str,
    parent_codes: tuple[str, ...],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """{parent -> {then_code -> [condition rows]}}; {} on failure/absence."""
    if not parent_codes:
        return {}
    version = (os.environ.get("ASAP_DECISION_VERSION", "parser-v1") or "").strip()
    try:
        from sqlalchemy import bindparam, text

        from db.db_session_manager import DbSessionManager

        rows = DbSessionManager.GetInstance().FetchRows(
            text(
                'SELECT branch_id, seq, then_code, cond_type, dto_field, op, value, source_text'
                ' FROM "branch_decision_index"'
                " WHERE level = :level AND branch_id IN :parents AND version = :version"
                " ORDER BY branch_id, seq"
            ).bindparams(bindparam("parents", expanding=True)),
            {"level": level, "parents": tuple(parent_codes), "version": version},
        )
    except Exception:  # noqa: BLE001 — sidecar absent = layer off
        return {}
    out: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for row in rows:
        data = dict(row)
        parent = str(data.get("branch_id") or "")
        code = str(data.get("then_code") or "")
        out.setdefault(parent, {}).setdefault(code, []).append(data)
    return out


def _phrase_sets(value_json: str) -> list[set[str]]:
    try:
        values = json.loads(str(value_json or "null"))
    except Exception:  # noqa: BLE001
        return []
    phrases: list[set[str]] = []
    for value in values or []:
        toks = {_stem(t) for t in _TOKEN.findall(str(value).lower()) if len(t) >= 3}
        if toks:
            phrases.append(toks)
    return phrases


def EvaluateCodeDecision(
    conditions: list[Mapping[str, Any]],
    product_facts: Mapping[str, Any] | None,
    fact_tokens: frozenset[str] | set[str],
    percentages: list[Any],
    quant_verdict_fn,
) -> tuple[str, list[dict[str, str]]]:
    """('confirmed'|'violated'|'undecided', detail) for ONE code's conditions."""
    pool = set(fact_tokens)
    detail: list[dict[str, str]] = []
    answers: list[str] = []
    for cond in conditions:
        cond_type = str(cond.get("cond_type") or "")
        op = str(cond.get("op") or "")
        dto_field = str(cond.get("dto_field") or "")
        verdict = "undecided"
        why = ""
        if op == "quant_gate":
            result = quant_verdict_fn(str(cond.get("source_text") or ""), percentages)
            verdict = {"satisfies": "true", "violates": "false"}.get(
                (result or {}).get("verdict"), "undecided")
            why = (result or {}).get("reason", "") or (
                "no_percentages" if not percentages else "threshold_unparsed")
        elif op == "not_contains":
            phrases = _phrase_sets(str(cond.get("value")))
            if any(p <= pool for p in phrases):
                verdict = "false"
                why = "exclusion_present_in_pool"
            else:
                why = "exclusion_absent"
        elif op == "has_token":
            phrases = _phrase_sets(str(cond.get("value")))
            bound = _field_tokens(product_facts, str(cond.get("dto_field") or ""))
            if cond_type in _ALIAS_AXES:
                alias = _aliases()
                bound = bound | {c for t in bound for c in alias.get(t, ())}
            if any(p <= bound for p in phrases):
                verdict = "true"
                # 확정 자격 심사용: 바인딩의 어느 '경로'가 실제로 답했는가
                # (identity_terms 단독 히트인지 typed 필드 히트인지 구분)
                hit_paths = []
                for path in dto_field.split(";"):
                    path = path.strip()
                    ptoks = _field_tokens(product_facts, path)
                    if cond_type in _ALIAS_AXES:
                        ptoks = ptoks | {c for t in ptoks for c in _aliases().get(t, ())}
                    if any(p <= ptoks for p in phrases):
                        hit_paths.append(path.rsplit(".", 1)[-1])
                # 단일 경로로는 부분 매치뿐인데 합집합으로만 성립한 히트는
                # 'union'으로 표시 — 서로 다른 필드의 파편이 합쳐진 약한 근거
                why = "field_hit:" + (",".join(hit_paths[:3]) or "union")
            elif not bound:
                why = "field_empty"       # 답안지 부재 — DTO가 이 질문에 침묵
            else:
                why = "field_no_match"    # 필드는 찼는데 값 불일치 (어휘 갭/오답)
        answers.append(verdict)
        detail.append({"cond": cond_type, "op": op, "verdict": verdict,
                       "field": dto_field.split(";")[0][:40], "why": why,
                       "value": str(cond.get("value") or "")[:80]})
    if "false" in answers:
        return "violated", detail
    if answers and all(a == "true" for a in answers):
        # typed 게이트: true의 근거 중 typed 경로 히트(또는 정량 게이트
        # 충족)가 하나는 있어야 확정. 자유서술 필드 단독 확정은 강등 —
        # 점수 경쟁(술어 +3)은 유지되고 +50 확정만 잃는다.
        # ASAP_DECISION_TYPED_GATE=0으로 이전(77% 커밋) 시맨틱 복귀.
        gate_on = (os.environ.get("ASAP_DECISION_TYPED_GATE", "1") or "1").strip() != "0"
        # 상태형 단독 확정 금지(동족 원칙 3호 — ingredient_class·NTD 제한과
        # 같은 계보): 'prepared' 같은 상태값은 조리식품 전부가 가져서 단독
        # 확정 자격이 없다 (실측: 오발동 21건 중 2102 효모 등 다수가 상태
        # 단독). 상태는 정체(identity/species/material) true를 전제로만
        # 확정을 가른다. ASAP_DECISION_STATE_ALONE=1 복귀.
        state_types = {"processing_method", "preservation_state",
                       "physical_form", "condition_quality"}
        if gate_on and (os.environ.get(
                "ASAP_DECISION_STATE_ALONE", "0") or "0").strip() != "1":
            true_types = {d["cond"] for d in detail if d["verdict"] == "true"}
            if true_types and true_types <= state_types:
                for d in detail:
                    if d["verdict"] == "true":
                        d["why"] += ";state_alone_blocked"
                return "undecided", detail
        typed_ok = any(
            (d["op"] == "quant_gate" and d["verdict"] == "true")
            or (d["verdict"] == "true"
                and any(leaf in _TYPED_LEAVES
                        for leaf in d["why"].removeprefix("field_hit:").split(",")))
            for d in detail
        )
        if gate_on and not typed_ok:
            for d in detail:
                if d["verdict"] == "true":
                    d["why"] += ";typed_gate_blocked"
            return "undecided", detail
        return "confirmed", detail
    # 부분 충족(일부 true, 일부 미결)은 확정도 탈락도 아니다 — 법조문상
    # 모든 조건이 맞아야 그 코드다.
    return "undecided", detail
