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
import logging
import os
import re
from typing import Any
from sqlalchemy import bindparam, text

from db.db_session_manager import DbSessionManager

_LOGGER = logging.getLogger(__name__)

# AXIS_MAP — decision axis -> baseline ProductUnderstandingFacts field paths.
# Reads the embedded 2-lane: identity_lane (DistilledIdentityFacts.ToTrace) +
# composition_lane (CompositionLaneFacts.ToTrace). No separate composition_facts object under B.
CLASSIFICATION_AXIS_MAP: dict[str, list[str]] = {
    "ingredient_taxonomy": [
        "identity_hints.ingredient_class",
        "identity_hints.normalized_tariff_description",
        "identity_hints.identity_terms",
        # chapter_hint_terms are LLM hints ALREADY filtered to cn_chapter_index
        # vocabulary — the tariff-register words ("molluscs", "aquatic
        # invertebrates") that everyday-English identity no longer carries.
        # Same signal the router scores; pure wiring, no new hint source.
        "identity_hints.chapter_hint_terms",
        "composition_facts.principal_ingredient",
        "composition_facts.ingredient_classes",
    ],
    "product_form": [
        "identity_hints.food_form",
        "identity_hints.commercial_identity",
        "identity_hints.identity_terms",
        "identity_hints.chapter_hint_terms",
        "identity_hints.product_form_terms",
    ],
    "processing_state": [
        "identity_hints.processing_state",
        "identity_hints.processing_terms",
        "composition_facts.processing_state",
        "composition_facts.processing_terms",
        "composition_facts.contains_wrapper_or_dough",
        "composition_facts.contains_sauce_or_broth",
    ],
    "composition_percentage": [
        "identity_hints.composition_terms",
        "composition_facts.composition_terms",
        "composition_facts.ingredient_percentages",
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
# Decision-table semantics: a CONFIRMED code (all its legal conditions
# answered true by the bound DTO fields) outranks any lexical score;
# a violated one is out. Undecided falls back to lexical ranking.
DECISION_CONFIRM = 50.0
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
# "containing no common wheat flour" negates wheat/flour — CN wording uses
# bare "no X" as often as not/without (measured: 19021910 matched wheat
# products it explicitly excludes, costing the sibling "Other" the win).
_NEGATION_RE = re.compile(
    r"\b(?:not|no|excluding|without|other\s+than)\s+([a-z]+(?:\s+[a-z]+){0,2})", re.I)


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


_CONDITIONAL_CLAUSE_RE = re.compile(
    r"whether\s+or\s+not\s+\w+(?:\s+or\s+(?:otherwise\s+)?\w+)*", re.I,
)


def _tokens(text: str) -> set[str]:
    # "whether or not cooked" is a condition-irrelevant clause: neither the
    # node nor the product should score on its words (cooked/prepared).
    cleaned = _CONDITIONAL_CLAUSE_RE.sub(" ", str(text or "").lower())
    # len>=3 drops function words (or/of/in/by) that would otherwise pass the
    # sibling-IDF filter and score as fake "discriminative" matches.
    return {
        _stem(token)
        for token in _TOKEN.findall(cleaned)
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
        start_parents: list[str] | None = None,
    ) -> dict[str, Any]:
        facts = self._read_facts(product_facts)
        # chapter_hint_terms are HS2/heading-selection signals ("cereal
        # preparation", "edible vegetables"). Once the chapter is fixed they
        # are chapter-generic by construction, and measured to leak into deep
        # sibling groups (190410 took hs6 on cereal/prepared/product against
        # every noodle product). Deep levels rank on identity/composition only.
        # PATH-based exclusion (not value-based): a typed field may carry the
        # same word a hint carries ("molluscs") and must survive the cut.
        facts_deep = self._read_facts(
            product_facts,
            exclude_paths=("identity_hints.chapter_hint_terms",),
        )
        percentages = _dig(product_facts, "composition_facts.ingredient_percentages")
        percentages = percentages if isinstance(percentages, list) else []
        # start_parents: validator-issued second-pass scope (a chapter or a
        # deeper prefix) — same narrowing, different root. No other behavior
        # differences, so a reroute is exactly one more classify() call.
        if start_parents:
            parents = [_digits(c, limit=8) for c in start_parents if _digits(c)]
        else:
            parents = self._start_chapters(routing_context)
        if not parents:
            return {"ok": False, "error": "no_route_chapters", "candidates": [], "stages": []}
        chapter_scores = self._chapter_scores(routing_context)
        if start_parents and parents:
            chapter_scores = {parents[0][:2]: 100.0}

        use_branch_index = (os.environ.get("ASAP_USE_BRANCH_INDEX", "1") or "").strip().lower() not in (
            "0", "false", "no", "off",
        )
        # Parent confidence carried level to level: chapters start with the
        # router's scores; afterwards each selected code carries its own score.
        parent_scores: dict[str, float] = dict(chapter_scores)

        stages: list[dict[str, Any]] = []
        # Phase-0 observability: per-level score maps for path assembly, plus
        # recovery records — a child of a NON-top parent that outscores the
        # top parent's best child is the classifier disagreeing with the
        # router. Recorded only; selection is untouched (promotion is a
        # later, data-calibrated step).
        level_score_maps: dict[str, dict[str, float]] = {}
        recovery_candidates: list[dict[str, Any]] = []
        route_disagreements: list[dict[str, Any]] = []
        # chapter_hint_terms stay ON at hs4 (default): retiring them was
        # A/B-measured at staged-only hs4 36% -> 24% — the hints carry live
        # heading evidence ("noodles", "molluscs") alongside the chapter-
        # generic tails, and the typed fields alone do not yet replace them.
        # ASAP_STAGED_HINT_AT_HS4=0 re-runs the retirement experiment.
        hint_at_hs4 = (os.environ.get("ASAP_STAGED_HINT_AT_HS4", "1") or "").strip().lower() in (
            "1", "true", "yes", "on",
        )
        for level, prefix_len in LEVELS:
            if parents and prefix_len <= len(parents[0]):
                continue  # start_parents가 이 레벨보다 깊은 prefix면 건너뜀
            level_facts = facts if (level == "hs4" and hint_at_hs4) else facts_deep
            branch_rows = self._load_branch_rows(level, parents) if use_branch_index else ()
            if branch_rows:
                if len(branch_rows) == 1:  # pass-through branch: no decision to make
                    only = _digits(branch_rows[0].get("code"), limit=prefix_len)
                    stages.append(self._trace(level, [], [only], level_facts, "pass_through", engine="branch_index"))
                    parent_scores = {only: max(parent_scores.values(), default=0.0)}
                    parents = [only]
                    continue
                decisions_by_parent = {}
                if (os.environ.get("ASAP_STAGED_DECISION_TABLE", "1") or "").strip().lower() not in (
                    "0", "false", "no", "off",
                ):
                    try:
                        from agents.tools.branch_decision_evaluator import LoadBranchDecisions

                        decisions_by_parent = LoadBranchDecisions(level, tuple(parents))
                    except Exception:  # noqa: BLE001 — 사이드카 부재 = 계층 off
                        decisions_by_parent = {}
                predicates_by_code = {}
                if (os.environ.get("ASAP_STAGED_PREDICATES", "1") or "").strip().lower() not in (
                    "0", "false", "no", "off",
                ):
                    try:
                        from agents.tools.branch_predicate_evaluator import LoadBranchPredicates

                        predicates_by_code = LoadBranchPredicates(
                            level,
                            tuple(_digits(r.get("code"), limit=prefix_len) for r in branch_rows),
                        )
                    except Exception:  # noqa: BLE001 — sidecar 부재 = 계층 off
                        predicates_by_code = {}
                ranked = self._branch_rank(
                    branch_rows, product_facts, level_facts, percentages, prefix_len,
                    parent_order=list(parents),
                    parent_scores=parent_scores,
                    predicates_by_code=predicates_by_code,
                    decisions_by_parent=decisions_by_parent,
                )
            else:
                children = self._load_children(parents, prefix_len)
                if not children:
                    stages.append(self._trace(level, [], [], level_facts, "no_children"))
                    return {"ok": False, "error": f"no_children_at_{level}",
                            "candidates": [], "stages": stages}
                ranked = self._lexical_rank(children, level_facts, level, percentages)
            if level == "hs4" and chapter_scores and not branch_rows:
                # Lexical fallback path only: add the router chapter score.
                # The branch path encodes parent ranking hierarchically inside
                # _branch_rank (round-robin merge), so no raw-score bonus there.
                for row in ranked:
                    row["score"] = round(
                        row["score"] + chapter_scores.get(str(row["code"])[:2], 0.0), 2,
                    )
                ranked.sort(key=lambda r: r["score"], reverse=True)
            full_ranked = ranked
            level_score_maps[level] = {r["code"]: float(r["score"]) for r in full_ranked}
            if branch_rows and parent_scores:
                parent_len = prefix_len - 2
                top_parent = max(parent_scores, key=lambda c: parent_scores.get(c, 0.0))
                # recovery 판정 기준: 기본은 부스트 포함 점수(hs4 77% 최고기록
                # 구성). 원점수(score_raw) 판정은 recovery를 폭증시켜 validator
                # 남발을 유발했던 처방 — ASAP_RECOVERY_RAW=1로만 재실험한다.
                raw_mode = (os.environ.get("ASAP_RECOVERY_RAW", "0") or "0").strip() == "1"
                rscore = (lambda r: r.get("score_raw", r["score"])) if raw_mode else (
                    lambda r: r["score"])
                best_top_child = max(
                    (rscore(r) for r in full_ranked
                     if r["code"][:parent_len] == top_parent),
                    default=0.0,
                )
                level_recoveries = sorted(
                    (
                        r for r in full_ranked
                        if r["code"][:parent_len] != top_parent
                        and rscore(r) > 0
                        and rscore(r) >= best_top_child
                    ),
                    key=rscore, reverse=True,
                )[:5]
                for r in level_recoveries:
                    recovery_candidates.append({
                        "level": level,
                        "code": r["code"],
                        "descr": str(r.get("descr") or "")[:160],
                        "score": r["score"],
                        "parent": r["code"][:parent_len],
                        "parent_score": parent_scores.get(r["code"][:parent_len], 0.0),
                        "top_parent": top_parent,
                        "top_parent_best_child_score": best_top_child,
                        "matched_terms": r.get("matched", []),
                    })
                if level_recoveries:
                    route_disagreements.append({
                        "level": level,
                        "router_top_parent": top_parent,
                        "top_parent_best_child_score": best_top_child,
                        "evidence_top_code": level_recoveries[0]["code"],
                        "evidence_top_score": level_recoveries[0]["score"],
                    })
            ranked = ranked[: self.rank_top_k]
            selected = self._llm_select(ranked, level_facts, level)
            if not selected:  # deterministic fallback = top lexical
                selected = [ranked[0]["code"]]
            # Residual guarantee: real answers are majority "Other" nodes
            # (P4 autopsy ~11/20). A shallow one-word match on a specific
            # sibling must not evict every residual — reserve the last slot.
            if branch_rows and len(selected) >= 2:
                score_by_code = {r["code"]: r["score"] for r in full_ranked}
                residual_codes = {r["code"] for r in full_ranked if r.get("residual")}
                viable_residuals = [
                    r for r in full_ranked
                    if r.get("residual") and r["score"] > -QUANT_PENALTY / 2
                ]
                # The guarantee is per BRANCHING POINT: when a specific sibling
                # wins its group on wording alone, the elimination alternative
                # is that group's own "Other" — a residual selected under a
                # DIFFERENT parent must not satisfy the guarantee for it
                # (measured: 07102900 "Other" masked 07108059 while sweet
                # peppers 07108051 won the 071080 group by one token).
                top_code = max(selected, key=lambda c: score_by_code.get(c, 0.0))
                best_residual = None
                if score_by_code.get(top_code, 0.0) > 0:
                    group = top_code[:-2]
                    if not any(c in residual_codes and c[:-2] == group for c in selected):
                        best_residual = next(
                            (r for r in viable_residuals if r["code"][:-2] == group),
                            None,
                        )
                if best_residual is None and not any(c in residual_codes for c in selected):
                    best_residual = next(iter(viable_residuals), None)
                # Only evict a ZERO-evidence slot: the guarantee exists for the
                # "no sibling scored" case and must never push out a candidate
                # that earned positive evidence (measured: it evicted the
                # correct 1605 at 2.0 in favour of a 0.0 residual).
                if (
                    best_residual
                    and best_residual["code"] not in selected
                    and score_by_code.get(selected[-1], 0.0) <= 0.0
                ):
                    selected = [*selected[:-1], best_residual["code"]]
            stages.append(self._trace(
                level, ranked, selected, level_facts, "ok",
                engine="branch_index" if branch_rows else "cn_table",
            ))
            ranked_scores = {r["code"]: float(r["score"]) for r in ranked}
            parent_scores = {code: ranked_scores.get(code, 0.0) for code in selected}
            # Elimination promotion must PROPAGATE: a residual selected as
            # this level's top would otherwise re-lose the next-level merge
            # to a sibling with a higher raw score (measured: jjokgalbi won
            # hs4 with 1602 but hs6 followed 1601's children again). The
            # level's chosen top carries top parent authority downward.
            if selected:
                parent_scores[selected[0]] = max(parent_scores.values())
            parents = selected

        candidates = self._final_candidates(parents, top_k=top_k)
        # 최종 DTO의 score는 cn8 스테이지 점수를 그대로 싣는다 — 키가 없으면
        # 소비측(ClassificationCandidate 조립)이 기본 0.0으로 표시해 버린다.
        cn8_scores = level_score_maps.get("cn8", {})
        for cand in candidates:
            cand["score"] = cn8_scores.get(str(cand.get("cn8")), 0.0)
        paths: list[dict[str, Any]] = []
        for cand in candidates:
            cn8 = _digits(cand.get("cn8"), limit=8)
            if len(cn8) != 8:
                continue
            paths.append({
                "hs2": cn8[:2],
                "hs4": cn8[:4],
                "hs6": cn8[:6],
                "cn8": cn8,
                "level_scores": {
                    lvl: level_score_maps.get(lvl, {}).get(cn8[:width])
                    for lvl, width in (("hs4", 4), ("hs6", 6), ("cn8", 8))
                },
                "source": "normal",
            })
        return {
            "ok": bool(candidates),
            "error": "" if candidates else "no_cn8",
            "candidates": candidates,
            "stages": stages,
            "paths": paths,
            "recovery_candidates": recovery_candidates,
            "route_disagreements": route_disagreements,
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
    # Structural morphemes of DTO field names — never product vocabulary.
    _PATH_STRUCTURE_WORDS = frozenset({"contains", "is", "has", "or", "and"})


    def _read_facts(
        self,
        product_facts: dict[str, Any],
        exclude_paths: tuple[str, ...] = (),
    ) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for axis, paths in CLASSIFICATION_AXIS_MAP.items():
            vals: list[str] = []
            for path in paths:
                if path in exclude_paths:
                    continue
                raw = _dig(product_facts, path)
                if isinstance(raw, bool):
                    # A boolean answers the QUESTION its field name asks —
                    # "contains_sauce_or_broth: true" means the product has
                    # sauce/broth. Stringifying it put the token "true" into
                    # the axis (measured in 28 stages), which no CN wording
                    # can match. Translate True to the field's own semantic
                    # words; False asserts nothing lexical.
                    if raw:
                        leaf = path.rsplit(".", 1)[-1]
                        vals.extend(
                            word for word in leaf.split("_")
                            if word and word not in self._PATH_STRUCTURE_WORDS
                        )
                    continue
                vals.extend(
                    value
                    for value in _string_values(raw)
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
        # Router-EVIDENCED chapters only (score > 0), ranked order. The
        # bucket-scope allowed list is the recall boundary for the fallback
        # classifiers, but feeding the whole bucket into staged puts
        # zero-evidence junk siblings in the top-8 window (measured: 0709
        # fresh vegetables in a noodle product's top-3, chapter 67/97 tails).
        # Score-through routing already gives guardrailed answer chapters a
        # real score (pepper 07 = 28.0), so the tail adds noise, not recall.
        details = routing_context.get("candidate_chapter_details")
        if isinstance(details, list):
            for item in details:
                if not isinstance(item, dict):
                    continue
                ch = _digits(item.get("chapter"), limit=2)
                try:
                    score = float(item.get("score") or 0.0)
                except (TypeError, ValueError):
                    score = 0.0
                if len(ch) == 2 and score > 0 and ch not in chapters:
                    chapters.append(ch)
        route_values = (
            routing_context.get("allowed_hs2")
            or routing_context.get("candidate_hs2")
            or routing_context.get("candidate_chapters")
            or []
        )
        for c in route_values:
            if len(chapters) >= 5:
                break
            ch = _digits(c.get("chapter") if isinstance(c, dict) else c, limit=2)
            if len(ch) == 2 and ch not in chapters:
                chapters.append(ch)
        return chapters[:5]

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
        except Exception as error:  # noqa: BLE001 — narrowing must not break the pipeline
            # DB 오류가 조용히 '자식 없음'으로 위장되면 no_children_at_hs4로만 보인다.
            _LOGGER.warning("staged _load_children DB query failed: %s", error)
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
        except Exception as error:  # noqa: BLE001
            _LOGGER.warning("staged _final_candidates DB query failed: %s", error)
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
        predicates_by_code: dict[str, list[dict[str, Any]]] | None = None,
        decisions_by_parent: dict[str, dict[str, list[dict[str, Any]]]] | None = None,
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
                predicates_by_code=predicates_by_code or {},
                group_decisions=(decisions_by_parent or {}).get(parent) or {},
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

    # Fields whose tokens count as PROOF of a specific sibling's criterion.
    # chapter_hint_terms (routing signal) and composition_terms (page-text
    # grab bag, OCR-prone) are deliberately excluded: a stray token from
    # them must not certify a branch (measured: 1601 "product", 1603 "fish"
    # kept the correct residual 1602 out for a pork-rib product).
    _PROOF_FIELD_PATHS = (
        "identity_hints.identity_terms",
        "identity_hints.normalized_tariff_description",
        "identity_hints.translated_product_name",
        "identity_hints.ingredient_class",
        "identity_hints.food_form",
        "identity_hints.processing_state",
        "identity_hints.product_form_terms",
        "composition_facts.principal_ingredient",
        "composition_facts.ingredient_classes",
    )

    def _proof_tokens(self, product_facts: dict[str, Any]) -> set[str]:
        out: set[str] = set()
        for path in self._PROOF_FIELD_PATHS:
            for value in _string_values(_dig(product_facts, path)):
                if value.strip().lower() not in self._INTERNAL_LABELS:
                    out |= _tokens(value)
        return out

    def _rank_sibling_group(
        self,
        items: list[dict[str, Any]],
        product_facts: dict[str, Any],
        fallback_tokens: set[str],
        percentages: list[Any],
        predicates_by_code: dict[str, list[dict[str, Any]]] | None = None,
        group_decisions: dict[str, list[dict[str, Any]]] | None = None,
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

        # Tie-breaker signal: the product's FORM words from the dedicated
        # form fields only (product_form_terms/food_form) — the mixed axis
        # pool also carries material words ("flour") that would re-pollute
        # the very tie this is meant to break (1901 flour-preparations vs
        # 1902 noodles, measured 2.0 = 2.0 -> code order picked 1901).
        form_tokens: set[str] = set()
        for path in ("identity_hints.product_form_terms", "identity_hints.food_form"):
            for value in _string_values(_dig(product_facts, path)):
                if value.strip().lower() in self._INTERNAL_LABELS:
                    continue
                # Single-word terms only: multi-word marketing phrases token-
                # split into false form evidence — "meal kit" put 'meal' into
                # form and collided with 1901's "flour, groats, MEAL" wording,
                # re-tying the very tie this breaker exists to break (measured).
                if " " in value.strip():
                    continue
                form_tokens |= _tokens(value)

        scored: list[dict[str, Any]] = []
        for entry in prepared:
            row = entry["row"]
            code = entry["code"]
            # Tokens from the DTO fields THIS branch says it needs; fall back
            # to the full fact-token pool when the paths yield nothing.
            fact_tokens: set[str] = set()
            # Targeted evidence is gated OFF by default: measured net-negative
            # while identity quality is weak — (a) siblings with/without
            # required_dto_fields compete on different-sized evidence pools
            # (0706 'edible,root' from the full pool beat 0710 'frozen' from
            # its narrow fields), (b) narrow fields cut the chapter_hint
            # lifeline when identity misses the species word (1605 matched
            # nothing while 1601 took hs4 on the stray token 'product').
            # Re-enable for A/B once typed identity fields are actually
            # filled: ASAP_STAGED_TARGETED_DTO=1.
            if (os.environ.get("ASAP_STAGED_TARGETED_DTO", "0") or "").strip().lower() in (
                "1", "true", "yes", "on",
            ):
                for path in str(row.get("required_dto_fields") or "").split(";"):
                    path = path.strip()
                    if not path:
                        continue
                    for value in _string_values(_dig(product_facts, path)):
                        if value.strip().lower() not in self._INTERNAL_LABELS:
                            fact_tokens |= _tokens(value)
            if not fact_tokens:
                fact_tokens = fallback_tokens

            negative = entry["negative"]
            residual = str(row.get("residual_other_flag") or "").strip().lower() == "true"
            if sibling_count > 1:
                positive = {
                    tok for tok in entry["positive"]
                    if doc_freq.get(tok, 0) * 2 <= sibling_count
                }
                score = float(len(positive & fact_tokens)) - float(len(negative & fact_tokens))
            else:
                # A single child is NOT a decision: it inherits its parent's
                # whole wording with no sibling-IDF discipline, so re-scoring
                # it re-earns the same tokens the parent already won at the
                # previous level (measured: 160300 "Extracts ... molluscs,
                # aquatic invertebrates" echoed 3.0 and outranked the true
                # species node 160555 "Octopus"). Rank it on parent
                # confidence alone; only the quantitative gate still applies.
                positive = entry["positive"]
                score = 0.0

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
            # Recovery observation compares RAW evidence (lexical + quant)
            # — a predicate/decision boost on a rival sibling must not
            # silence the dissent record (measured: 16041991's frozen boost
            # pushed 0304's recovery below threshold, muting the validator).
            score_raw = score
            # Compiled predicates (sidecar): three-valued, ADDITIVE over the
            # lexical score — true boosts, violated hard-blocks, unknown is 0.
            predicate_results: list[dict[str, str]] = []
            group_predicates = (predicates_by_code or {}).get(code)
            if group_predicates:
                from agents.tools.branch_predicate_evaluator import EvaluatePredicates

                pred_delta, predicate_results = EvaluatePredicates(
                    group_predicates, fact_tokens, product_facts,
                )
                score += pred_delta
            decision_status = ""
            decision_detail: list[dict[str, str]] = []
            code_conditions = (group_decisions or {}).get(code)
            if code_conditions:
                from agents.tools.branch_decision_evaluator import EvaluateCodeDecision

                decision_status, decision_detail = EvaluateCodeDecision(
                    code_conditions, product_facts, fact_tokens, percentages,
                    _quantitative_verdict,
                )
                if decision_status == "confirmed":
                    score += DECISION_CONFIRM
                elif decision_status == "violated":
                    score -= QUANT_PENALTY
            if residual:
                score = min(score, 0.0)  # residuals never win on wording
                score_raw = min(score_raw, 0.0)

            scored.append({
                "code": code,
                "descr": str(row.get("option_label_en") or ""),
                "incl": str(row.get("positive_terms") or ""),
                "excl": str(row.get("negative_terms") or ""),
                "residual": residual,
                "score": round(score, 2),
                "score_raw": round(score_raw, 2),
                # IDF-filtered positive only: a form word every sibling shares
                # cannot break their tie either.
                "form_hits": len(positive & form_tokens) if sibling_count > 1 else 0,
                "matched": sorted(positive & fact_tokens)[:6],
                "neg_matched": sorted(negative & fact_tokens)[:4],
                "predicate_results": predicate_results,
                "decision": decision_status,
                "decision_detail": decision_detail,
                "quantitative_verdict": verdict,
            })

        # Elimination order: positive-scoring specific nodes first; residual
        # ("Other") nodes surface only when no specific sibling scored > 0.
        specific = [r for r in scored if not r["residual"]]
        residuals = [r for r in scored if r["residual"]]
        # Equal lexical scores fall back to product-form agreement, not code
        # order: which sibling the product's FORM points at is evidence; code
        # order is not.
        specific.sort(key=lambda r: (r["score"], r["form_hits"]), reverse=True)
        residuals.sort(key=lambda r: r["score"], reverse=True)
        # DECISION short-circuit (designer model): inside a branching point,
        # an answered condition IS the selection — a confirmed code heads the
        # group regardless of lexical order; several confirmed codes follow
        # the LEGAL check order (seq). Parent-vs-parent merging stays
        # lexicographic outside the group, so a mis-confirmed code in a weak
        # chapter still cannot hijack the product (measured: 2104 soup).
        # 결정 단락(그룹 내 confirmed 즉시 선두)은 확정 신호의 정밀도가
        # 확보돼야 이득이다 — 실측: 정 7/오 33(17%) 상태로 켜면 2103/2104
        # 오발동이 부모 병합까지 뒤집어 hs2 86→73%. 순도 개선(typed 제한)
        # 후 ASAP_STAGED_SHORT_CIRCUIT=1로 재도전한다. 기본 OFF일 때도
        # confirmed는 +50 점수로 계속 싸운다(77% 최고기록 구성).
        short_circuit = (os.environ.get("ASAP_STAGED_SHORT_CIRCUIT", "0") or "0").strip() == "1"
        confirmed_entries = [r for r in scored if r.get("decision") == "confirmed"] if short_circuit else []
        if confirmed_entries:
            def _legal_seq(entry: dict[str, Any]) -> int:
                rows_ = (group_decisions or {}).get(entry["code"]) or []
                return min((int(row.get("seq") or 0) for row in rows_), default=999)
            confirmed_entries.sort(key=lambda r: (_legal_seq(r), -r["score"]))
            confirmed_codes = {r["code"] for r in confirmed_entries}
            rest = [r for r in scored if r["code"] not in confirmed_codes]
            rest_specific = [r for r in rest if not r["residual"]]
            rest_residuals = [r for r in rest if r["residual"]]
            rest_specific.sort(key=lambda r: (r["score"], r["form_hits"]), reverse=True)
            rest_residuals.sort(key=lambda r: r["score"], reverse=True)
            return confirmed_entries + rest_specific + rest_residuals

        # PROOF-based elimination (tariff logic): a specific line only beats
        # "Other" when its criterion is PROVEN — a predicate answered true,
        # or its matched wording comes from the product's semantic identity
        # fields. A stray pool token is a match, not a proof. When no
        # sibling proves its criterion, the product belongs to the group's
        # residual by elimination — that is what "Other" means.
        proof = self._proof_tokens(product_facts)
        viable_residuals = [r for r in residuals if r["score"] > -QUANT_PENALTY / 2]
        if viable_residuals and specific:
            def _proven(r: dict[str, Any]) -> bool:
                if r.get("decision") == "confirmed":
                    return True
                # Only a FIELD-answered predicate (verdict "true") certifies a
                # branch. true_pool is a broad-pool match — the same floating-
                # token risk the proof rule exists to guard against — so it is
                # not proof on its own; it still needs a semantic-field match.
                if any(
                    pr.get("verdict") == "true"
                    for pr in r.get("predicate_results") or []
                ):
                    return True
                return bool(set(r.get("matched") or []) & proof)
            if not any(_proven(r) for r in specific if r["score"] > 0):
                return viable_residuals + specific + [
                    r for r in residuals if r not in viable_residuals
                ]
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
            from agents.candiate_classfier import build_runtime_adapter
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

    def validate_selection(
        self,
        *,
        staged: dict[str, Any],
        product_facts: dict[str, Any],
        routing_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Closed-choice final validation over the EXISTING result.

        The LLM may only (a) keep the current top path, (b) promote one of
        the RECORDED recovery candidates, or (c) reroute into one of the
        router's own scored chapters. It cannot invent codes; every option it
        sees came from deterministic evidence, so its authority is a veto,
        not a generator. Fires only on recorded disagreement signals.
        """
        recoveries = staged.get("recovery_candidates") or []
        paths = staged.get("paths") or []
        if not paths:
            return {"verdict": "keep", "fired": False, "reason": "no_paths"}
        top_chapter = str(paths[0].get("hs2") or "")
        chapter_options = [
            {"chapter": str(d.get("chapter")), "score": d.get("score")}
            for d in (routing_context.get("candidate_chapter_details") or [])
            if isinstance(d, dict) and float(d.get("score") or 0) > 0
            and str(d.get("chapter")) != top_chapter
        ][:6]
        if not recoveries:
            # Recorded dissent is the firing signal; scored alternate chapters
            # alone are normal routing spread, not disagreement.
            return {"verdict": "keep", "fired": False, "reason": "no_disagreement_signal"}

        ih = product_facts.get("identity_hints") or {}
        identity_view = {
            "product": ih.get("translated_product_name") or "",
            "description": ih.get("normalized_tariff_description") or "",
            "identity_terms": (ih.get("identity_terms") or [])[:8],
            "ingredient_class": ih.get("ingredient_class") or "",
            "food_form": ih.get("food_form") or "",
            "processing_state": ih.get("processing_state") or "",
        }
        current_view = [
            {"cn8": c.get("cn8"), "desc": str(c.get("descr") or c.get("description") or "")[:160]}
            for c in (staged.get("candidates") or [])[:3]
        ]
        # 기록은 전부 blackboard에 남기되, 판사에게는 강한 이의만 보인다 —
        # 1점짜리 약한 recovery가 대량으로 제시되면 LLM 편차가 그대로
        # 결과 분산이 된다 (실측: r9 런에서 override 15건 역대 최다).
        strongest = sorted(
            recoveries, key=lambda r: float(r.get("score") or 0.0), reverse=True,
        )[:3]
        recovery_view = [
            {"level": r.get("level"), "code": r.get("code"),
             "desc": str(r.get("descr") or "")[:160],
             "evidence": r.get("matched_terms") or []}
            for r in strongest
        ]
        prompt_lines = [
            "A staged EU customs classifier proposed candidates for this product.",
            "Product identity:",
            json.dumps(identity_view, ensure_ascii=False),
            "Current candidates (in ranked order):",
            json.dumps(current_view, ensure_ascii=False),
            "Recorded dissenting candidates (stronger evidence under a non-top parent):",
            json.dumps(recovery_view, ensure_ascii=False),
            "Other router-scored chapters:",
            json.dumps(chapter_options, ensure_ascii=False),
            "Decision rule (strict order):",
            "1) State what the product IS (its essential character) from the identity.",
            "2) If candidate #1's description can plausibly describe that thing: keep.",
            "3) Else if ANOTHER current candidate describes it: promote_candidate.",
            "4) Else if a dissenting candidate describes it: promote_recovery.",
            "5) If the right HEADING is visible among current candidates but none of its",
            "   listed lines fits (e.g. every line excludes this product), answer narrow",
            "   with that 4-digit heading to re-search inside it.",
            "6) reroute is a LAST resort, only when NO listed candidate or heading can",
            "   describe the product at all.",
            "GIR 3(b): a complete product is classified by its essential character;",
            "accompanying sauces, broths or seasonings mentioned in the text do not",
            "determine the classification of a complete dish.",
            "Return ONE JSON object only:",
            '{"verdict":"keep"} or {"verdict":"promote_candidate","cn8":"<cn8 from current list>"}',
            'or {"verdict":"promote_recovery","code":"<code from dissenting list>"}',
            'or {"verdict":"narrow","heading":"<4-digit heading of a current candidate>"}',
            'or {"verdict":"reroute","chapter":"<chapter from list>"} - plus "reason":"<short>".',
        ]
        try:
            from bussiness_logic.bridge.schema import LlmRequest, LlmGenerationOptions

            resp = self._get_adapter().Generate(
                LlmRequest(
                    user_prompt="\n".join(prompt_lines),
                    system_prompt=(
                        "You validate EU customs classification results. Choose only from the "
                        "given options. Output one JSON object only."
                    ),
                    generation_options=LlmGenerationOptions(
                        temperature=0,
                        max_tokens=int(os.environ.get("ASAP_STAGED_LLM_MAX_TOKENS", "512")),
                    ),
                )
            )
            parsed = _extract_json(resp.generatedText)
        except Exception as error:  # noqa: BLE001 - validation must never break the pipeline
            return {"verdict": "keep", "fired": True, "reason": f"llm_error:{type(error).__name__}"}

        verdict = str(parsed.get("verdict") or "keep").strip()
        reason = str(parsed.get("reason") or "")[:200]
        if verdict == "promote_candidate":
            cn8 = _digits(parsed.get("cn8"), limit=8)
            if any(_digits(c.get("cn8"), limit=8) == cn8 for c in current_view if isinstance(c, dict)):
                return {"verdict": verdict, "cn8": cn8, "fired": True, "reason": reason}
        if verdict == "promote_recovery":
            code = _digits(parsed.get("code"), limit=8)
            if any(_digits(r.get("code"), limit=8) == code for r in recoveries):
                return {"verdict": verdict, "code": code, "fired": True, "reason": reason}
        elif verdict == "narrow":
            heading = _digits(parsed.get("heading"), limit=4)
            candidate_headings = {
                _digits(c.get("cn8"), limit=8)[:4] for c in current_view if isinstance(c, dict)
            }
            if len(heading) == 4 and heading in candidate_headings:
                return {"verdict": verdict, "heading": heading, "fired": True, "reason": reason}
        elif verdict == "reroute":
            chapter = _digits(parsed.get("chapter"), limit=2)
            if any(o["chapter"] == chapter for o in chapter_options):
                return {"verdict": verdict, "chapter": chapter, "fired": True, "reason": reason}
        return {"verdict": "keep", "fired": True, "reason": reason or "kept"}

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
                    "matched_terms": r.get("matched", []),
                    "negative_matched_terms": r.get("neg_matched", []),
                    "predicate_results": r.get("predicate_results", []),
                    "decision": r.get("decision", ""),
                    "decision_detail": r.get("decision_detail", []),
                    "quantitative_verdict": (r.get("quantitative_verdict") or {}).get("verdict", "neutral"),
                }
                for r in ranked[:8]
            ],
            "selected_codes": selected,
            "missing_facts": [a for a in LEVEL_AXES[level] if not facts.get(a)],
        }
