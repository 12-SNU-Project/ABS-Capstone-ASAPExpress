"""StagedClassificationTool (baseline-adapted).

Controller-driven HS4 -> HS6 -> CN8 *narrowing* classifier. Unlike a one-shot
full-cn_table search, each level only ranks the *children* of the codes selected
at the previous level, so the right node cannot be drowned out by unrelated
chapters.

Baseline building blocks (no dependency on the removed ``llm_classifier``):
  - cn_table children  : direct prefix query via ``document_package._connect_db``
  - LLM stage-select   : ``_external_classifier.build_runtime_adapter`` +
                         ``bussiness_logic.bridge.schema.LlmRequest`` (RuntimeAdapter.Generate)

Reads baseline ProductUnderstandingFacts / RoutingContext shaped blackboard dicts. Returns compact
per-stage payloads so ``classification_stage_results`` on the blackboard can
explain why HS4/HS6/CN8 were chosen. Degrades gracefully (never raises).
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

# AXIS_MAP — decision axis -> baseline ProductUnderstandingFacts field paths.
# Reads the embedded 2-lane: identity_lane (DistilledIdentityFacts.ToTrace) +
# composition_lane (CompositionLaneFacts.ToTrace). No separate composition_facts object under B.
CLASSIFICATION_AXIS_MAP: dict[str, list[str]] = {
    "ingredient_taxonomy": [
        "identity_lane.ingredient_class",
        "identity_lane.normalized_tariff_description",
        "identity_lane.identity_terms",
        "composition_lane.principal_ingredient",
        "composition_lane.ingredient_classes",
    ],
    "product_form": [
        "identity_lane.food_form",
        "identity_lane.commercial_identity",
        "identity_lane.identity_terms",
    ],
    "processing_state": [
        "identity_lane.processing_state",
        "identity_lane.processing_terms",
        "composition_lane.processing_state",
        "composition_lane.processing_terms",
        "composition_lane.contains_wrapper_or_dough",
        "composition_lane.contains_sauce_or_broth",
    ],
    "composition_percentage": [
        "identity_lane.composition_terms",
        "composition_lane.composition_terms",
        "composition_lane.ingredient_percentages",
    ],
}
# Which axes matter at each level (identity high, composition low).
LEVEL_AXES: dict[str, list[str]] = {
    "hs4": ["ingredient_taxonomy", "product_form"],
    "hs6": ["ingredient_taxonomy", "product_form", "processing_state"],
    "cn8": ["ingredient_taxonomy", "processing_state", "composition_percentage"],
}
# Per-level axis weights for lexical ranking: identity dominates the "what is it"
# question at hs4; composition/% dominates the fine cn8 split (GIR-aligned).
LEVEL_AXIS_WEIGHTS: dict[str, dict[str, float]] = {
    "hs4": {"ingredient_taxonomy": 2.0, "product_form": 1.0},
    "hs6": {"ingredient_taxonomy": 1.5, "product_form": 1.0, "processing_state": 1.5},
    "cn8": {"ingredient_taxonomy": 1.0, "processing_state": 1.0, "composition_percentage": 2.0},
}
# Quantitative gate: a node whose CN %-threshold is satisfied by the product's
# ingredient_percentages is boosted; one contradicted is effectively dropped.
QUANT_BOOST = 3.0
QUANT_PENALTY = 100.0
LEVELS = (("hs4", 4), ("hs6", 6), ("cn8", 8))
_TOKEN = re.compile(r"[a-z0-9]+")


def _digits(value: Any, *, limit: int = 8) -> str:
    return re.sub(r"\D", "", str(value or ""))[:limit]


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(str(text or "").lower()))


def _extract_json(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if "```" in raw:  # strip ```json ... ``` fences
        raw = re.sub(r"^```[a-zA-Z]*", "", raw).strip().rstrip("`").strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _dig(obj: Any, path: str) -> Any:
    cur = obj
    for key in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(key)
        else:
            return None
    return cur


def _string_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, bool):
        return [str(value).lower()] if value else []
    if isinstance(value, (str, int, float)):
        text = str(value).strip()
        return [text] if text else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_string_values(item))
        return out
    if isinstance(value, dict):
        return [
            str(item).strip()
            for item in value.values()
            if str(item).strip()
        ]
    text = str(value).strip()
    return [text] if text else []


# ---- quantitative %-gate (deterministic; never guesses percentages) ----------
# EU CN uses stable threshold phrasings, e.g. "content exceeding 20 % by weight",
# "not exceeding 30 %", "20 % or more by weight of". We parse the node text and
# compare against the product's composition_lane.ingredient_percentages.
_PCT_BEFORE = re.compile(
    r"(?P<op>not exceeding|exceeding|more than|less than|at least)\s*(?P<val>\d+(?:\.\d+)?)\s*%",
    re.I,
)
_PCT_AFTER = re.compile(r"(?P<val>\d+(?:\.\d+)?)\s*%\s*(?P<op>or more|or less)", re.I)
_GE_STRICT = {"exceeding", "more than"}
_GE_EQ = {"at least", "or more"}
_LE_STRICT = {"less than"}
_LE_EQ = {"not exceeding", "or less"}


def _to_float(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None


def _parse_thresholds(text: str) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for rx in (_PCT_BEFORE, _PCT_AFTER):
        for m in rx.finditer(str(text or "")):
            val = _to_float(m.group("val"))
            if val is not None:
                out.append((m.group("op").lower(), val))
    return out


def _threshold_holds(op: str, pct: float, val: float) -> bool | None:
    if op in _GE_STRICT:
        return pct > val
    if op in _GE_EQ:
        return pct >= val
    if op in _LE_STRICT:
        return pct < val
    if op in _LE_EQ:
        return pct <= val
    return None


def _quantitative_verdict(descr: str, percentages: list[Any]) -> dict[str, Any]:
    if not percentages:
        return {"verdict": "neutral", "reason": "no_percentages"}
    thresholds = _parse_thresholds(descr)
    if not thresholds:
        return {"verdict": "neutral", "reason": "no_threshold_in_node"}
    node_tokens = _tokens(descr)
    matched: tuple[str, float] | None = None
    for p in percentages:
        if not isinstance(p, dict):
            continue
        pct = _to_float(p.get("percent"))
        term = str(p.get("term") or "").strip()
        if pct is not None and term and (_tokens(term) & node_tokens):
            matched = (term, pct)
            break
    if matched is None:
        return {"verdict": "neutral", "reason": "ingredient_not_in_node"}
    term, pct = matched
    checks = [_threshold_holds(op, pct, val) for op, val in thresholds]
    decided = [c for c in checks if c is not None]
    base = {"ingredient": term, "percent": pct,
            "thresholds": [f"{op} {val}%" for op, val in thresholds]}
    if decided and all(decided):
        return {"verdict": "satisfies", **base}
    if any(c is False for c in checks):
        return {"verdict": "violates", **base}
    return {"verdict": "neutral", "reason": "indeterminate"}


class StagedClassificationTool:
    tool_name = "StagedClassificationTool"

    def __init__(self, *, keep_per_level: int = 3, rank_top_k: int = 8) -> None:
        self._adapter = None
        self.keep_per_level = keep_per_level
        self.rank_top_k = rank_top_k

    # ---- public -----------------------------------------------------------
    def classify(
        self,
        *,
        product_facts: dict[str, Any],
        routing_context: dict[str, Any],
        top_k: int = 8,
    ) -> dict[str, Any]:
        facts = self._read_facts(product_facts)
        percentages = _dig(product_facts, "composition_lane.ingredient_percentages")
        percentages = percentages if isinstance(percentages, list) else []
        parents = self._start_chapters(routing_context)
        if not parents:
            return {"ok": False, "error": "no_route_chapters", "candidates": [], "stages": []}

        stages: list[dict[str, Any]] = []
        for level, prefix_len in LEVELS:
            children = self._load_children(parents, prefix_len)
            if not children:
                stages.append(self._trace(level, [], [], facts, "no_children"))
                return {"ok": False, "error": f"no_children_at_{level}",
                        "candidates": [], "stages": stages}
            ranked = self._lexical_rank(children, facts, level, percentages)[: self.rank_top_k]
            selected = self._llm_select(ranked, facts, level)
            if not selected:  # deterministic fallback = top lexical
                selected = [ranked[0]["code"]]
            stages.append(self._trace(level, ranked, selected, facts, "ok"))
            parents = selected

        candidates = self._final_candidates(parents, top_k=top_k)
        return {
            "ok": bool(candidates),
            "error": "" if candidates else "no_cn8",
            "candidates": candidates,
            "stages": stages,
        }

    # ---- facts / route ----------------------------------------------------
    def _read_facts(self, product_facts: dict[str, Any]) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for axis, paths in CLASSIFICATION_AXIS_MAP.items():
            vals: list[str] = []
            for path in paths:
                vals.extend(_string_values(_dig(product_facts, path)))
            out[axis] = vals[:16]
        return out

    def _start_chapters(self, routing_context: dict[str, Any]) -> list[str]:
        chapters: list[str] = []
        route_values = (
            routing_context.get("candidate_hs2")
            or routing_context.get("candidate_chapters")
            or []
        )
        for c in route_values[:5]:
            ch = _digits(c.get("chapter") if isinstance(c, dict) else c, limit=2)
            if len(ch) == 2 and ch not in chapters:
                chapters.append(ch)
        return chapters

    # ---- cn_table children (deterministic, baseline DB) -------------------
    def _load_children(self, parent_codes: list[str], prefix_len: int) -> list[dict[str, Any]]:
        from agents.document_package import _connect_db, _release_db

        parent_len = len(parent_codes[0]) if parent_codes else 0
        desc_col = {4: "heading_description", 6: "subheading_description", 8: "cn8_description"}[prefix_len]
        conn = None
        rows: list[dict[str, Any]] = []
        try:
            conn = _connect_db()
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT DISTINCT ON (left(cn8, %s))
                       left(cn8, %s) AS code,
                       coalesce({desc_col}, combined_description, cn8_description, '') AS descr,
                       coalesce(include_rule_keywords, '') AS incl,
                       coalesce(exclude_rule_keywords, '') AS excl
                FROM cn_table
                WHERE left(cn8, %s) = ANY(%s)
                ORDER BY left(cn8, %s), cn8
                """,
                (prefix_len, prefix_len, parent_len, parent_codes, prefix_len),
            )
            for code, descr, incl, excl in cur.fetchall():
                rows.append({"code": code, "descr": descr, "incl": incl, "excl": excl})
            cur.close()
        except Exception:  # noqa: BLE001 — narrowing must not break the pipeline
            return []
        finally:
            _release_db(conn)
        return rows

    # ---- weighted lexical rank + quantitative gate ------------------------
    def _lexical_rank(
        self,
        children: list[dict[str, Any]],
        facts: dict[str, list[str]],
        level: str,
        percentages: list[Any],
    ) -> list[dict[str, Any]]:
        weights = LEVEL_AXIS_WEIGHTS[level]
        axis_tokens: dict[str, set[str]] = {}
        for axis in LEVEL_AXES[level]:
            toks: set[str] = set()
            for v in facts.get(axis, []):
                toks |= _tokens(v)
            axis_tokens[axis] = toks
        all_terms: set[str] = set()
        for toks in axis_tokens.values():
            all_terms |= toks

        scored = []
        for row in children:
            node_terms = _tokens(row["descr"]) | _tokens(row["incl"])
            excl_terms = _tokens(row["excl"])
            score = 0.0
            for axis, toks in axis_tokens.items():
                score += weights.get(axis, 1.0) * len(toks & node_terms)
            score -= 0.5 * len(all_terms & excl_terms)
            verdict = _quantitative_verdict(row["descr"], percentages)
            if verdict["verdict"] == "satisfies":
                score += QUANT_BOOST
            elif verdict["verdict"] == "violates":
                score -= QUANT_PENALTY
            scored.append({**row, "score": round(score, 2), "quantitative_verdict": verdict})
        scored.sort(key=lambda r: r["score"], reverse=True)
        return scored

    # ---- LLM select (bridge) ---------------------------------------------
    def _get_adapter(self):
        if self._adapter is None:
            from agents._external_classifier import build_runtime_adapter
            self._adapter = build_runtime_adapter()
        return self._adapter

    def _llm_select(self, ranked: list[dict[str, Any]], facts: dict[str, list[str]], level: str) -> list[str]:
        if not ranked:
            return []
        from bussiness_logic.bridge.schema import LlmRequest, LlmGenerationOptions

        facts_view = {axis: facts.get(axis, [])[:8] for axis in LEVEL_AXES[level]}
        cand_view = [{"code": r["code"], "desc": (r["descr"] or "")[:180]} for r in ranked]
        prompt = (
            f"Select up to {self.keep_per_level} best EU CN {level.upper()} prefixes for this product.\n"
            f"Product facts (decision axes):\n{json.dumps(facts_view, ensure_ascii=False)}\n"
            f"Candidate {level.upper()} nodes:\n{json.dumps(cand_view, ensure_ascii=False)}\n"
            'Return ONE JSON object only: {"selected":["<code>",...],"basis":"<short reason>"}.\n'
            "Prefer nodes whose description matches the commodity + form. No codes outside the candidates."
        )
        try:
            resp = self._get_adapter().Generate(
                LlmRequest(
                    user_prompt=prompt,
                    system_prompt="You pick EU customs classification prefixes. Output one JSON object only.",
                    generation_options=LlmGenerationOptions(
                        temperature=0,
                        max_tokens=int(os.environ.get("ASAP_STAGED_LLM_MAX_TOKENS", "512")),
                    ),
                )
            )
            parsed = _extract_json(resp.generatedText)
        except Exception:  # noqa: BLE001
            return []
        valid = {r["code"] for r in ranked}
        picked = [str(c) for c in (parsed.get("selected") or []) if str(c) in valid]
        return picked[: self.keep_per_level]

    # ---- final cn8 + trace ------------------------------------------------
    def _final_candidates(self, cn8_prefixes: list[str], *, top_k: int) -> list[dict[str, Any]]:
        from agents.document_package import _connect_db, _release_db

        out: list[dict[str, Any]] = []
        conn = None
        try:
            conn = _connect_db()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT cn8, coalesce(cn8_description, combined_description, '') d
                FROM cn_table WHERE cn8 = ANY(%s) ORDER BY cn8 LIMIT %s
                """,
                (cn8_prefixes, top_k),
            )
            for cn8, d in cur.fetchall():
                code = _digits(cn8, limit=8)
                if len(code) == 8:
                    out.append({"cn8": code, "hs6": code[:6], "hs4": code[:4], "description": d})
            cur.close()
        except Exception:  # noqa: BLE001
            return []
        finally:
            _release_db(conn)
        return out

    def _trace(self, level: str, ranked: list[dict[str, Any]], selected: list[str], facts: dict[str, list[str]], status: str) -> dict[str, Any]:
        return {
            "stage": level,
            "status": status,
            "decision_axes": [{"axis": a, "values": facts.get(a, [])[:8]} for a in LEVEL_AXES[level]],
            "candidates_considered": [
                {
                    "code": r["code"],
                    "score": r["score"],
                    "quantitative_verdict": (r.get("quantitative_verdict") or {}).get("verdict", "neutral"),
                }
                for r in ranked[:8]
            ],
            "selected_codes": selected,
            "missing_facts": [a for a in LEVEL_AXES[level] if not facts.get(a)],
        }
