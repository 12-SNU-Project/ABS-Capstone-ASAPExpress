"""StagedClassificationTool (baseline-adapted).

Controller-driven HS4 -> HS6 -> CN8 *narrowing* classifier. Unlike a one-shot
full-cn_table search, each level only ranks the *children* of the codes selected
at the previous level, so the right node cannot be drowned out by unrelated
chapters.

Baseline building blocks (no dependency on the removed ``llm_classifier``):
  - cn_table children  : managed session-based query via ``DbSessionManager``
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
from sqlalchemy import bindparam, text

from agents.tools.db_session_manager import DbSessionManager

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


def _stem(token: str) -> str:
    """Naive singular/plural normalisation — CN wording is mostly plural
    (molluscs, cockles) while product facts are often singular; without this
    the species-deciding words never match."""
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("es") and not token.endswith(("ses", "oes")):
        return token[:-2] if token.endswith(("ches", "shes", "xes")) else token[:-1]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


# Operator grammar of CN quantitative clauses ("containing more than 20 % by
# weight of ..."). These words describe the THRESHOLD, not the product; the
# quantitative gate (_quantitative_verdict) owns that clause, so counting them
# as lexical evidence would double-score a condition without checking it.
# Derived from the _PCT_BEFORE/_PCT_AFTER grammar — not a product-word list.
_QUANT_OPERATOR_TOKENS = frozenset({
    "containing", "content", "exceeding", "more", "less", "than", "least",
    "most", "weight", "percent", "cent", "minimum", "maximum",
})

_WHETHER_OR_NOT_RE = re.compile(r"whether\s+or\s+not", re.I)
_NEGATION_RE = re.compile(r"\b(?:not|excluding|without|other\s+than)\s+([a-z]+(?:\s+[a-z]+)?)", re.I)


def _negated_tokens(label: str) -> set[str]:
    """Tokens a node label explicitly negates ("not stuffed" -> {stuffed}).

    "whether or not X" means *irrespective of X* — stripped first so it is not
    treated as a negation.
    """
    cleaned = _WHETHER_OR_NOT_RE.sub(" ", str(label or "").lower())
    out: set[str] = set()
    for match in _NEGATION_RE.finditer(cleaned):
        out |= _tokens(match.group(1))
    return out


def _tokens(text: str) -> set[str]:
    # len>=3 drops function words (or/of/in/by) that would otherwise pass the
    # sibling-IDF filter and score as fake "discriminative" matches.
    return {
        _stem(token)
        for token in _TOKEN.findall(str(text or "").lower())
        if len(token) >= 3
    }


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
        chapter_scores = self._chapter_scores(routing_context)

        use_branch_index = (os.environ.get("ASAP_USE_BRANCH_INDEX", "1") or "").strip().lower() not in (
            "0", "false", "no", "off",
        )
        # Parent confidence carried level to level: chapters start with the
        # router's scores; afterwards each selected code carries its own score.
        parent_scores: dict[str, float] = dict(chapter_scores)

        stages: list[dict[str, Any]] = []
        for level, prefix_len in LEVELS:
            branch_rows = self._load_branch_rows(level, parents) if use_branch_index else ()
            if branch_rows:
                if len(branch_rows) == 1:  # pass-through branch: no decision to make
                    only = _digits(branch_rows[0].get("code"), limit=prefix_len)
                    stages.append(self._trace(level, [], [only], facts, "pass_through", engine="branch_index"))
                    parent_scores = {only: max(parent_scores.values(), default=0.0)}
                    parents = [only]
                    continue
                ranked = self._branch_rank(
                    branch_rows, product_facts, facts, percentages, prefix_len,
                    parent_order=list(parents),
                    parent_scores=parent_scores,
                )
            else:
                children = self._load_children(parents, prefix_len)
                if not children:
                    stages.append(self._trace(level, [], [], facts, "no_children"))
                    return {"ok": False, "error": f"no_children_at_{level}",
                            "candidates": [], "stages": stages}
                ranked = self._lexical_rank(children, facts, level, percentages)
            if level == "hs4" and chapter_scores and not branch_rows:
                # Lexical fallback path only: add the router chapter score.
                # The branch path encodes parent ranking hierarchically inside
                # _branch_rank (round-robin merge), so no raw-score bonus there.
                for row in ranked:
                    row["score"] = round(
                        row["score"] + chapter_scores.get(str(row["code"])[:2], 0.0), 2,
                    )
                ranked.sort(key=lambda r: r["score"], reverse=True)
            ranked = ranked[: self.rank_top_k]
            selected = self._llm_select(ranked, facts, level)
            if not selected:  # deterministic fallback = top lexical
                selected = [ranked[0]["code"]]
            stages.append(self._trace(
                level, ranked, selected, facts, "ok",
                engine="branch_index" if branch_rows else "cn_table",
            ))
            ranked_scores = {r["code"]: float(r["score"]) for r in ranked}
            parent_scores = {code: ranked_scores.get(code, 0.0) for code in selected}
            parents = selected

        candidates = self._final_candidates(parents, top_k=top_k)
        return {
            "ok": bool(candidates),
            "error": "" if candidates else "no_cn8",
            "candidates": candidates,
            "stages": stages,
        }

    # ---- facts / route ----------------------------------------------------
    # Internal categorical labels must not become search tokens: composite
    # labels split into misleading words ("bread_pastry" -> bread+pastry pushed
    # 만두 to ch19 bakery) and "other" matches every residual "Other" node.
    _INTERNAL_LABELS = frozenset({
        "other", "unknown", "bread_pastry", "processed_or_prepared",
        "raw_or_fresh", "not_food_processing", "label", "label_text_no_percent",
        "coi_text",
    })

    def _read_facts(self, product_facts: dict[str, Any]) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for axis, paths in CLASSIFICATION_AXIS_MAP.items():
            vals: list[str] = []
            for path in paths:
                vals.extend(
                    value
                    for value in _string_values(_dig(product_facts, path))
                    if value.strip().lower() not in self._INTERNAL_LABELS
                )
            out[axis] = vals[:16]
        return out

    @staticmethod
    def _chapter_scores(routing_context: dict[str, Any]) -> dict[str, float]:
        """Router chapter scores from candidate_chapter_details ({} if absent)."""
        details = routing_context.get("candidate_chapter_details")
        if not isinstance(details, list):
            return {}
        scores: dict[str, float] = {}
        for item in details:
            if not isinstance(item, dict):
                continue
            chapter = _digits(item.get("chapter"), limit=2)
            try:
                score = float(item.get("score") or 0.0)
            except (TypeError, ValueError):
                score = 0.0
            if len(chapter) == 2 and score > 0:
                scores[chapter] = score
        return scores

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
        parent_len = len(parent_codes[0]) if parent_codes else 0
        desc_col = {4: "heading_description", 6: "subheading_description", 8: "cn8_description"}[prefix_len]
        rows: list[dict[str, Any]] = []
        if not parent_codes:
            return rows

        try:
            manager = DbSessionManager.GetInstance()
            for row in manager.FetchRows(
                text(
                    f"""
                    SELECT DISTINCT ON (left(cn8, :prefixLen))
                           left(cn8, :prefixLen) AS code,
                           coalesce({desc_col}, combined_description, cn8_description, '') AS descr,
                           coalesce(include_rule_keywords, '') AS incl,
                           coalesce(exclude_rule_keywords, '') AS excl
                    FROM cn_table
                    WHERE left(cn8, :parentLen) IN :parentCodes
                    ORDER BY left(cn8, :prefixLen), cn8
                    """
                ).bindparams(bindparam("parentCodes", expanding=True)),
                {
                    "prefixLen": prefix_len,
                    "parentLen": parent_len,
                    "parentCodes": tuple(parent_codes),
                },
            ):
                rows.append(
                    {
                        "code": row.get("code"),
                        "descr": row.get("descr"),
                        "incl": row.get("incl"),
                        "excl": row.get("excl"),
                    }
                )
        except Exception:  # noqa: BLE001 — narrowing must not break the pipeline
            return []
        return rows

    # ---- final cn8 + trace ------------------------------------------------
    def _final_candidates(self, cn8_prefixes: list[str], *, top_k: int) -> list[dict[str, Any]]:
        if not cn8_prefixes:
            return []
        out: list[dict[str, Any]] = []
        try:
            manager = DbSessionManager.GetInstance()
            for row in manager.FetchRows(
                text(
                    """
                    SELECT cn8, coalesce(cn8_description, combined_description, '') d
                    FROM cn_table WHERE cn8 IN :cn8Prefixes ORDER BY cn8 LIMIT :topK
                    """
                ).bindparams(bindparam("cn8Prefixes", expanding=True)),
                {
                    "cn8Prefixes": tuple(code for code in cn8_prefixes if _digits(code, limit=8)),
                    "topK": top_k,
                },
            ):
                code = _digits(row.get("cn8"), limit=8)
                if len(code) == 8:
                    out.append({"cn8": code, "hs6": code[:6], "hs4": code[:4], "description": row.get("d")})
        except Exception:  # noqa: BLE001
            return []
        # Preserve the staged score order (cn8_prefixes is already ranked by the
        # cn8 stage); the SQL's ORDER BY cn8 would otherwise destroy the ranking
        # and demote a top-1 answer to a code-sorted position.
        rank = {_digits(code, limit=8): index for index, code in enumerate(cn8_prefixes)}
        out.sort(key=lambda item: rank.get(item["cn8"], len(rank)))
        return out

    # ---- branch-index driven rank (P2: node-local criteria from Supabase) --
    @staticmethod
    def _load_branch_rows(level: str, parents: list[str]) -> tuple[dict[str, Any], ...]:
        try:
            from agents.tools.branch_index_repository import LoadBranchRows
        except Exception:  # noqa: BLE001
            return ()
        return tuple(dict(row) for row in LoadBranchRows(level, tuple(parents)))

    def _branch_rank(
        self,
        branch_rows: tuple[dict[str, Any], ...],
        product_facts: dict[str, Any],
        facts: dict[str, list[str]],
        percentages: list[Any],
        prefix_len: int,
        parent_order: list[str],
        parent_scores: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        """Hierarchical branch ranking: children compete ONLY with their own
        siblings; families are merged by PARENT CONFIDENCE first.

        A branch is a parent-local question, so pooling children of different
        parents is an unfair fight (a single-leaf child inherits its parent's
        whole wording; leaf-level siblings only carry their distinguisher).
        Merge order: (parent score desc, rank within own family, child score
        desc) — a router/previous-stage confidence of 86 vs 20 must not be
        flattened into one-slot-per-family; only near-tied parents let child
        evidence decide.
        """
        fallback_tokens: set[str] = set()
        for values in facts.values():
            for value in values:
                fallback_tokens |= _tokens(value)

        # Group children under their own parent (the actual branching point).
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in branch_rows:
            code = _digits(row.get("code"), limit=prefix_len)
            if len(code) != prefix_len:
                continue
            parent = _digits(row.get("parent_code"), limit=prefix_len) or code[:-2]
            groups.setdefault(parent, []).append({"row": row, "code": code})

        parent_rank = {p: i for i, p in enumerate(parent_order)}
        scores_by_parent = parent_scores or {}
        merged: list[dict[str, Any]] = []
        for parent, items in groups.items():
            ranked_group = self._rank_sibling_group(
                items, product_facts, fallback_tokens, percentages,
            )
            for round_index, entry in enumerate(ranked_group):
                entry["_parent_score"] = float(scores_by_parent.get(parent, 0.0))
                entry["_round"] = round_index
                entry["_parent_rank"] = parent_rank.get(parent, len(parent_rank))
                merged.append(entry)

        merged.sort(key=lambda r: (
            -r["_parent_score"], r["_round"], -r["score"], r["_parent_rank"], r["code"],
        ))
        for entry in merged:
            entry.pop("_parent_score", None)
            entry.pop("_round", None)
            entry.pop("_parent_rank", None)
        return merged

    def _rank_sibling_group(
        self,
        items: list[dict[str, Any]],
        product_facts: dict[str, Any],
        fallback_tokens: set[str],
        percentages: list[Any],
    ) -> list[dict[str, Any]]:
        """Rank ONE family of siblings by their own decision criteria.

        H2: tokens the label negates ("NOT stuffed") move to negative.
        Quant-operator grammar (containing/exceeding/weight/…) is excluded from
        lexical evidence — that clause belongs to the quantitative gate.
        H1: sibling-IDF within the family (skipped for a single child — there
        is nothing to discriminate). Residuals never win by wording.
        """
        prepared: list[dict[str, Any]] = []
        for item in items:
            row = item["row"]
            negated = _negated_tokens(str(row.get("option_label_en") or ""))
            positive = (
                _tokens(str(row.get("positive_terms") or "").replace(";", " "))
                - negated - _QUANT_OPERATOR_TOKENS
            )
            negative = _tokens(str(row.get("negative_terms") or "").replace(";", " ")) | negated
            prepared.append({**item, "positive": positive, "negative": negative})

        sibling_count = len(prepared)
        doc_freq: dict[str, int] = {}
        for entry in prepared:
            for tok in entry["positive"]:
                doc_freq[tok] = doc_freq.get(tok, 0) + 1

        scored: list[dict[str, Any]] = []
        for entry in prepared:
            row = entry["row"]
            code = entry["code"]
            # Tokens from the DTO fields THIS branch says it needs; fall back
            # to the full fact-token pool when the paths yield nothing.
            fact_tokens: set[str] = set()
            for path in str(row.get("required_dto_fields") or "").split(";"):
                path = path.strip()
                if path:
                    for value in _string_values(_dig(product_facts, path)):
                        if value.strip().lower() not in self._INTERNAL_LABELS:
                            fact_tokens |= _tokens(value)
            if not fact_tokens:
                fact_tokens = fallback_tokens

            if sibling_count > 1:
                positive = {
                    tok for tok in entry["positive"]
                    if doc_freq.get(tok, 0) * 2 <= sibling_count
                }
            else:
                positive = entry["positive"]
            negative = entry["negative"]
            residual = str(row.get("residual_other_flag") or "").strip().lower() == "true"
            score = float(len(positive & fact_tokens)) - float(len(negative & fact_tokens))

            # Give the verdict the node's full wording (label + terms), not just
            # the thresholds — it needs the ingredient words to know WHICH
            # ingredient the % condition is about.
            quant_conditions = " ; ".join(
                part for part in (
                    str(row.get("quantitative_conditions") or ""),
                    str(row.get("hard_conditions") or ""),
                ) if part.strip()
            )
            quant_text = " ; ".join(
                part for part in (
                    str(row.get("option_label_en") or ""),
                    str(row.get("positive_terms") or "").replace(";", " "),
                    quant_conditions,
                ) if part.strip()
            )
            verdict = _quantitative_verdict(quant_text, percentages) if quant_conditions else {
                "verdict": "neutral", "reason": "no_threshold_in_node",
            }
            if verdict["verdict"] == "satisfies":
                score += QUANT_BOOST
            elif verdict["verdict"] == "violates":
                score -= QUANT_PENALTY  # legal condition contradicted -> effectively out
            if residual:
                score = min(score, 0.0)  # residuals never win on wording

            scored.append({
                "code": code,
                "descr": str(row.get("option_label_en") or ""),
                "incl": str(row.get("positive_terms") or ""),
                "excl": str(row.get("negative_terms") or ""),
                "residual": residual,
                "score": round(score, 2),
                "quantitative_verdict": verdict,
            })

        # Elimination order: positive-scoring specific nodes first; residual
        # ("Other") nodes surface only when no specific sibling scored > 0.
        specific = [r for r in scored if not r["residual"]]
        residuals = [r for r in scored if r["residual"]]
        specific.sort(key=lambda r: r["score"], reverse=True)
        residuals.sort(key=lambda r: r["score"], reverse=True)
        if specific and specific[0]["score"] > 0:
            return specific + residuals
        return residuals + specific if residuals else specific

    # ---- weighted lexical rank + quantitative gate ------------------------
    def _lexical_rank(
        self,
        children: list[dict[str, Any]],
        facts: dict[str, list[str]],
        level: str,
        percentages: list[Any],
    ) -> list[dict[str, Any]]:
        weights = LEVEL_AXIS_WEIGHTS[level]
        # Per-token best weight: a token that appears in several axes must not
        # be scored once per axis — generic words ("prepared", "preserved")
        # otherwise pile up and outrank species-specific headings.
        token_weight: dict[str, float] = {}
        for axis in LEVEL_AXES[level]:
            axis_w = weights.get(axis, 1.0)
            for v in facts.get(axis, []):
                for tok in _tokens(v):
                    if axis_w > token_weight.get(tok, 0.0):
                        token_weight[tok] = axis_w
        all_terms = set(token_weight)

        # Sibling-IDF: a token carried by more than half of the siblings being
        # ranked cannot tell them apart ("prepared", "preserved", "frozen" …)
        # and must score zero — otherwise generic-word piles outrank the one
        # species-deciding word (octopus, cockles). Runtime counterpart of the
        # branch_index positive_terms idea; no hardcoded word list.
        node_term_sets = [
            (row, _tokens(row["descr"]) | _tokens(row["incl"]))
            for row in children
        ]
        doc_freq: dict[str, int] = {}
        for _, terms in node_term_sets:
            for tok in terms & all_terms:
                doc_freq[tok] = doc_freq.get(tok, 0) + 1
        sibling_count = len(children)
        discriminative_weight = {
            tok: weight
            for tok, weight in token_weight.items()
            if doc_freq.get(tok, 0) * 2 <= sibling_count
        }

        scored = []
        for row, node_terms in node_term_sets:
            excl_terms = _tokens(row["excl"])
            score = sum(
                discriminative_weight[tok]
                for tok in node_terms
                if tok in discriminative_weight
            )
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
        # code_driven by default (designer decision): the deterministic lexical
        # top-k is the stage answer; the LLM re-selector is opt-in only.
        if (os.environ.get("ASAP_STAGED_USE_LLM_SELECT", "0") or "").strip().lower() not in (
            "1", "true", "yes", "on",
        ):
            return [r["code"] for r in ranked[: self.keep_per_level]]
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

    def _trace(self, level: str, ranked: list[dict[str, Any]], selected: list[str], facts: dict[str, list[str]], status: str, engine: str = "cn_table") -> dict[str, Any]:
        return {
            "stage": level,
            "status": status,
            "engine": engine,
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
