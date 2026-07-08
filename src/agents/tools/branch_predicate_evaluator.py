"""Three-valued branch predicate evaluator (runtime, no LLM).

Reads the ``branch_predicate_index`` sidecar (built offline by
branch_predicate_compiler) and evaluates each branch's predicates against the
product's fact tokens:

  true     condition satisfied            -> boost
  false    condition violated             -> hard penalty (effectively out)
  unknown  DTO cannot answer              -> neutral (0) — NOT a mismatch

The score contribution is ADDITIVE over the lexical score so siblings with
and without compiled predicates stay on a symmetric footing (a mode switch
was measured to create unfair sibling fights when only some rows carried
required_dto_fields). ``pct`` predicates are delegated to the existing quant
gate and ``residual`` markers to the elimination policy — both skipped here.

Degrades to no-op ({} / 0.0) on any DB failure, per repository convention.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Mapping

_FIELD_BOOST = 3.0   # the bound DTO field answers the question directly
_POOL_BOOST = 1.0    # only the broad token pool answers — weak support
_PREDICATE_BLOCK = 100.0  # mirrors QUANT_PENALTY: a violated condition is out

_SKIP_AXES = frozenset({"pct", "residual"})
# IS-A alias (cn_alias_index, compiled offline from the CN tree itself):
# product token "octopus" answers a class question "molluscs". Applied to
# species/contains only — physical-state axes have no IS-A structure.
_ALIAS_AXES = frozenset({"species", "contains"})
_alias_cache: list[dict[str, list[str]]] = []


def _aliases() -> dict[str, list[str]]:
    if not _alias_cache:
        loaded: dict[str, list[str]] = {}
        try:
            from sqlalchemy import text

            from db.db_session_manager import DbSessionManager

            version = (os.environ.get("ASAP_ALIAS_VERSION", "tree-v1") or "").strip()
            for row in DbSessionManager.GetInstance().FetchRows(
                text('SELECT token, class_tokens FROM "cn_alias_index"'
                     " WHERE alias_version = :version"),
                {"version": version},
            ):
                data = dict(row)
                try:
                    loaded[str(data.get("token"))] = list(json.loads(str(data.get("class_tokens") or "[]")))
                except Exception:  # noqa: BLE001
                    continue
        except Exception:  # noqa: BLE001 — sidecar absent = no expansion
            loaded = {}
        _alias_cache.append(loaded)
    return _alias_cache[0]


def _expand(tokens: set[str]) -> set[str]:
    alias = _aliases()
    if not alias:
        return tokens
    out = set(tokens)
    for token in tokens:
        out.update(alias.get(token, ()))
    return out
# form/processing answer PHYSICAL-STATE questions: only the dedicated fields
# may answer them — a stray OCR word in the broad pool must not satisfy a
# form predicate (designer decision). species/contains keep the graded pool
# fallback because ingredient words legitimately live in many fields.
_STRICT_FIELD_AXES = frozenset({"form", "processing"})
_PATH_STRUCTURE_WORDS = frozenset({"contains", "is", "has", "or", "and"})
_TOKEN = re.compile(r"[a-z]+")


def _stem(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("es") and not token.endswith(("ses", "oes")):
        return token[:-2] if token.endswith(("ches", "shes", "xes")) else token[:-1]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _dig(obj: Any, path: str) -> Any:
    cur = obj
    for key in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(key)
        else:
            return None
    return cur


# 센티널은 '채워짐'이 아니라 '모름'이다 — 토큰으로 흘리면 field_empty가
# field_no_match로 위장된다 (comp.processing_state='unknown' 22/22 실측).
_FIELD_SENTINELS = frozenset({"unknown", "other", "none", "n/a", "na"})


def _field_tokens(product_facts: Mapping[str, Any] | None, dto_field: str) -> set[str]:
    """Token set of the bound DTO fields (';'-separated paths)."""
    if not product_facts or not dto_field or dto_field == "*tokens*":
        return set()
    out: set[str] = set()
    for path in dto_field.split(";"):
        path = path.strip()
        value = _dig(product_facts, path)
        parts: list[str] = []
        if isinstance(value, bool):
            # booleans answer the question their field NAME asks
            # (contains_sauce_or_broth=True -> sauce/broth)
            if value:
                leaf = path.rsplit(".", 1)[-1]
                parts = [w for w in leaf.split("_") if w not in _PATH_STRUCTURE_WORDS]
        elif isinstance(value, str):
            parts = [] if value.strip().lower() in _FIELD_SENTINELS else [value]
        elif isinstance(value, list):
            parts = [str(v) for v in value
                     if str(v).strip().lower() not in _FIELD_SENTINELS]
        for part in parts:
            out |= {_stem(t) for t in _TOKEN.findall(part.lower()) if len(t) >= 3}
    return out


def LoadBranchPredicates(level: str, codes: tuple[str, ...]) -> dict[str, list[dict[str, Any]]]:
    """{code -> [predicate rows]} from the sidecar; () -> {} on any failure."""
    if not codes:
        return {}
    try:
        from sqlalchemy import bindparam, text

        from db.db_session_manager import DbSessionManager

        manager = DbSessionManager.GetInstance()
        # A/B between compiler generations: ASAP_PREDICATE_VERSION selects
        # which sidecar generation feeds the runtime. Default rule-v2 matches
        # branch_predicate_compiler.py, so a freshly compiled sidecar is read
        # without requiring an env override. "all" stacks generations and is
        # NOT a measured/default configuration.
        version = (os.environ.get("ASAP_PREDICATE_VERSION", "rule-v2") or "").strip()
        version_clause = " AND predicate_version = :version" if version and version != "all" else ""
        params: dict[str, Any] = {"level": level, "codes": tuple(codes)}
        if version_clause:
            params["version"] = version
        rows = manager.FetchRows(
            text(
                'SELECT code, axis, dto_field, op, value, severity, compile_status'
                ' FROM "branch_predicate_index"'
                " WHERE level = :level AND code IN :codes" + version_clause
            ).bindparams(bindparam("codes", expanding=True)),
            params,
        )
    except Exception:  # noqa: BLE001 — sidecar absent = layer off
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        data = dict(row)
        if str(data.get("compile_status") or "") != "active":
            continue
        out.setdefault(str(data.get("code") or ""), []).append(data)
    return out


def EvaluatePredicates(
    predicates: list[Mapping[str, Any]],
    fact_tokens: frozenset[str] | set[str],
    product_facts: Mapping[str, Any] | None = None,
) -> tuple[float, list[dict[str, str]]]:
    """(score delta, per-predicate verdicts) — three-valued, GRADED.

    has_token axes evaluate the bound DTO field first (strong true, +3);
    when the field is silent the broad token pool may still answer (weak
    true, +1); otherwise unknown (0). Violations (not_contains) stay on the
    pool — a violation must be caught wherever the token lives.
    """
    delta = 0.0
    verdicts: list[dict[str, str]] = []
    pool = set(fact_tokens)
    # 잔존하는 유일한 broad-pool 지원 경로(true_pool +1)의 A/B 스위치.
    # 기본 ON(73% 실측 구성). OFF면 has_token은 바인딩 필드로만 답한다.
    pool_boost_on = (os.environ.get("ASAP_PREDICATE_POOL_BOOST", "1") or "1").strip() != "0"
    for pred in predicates:
        axis = str(pred.get("axis") or "")
        if axis in _SKIP_AXES:
            continue
        try:
            values = json.loads(str(pred.get("value") or "null"))
        except Exception:  # noqa: BLE001
            values = None
        tokens = {str(v).strip().lower() for v in (values or []) if str(v).strip()}
        if not tokens:
            continue
        op = str(pred.get("op") or "")
        if op == "not_contains":
            hit = bool(tokens & pool)
            verdict = "false" if hit else "unknown"
            if hit:
                delta -= _PREDICATE_BLOCK
        elif op == "has_token":
            bound = _field_tokens(product_facts, str(pred.get("dto_field") or ""))
            if axis in _ALIAS_AXES:
                bound = _expand(bound)
            if tokens & bound:
                verdict = "true"
                delta += _FIELD_BOOST
            elif pool_boost_on and axis not in _STRICT_FIELD_AXES and tokens & (
                _expand(pool) if axis in _ALIAS_AXES else pool
            ):
                verdict = "true_pool"
                delta += _POOL_BOOST
            else:
                verdict = "unknown"
        else:
            verdict = "unknown"
        why = ""
        if op == "has_token" and verdict == "unknown":
            bound_probe = _field_tokens(product_facts, str(pred.get("dto_field") or ""))
            why = "field_empty" if not bound_probe else "field_no_match"
        verdicts.append({
            "axis": axis,
            "op": op,
            "value": ",".join(sorted(tokens))[:60],
            "verdict": verdict,
            "why": why,
        })
    return delta, verdicts
