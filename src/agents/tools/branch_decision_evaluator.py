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
                'SELECT branch_id, seq, then_code, cond_type, dto_field, op, value'
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
                       "field": dto_field.split(";")[0][:40], "why": why})
    if "false" in answers:
        return "violated", detail
    if answers and all(a == "true" for a in answers):
        return "confirmed", detail
    # 부분 충족(일부 true, 일부 미결)은 확정도 탈락도 아니다 — 법조문상
    # 모든 조건이 맞아야 그 코드다.
    return "undecided", detail
