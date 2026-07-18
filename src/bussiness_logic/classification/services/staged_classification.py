"""StagedClassificationTool (baseline-adapted).

Controller-driven HS4 -> HS6 -> CN8 *narrowing* classifier. Unlike a one-shot
full-cn_table search, each level only ranks the *children* of the codes selected
at the previous level, so the right node cannot be drowned out by unrelated
chapters.

Baseline building blocks (no dependency on the removed ``llm_classifier``):
  - cn_table children  : managed session-based query via ``DbSessionManager``
  - LLM validation     : shared ``bussiness_logic.bridge.runtime_adapter`` RuntimeAdapter

Reads baseline ProductUnderstandingFacts / RoutingContext shaped blackboard dicts. Returns compact
per-stage payloads so ``classification_stage_results`` on the blackboard can
explain why HS4/HS6/CN8 were chosen. Degrades gracefully (never raises).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
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
        "composition_facts.processing_state",
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
# 답한 조건의 부분 지지 — 확정(typed 필수)이 막혀도 "법조문 조건에 true로
# 답했다"는 증거는 술어 true(+3)와 동급 가산. all-or-nothing이던 결정층이
# lexical 1점 잡음에 정답을 내주던 구멍의 처방 (칼국수 1902 실측: 두 런
# 모두 조건 true인데 지각 잡음 1점 차로 승패가 갈림). ASAP_DECISION_TRUE_SUPPORT=0 복귀.
DECISION_TRUE_SUPPORT = 3.0
# [P3-b] 상태 arm 어휘 — dash 계층이 그룹을 상태로 분할할 때 쓰는 전형
# 상태어(qualifier 상태-모순 자격 심사 전용, 이 밖의 qualifier 값은 심사
# 불참). 스템 표기.
_STATE_ARM_LEXICON = frozenset({
    "frozen", "fresh", "chilled", "live", "dried", "dehydrated", "salted",
    "brine", "smoked", "cooked", "uncooked", "boiled", "steamed", "raw",
})
# [7회차-1 FORMSET] 형태 arm 어휘 — 컴파일러 _FORM_LEXICON과 동일 집합
# (physical_form 패턴 실소유분만). FORMSET 라벨 집합의 모순 자격 심사
# 전용 — 감점·가산 없음, 상태 게이트와 같은 자격 박탈 계보.
_FORM_ARM_LEXICON = frozenset({
    "whole", "broken", "powder", "granule", "flake", "pellet", "paste",
    "liquid", "solid", "sheet", "plate", "bar", "rod", "tube", "pipe",
})
# [8회차-4] 재질 arm 어휘 — 컴파일러 _MATERIAL_LEXICON과 동일 집합
# (비식품 재질만 — 식품 재질은 함유 조건 지대라 모순 심사 불참)
_MATERIAL_ARM_LEXICON = frozenset({
    "steel", "iron", "aluminium", "copper", "nickel", "zinc", "tin",
    "lead", "plastic", "rubber", "wood", "paper", "glass", "ceramic",
    "cotton", "wool", "silk", "textile", "leather", "stone",
})
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
    # [9회차 [2]] 교차참조 배제절은 부정이 아니다 — 'other than pencils
    # of heading 9608'은 코드 간 경계 참조(그 heading의 물품)이지 상품
    # 어휘의 부정이 아니다. heading/chapter+코드 숫자가 실린 절을 부정
    # 수확 전에 제거 (9609가 자기 정체어 pencil로 0점 되던 실측 처방 —
    # 문법 연산, 규칙 대장 등재).
    cleaned = re.sub(
        r"(?:other\s+than|excluding|except)[^,;.()]*"
        r"(?:heading|chapter)\s*\d{2,4}[^,;.()]*",
        " ", cleaned)
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
        aliases = p.get("term_aliases")
        term_candidates = [term]
        if isinstance(aliases, list):
            term_candidates.extend(str(alias) for alias in aliases if str(alias).strip())
        if pct is not None and any(_tokens(candidate) & node_tokens for candidate in term_candidates):
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


_BTI_RECALL_CACHE: dict | None = None


def _bti_recall_index() -> dict:
    """컴파일 시점 빌드된 BM25 인덱스(DB/artifacts/bti_recall_index.json).

    부재 = 소환층 전체 no-op. 코퍼스 고정 — 런타임은 사칙연산만(결정론).
    """
    global _BTI_RECALL_CACHE
    if _BTI_RECALL_CACHE is None:
        import pathlib
        try:
            path = (pathlib.Path(__file__).resolve().parents[3]
                    ).parent / "DB" / "artifacts" / "bti_recall_index.json"
            _BTI_RECALL_CACHE = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            _BTI_RECALL_CACHE = {}
    return _BTI_RECALL_CACHE


def _bti_summon(scope_prefixes: list[str], q_primary: set, q_all: set,
                cut: int, existing: set) -> dict | None:
    """[7회차-3] BTI 후보 소환 — BM25 추림 + 이산 발동 (스펙 확정판).

    scope_prefixes: '그 단계 진입 시점의 생존 후보 접두 집합'(복수 —
      hs4 stall은 allowed_hs2 전체, 이하는 생존 상위 코드들. 필수 1)
    q_primary: 법정 어휘 병기분 우선 쿼리(term_bridge EN 병기·term_aliases·
      NTD·identity 영문 — 필수 2. 서명에 매치 실물로 남긴다)
    q_all: q_primary + raw DTO 토큰(보조 — 한글은 영문 코퍼스와 교차 0)
    cut: stall 레벨 자릿수만 소비(staged narrowing 주권 — 요구 3)
    existing: 현행 트리 실존 절단 코드 집합(개정 시차 — 요구 5)

    역할 격리(설계자 확정): BM25는 후보 사건 상위 N **추림 전용**이다.
    발동 판정은 이산 요건만 — ①공유 '구문 전 토큰 일치' 사건 수 k≥2
    (ASAP_BTI_K, 민감도 표는 k축만) ②절단 코드 반례 0. BM25 점수는 판정
    입력이 될 수 없다(점수 임계 발동 금지 — 튜닝 손잡이 차단). 인덱스의
    컴파일 시점 빌드는 '사전 각인 금지'와 무모순 — 금지 대상은 판례→코드
    매핑 각인이고 인덱스는 검색 구조다. 오확정 지대는 소환이 아니라 강등
    장치(D3 백과 상한·상태 모순·typed 게이트)의 몫(요구 6 의존 관계).
    산출은 입장권+지지까지 — 확정 자격 없음.
    """
    idx = _bti_recall_index()
    cases = idx.get("cases") or []
    if not cases or not q_all:
        return None
    df = idx.get("df") or {}
    n_docs = float(idx.get("n_docs") or 1)
    avg_len = float(idx.get("avg_len") or 1.0)
    import math
    k1, b = 1.2, 0.75
    scored = []
    for i, c in enumerate(cases):
        cn8 = str(c.get("cn8") or "")
        if not any(cn8.startswith(p2) for p2 in scope_prefixes):
            continue  # 경계 밖 판례는 조회 자체 금지(납치 원천 차단)
        toks = c.get("toks") or []
        overlap = [t for t in toks if t in q_all]
        if not overlap:
            continue
        dl = len(toks) or 1
        score = 0.0
        for t in overlap:
            idf = math.log(1.0 + (n_docs - df.get(t, 0) + 0.5)
                           / (df.get(t, 0) + 0.5))
            score += idf * (k1 + 1) / (1 + k1 * (1 - b + b * dl / avg_len))
        scored.append((-score, i, cn8[:cut], c))
    if not scored:
        # [기록 의무화 07-18 — 메인 그래프트 재이식] 침묵도 근거다 —
        # 시도 사실·사유 서명(UI 노출·감사, 판정 불변: code=""는 발동 아님).
        return {"code": "", "refs": [], "matched": [], "distribution": {},
                "silence": "no_lexical_overlap"}
    scored.sort()
    shortlist = scored[:20]  # 추림 전용 — 이하 판정에 score 불참
    # 이산 발동: 구문 '전 토큰' 동시 존재 사건만 (부분 토큰 잡음 차단 —
    # _phrase_sets 계보). 매치 구문은 서명 실물.
    hits: list[tuple[str, dict, list[str]]] = []
    for _s, _i, code_c, c in shortlist:
        full = [ph for ph in (c.get("phrases") or [])
                if ph and all(t in q_all for t in ph.split())]
        if full:
            hits.append((code_c, c, full))
    if not hits:
        return {"code": "", "refs": [], "matched": [], "distribution": {},
                "silence": "no_phrase_match",
                "shortlist_n": len(shortlist)}  # 침묵 — 공유 구문 일치 사건 0
    dist: dict[str, int] = {}
    for code_c, _c, _f in hits:
        dist[code_c] = dist.get(code_c, 0) + 1
    # [기록 의무화 — 메인 그래프트 재이식] 침묵 경로도 근거 판례(refs)·
    # 매치 구문 서명 — 어떤 사건이 분포를 만들었는지가 UI·감사 실물.
    refs = list(dict.fromkeys(c["ref"] for _cc, c, _f in hits))
    phrases = sorted({ph for _cc, _c, full in hits for ph in full})[:6]
    matched = sorted({t for ph in phrases for t in ph.split()})[:8]
    if len(dist) != 1:
        return {"code": "", "refs": refs[:4], "matched": matched,
                "phrases": phrases, "distribution": dist,
                "silence": "distribution_split"}  # 반례 존재 — 유보(C안 몫)
    code_w = next(iter(dist))
    if existing and code_w not in existing:
        return {"code": "", "refs": refs[:4], "matched": matched,
                "phrases": phrases, "distribution": dist,
                "not_in_tree": code_w,
                "silence": "not_in_tree"}  # 실존 검증 실패(개정 시차) — 유보
    try:
        k_min = int((os.environ.get("ASAP_BTI_K", "2") or "2").strip())
    except ValueError:
        k_min = 2
    if len(refs) < k_min:
        return {"code": "", "refs": refs[:4], "matched": matched,
                "phrases": phrases, "distribution": dist, "k": len(refs),
                "silence": "k_below_min"}  # 침묵 규율 — k 하향 금지(기본 2)
    return {"code": code_w, "refs": refs[:4], "matched": matched,
            "phrases": phrases, "k": len(refs),
            "primary_matched": sorted(
                {t for t in matched if t in q_primary})[:6],
            "counter": 0, "distribution": dist,
            "shortlist_n": len(shortlist)}


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
        # 조상 조건 위반 상속: 부모 코드가 결정 조건 위반이면 그 자식들은
        # 후보 자격이 없다 (법리: "Stuffed pasta" 위반 제품이 그 하위
        # 19022091 'Cooked'로 안착하던 실측 — 떡볶이·모둠나물면).
        # ASAP_ANCESTOR_INHERIT=0 복귀.
        ancestor_violated: set[str] = set()
        # Phase-0 observability: per-level score maps for path assembly, plus
        # recovery records — a child of a NON-top parent that outscores the
        # top parent's best child is the classifier disagreeing with the
        # router. Recorded only; selection is untouched (promotion is a
        # later, data-calibrated step).
        level_score_maps: dict[str, dict[str, float]] = {}
        recovery_candidates: list[dict[str, Any]] = []
        route_disagreements: list[dict[str, Any]] = []
        merge_gate_observations: list[dict[str, Any]] = []
        bti_summons: list[dict[str, Any]] = []
        # [10회차-1A] hs4 판별 축 지도 — 최종 병합의 정체 직격 서열 판정용
        _hs4_axis: dict[str, str] = {}
        # [7회차-2 G1] 라우터 신뢰 게이트 — 창밖 회수 (조건부 승인 반영).
        # 부검 실측: 병합 유실 16건 중 11건이 시작 창 [:5] 컷으로 정답
        # 챕터 미스캔(볼펜 지각·vocab 양존인데 0회). 기본 observe(관측만),
        # ASAP_ROUTER_TRUST_GATE=1 ON(입장권 추가)/0 OFF. ON 실험은 비식품
        # 실험장 + 22캐시·coi50 기준선 유지 조건.
        _rt_gate = (os.environ.get(
            "ASAP_ROUTER_TRUST_GATE", "observe") or "observe").strip().lower()
        router_trust_obs: list[dict[str, Any]] = []
        # 직격 어휘 = 백과 '제목'+상업 정체만 — 본문 서술 토큰은 오동의
        # 오염원(탐폰→'Tampon Run' 비디오게임 실측)이라 불참.
        # lane 확정(오염 실측 반영): identity_hints.commercial_identity는
        # 백과 '본문 요약' 성격이라 오동의를 그대로 승계한다(탐폰
        # ih.ci='video game' 실측). 원문 직역(translated_product_name)과
        # 백과 '제목'(distilled source_titles/commercial_identity)만 소비.
        _rt_title_toks: set = set()
        for _p_t in ("identity_hints.translated_product_name",
                     "distilled_identity.commercial_identity",
                     "distilled_identity.source_titles"):
            for _v_t in _string_values(_dig(product_facts, _p_t)):
                _rt_title_toks |= {t_t for t_t in _tokens(_v_t)
                                   if t_t.isascii()}
        _RT_GENERIC = frozenset({
            "other", "article", "part", "similar", "product", "products",
            "preparation", "accessory", "material", "the", "and", "for"})
        _rt_title_toks -= _RT_GENERIC
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
                        from bussiness_logic.classification.rules.branch_decision_evaluator import LoadBranchDecisions

                        decisions_by_parent = LoadBranchDecisions(level, tuple(parents))
                    except Exception:  # noqa: BLE001 — 사이드카 부재 = 계층 off
                        decisions_by_parent = {}
                    if level == "hs4":
                        for _p_ax, _codes_ax in (decisions_by_parent or {}).items():
                            for _c_ax, _rows_ax in (_codes_ax or {}).items():
                                for _r_ax in _rows_ax:
                                    if str(_r_ax.get("role")) == "discriminator":
                                        _hs4_axis.setdefault(
                                            str(_c_ax),
                                            str(_r_ax.get("cond_type") or ""))
                                        break
                predicates_by_code = {}
                if (os.environ.get("ASAP_STAGED_PREDICATES", "1") or "").strip().lower() not in (
                    "0", "false", "no", "off",
                ):
                    try:
                        from bussiness_logic.classification.rules.branch_predicate_evaluator import LoadBranchPredicates

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
                # [관측] 병합 게이트 observe 기록 수거 (순위 무영향 —
                # 정렬로 부착 엔트리 위치가 바뀔 수 있어 전 엔트리 스캔)
                for _e_obs in ranked:
                    _obs = _e_obs.pop("_merge_gate_obs", None)
                    if _obs:
                        merge_gate_observations.append({"level": level, **_obs})
                # [7회차-3] BTI 후보 소환 — 발동은 '해당 단계 전원 증거 0'
                # (stall)일 때만. scope=현 부모 접두 집합(후보 풀 잠금),
                # 판례 결정번호는 이 레벨 자릿수만 소비(staged 주권), 소환
                # 코드는 현행 분기(branch rows) 실존 검증(판례 개정 시차).
                # 산출 = 입장권(다음 병합 참여)뿐 — 지지는 기존 판례 행
                # (+3), 서열은 기존 기제·A 3중 전제. ASAP_BTI_RECALL=0 복귀.
                if ((os.environ.get("ASAP_BTI_RECALL", "1") or "1").strip()
                        != "0" and ranked):
                    def _no_evidence(e2: dict[str, Any]) -> bool:
                        if float(e2.get("score") or 0.0) > 0:
                            return False
                        if e2.get("decision") == "confirmed":
                            return False
                        if any(d2.get("verdict") == "true"
                               for d2 in e2.get("decision_detail") or []):
                            return False
                        return not any(
                            pr2.get("verdict") == "true"
                            for pr2 in e2.get("predicate_results") or [])
                    if all(_no_evidence(e2) for e2 in ranked):
                        q_toks: set = set()
                        for vals2 in level_facts.values():
                            for v2 in vals2:
                                q_toks |= _tokens(v2)
                        # [필수 2] 법정 어휘 병기분 우선 쿼리 — term_bridge
                        # 산출(EN 병기·term_aliases)+NTD+identity 영문.
                        # raw 한글 fact만으로는 유럽 판례와 교차 0([A]
                        # 자연발동 0 실측) — Track 2 사전 개선이 소환
                        # 재현율로 연동되는 구조.
                        q_pri: set = set()
                        for e3 in (_dig(product_facts,
                                        "composition_facts.ingredient_entries")
                                   or []):
                            if not isinstance(e3, dict):
                                continue
                            for a3 in (e3.get("term_aliases") or []):
                                q_pri |= _tokens(a3)
                            nm3 = str(e3.get("ingredient_name") or "")
                            if " / " in nm3:  # 원문 / EN 병기의 EN부
                                q_pri |= _tokens(nm3.split(" / ", 1)[1])
                        for p3 in ("identity_hints.normalized_tariff_description",
                                   "identity_hints.identity_terms"):
                            for v3 in _string_values(_dig(product_facts, p3)):
                                q_pri |= {t3 for t3 in _tokens(v3)
                                          if t3.isascii()}
                        # [필수 1] scope = 그 단계 진입 시점의 생존 후보
                        # 접두 집합 — hs4 stall은 라우터 allowed 전체(시작
                        # 창 [:5] 락인을 소환이 상속하면 회수력 반감),
                        # 이하는 생존 상위 코드들.
                        if level == "hs4":
                            scope3 = [
                                _digits(c3.get("chapter")
                                        if isinstance(c3, dict) else c3,
                                        limit=2)
                                for c3 in (routing_context.get("allowed_hs2")
                                           or routing_context.get("candidate_hs2")
                                           or [])]
                            scope3 = [s3 for s3 in scope3 if len(s3) == 2] \
                                or [str(p2) for p2 in parents]
                        else:
                            scope3 = [str(p2) for p2 in parents]
                        summon = _bti_summon(
                            scope3, q_pri, q_pri | q_toks,
                            prefix_len, set())
                        if summon is not None:
                            record = {"level": level, **summon}
                            if summon.get("code"):
                                chk = self._load_branch_rows(
                                    level, [summon["code"][:prefix_len - 2]])
                                if any(_digits(r2.get("code"), limit=prefix_len)
                                       == summon["code"] for r2 in chk):
                                    record["summoned_by"] = (
                                        "BTI:" + ",".join(summon["refs"]))
                                else:
                                    record["code"] = ""
                                    record["not_in_tree"] = summon["code"]
                            bti_summons.append(record)
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
            if ancestor_violated and (os.environ.get(
                    "ASAP_ANCESTOR_INHERIT", "1") or "1").strip() != "0":
                parent_len_inh = prefix_len - 2
                inherited = [r for r in ranked
                             if r["code"][:parent_len_inh] in ancestor_violated]
                if inherited:
                    for r in inherited:
                        r["score"] = round(r["score"] - QUANT_PENALTY, 2)
                        r["decision"] = "violated"
                        r.setdefault("decision_detail", []).append({
                            "cond": "ancestor", "op": "inherit",
                            "verdict": "false", "field": "",
                            "why": f"ancestor_violated:{r['code'][:parent_len_inh]}",
                            "value": "",
                        })
                    ranked = [r for r in ranked if r not in inherited] + inherited
            full_ranked = ranked
            # [7회차-2 G1] 창밖 회수 — hs4 전용. 발동·직격 요건 전부 이산
            # (점수 입력 0): 선두가 ①1급 확정(confirmed) 미보유 ②제목·
            # 상업정체 비범용 직격 미보유일 때만, 라우터 허용 '전' 챕터의
            # hs4 vocab을 스캔해 '직격 토큰 ≥2 or 유일 직격' hs4에 입장권.
            # 비용 주석(승인 조건 ③): 발동시에만 1회 추가 인덱스 로드 —
            # hs4 전행 ~1.2k 행 상한, stall 지형 한정이라 상시 비용 0.
            if (_rt_gate != "0" and _rt_title_toks
                    and ranked and branch_rows):
                _rt_leader = ranked[0]
                _rt_row_toks: dict[str, set] = {}
                for _r_b in branch_rows:
                    _c_b = _digits(_r_b.get("code"), limit=prefix_len)
                    _rt_row_toks[_c_b] = _tokens(
                        str(_r_b.get("positive_terms") or "").replace(";", " "))
                _leader_hit = (_rt_title_toks
                               & _rt_row_toks.get(_rt_leader["code"], set()))
                # 발동 전제 강화(식품 observe 실측 반영): 선두에 결정층·
                # 술어 true가 하나라도 있으면 G2 불참 — 질문 계층 실증거
                # 보유 선두(청양고추 0710 true×1)는 '증거 0 선두'가 아니다.
                _rt_leader_true = (
                    any(d5.get("verdict") == "true"
                        for d5 in _rt_leader.get("decision_detail") or [])
                    or any(p5.get("verdict") == "true"
                           for p5 in _rt_leader.get("predicate_results") or []))
                _rt_stalled = (_rt_leader.get("decision") != "confirmed"
                               and not _leader_hit
                               and not _rt_leader_true)
                # [G2] 승자 자격 — 경쟁 풀(동일 ranked + G1 창밖 직격 후보)
                # 에서 '비범용 직격 ≥2 or 유일 직격' 보유자로 선두 교대.
                # demote-not-penalize: 점수·풀 불변, 순서 1자리만. violated
                # 수혜 금지·confirmed 선두 불가침. 임계 0(전부 이산 사실).
                _g2_pool: list[tuple[str, set, int]] = []
                # G2도 hs4 한정 — 라우터 신뢰 게이트는 '챕터 선택' 레벨의
                # 장치다. hs6+에서의 단독 직격은 재질·부품 어휘 함정이
                # 실측됨(만년필 'pen'→8304 트레이, 샤프심 'lead'→7806
                # 납제품): 가족 내부 서열은 기존 기제 소관.
                if _rt_stalled and level == "hs4":
                    for _i_r, _r_g in enumerate(ranked[1:], 1):
                        if _r_g.get("decision") == "violated":
                            continue
                        # 같은 분기 형제 제외 — 잔반(Other) 정답 vs named
                        # 형제의 직격 경쟁은 소거 기제(_proven·post-pass)
                        # 소관이다. G2는 가족(부모) 단위 신뢰 게이트
                        # (실측: 07108059 정답 잔반이 8051 'pepper' 직격에
                        # 축출되는 회귀를 이 제외가 막는다).
                        if (_r_g["code"][:prefix_len - 2]
                                == _rt_leader["code"][:prefix_len - 2]):
                            continue
                        _d_g = ((_rt_title_toks - _RT_GENERIC)
                                & _rt_row_toks.get(_r_g["code"], set()))
                        if _d_g:
                            _g2_pool.append((_r_g["code"], _d_g, _i_r))
                if (level == "hs4" and _rt_stalled):
                    _sc_chs = [
                        _digits(c4.get("chapter")
                                if isinstance(c4, dict) else c4, limit=2)
                        for c4 in (routing_context.get("allowed_hs2")
                                   or routing_context.get("candidate_hs2")
                                   or [])]
                    _sc_chs = [c4 for c4 in dict.fromkeys(_sc_chs)
                               if len(c4) == 2 and c4 not in set(parents)]
                    if _sc_chs:
                        _scan_rows = self._load_branch_rows("hs4", _sc_chs)
                        _hit_by_code: dict[str, set] = {}
                        _tok_codes: dict[str, set] = {}
                        for _r_s in _scan_rows or ():
                            _c_s = _digits(_r_s.get("code"), limit=4)
                            _d_s = (_rt_title_toks - _RT_GENERIC) & _tokens(
                                str(_r_s.get("positive_terms") or ""
                                    ).replace(";", " "))
                            if _d_s:
                                _hit_by_code[_c_s] = (
                                    _hit_by_code.get(_c_s, set()) | _d_s)
                                for _t_s in _d_s:
                                    _tok_codes.setdefault(_t_s, set()).add(_c_s)
                        _quals = []
                        for _c_s, _d_s in _hit_by_code.items():
                            _sole = any(len(_tok_codes[_t_s]) == 1
                                        for _t_s in _d_s)
                            if len(_d_s) >= 2 or (len(_d_s) == 1 and _sole):
                                _quals.append((-len(_d_s), _c_s,
                                               sorted(_d_s)))
                        _quals.sort()
                        _quals = _quals[:3]
                        if _quals:
                            _obs_rt = {
                                "level": level, "mode": _rt_gate,
                                "leader": _rt_leader["code"],
                                "candidates": [
                                    {"code": _c_s, "tokens": _d_s}
                                    for _n_s, _c_s, _d_s in _quals],
                            }
                            router_trust_obs.append(_obs_rt)
                            for _n_s, _c_s, _d_s in _quals:
                                _g2_pool.append((_c_s, set(_d_s), 10_000))
            if (_rt_gate != "0" and ranked and branch_rows
                    and _rt_title_toks and _rt_stalled and _g2_pool):
                _tok_owner: dict[str, set] = {}
                for _c_g, _d_g, _i_g in _g2_pool:
                    for _t_g in _d_g:
                        _tok_owner.setdefault(_t_g, set()).add(_c_g)
                _g2_quals = []
                for _c_g, _d_g, _i_g in _g2_pool:
                    _sole_g = any(len(_tok_owner[_t_g]) == 1 for _t_g in _d_g)
                    if len(_d_g) >= 2 or (len(_d_g) == 1 and _sole_g):
                        _g2_quals.append((-len(_d_g), _i_g, _c_g,
                                          sorted(_d_g)))
                # 단독 우세 요건(생리대 실측 반영): 최다 직격이 동수로
                # 복수 코드에 걸리면 침묵 — 다수 소유 직격은 판별력이
                # 없고, 코드순 임의 선택은 이산 원칙 위반(7418 구리
                # 위생용품이 'pad,sanitary' 동수로 9619를 가로채는 오방향
                # 교대 관측). G1 입장권은 복수 유지 — 서열은 하류 증거 몫.
                if _g2_quals:
                    _g2_quals.sort()
                    _best_n = _g2_quals[0][0]
                    if sum(1 for _q_g in _g2_quals
                           if _q_g[0] == _best_n) > 1:
                        _g2_quals = []
                if _g2_quals:
                    _n_g, _i_g, _c_g, _d_g = _g2_quals[0]
                    _obs_g2 = {
                        "level": level, "mode": _rt_gate, "gate": "G2",
                        "leader": ranked[0]["code"],
                        "new_leader": _c_g, "tokens": _d_g,
                        "would_change": _c_g != ranked[0]["code"],
                    }
                    router_trust_obs.append(_obs_g2)
                    if _rt_gate == "1" and _c_g != ranked[0]["code"]:
                        _obs_g2["applied"] = _c_g
                        _hit_g = next((r5 for r5 in ranked
                                       if r5["code"] == _c_g), None)
                        if _hit_g is None:
                            _hit_g = {"code": _c_g, "score": 0.0,
                                      "decision": "undecided",
                                      "router_trust_entry": ",".join(_d_g)}
                        else:
                            ranked.remove(_hit_g)
                        _hit_g["router_trust_gate"] = "G2:" + ",".join(_d_g)
                        ranked.insert(0, _hit_g)
            level_score_maps[level] = {r["code"]: float(r["score"]) for r in full_ranked}
            ancestor_violated = {
                r["code"] for r in full_ranked if r.get("decision") == "violated"
            } | {c for c in ancestor_violated}
            if branch_rows and parent_scores:
                parent_len = prefix_len - 2
                top_parent = max(parent_scores, key=lambda c: parent_scores.get(c, 0.0))
                # recovery 판정 기준: 기본은 부스트 포함 점수(hs4 77% 최고기록
                # 구성). 원점수(score_raw) 판정은 recovery를 폭증시켜 validator
                # 남발을 유발했던 처방 — ASAP_RECOVERY_RAW=1로만 재실험한다.
                raw_mode = (os.environ.get("ASAP_RECOVERY_RAW", "0") or "0").strip() == "1"
                rscore = (lambda r: r.get("score_raw", r["score"])) if raw_mode else (
                    lambda r: r["score"])
                # 문턱에서 확정(+50) 성분 제외: confirm은 '그룹 내' 판정이라
                # 부모 간 이견 문턱에 포함되면 확정 1건이 recovery 기록을
                # 원천 봉쇄한다 (실측: 확정 대량 발화 런에서 recovery 0건 —
                # 재첩국·달래 구제 경로 질식). 이견 후보 자격은 그대로 둔다.
                # ASAP_RECOVERY_BAR_FULL=1 이전 동작 복귀.
                bar_full = (os.environ.get(
                    "ASAP_RECOVERY_BAR_FULL", "0") or "0").strip() == "1"

                def _bar_score(r: dict[str, Any]) -> float:
                    s = rscore(r)
                    if not bar_full and r.get("decision") == "confirmed":
                        s -= DECISION_CONFIRM
                    return s

                best_top_child = max(
                    (_bar_score(r) for r in full_ranked
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
            # [9회차 [1]] window_ticket 자식 입장권 — 라우터가 정체
            # 유일-직격으로 창 입장시킨 챕터(서명 window_ticket:)의 최고
            # 자식을 selected 말미에 보존. 부모 라운드로빈 서열(재첩국
            # ch21 5위)이 정체 직격 가족을 keep 밖으로 밀어 2104가 풀
            # 실재에도 소멸하던 실측의 처방 — 입장권 계보(점수·서열
            # 불변, 생존만). ASAP_WINDOW_TICKET_CHILD=0 복귀.
            if (os.environ.get("ASAP_WINDOW_TICKET_CHILD", "1")
                    or "1").strip() != "0":
                _wt_chs: set = set()
                for _d_wt in (routing_context.get(
                        "candidate_chapter_details") or []):
                    if any(str(m_wt).startswith(
                            ("window_ticket:", "window_ticket_prep:"))
                           for m_wt in (_d_wt.get("matched_terms") or [])):
                        _wt_chs.add(str(_d_wt.get("chapter")))
                for _ch_wt in sorted(_wt_chs):
                    if any(str(c_wt).startswith(_ch_wt)
                           for c_wt in selected):
                        continue
                    _best_wt = max(
                        (r_wt for r_wt in full_ranked
                         if r_wt["code"].startswith(_ch_wt)
                         and r_wt.get("decision") != "violated"),
                        key=lambda r_wt: float(r_wt.get("score") or 0.0),
                        default=None)
                    if _best_wt is not None:
                        selected = [*selected, _best_wt["code"]]
            # [10회차-1A] 정체 축 보존 — hs4 선두 가족이 성분 축(material_
            # composition)일 때 정체 축(product_identity) 최고 자식을
            # selected 말미 보존(입장권 계보 — 재첩국 신지각: 21 창안
            # 3위인데 2104가 keep 밖 소멸 → 최종 축 교대 자체가 불가하던
            # 실측). 면류 보호: 선두가 정체 축이면 무발동. ASAP_AXIS_RANK.
            if (selected
                    and (os.environ.get("ASAP_AXIS_RANK", "1")
                         or "1").strip() != "0"
                    and _hs4_axis.get(str(selected[0])[:4])
                    == "material_composition"):
                _best_ax = max(
                    (r_ax2 for r_ax2 in full_ranked
                     if _hs4_axis.get(str(r_ax2["code"])[:4])
                     == "product_identity"
                     and r_ax2.get("decision") != "violated"),
                    key=lambda r_ax2: float(r_ax2.get("score") or 0.0),
                    default=None)
                if (_best_ax is not None
                        and _best_ax["code"] not in selected):
                    selected = [*selected, _best_ax["code"]]
            # [7회차-3] 소환 입장권 — 이 레벨 stall 소환이 성립했으면
            # 다음 레벨 부모 풀에 합류(신뢰 0 — 서열은 기존 기제가 결정)
            for _sm in bti_summons:
                if (_sm.get("level") == level and _sm.get("code")
                        and _sm["code"] not in selected):
                    selected = [*selected, _sm["code"]]
            # [7회차-2 G1] 창밖 회수 입장권 (ON시에만) — BTI와 동일 계보:
            # selected 말미 추가만(신뢰 0), rank_top_k 절단의 영향 밖.
            if _rt_gate == "1":
                for _o_rt in router_trust_obs:
                    if _o_rt.get("level") != level:
                        continue
                    for _cand_rt in _o_rt.get("candidates") or []:
                        if _cand_rt["code"] not in selected:
                            selected = [*selected, _cand_rt["code"]]
                            # [8회차-0] ON 발동 서명 — 실제 개입(입장권
                            # 부여)을 관측 레코드에 실물로 남긴다. 무서명
                            # 개입 사고(6런 A/B)의 재발 방지.
                            _o_rt.setdefault("applied", []).append(
                                _cand_rt["code"])
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
            # [8회차-3] 병합 증거화 — 부모 서열 세습에 자식 증거 조건.
            # 세습(선두 최상 부여) 자격 = 선두 가족이 ①1급 확정(confirmed)
            # ②원문·제목 직격 ③'마커 무보유' 직접 true(강등 계보 마커
            # encyclopedia/alias/precedent_hit·qualifier_state_conflict·
            # broad_pool_hit_guarded·typed_gate_blocked·state_alone·
            # qualifier_rank_excluded 보유 true는 불인정 — 승인 조건 1)
            # 중 하나 보유. 미달 시 세습 생략(부모 순서만 유지) — 무증거
            # 상위 오선택의 하위 고착(볼펜 좌표) 차단. G1/G2는 이 구조
            # 완성 시 소멸 예정 과도 장치. ASAP_PARENT_TRUST_EVIDENCE=0 복귀.
            _pte_on = (os.environ.get(
                "ASAP_PARENT_TRUST_EVIDENCE", "1") or "1").strip() != "0"
            _MARKERS = ("encyclopedia_hit", "alias_hit", "precedent_hit",
                        "qualifier_state_conflict", "broad_pool_hit_guarded",
                        "typed_gate_blocked", "state_alone",
                        "qualifier_rank_excluded")

            def _direct_true(e6: dict) -> bool:
                for d6 in (list(e6.get("decision_detail") or [])
                           + list(e6.get("predicate_results") or [])):
                    if d6.get("verdict") != "true":
                        continue
                    why6 = str(d6.get("why") or "")
                    if not any(mk in why6 for mk in _MARKERS):
                        return True
                return False

            if selected:
                _top_e = next((r6 for r6 in full_ranked
                               if r6["code"] == selected[0]), None)
                try:
                    _top_hit = (_rt_title_toks
                                & _rt_row_toks.get(selected[0], set()))
                except NameError:  # 게이트 OFF 경로 — 직격 lane 미구축
                    _top_hit = set()
                _inherit = (not _pte_on) or (_top_e is not None and (
                    _top_e.get("decision") == "confirmed"
                    or bool(_top_hit)
                    or _direct_true(_top_e)
                    # ④ 소거 승격 잔반 — 소거(형제 위반·미입증)로 선두에
                    # 선 잔반의 세습은 이 승계 장치의 원 처방(쪽갈비
                    # 1602→1601 재이탈 방지). 소거도 증거의 한 형태.
                    or bool(_top_e.get("residual"))))
                if _inherit:
                    parent_scores[selected[0]] = max(parent_scores.values())
            parents = selected

        candidates = self._final_candidates(parents, top_k=top_k)
        # 최종 DTO의 score는 cn8 스테이지 점수를 그대로 싣는다 — 키가 없으면
        # 소비측(ClassificationCandidate 조립)이 기본 0.0으로 표시해 버린다.
        cn8_scores = level_score_maps.get("cn8", {})
        _phase_by_code = {str(r_ph.get("code")): r_ph.get("residual_phase")
                          for r_ph in (full_ranked or [])
                          if r_ph.get("residual_phase")}
        for cand in candidates:
            cand["score"] = cn8_scores.get(str(cand.get("cn8")), 0.0)
            _ph_c = _phase_by_code.get(str(cand.get("cn8") or ""))
            if _ph_c:
                cand["residual_phase"] = _ph_c  # [10회차-2] trace 전파(내부)
        # [9회차 [1] 결승] 입장권 자식의 점수 우위 교대 — 정체 유일-직격
        # 챕터(window_ticket)의 자식이 최종 점수에서 현 선두를 이기면
        # 선두 교대(순서만 — demote-not-penalize). 부모 라운드로빈이
        # 점수 우위·동점 후보를 하위로 미는 재첩국 실측(cn8 3.0=3.0
        # 동점 — §2 '동점은 정체 직격 우선'의 최종병합판)의 처방.
        # 열세면 불변. 서명 window_ticket_lead.
        if (os.environ.get("ASAP_WINDOW_TICKET_CHILD", "1")
                or "1").strip() != "0" and len(candidates) >= 2:
            _wt_prep = set()
            _wt_chs2 = set()
            for _d_w2 in (routing_context.get(
                    "candidate_chapter_details") or []):
                _ms_w2 = [str(m_w2) for m_w2 in
                          (_d_w2.get("matched_terms") or [])]
                if any(m_w2.startswith("window_ticket_prep:")
                       for m_w2 in _ms_w2):
                    _wt_prep.add(str(_d_w2.get("chapter")))
                    _wt_chs2.add(str(_d_w2.get("chapter")))
                elif any(m_w2.startswith("window_ticket:")
                         for m_w2 in _ms_w2):
                    _wt_chs2.add(str(_d_w2.get("chapter")))
            if _wt_chs2:
                # 동점(>=) 교대는 §2 지대(조제 측 티켓 — redirect 원천
                # 서명 window_ticket_prep)에서만. 그 외 티켓은 순수
                # 우위(>)만 — 잡음 티켓의 동점 선두 탈취 실측(주꾸미
                # ch48·멘보샤 ch85) 차단.
                _lead_sc = float(candidates[0].get("score") or 0.0)

                def _wt_beats(i_w: int) -> bool:
                    _c2 = str(candidates[i_w].get("cn8") or "")[:2]
                    _s2 = float(candidates[i_w].get("score") or 0.0)
                    if _c2 not in _wt_chs2:
                        return False
                    return _s2 >= _lead_sc if _c2 in _wt_prep \
                        else _s2 > _lead_sc
                _best_i = max(
                    (i_w for i_w in range(1, len(candidates))
                     if _wt_beats(i_w)),
                    key=lambda i_w: float(
                        candidates[i_w].get("score") or 0.0),
                    default=None)
                if _best_i is not None:
                    _wt_cand = candidates.pop(_best_i)
                    _wt_cand["window_ticket_lead"] = True
                    candidates.insert(0, _wt_cand)
        # [10회차-1A] 정체 직격 서열 — 최종 동점에서 '정체 축(product_
        # identity) 판별 가족' 후보가 '성분 축(material_composition)
        # 판별 가족' 선두를 이긴다 (이산·수기 0 — 축은 taxonomy 원천.
        # 재첩국 신지각: 1605(성분 clam) 3.0 = 2104(정체 soup) 3.0 동점
        # 코드순 패배의 처방. 면류 보호: 1902도 정체 축이라 불변).
        # ASAP_AXIS_RANK=0 복귀. 서명 identity_axis_lead.
        if (os.environ.get("ASAP_AXIS_RANK", "1") or "1").strip() != "0" \
                and len(candidates) >= 2:
            _lead_c = candidates[0]
            _lead_ax = _hs4_axis.get(str(_lead_c.get("cn8") or "")[:4], "")
            if _lead_ax == "material_composition":
                _lead_s = float(_lead_c.get("score") or 0.0)
                _ax_i = next(
                    (i_a for i_a in range(1, len(candidates))
                     if _hs4_axis.get(str(candidates[i_a].get("cn8")
                                          or "")[:4]) == "product_identity"
                     and float(candidates[i_a].get("score") or 0.0)
                     >= _lead_s),
                    None)
                if _ax_i is not None:
                    _ax_cand = candidates.pop(_ax_i)
                    _ax_cand["identity_axis_lead"] = True
                    candidates.insert(0, _ax_cand)
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
            "merge_gate_observations": merge_gate_observations,
            "router_trust_gate": router_trust_obs,
            "bti_summons": bti_summons,
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
            from bussiness_logic.classification.repositories.branch_index_repository import LoadBranchRows
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
        fam_entries: dict[str, list[dict[str, Any]]] = {}
        for parent, items in groups.items():
            ranked_group = self._rank_sibling_group(
                items, product_facts, fallback_tokens, percentages,
                predicates_by_code=predicates_by_code or {},
                group_decisions=(decisions_by_parent or {}).get(parent) or {},
            )
            fam_entries[parent] = ranked_group
            for round_index, entry in enumerate(ranked_group):
                entry["_parent_score"] = float(scores_by_parent.get(parent, 0.0))
                entry["_round"] = round_index
                entry["_parent_rank"] = parent_rank.get(parent, len(parent_rank))
                entry["_fam"] = parent
                merged.append(entry)

        # [5회차-1] 가족 단위 증거 게이트 (설계자 조건부 승인 2026-07-17):
        # '증거 0 가족은 부모 신뢰를 순위 근거로 승계할 수 없다'(원리 1의
        # 병합판). 꼬마바 실측: ch14 가족 전원 0.0이 부모 신뢰 8.0을 승계해
        # 타 가족의 1504(7.0, 'fish')를 눌렀다 — recovery 층이 기록만 하던
        # 이견 신호를 선택에 반영하는 최소 규칙. [승인 조건 1] 대조 발동:
        # 증거 보유 가족이 1개 이상일 때만 — 전 가족 0인 완비 미달 지대
        # (면류형: 정답 가족 전원 0 + 상위 confirmed가 방어선)에선 no-op.
        # 가족 내부 순서·잔반 소거 판정은 불변(가족 내 라운드 그대로).
        # [관측 사이클 — 설계자 결정 2026-07-17] 기본 'observe': 게이트
        # 판정을 전부 계산하되 순위 무영향, 마커·가정 순위 변화만 기록 —
        # 등급 결합 발동안 설계의 실측 자료. '1'=강등 적용(옵트인),
        # '0'=완전 OFF. (보류 사유: 산채 hs2 회귀 — 정답 가족 증거 0 vs
        # 오답 진증거 지형에선 부모 신뢰가 정답의 방어선.)
        _gate_mode = (os.environ.get("ASAP_MERGE_EVIDENCE_GATE",
                                     "observe") or "observe").strip()
        if _gate_mode in ("1", "observe"):
            # [8회차-3] 등급 결합안(승인) — 가족 면제 자격은 '1급' 증거만:
            # confirmed 또는 마커 무보유 직접 true. lexical 점수·강등 계보
            # 마커 보유 true(2급 이하)는 면제 자격이 아니다 — "오답 가족
            # 증거가 2급 이하뿐일 때만 강등"의 이산 구현.
            _GATE_MARKERS = (
                "encyclopedia_hit", "alias_hit", "precedent_hit",
                "qualifier_state_conflict", "broad_pool_hit_guarded",
                "typed_gate_blocked", "state_alone",
                "qualifier_rank_excluded")

            def _fam_has_evidence(entries: list[dict[str, Any]]) -> bool:
                for e in entries:
                    if e.get("decision") == "confirmed":
                        return True
                    for d in (list(e.get("decision_detail") or [])
                              + list(e.get("predicate_results") or [])):
                        if d.get("verdict") != "true":
                            continue
                        if not any(mk in str(d.get("why") or "")
                                   for mk in _GATE_MARKERS):
                            return True
                return False
            fam_ev = {p: _fam_has_evidence(es) for p, es in fam_entries.items()}
            gated_fams = [p for p, ok in fam_ev.items() if not ok]
            if any(fam_ev.values()) and gated_fams:
                if _gate_mode == "1":
                    for entry in merged:
                        if not fam_ev.get(entry.get("_fam"), False):
                            entry["_parent_score"] = 0.0
                            entry["merge_evidence_gated"] = True  # 관측 마커
                else:
                    # observe: 실제 순위와 '강등했을' 가정 순위를 비교만
                    def _key(gate: bool):
                        return lambda r: (
                            -(0.0 if gate and not fam_ev.get(r.get("_fam"), False)
                              else r["_parent_score"]),
                            r["_round"], -r["score"], r["_parent_rank"], r["code"])
                    actual = sorted(merged, key=_key(False))
                    hypo = sorted(merged, key=_key(True))
                    obs = {
                        "gated_families": sorted(gated_fams),
                        "contrast_met": True,  # 증거 보유 가족 ≥1 (대조 조건)
                        "top1_actual": actual[0]["code"] if actual else "",
                        "top1_if_gated": hypo[0]["code"] if hypo else "",
                        "top1_would_change": bool(
                            actual and hypo and actual[0]["code"] != hypo[0]["code"]),
                    }
                    for entry in merged:
                        if not fam_ev.get(entry.get("_fam"), False):
                            entry["merge_evidence_gated_observed"] = True
                    if merged:
                        merged[0]["_merge_gate_obs"] = obs

        merged.sort(key=lambda r: (
            -r["_parent_score"], r["_round"], -r["score"], r["_parent_rank"], r["code"],
        ))
        for entry in merged:
            entry.pop("_parent_score", None)
            entry.pop("_round", None)
            entry.pop("_parent_rank", None)
            entry.pop("_fam", None)
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
            # [9회차 [2]] 자기모순 negative 박탈 — positive에도 등장하는
            # negative 토큰은 배제절 오수확의 서명('Pencils (other than
            # pencils of heading 9608), … pencil leads' → negative에
            # pencil — 코드 간 한정 참조지 상품 어휘 부정이 아님. 9609가
            # 자기 정체어로 0점 되던 실측). 진짜 배제 어휘는 positive에
            # 없다 — 교집합 박탈은 기계적·전 계급 일괄.
            negative -= positive
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

        # [P3-b] qualifier 상태-모순 자격 심사 준비 — 그룹의 '상태 arm 지도'.
        # dash 계층이 그룹을 상태로 분할할 때(0306: Frozen/Live·fresh/Other),
        # 제품의 typed 상태가 어느 arm과 일치하는지는 그룹 시야에서만 보인다.
        # 제품 상태 토큰이 '다른 형제의 qualifier 상태값'에 있는데 자기 arm에
        # 없으면 그 코드의 소속(조상)이 제품 상태와 모순 — confirmed만 강등
        # (감점·분기 전멸 금지, 마커 qualifier_state_conflict 노출). 실측:
        # frozen 새우살에서 비냉동 'Other' arm의 030695가 정체 단독 confirm
        # +50으로 정답 030617(Frozen arm 잔반)의 승격을 봉쇄.
        qual_state_by_code: dict[str, set] = {}
        label_state_by_code: dict[str, set] = {}
        for code_q, rows_q in (group_decisions or {}).items():
            toks_q: set = set()
            for row_q in rows_q:
                if str(row_q.get("role") or "") != "qualifier":
                    continue
                # arm 지도는 '조상 dash' qualifier만 — NOTE(법정 주 포섭)·
                # STATESET(자기 라벨 상태 집합)은 코드 자신의 서술이라 arm이
                # 아니다 (실측 2건: 0710 노트/라벨의 frozen이 arm으로 오인돼
                # frozen true 입증 박탈 → 잔반 0709 소거 승격). 라벨 집합은
                # 아래 label_state 지도로 따로 모아 모순 심사에만 쓴다.
                src_q = str(row_q.get("source_text") or "")
                if src_q.startswith("NOTE:"):
                    continue
                if src_q.startswith(("STATESET:", "FORMSET:", "MATERIALSET:")):
                    try:
                        vals_ls = json.loads(str(row_q.get("value") or "null")) or []
                    except Exception:  # noqa: BLE001
                        vals_ls = []
                    ls = {t2 for v2 in vals_ls for t2 in str(v2).split()}                         & (_STATE_ARM_LEXICON | _FORM_ARM_LEXICON
                           | _MATERIAL_ARM_LEXICON)
                    if ls:
                        label_state_by_code[code_q] = (
                            label_state_by_code.get(code_q, set()) | ls)
                    continue
                try:
                    vals_q = json.loads(str(row_q.get("value") or "null")) or []
                except Exception:  # noqa: BLE001
                    vals_q = []
                for v_q in vals_q:
                    toks_q |= set(str(v_q).split()) & _STATE_ARM_LEXICON
            if toks_q:
                qual_state_by_code[code_q] = toks_q
        product_state_toks: set = set()
        if qual_state_by_code or label_state_by_code:
            for path in ("identity_hints.processing_state",
                         "composition_facts.processing_state",
                         # [7회차-1 FORMSET] 제품 형태 지각도 심사 풀에 —
                         # 상태와 같은 채널, lexicon 교집합이 lane을 지킨다.
                         "identity_hints.food_form",
                         "identity_hints.product_form_terms",
                         # [8회차-4] 재질 지각 — 백과→조성 경로가 실은
                         # 재질(steel/paper…)을 심사 풀에 (비식품 lexicon
                         # 교집합이 식품 조성 오발동을 차단)
                         "composition_facts.composition_terms"):
                for value in _string_values(_dig(product_facts, path)):
                    product_state_toks |= _tokens(value)
            product_state_toks &= (_STATE_ARM_LEXICON | _FORM_ARM_LEXICON
                           | _MATERIAL_ARM_LEXICON)

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
                from bussiness_logic.classification.rules.branch_predicate_evaluator import EvaluatePredicates

                pred_delta, predicate_results = EvaluatePredicates(
                    group_predicates, fact_tokens, product_facts,
                )
                score += pred_delta
            decision_status = ""
            decision_detail: list[dict[str, str]] = []
            code_conditions = (group_decisions or {}).get(code)
            if code_conditions:
                from bussiness_logic.classification.rules.branch_decision_evaluator import EvaluateCodeDecision

                decision_status, decision_detail = EvaluateCodeDecision(
                    code_conditions, product_facts, fact_tokens, percentages,
                    _quantitative_verdict,
                )
                # [10회차-0 위생] 치환 스프린트 섀도 블록 뿌리 제거 —
                # 표 해석 섀도 모듈은 원장 §4.3 폐기 계보(메인 삭제).
                # 6차 재출현의 원본이 이 지점이었다 — 재도입 금지 (감사
                # 게이트는 규칙 대장 §6 섀도 grep 0).
                # [P3-b] 상태 arm 모순 자격 심사 (자격 박탈 계보 — 백과 상한·
                # typed_gate_blocked과 동일 원칙: 감점 없음). 마커는 확정
                # 여부와 무관하게 부착한다 — undecided true(+3)도 입증
                # 자격(_proven)은 없어야 잔반 승격이 막히지 않는다 (실측:
                # 030695가 confirmed가 아닐 때 마커 없이 proven 처리되어
                # 정답 잔반 030617의 승격을 재봉쇄). 점수는 불변, confirmed
                # 였을 때만 undecided로 강등.
                if (product_state_toks
                        and any(d.get("verdict") == "true"
                                for d in decision_detail)
                        and (os.environ.get(
                            "ASAP_DECISION_QUAL_STATE_CONFLICT",
                            "1") or "1").strip() != "0"):
                    own_arm = (qual_state_by_code.get(code, set())
                               | label_state_by_code.get(code, set()))
                    other_arms: set = set()
                    for c2 in set(qual_state_by_code) | set(label_state_by_code):
                        if c2 != code:
                            other_arms |= qual_state_by_code.get(c2, set())
                            other_arms |= label_state_by_code.get(c2, set())
                    if (product_state_toks & other_arms
                            and not (product_state_toks & own_arm)):
                        if decision_status == "confirmed":
                            decision_status = "undecided"
                        for d in decision_detail:
                            if d.get("verdict") == "true":
                                d["why"] = (str(d.get("why") or "")
                                            + ";qualifier_state_conflict")
                if decision_status == "confirmed":
                    score += DECISION_CONFIRM
                elif decision_status == "violated":
                    score -= QUANT_PENALTY
                elif decision_status == "undecided" and (
                    os.environ.get("ASAP_DECISION_TRUE_SUPPORT", "1") or "1"
                ).strip() != "0":
                    # 부분 충족 가산: true 조건당 +3, 상한 2개(과대 라벨 방지)
                    # [P1-D3] 백과 유래 매치(encyclopedia_hit)는 합산에서
                    # 집합적으로 1개(+3 상한)로만 친다 — 백과 잡음 여러 건이
                    # 지지를 쌓아 확정 없이도 점수를 독식하는 것을 차단.
                    trues = [d for d in decision_detail if d.get("verdict") == "true"]
                    n_direct = sum(
                        1 for d in trues
                        if not str(d.get("why") or "").startswith("encyclopedia_hit"))
                    n_true = n_direct + (1 if len(trues) > n_direct else 0)
                    score += DECISION_TRUE_SUPPORT * min(n_true, 2)
            if residual:
                score = min(score, 0.0)  # residuals never win on wording
                # score_raw는 캡하지 않는다 — 잔반 간 동률의 tie-break·관측
                # 정보(캡은 named와의 경쟁 규율일 뿐). [D3] 071080('capsicum'
                # raw 1.0)이 무증거 콩류 잔반에 코드순으로 밀리던 실측 처방.

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
        # [D3] 잔반 간 동률은 캡 전 원점수(score_raw)로 — 캡(0 상한)은
        # named와의 경쟁 규율이지 잔반끼리의 증거 정보를 지울 이유가 없다
        # (실측: 071080 'capsicum' 증거 보유가 콩류 잔반과 0.0 동률로
        # 코드순에 밀려 정답 잔반 승격이 타 가족 잔반에 넘어감).
        residuals.sort(key=lambda r: (r["score"], r.get("score_raw", r["score"])),
                       reverse=True)
        # [6회차 A] 판례 동점 해소 — 과도기 '이산 선택' 규칙(점수 가산 아님).
        # 발동 3중 전제: ①비잔반 형제 전원 동점 ∧ 전원 미확정 ②공유 어휘
        # (판례 구문 전 토큰이 fact에 존재 — AND) 판례 ≥k(기본 2)가 한
        # 형제에만 ③타 형제의 판례 매치 0 (사건 dedupe는 컴파일 시 —
        # 동일 상품군·발급국 뭉치 1건). confirmed/violated 서열 불가침
        # (전원 미확정일 때만 발동 — 구조 보장). 서명 precedent_tiebreak
        # (사건ID·공유어휘) 노출. ASAP_PRECEDENT_TIEBREAK=0 복귀.
        if (specific and len(specific) >= 2
                and (os.environ.get("ASAP_PRECEDENT_TIEBREAK",
                                    "1") or "1").strip() != "0"
                and len({r["score"] for r in specific}) == 1
                and all(r.get("decision") in ("", "undecided")
                        for r in specific)):
            _K_MIN = 2
            _pt_matches: dict[str, tuple[list[str], list[str]]] = {}
            for r_t in specific:
                refs_hit: list[str] = []
                shared: list[str] = []
                for row_t in (group_decisions or {}).get(r_t["code"], []):
                    if str(row_t.get("grade") or "") != "precedent":
                        continue
                    try:
                        vals_t = json.loads(str(row_t.get("value") or "null")) or []
                    except Exception:  # noqa: BLE001
                        vals_t = []
                    for v_t in vals_t:
                        toks_t = set(str(v_t).split())
                        if toks_t and toks_t <= fallback_tokens:
                            m_t = re.match(r"BTI:([^:]+):",
                                           str(row_t.get("source_text") or ""))
                            if m_t:
                                refs_hit += [x for x in m_t.group(1).split(",") if x]
                            shared.append(str(v_t))
                refs_hit = list(dict.fromkeys(refs_hit))
                if refs_hit:
                    _pt_matches[r_t["code"]] = (refs_hit, shared)
            if len(_pt_matches) == 1:  # 한 형제에만 존재 + 타 형제 반례 0
                _code_w, (_refs_w, _shared_w) = next(iter(_pt_matches.items()))
                if len(_refs_w) >= _K_MIN:
                    for _i, r_t in enumerate(specific):
                        if r_t["code"] == _code_w:
                            r_t["precedent_tiebreak"] = {
                                "refs": _refs_w[:4],
                                "shared": list(dict.fromkeys(_shared_w))[:4]}
                            specific.insert(0, specific.pop(_i))
                            break
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
            rest_residuals.sort(
                key=lambda r: (r["score"], r.get("score_raw", r["score"])),
                reverse=True)
            return confirmed_entries + rest_specific + rest_residuals

        # PROOF-based elimination (tariff logic): a specific line only beats
        # "Other" when its criterion is PROVEN — a predicate answered true,
        # or its matched wording comes from the product's semantic identity
        # fields. A stray pool token is a match, not a proof. When no
        # sibling proves its criterion, the product belongs to the group's
        # residual by elimination — that is what "Other" means.
        proof = self._proof_tokens(product_facts)
        viable_residuals = [r for r in residuals if r["score"] > -QUANT_PENALTY / 2]
        # 소거의 자격: "질문이 있었는데 아무도 입증 못함"과 "질문 자체가
        # 없음"은 다르다 — 무정보 그룹의 residual 승격은 소거가 아니라 추측
        # (실측: 비식품 residual 안착 30건 중 정답 1건). 그룹에 평가된
        # 조건·술어가 하나도 없으면 승격하지 않고 lexical 순위 유지.
        # ASAP_ELIMINATION_NEEDS_QUESTIONS=0 복귀.
        # [P1-D2] '질문 존재' 판정에서 qualifier(그룹 공통 자격층)는 제외 —
        # qualifier만 있는 그룹의 잔반 승격은 여전히 소거가 아니라 추측이다.
        questions_existed = any(
            any(str(d.get("why") or "") != "qualifier_rank_excluded"
                for d in (r.get("decision_detail") or []))
            or bool(r.get("predicate_results"))
            for r in [*specific, *residuals]
        )
        needs_q = (os.environ.get(
            "ASAP_ELIMINATION_NEEDS_QUESTIONS", "1") or "1").strip() != "0"
        if needs_q and not questions_existed:
            viable_residuals = []
        if viable_residuals and specific:
            # [P1-D2] 잔반 승격을 막는 '입증'은 leaf 판별 직접 매치만 —
            # qualifier(그룹 공통 자격층) 값 토큰은 형제 전원이 공유하는
            # 류 정의라 특정 형제의 입증이 될 수 없다. lexical matched에서
            # 차감한다. (alias 2급 매치는 confirmed 자격에서 이미 차단되고
            # — ASAP_ALIAS_CONFIRM_GUARD — matched는 alias 확장이 없다.)
            qualifier_toks: set[str] = set()
            for rows_ in (group_decisions or {}).values():
                for row_ in rows_:
                    if str(row_.get("role") or "") != "qualifier":
                        continue
                    try:
                        vals_ = json.loads(str(row_.get("value") or "null")) or []
                    except Exception:  # noqa: BLE001
                        vals_ = []
                    for v_ in vals_:
                        qualifier_toks |= set(str(v_).split())
            # [D3 처방 2절] 잔반 형제가 '자기 서술로도 보유'한 어휘는 특정
            # named 형제의 입증이 될 수 없다 — 51·59가 같은 계열이라 둘 다
            # positive_terms에 지닌 'pepper'가 51의 lexical proof를 세워
            # 잔반 소거 승격을 차단했다 (FULL 리플레이 확증, T03 run).
            # 차감 집합에 잔반 형제들의 positive 토큰을 합류.
            for r_res in residuals:
                qualifier_toks |= _tokens(
                    str(r_res.get("incl") or "").replace(";", " "))

            def _proven(r: dict[str, Any]) -> bool:
                if r.get("decision") == "confirmed":
                    return True
                # [P1-D2] leaf 판별 조건의 '직접' field_hit true는 입증이다 —
                # 확정(+50)까지는 못 가도(typed 게이트) 그 형제가 자기 조건에
                # 답한 사실은 잔반 승격을 막아야 한다 (실측: 청양고추 hs4 —
                # 0710이 frozen 직접 true×2인데 미입증 처리되어 잔반 0709가
                # 소거 승격, 이후 전 경로가 fresh 쪽으로 이탈). alias_hit·
                # encyclopedia_hit·field_hit:union(파편 합성)·qualifier는
                # 직접 매치가 아니므로 입증 불인정.
                _PROOF_STATE_TYPES = ("preservation_state", "processing_method",
                                      "physical_form", "condition_quality")
                for d in r.get("decision_detail") or []:
                    why_ = str(d.get("why") or "")
                    if (d.get("verdict") != "true"
                            or not why_.startswith("field_hit:")
                            or why_.startswith("field_hit:union")
                            or "qualifier_state_conflict" in why_):
                        continue
                    # [P3-a 정밀화] 상태축 true의 입증 자격은 'arm 공통 여부'
                    # 로 가른다 — 마커(state_alone_blocked)는 전 조건 true
                    # 경로에서만 찍혀 미결 조건(B2 조합행)이 섞이면 우회된다.
                    # 제품 상태가 자기 arm(조상 dash) 공통이면 같은 arm의
                    # 잔반도 그 상태를 공유하므로 입증 불인정 (030611 frozen
                    # — 잔반 030617도 Frozen arm); arm 밖 상태는 그 코드
                    # 고유의 판별이라 입증 유효 (0710 frozen — 잔반 0709는
                    # fresh, 미인정 시 fresh 잔반이 소거 승격하는 역사고 실측).
                    if str(d.get("cond") or "") in _PROOF_STATE_TYPES:
                        if product_state_toks & qual_state_by_code.get(
                                str(r.get("code") or ""), set()):
                            continue
                    return True
                # Only a FIELD-answered predicate (verdict "true") certifies a
                # branch. true_pool is a broad-pool match — the same floating-
                # token risk the proof rule exists to guard against — so it is
                # not proof on its own; it still needs a semantic-field match.
                # [5회차 D3 처방] 술어 true의 입증 자격은 value '전 토큰 동시
                # 존재'(AND 재검)일 때만 — 술어 판정은 ANY 교집합(OR)이라
                # 'pepper,sweet'가 'pepper'만으로 true(+3)가 되고, 그 부분
                # 매치가 proof를 세워 같은 계열 잔반(59)의 소거 승격을 차단
                # 했다(FULL 리플레이 확증 — 사고 run 51:59=5:0). 부분·계열
                # 매치는 판별 입증이 아니다 — 결정테이블 _phrase_sets(구문 전
                # 토큰 동시 요구)와 동일 계보. 순위 +3은 불변, 자격만 재검.
                if any(
                    pr.get("verdict") == "true"
                    and all(t in fallback_tokens
                            for t in str(pr.get("value") or "").split(",") if t)
                    for pr in r.get("predicate_results") or []
                ):
                    return True
                # [D3 처방 3절 — 구문 동시성의 lexical판] 코드의 결정 판별
                # 구문('sweet pepper')에 속한 토큰은 구문 '전체'가 충족될
                # 때만 입증 자격 — 부분 토큰('pepper')만의 매치는 계열어
                # 수준이라 같은 계열 잔반(59)의 소거를 막을 자격이 없다.
                # 결정테이블 _phrase_sets(구문 내 전 토큰 동시 존재)와 동일
                # 원칙의 proof 적용 (FULL 리플레이 확증: T03 run에서 'pepper'
                # 단독 매치가 51 proof를 세워 59 승격 차단).
                own_phrases: list[set] = []
                for row_c in (group_decisions or {}).get(str(r.get("code") or ""), []):
                    if (str(row_c.get("role") or "") != "discriminator"
                            or str(row_c.get("op") or "") != "has_token"):
                        continue
                    try:
                        for v_c in json.loads(str(row_c.get("value") or "null")) or []:
                            toks_c = set(str(v_c).split())
                            if toks_c:
                                own_phrases.append(toks_c)
                    except Exception:  # noqa: BLE001
                        continue
                # [10회차-2] 자격 강화 — 상태·형태·재질 계급(arm lexicon
                # 원천, 수기 0) 토큰은 lexical proof 무자격: 'frozen/
                # paste/steel' 류 계급 매치만으로 named가 잔반을 이기는
                # 무자격 승리(미도달 34%)의 한 축을 이산 차단.
                eligible = ((set(r.get("matched") or []) - qualifier_toks)
                            & proof) - (_STATE_ARM_LEXICON
                                        | _FORM_ARM_LEXICON
                                        | _MATERIAL_ARM_LEXICON)
                for t_m in list(eligible):
                    partial = [ph for ph in own_phrases if t_m in ph]
                    if partial and not any(ph <= fallback_tokens for ph in partial):
                        eligible.discard(t_m)  # 구문 부분 매치 — 무자격
                return bool(eligible)
            if not any(_proven(r) for r in specific if r["score"] > 0):
                # [10회차-2] 3상 출력 — 소거 승격(residual_promoted) 또는
                # 전원 무자격(unqualified_question = 질문 승격 후보; UI
                # 노출은 4군 합의 전 — 내부 상태+trace 기록까지만).
                _phase = ("residual_promoted" if viable_residuals
                          else "unqualified_question")
                for _e_ph in (*viable_residuals, *specific):
                    _e_ph["residual_phase"] = _phase
                return viable_residuals + specific + [
                    r for r in residuals if r not in viable_residuals
                ]
        if specific and specific[0]["score"] > 0:
            for _e_ph in specific[:1]:
                _e_ph["residual_phase"] = "qualified_named"
            return specific + residuals
        for _e_ph in (*residuals, *specific):
            _e_ph.setdefault("residual_phase", "unqualified_question")
        return residuals + specific if residuals else specific

    # ---- weighted lexical rank + quantitative gate ------------------------
    @staticmethod
    def _heading_vocab() -> dict:
        """DB/artifacts/heading_vocab.json — pair_rows including/excluding
        수확분(HS 해설서 유래, 원문 보존). 부재/오류 = 빈 dict no-op.
        ASAP_HEADING_VOCAB=0 비활성."""
        global _HEADING_VOCAB_CACHE
        try:
            return _HEADING_VOCAB_CACHE
        except NameError:
            pass
        vocab: dict = {}
        try:
            path = Path(__file__).resolve().parents[4] / "DB" / "artifacts" / "heading_vocab.json"
            with open(path, encoding="utf-8") as f:
                vocab = json.load(f)
        except Exception:  # noqa: BLE001 — 아티팩트 부재는 기능 OFF와 동일
            vocab = {}
        globals()["_HEADING_VOCAB_CACHE"] = vocab
        return vocab

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
        # 어휘 수확 소비(기본 ON): 당국 저자(HS 해설서 유래) including/
        # excluding 구문을 형제 비교 어휘에 합류. 같은 부모를 공유하는
        # 형제들이 동일 어휘를 받으면 sibling-IDF가 자동 0점 처리하므로
        # 판별에 기여하는 것은 형제 간 서로 다른 heading 어휘뿐이다.
        vocab_on = (os.environ.get("ASAP_HEADING_VOCAB", "1") or "1").strip() != "0"
        hv = self._heading_vocab() if vocab_on else {}

        def _hv_terms(code: str, kind: str) -> set[str]:
            if not hv:
                return set()
            out: set[str] = set()
            for lvl_key, width in (("chapter", 2), ("heading", 4), ("subheading", 6)):
                bucket = (hv.get(lvl_key) or {}).get(str(code)[:width])
                if bucket:
                    for phrase in bucket.get(kind) or ():
                        out |= _tokens(phrase)
            return out

        node_term_sets = [
            (row, _tokens(row["descr"]) | _tokens(row["incl"]) | _hv_terms(str(row["code"]), "including"))
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
            excl_terms = _tokens(row["excl"]) | _hv_terms(str(row["code"]), "excluding")
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
            from bussiness_logic.bridge.runtime_adapter import BuildPipelineRuntimeAdapter
            self._adapter = BuildPipelineRuntimeAdapter()
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
            # 전 형제 점수·결정 요약 — top8 밖으로 밀린 코드(예: 정답)의
            # 패배 원인을 사후 판독하기 위한 전수 맵. 디테일은 top8 유지.
            "scores_all": {
                str(r.get("code")): [round(float(r.get("score") or 0.0), 1),
                                     str(r.get("decision") or "")]
                for r in ranked
            },
            "candidates_considered": [
                {
                    "code": r["code"],
                    "score": r["score"],
                    "matched_terms": r.get("matched", []),
                    "negative_matched_terms": r.get("neg_matched", []),
                    "predicate_results": r.get("predicate_results", []),
                    "decision": r.get("decision", ""),
                    "decision_detail": r.get("decision_detail", []),
                    "precedent_tiebreak": r.get("precedent_tiebreak"),
                    "quantitative_verdict": (r.get("quantitative_verdict") or {}).get("verdict", "neutral"),
                    # [기록 의무화 07-18 — 메인 그래프트 재이식] 잔반·형태
                    # 히트 trace 병기(UI 계약·잔반 혼동 행렬 실물). 판정 불변.
                    "residual": bool(r.get("residual")),
                    "form_hits": r.get("form_hits", 0),
                }
                for r in ranked[:8]
            ],
            "selected_codes": selected,
            "missing_facts": [a for a in LEVEL_AXES[level] if not facts.get(a)],
        }
