"""Branch DECISION-TABLE compiler (offline, deterministic parser — no LLM).

The designer model this implements: classification is not scoring but a
walk of legal condition checks — at every branching point, compare the
description's CONDITION against a specific ProductUnderstandingFacts field;
met -> that code, not met -> next line, nothing met -> "Other" (the else
branch). Repeated per level (hs4 -> hs6 -> cn8).

This compiler reads cn_table branch groups (parent label + sibling labels)
and emits one condition row per (code, condition) into the LEAN sidecar
``branch_decision_index``:

  level, branch_id(parent), seq(legal check order = code order),
  then_code, cond_type, dto_field, op, value(JSON), source_text, version

No unit/severity/confidence/predicate_id sprawl — a condition either parses
deterministically or is not emitted (the lexical engine remains the
fallback for unparsed branches). "Other" lines emit nothing: else is
implicit in elimination.

Usage:
  PYTHONPATH=src python -m bussiness_logic.classification.offline.branch_decision_compiler                 # audit
  PYTHONPATH=src python -m bussiness_logic.classification.offline.branch_decision_compiler --apply
  PYTHONPATH=src python -m bussiness_logic.classification.offline.branch_decision_compiler --chapters 16,19 --apply
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import csv

from bussiness_logic.classification.offline.cn_predicate_llm_compiler import _TOKEN, _build_groups, _stem, _toks
from bussiness_logic.classification.rules.axis_field_binding import (
    CompilerFieldBindings,
)

# ── 기준 유형 taxonomy (7/2 설계 사양서) ─────────────────────────────
# data/classification_criterion_taxonomy_20260702.csv 가 유일한 축 정의다:
# criterion_type + 탐지 정규식(examples) + role. 손으로 재발명했던 7축
# (species/form/... )은 이 16유형의 부분집합이라 폐기.
_TAXONOMY_CSV = Path(__file__).resolve().parents[4] / "data" / "classification_criterion_taxonomy_20260702.csv"

# criterion_type -> 질문에 답할 DTO 필드. Runtime과 offline compiler가
# 같은 registry를 읽어 split-brain binding을 만들지 않는다.
CRITERION_FIELD_BINDING = CompilerFieldBindings()

_COND_CLAUSE = re.compile(r"whether\s+or\s+not[^,;.)]*", re.I)

# [12회차-2 A안] 교대(OR) 원자 도출 문법 — 조문 표기 규칙만 본다(어휘 0).
#  · 괄호절 안의 ' or ' 열거: "(uncooked or cooked by steaming…)"
#  · 최상위 ' or ' 열거: "bread, pastry … or wafer, rice paper"
# 진성 누적(AND)과 교대(OR)를 가르는 것은 접속사이지 의미가 아니다 —
# 'and'/쉼표 단독 열거는 누적으로 남고, 'or'로 이어진 원자만 묶는다.
# 그룹은 반드시 **행 부분집합**에 붙는다(코드 단위 X): 0710 =
# vegetable ∧ frozen ∧ (uncooked ∨ steaming/boiling).
_ALT_PAREN = re.compile(r"\(([^()]*\bor\b[^()]*)\)", re.I)
_ALT_SPLIT = re.compile(r"\s+or\s+", re.I)
# [12회차 B-2] whether-or-not 선택 성분 — '조건 태깅' 억제용 마스크.
# _COND_CLAUSE 스크럽(값 수확용)은 쉼표에서 멈춰 "whether or not
# concentrated[, or containing added sugar…]" 꼬리의 or들이 교대로
# 오태깅됐다(0403 g1 'nut, cocoa' 실측). 선택 성분은 질문이 아니므로
# 절 전체(다음 ';' 또는 끝까지)를 **동일 길이 공백으로 마스킹**해
# 오프셋을 보존한 채 교대 도출에서만 제외한다(값 수확 스크럽 불변).
# 마스크 경계: ';' **또는 예시 도입구(', such as')** — 1902 실측: [^;]*
# 로만 끊으면 "whether or not cooked or stuffed … , such as spaghetti,
# …, noodles, …"의 판별 열거(noodle)까지 삼켜 confirmed가 붕괴한다
# (칼국수 -3 회귀). such as 이하는 선택 성분이 아니라 판별 어휘의
# 보고다(용도 참조절 스크럽과 같은 조문 관용구 문법 계보).
_WON_RX = re.compile(
    r"\bwhether\s+or\s+not\b(?:(?!,\s*such\s+as\b)[^;])*", re.I)
# [12회차 E §6] of-원료 참조절 — 참조절 문법 가족의 **3좌표째**(①용도
# 참조절 'of a kind used for…' ②교차참조 배제절 'of heading/chapter'
# ③본 좌표). 선두 정체 명사구 뒤의 `of <다항 원료 열거>`(콤마 ≥1 ∧
# ' or ' 포함)는 원료 참조지 판별 서술이 아니다 — 1603 "Extracts and
# juices of meat, fish or crustaceans, molluscs…"의 원료 열거가
# material 판별값으로 수확돼 mollusc 제품이 1603에 끌리던 실측([C]
# §6)의 처방. 경계 설계: **다항 열거만**(콤마+or 동시 요구) — "articles
# of leather"·"flour of wheat"(단일 원료 = 정당 재질 판별값)와 대시
# 라벨 선두 "Of coffee"(선두 정체 없음 — (?<=\w) 요구)는 보존된다.
# 선두 정체(extract·juice 실단어)는 마스크 밖 — 설계자 조건 그대로.
_OF_SOURCE_RX = re.compile(
    r"(?<=\w)\s+of\s+((?:[^,;()]{1,60},\s*)+[^,;()]{0,60}?\bor\b[^,;()]{0,60})",
    re.I)


def _of_clause_is_source(listing: str) -> bool:
    """of-절의 or-열거가 '원료 열거'인가 — **상태축 열거면 아니다**.

    표면 문법이 동형인 두 지형의 기계 갈림(수기 0 — taxonomy 패턴):
      1603 "of meat, fish or crustaceans, molluscs…" → 원소 전부 명사
      0201 "of bovine animals, fresh or chilled"   → fresh·chilled가
           상태축 매치 → 상태 열거(뒤따르는 조건 서술)지 원료 열거가
           아님 — 마스크 취소(bovine 판별값 전멸 실측의 처방).
    """
    parts = [s.strip() for s in re.split(r",|\bor\b", listing, flags=re.I)
             if s.strip()]
    for part in parts:
        for entry in _TAXONOMY:
            if entry["criterion_type"] not in _STATE_TYPES:
                continue
            if entry["pattern"].fullmatch(part) or (
                    len(part.split()) <= 2 and entry["pattern"].search(part)):
                return False
    return True


# [12회차 E-편입] 유래 참조절 — 가족 **4좌표째**(설계자 '가족 확장'
# 조건의 첫 적용): 'obtained/derived from X'의 동사구는 연산어지 판별
# 어휘가 아니다 — 19049010 "Obtained from rice"가 폴백에서 'obtained
# rice' 파편으로 수확되던 실측의 처방. **동사구만** 동일 길이 공백
# 치환해 목적어(rice — 정당 판별값)는 보존한다. 동사 목록은 실측 좌표
# 최소(obtained·derived) — 'prepared from'(1604 caviar 계보)은 판례
# 상한 기보호라 확장 보류.
_DERIV_RX = re.compile(
    r"\b(?:obtained|derived)\s+(?:entirely\s+|wholly\s+|partly\s+)?from\b",
    re.I)


def _mask_optional_clauses(text_in: str) -> str:
    body = str(text_in or "")
    body = _WON_RX.sub(lambda m: " " * len(m.group(0)), body)
    body = _DERIV_RX.sub(lambda m: " " * len(m.group(0)), body)
    if (os.environ.get("ASAP_OF_SOURCE_SCRUB", "1") or "1").strip() != "0":
        body = _OF_SOURCE_RX.sub(
            lambda m: (" " * len(m.group(0))
                       if _of_clause_is_source(m.group(1)) else m.group(0)),
            body)
    return body


def _alt_spans(text_in: str) -> list[tuple[int, int, int]]:
    """교대 원자의 **문자 오프셋 구간** — [(start, end, group_idx), …].

    스펙 확정: source_text 사후 문자열 매칭은 기각(0201 'fresh or
    chilled' 오탐 대량·상한 1,989↔하한 620). 컴파일 시점에 '값을 뽑은
    match 위치'가 어느 원자 구간에 들어가는지로 판정하면 문자열 오탐이
    구조적으로 불가능하다 — 이것이 유일 해법.
    """
    spans: list[tuple[int, int, int]] = []
    body = str(text_in or "")
    gid = 0
    covered: list[tuple[int, int]] = []
    for m in _ALT_PAREN.finditer(body):
        inner_off = m.start(1)
        cuts = [(mm.start(), mm.end()) for mm in _ALT_SPLIT.finditer(m.group(1))]
        if not cuts:
            continue
        bounds = [0] + [c for cut in cuts for c in cut] + [len(m.group(1))]
        parts = [(bounds[i], bounds[i + 1]) for i in range(0, len(bounds) - 1, 2)]
        if len(parts) >= 2:
            for s, e in parts:
                spans.append((inner_off + s, inner_off + e, gid))
            covered.append((m.start(), m.end()))
            gid += 1
    # [12회차 3-수리] 괄호 밖 or 열거 — 원자 경계를 **쉼표**로 제한한다.
    # 문장 전체를 or로 가르면 무관한 진성 누적 조건까지 한 그룹이 되어
    # (0403: fermented ∧ cream/kephir / 0304: fresh ∧ fillet/meat) 곧
    # 오확정이다. 실제 조문에서 교대 원자의 경계는 쉼표다:
    #   0811 "Fruit and nuts, [uncooked] or [cooked by steaming] or
    #         [boiling in water], frozen"  → 세 원자만 묶이고 nuts·frozen
    #         (진성 누적)은 그룹 밖으로 남는다.
    # 따라서 or 매치의 좌우로 **직전/직후 쉼표까지만** 확장한다.
    def _inside(pos: int) -> bool:
        return any(a <= pos < b for a, b in covered)

    _SEP = ",;:()"
    tops = [(mm.start(), mm.end()) for mm in _ALT_SPLIT.finditer(body)
            if not _inside(mm.start())]
    if tops:
        # 인접한 or들은 하나의 열거다 — 열거 범위를 [첫 or의 직전 쉼표+1,
        # 마지막 or의 직후 쉼표)로 잡고 그 안을 or로 분할한다.
        runs: list[list[tuple[int, int]]] = [[tops[0]]]
        for s_or, e_or in tops[1:]:
            prev_end = runs[-1][-1][1]
            if any(ch in body[prev_end:s_or] for ch in _SEP):
                runs.append([(s_or, e_or)])
            else:
                runs[-1].append((s_or, e_or))
        for run in runs:
            first_s, last_e = run[0][0], run[-1][1]
            left_cut = max((body.rfind(ch, 0, first_s) for ch in _SEP),
                           default=-1)
            right_cut = min(
                (p for p in (body.find(ch, last_e) for ch in _SEP) if p >= 0),
                default=len(body))
            l_s, r_e = left_cut + 1, right_cut
            atoms: list[tuple[int, int]] = []
            cur = l_s
            for s_or, e_or in run:
                atoms.append((cur, s_or))
                cur = e_or
            atoms.append((cur, r_e))
            atoms = [(s_a, e_a) for s_a, e_a in atoms
                     if body[s_a:e_a].strip()]
            if len(atoms) >= 2:
                for s_a, e_a in atoms:
                    spans.append((s_a, e_a, gid))
                gid += 1
    return spans
# 상태축 — dash 헤더 소비가 정당한 유형(R1 원형). 값 추출·거울 배제에서
# 명사(정체) 계열과 다른 규칙을 탄다.
_STATE_TYPES = frozenset({"preservation_state", "processing_method",
                          "physical_form", "condition_quality"})
# 상태 어휘 lane — 상태어는 상태축(preservation/processing)이 소유한다.
# 비상태 축(material 등)의 값 창에 상태 열거("…frozen, dried, salted…")가
# 새어 들면 절반-경계 공유에서 살아남아 교차 오발동을 만든다 (실측:
# 0306 material 행의 'frozen'이 냉동 대구살을 0304에서 탈취 — 스크럽
# 수리로 leaf가 넓어지며 표면화). _QUANT_OPERATOR_TOKENS 선례와 동일 원칙.
_STATE_LEXICON = frozenset({
    # 상태축 taxonomy 패턴이 '실제 소유'한 어휘만 — 소유자 없는 토큰
    # (raw/live: 어느 상태 패턴에도 없음)을 lane에서 빼앗으면 그 라벨은
    # 어디서도 수확되지 않는다 (05051010 'Raw' bare 재발 실측).
    "frozen", "fresh", "chilled", "dried", "dehydrated", "salted",
    "brine", "smoked", "cooked", "uncooked", "boiled", "steamed",
})
# [7회차-1] 형태 어휘 lane — physical_form 패턴 실소유분만 (FORMSET
# qualifier의 집합 원천 · 모순 자격 심사 전용, 순위 가산 없음)
_FORM_LEXICON = frozenset({
    "whole", "broken", "powder", "granule", "flake", "pellet", "paste",
    "liquid", "solid", "sheet", "plate", "bar", "rod", "tube", "pipe",
})
# [8회차-4] 재질 어휘 lane — material_composition 패턴 실소유 '비식품'
# 재질만 (MATERIALSET qualifier 원천). 식품 재질(cocoa/milk…)은 함유
# 조건('containing cocoa')의 정당 지대라 심사 불참 — 식품/비식품 경계만
# 수기 선언, 어휘는 taxonomy CSV 원천(종이컵 392410 'of plastics' 오확정
# 실측의 처방 좌표).
_MATERIAL_LEXICON = frozenset({
    "steel", "iron", "aluminium", "copper", "nickel", "zinc", "tin",
    "lead", "plastic", "rubber", "wood", "paper", "glass", "ceramic",
    "cotton", "wool", "silk", "textile", "leather", "stone",
})
_NEG_VALUE = re.compile(
    r"\b(?:other\s+than|excluding|except|does\s+not\s+include|not\s+including|"
    # 꼬리 [a-z]*: 캡처 60자 상한이 단어 중간에서 끊기지 않게 잔여 문자까지
    # 소비 — 'known'의 'k'만 지워져 'nown' 파편이 값으로 남던 실측(0207).
    r"not\s+containing|without|no|not)\s+([a-z][a-z ,\-]{2,60}[a-z]*)", re.I)
# 수량 부정("not more than 20 %", "not exceeding 500 g")은 배제 조건이
# 아니라 수량 게이트다 — 캡처가 숫자 앞에서 끊겨 'more/than' 같은 만능
# 토큰이 not_contains 값이 되면 "more than" 포함 서술 전부에 오발동하는
# 자충수(재컴파일 로그 실측: source 'not more than ' → not_contains
# ["more","than"]). 판정은 두 갈래: 캡처 선두어가 수량 비교어이거나,
# 캡처 토큰 전부가 수량·불용 토큰뿐일 때. 일반 부정("not stuffed")은
# 어느 쪽에도 안 걸려 배제 캡처가 그대로 유지된다.
_QUANT_NEG_HEAD = frozenset({"more", "less", "exceeding"})
_QUANT_NEG_TOKENS = frozenset({
    "more", "less", "than", "exceed", "exceeding", "least", "most",
    "over", "under", "weigh", "weighing", "contain", "containing",
    "and", "the", "for", "with", "not", "its", "this", "that", "but",
})


def _load_taxonomy() -> list[dict[str, Any]]:
    rows = list(csv.DictReader(open(_TAXONOMY_CSV, encoding="utf-8-sig")))
    out = []
    for r in rows:
        pattern = str(r.get("examples") or "").strip()
        if not pattern or str(r.get("criterion_type")) == "product_identity":
            continue  # identity는 정규식이 아니라 예시 목록 — 명사 폴백이 담당
        try:
            compiled = re.compile(pattern.replace(" | ", "|"), re.I)
        except re.error:
            continue
        out.append({"criterion_type": str(r["criterion_type"]),
                    "role": str(r.get("role") or ""), "pattern": compiled})
    return out


_TAXONOMY = _load_taxonomy()
_RESIDUAL_RX = next((t["pattern"] for t in _TAXONOMY if t["criterion_type"] == "residual_other"), None)


def _grounded_source(source: str, values) -> str:
    """source_text 기록 — 채택 값 토큰의 원문 등장 보장 (정합 (c) 원칙).

    quant_gate(values=None) 행은 120자 컷 유지 — source_text가 런타임
    quant_verdict_fn(evaluator L164)의 파싱 입력이라 길이 변경이 수량
    판정에 영향을 준다. 값 보유 행은 400자로 상향하고(2916/2918류 장문
    화학 헤딩에서 값 토큰이 120자 밖이라 정합 위반 26행 실측), 그래도
    컷 밖에 남는 값 토큰은 포함 구간을 ' … ' 병기로 등장을 보장한다.
    """
    source = str(source or "")
    if not values:
        return source[:120]
    src = source[:400]
    have = {_stem(t) for t in _TOKEN.findall(src.lower())}
    need = {t for phrase in values for t in str(phrase).split() if t not in have}
    if not need:
        return src
    extras: list[str] = []
    for m in _TOKEN.finditer(source.lower()):
        stemmed = _stem(m.group(0))
        if stemmed in need:
            snippet = source[max(0, m.start() - 20):m.end() + 40].strip()
            if snippet:
                extras.append(snippet)
                # 스니펫에 같이 실려 온 나머지 필요 토큰도 해소 — 중복 병기 방지
                need -= {_stem(t) for t in _TOKEN.findall(snippet.lower())}
            else:
                need.discard(stemmed)
        if not need:
            break
    return (src + " … " + " … ".join(extras)) if extras else src


_LEDGER_PATH = (Path(__file__).resolve().parents[4] / "DB" / "artifacts"
                / "condition_ledger.jsonl")
_LEDGER_CACHE: dict[str, dict[str, list[str]]] | None = None


def _condition_ledger() -> dict[str, dict[str, list[str]]]:
    """condition_ledger.jsonl → {scope: {kind: [원문 텍스트]}} (지연 로드).

    Phase A 산출물(법정 주 원장). 부재·오류 = 빈 dict no-op — 원장 없이도
    라벨 수확만으로 컴파일이 성립해야 한다(원천 의존 하드 실패 금지).
    """
    global _LEDGER_CACHE
    if _LEDGER_CACHE is not None:
        return _LEDGER_CACHE
    out: dict[str, dict[str, list[str]]] = {}
    try:
        with open(_LEDGER_PATH, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                scope = str(rec.get("scope") or "")
                kind = str(rec.get("kind") or "")
                text = str(rec.get("text") or "").strip()
                if scope and kind and text:
                    out.setdefault(scope, {}).setdefault(kind, []).append(text)
    except OSError:
        out = {}
    _LEDGER_CACHE = out
    return out


# 법정 주의 배제 절 — CNEN 수확기와 같은 어휘, 주(note) 문장 형태 포함
# ("This heading excludes …", "The heading does not cover …").
_NOTE_EXCLUDE_RX = re.compile(
    r"(?:does not cover|do not cover|excludes?|excluding|are not included|"
    r"is not included|not covered by)[:\s]+([^.;(]{4,90})",
    re.IGNORECASE,
)


def CompileGroupDecisions(
    level: str,
    parent: str,
    members: dict[str, str],
) -> list[dict[str, Any]]:
    """Taxonomy-driven condition rows for one branch group (pure function).

    For each non-residual sibling label: run every taxonomy detector; each
    hit becomes one typed condition whose value is the matched span's
    content words, kept only if sibling-discriminative. exclusion_boundary
    captures the excluded phrase (whole-phrase block semantics downstream).
    residual_other labels emit nothing — else by elimination.
    """
    rows: list[dict[str, Any]] = []
    ordered = sorted(members.items())
    _VALUE_STOP = frozenset({
        "and", "for", "the", "its", "with", "from", "this", "thi", "that",
        "heading", "subheading", "chapter", "note", "other", "otherwise",
        "including", "included", "containing", "mixture", "weigh", "whether",
        "kind", "use", "used", "but", "less", "more", "than",
        # 수량 비교 문법은 quant lane 소유 — 값 자격 없음 (more/less/than과
        # 동일 계보; 'at least 31,8 %'의 least가 값·거울 배제로 새던 실측)
        "least",
        # ch16/19/20 법조문 만능 꼬리 — 거의 모든 조제품 라벨에 등장해
        # 값으로서의 판별력이 없고 DTO processing_state와 오발동만 만든다
        # (달래꼬막장 'prepared' 실측). 상태 판별은 uncooked/frozen 등
        # 구체 상태어와 preservation_state 축이 담당.
        "prepared", "preserved",
        # [무의미 disc 스크럽 07-20] disc has_token 12,487행 전수 감사에서
        # '값 전체가 무의미 토큰'인 227행(의류 91·식품 24…)의 잔재 토큰.
        # 조문 만능어라 판별력 0(620349 'material'·1903 'form'·3707
        # 'preparation'·human consumption 보일러플레이트). 구체 판별어
        # (textile·photographic 등)는 phrase에 병존하면 살아남는다 —
        # 이 토큰만 단독일 때 그 행이 비어 미방출(정직한 미결).
        "material", "materials", "preparation", "preparations",
        "product", "products", "food", "foods", "weight",
        "consumption", "human", "purpose", "form", "forms",
        "type", "types", "content", "contents", "goods", "article",
        "articles",
    })
    residual_members: list[tuple[int, str]] = []  # [P1-C] 거울 배제 대상
    ancestor_by_code: dict[str, str] = {}         # [P3] arm(조상) 경계 지도
    # [B2] 그룹 leaf 토큰 합집합 — 차분 정밀화의 기준선. 열거형 dash 헤더
    # (0303.5x "Herrings, …, cobia ; Cobia")는 형제들의 leaf 판별자를 전부
    # 나열하므로 '조상 − 형제 leaf 합집합'만이 순수 류 정의어다. 이 차분
    # 없이는 열거형 조상이 leaf 판별자(cobia)를 삼킨다 (3회차 (e′) 표본
    # 77%의 단일 사인 — 열거형 조상 차분).
    leaf_union: set[str] = set()
    for _c, _l in ordered:
        _raw = [s.strip() for s in str(_l or "").split(" ; ") if s.strip()]
        if _raw:
            leaf_union |= {_stem(t) for t in _TOKEN.findall(
                _COND_CLAUSE.sub(" ", _raw[-1]).lower())}
    for seq, (code, label) in enumerate(ordered):
        # [B2·스크럽 수리 — 3회차 인계분, 축-조합과 동반 적용 승인] 계층
        # 분리는 '원본 라벨'의 ' ; '로 먼저 한다 — _COND_CLAUSE 스크럽을
        # 먼저 하면 "wares, whether or not containing cocoa; communion"이
        # "wares,  ; communion"으로 변해 인공 계층 구분자가 생기고, 1905의
        # 진짜 정체('Bread, pastry, cakes, biscuits')가 조상으로 오인돼
        # qualifier로 유출된다 (설기·콩찰떡 1905 미도달의 직접 사인).
        raw_segs = [s.strip() for s in str(label or "").split(" ; ") if s.strip()]
        segs_all = [t for t in (_COND_CLAUSE.sub(" ", s).strip()
                                for s in raw_segs) if t]
        clean = " ; ".join(segs_all)
        # residual 판정은 leaf 세그먼트에서만 — 경로(dash 헤더)에 낀 'Other'
        # 가 라벨 전체 검사에 걸리면 실 조건 보유 코드가 else로 오인된다.
        # leaf 분리도 ' ; '(트리 헤더 조립 구분자) 기준 — 서술 자체의 ';'
        # 열거("…structure; salts thereof", 2941 실측)가 leaf로 오인되면
        # 공유 꼬리('salts thereof')만 남아 분기가 전멸한다.
        # leaf = '원본' 마지막 세그먼트의 스크럽본(segs_all[-1]) — clean의
        # rsplit을 쓰면 스크럽이 만든 인공 ' ; '가 재유입되어 leaf가 중간
        # 절단된다 (1905 leaf가 'communion…'으로 잘려 bread/pastry/cakes
        # 정체 수확 실패 실측 — 스크럽 수리의 잔여 경로).
        is_residual = bool(_RESIDUAL_RX is not None and _RESIDUAL_RX.search(
            (segs_all[-1] if segs_all else "").strip().lower()))
        if is_residual:
            residual_members.append((seq, code))
        # [P1-B] 조상(dash 헤더) 토큰 — 형제 전원이 공유하는 류(類) 정의라
        # 판별 값 자격이 없다 (청양고추 R5: 'fruit genu capsicum'이 51의
        # 조건 값이 되어 고추속이기만 하면 51이 이겼다). 판별 값 추출에서
        # 차분하고, 대신 role='qualifier' 층으로 분리 emit한다.
        # 분리 구분자는 ' ; '(공백 포함) — _rows_from_tree가 계층 헤더를
        # 이 형태로 조립한다. 헤딩 서술 자체의 ';'(열거, hs4 0306/7104류)
        # 는 계층이 아니므로 조상으로 오인하면 자기 서술이 차분당한다.
        # 토큰은 무필터 스템 — 'U 235'의 'u' 같은 홑글자 기호도 조상이면
        # 판별 자격이 없다 (len≥3 _toks만 쓰면 홑 대문자 승격 규칙과 어긋남).
        ancestor_text = " ; ".join(segs_all[:-1])
        ancestor_by_code[code] = ancestor_text
        # [B2] 차분 배제 집합 = 조상 − 형제 leaf 합집합. 열거형 헤더 토큰은
        # 형제 leaf에도 각각 등장하므로 자동 면제되고(cobia 생존), 순수 류
        # 정의어('molluscs')만 차분된다 — R1 원칙 불변, 국소 정밀화.
        ancestor_toks = frozenset(
            {_stem(t) for t in _TOKEN.findall(ancestor_text.lower())}
            - leaf_union)
        siblings = tuple(l for c, l in ordered if c != code)
        # 형제 '배타' 필터는 상태×종 행렬 그룹(0203/0306: fresh·frozen 쌍이
        # 같은 종 라벨을 반복)에서 모든 토큰을 공유로 판정해 조건을 전멸시킨다
        # (실측: 0306 20형제 조건 0개). 판별력의 올바른 기준은 배타가 아니라
        # 희소성 — 형제 '과반'이 공유하는 토큰만 비판별로 기각한다.
        sib_tok_sets = [_toks(l) for l in siblings]
        half = max(1, len(sib_tok_sets)) / 2

        def _discriminative(w: str) -> bool:
            return sum(1 for s in sib_tok_sets if w in s) <= half

        def _phrase_units(text: str, exclude: frozenset = frozenset(),
                          check_disc: bool = True) -> list[str]:
            """구문 단위 값 추출 — 낱토큰 분해의 처방.

            exclude: 조상(dash 헤더) 토큰 차분 — 판별 값에서 류 정의어 제거
            ([P1-B] leaf 판별 값 = leaf − 조상 − 과반공유).
            check_disc=False: qualifier 층 전용 — 공유가 본질이므로 형제
            판별 필터를 걸지 않는다.

            법조문 "other aquatic invertebrates"가 ['aquatic','invertebrat']
            낱토큰으로 쪼개지면 'aquatic' 하나로 성립해 어묵·돼지갈비가
            1605로 오발동한다(실측 hs4 사인 5건: form·prepared·sweet·
            aquatic·vegetable). 쉼표·and/or 열거 경계로만 나누고 경계 안의
            인접 토큰은 한 phrase 문자열로 묶는다 — 평가기 _phrase_sets가
            phrase 내 전 토큰 동시 존재를 요구하므로 통짜 의미가 복원된다.
            """
            units: list[str] = []
            for seg in re.split(r"[,;:()]|\band\b|\bor\b", str(text or "").lower()):
                toks = [w for w in (_stem(x) for x in _TOKEN.findall(seg))
                        if len(w) >= 3 and w not in _VALUE_STOP
                        and w not in exclude
                        and (not check_disc or _discriminative(w))]
                unit = " ".join(toks[:4])
                if unit and unit not in units:
                    units.append(unit)
            # [Phase 1.5] 원문 홑 대문자 지시 기호 보존 — 'L sections' vs
            # 'T sections'(721640)처럼 판별자가 낱글자 기호일 때 길이 필터
            # (≥3)로 소실돼 분기가 bare가 된다. 원문에 독립 대문자로 등장한
            # 글자만 값으로 승격 (소문자 관사·전치사 of/or 등은 해당 없음).
            # 형제 전원이 공유하는 기호(U/I/H 병기 등)는 post-pass 정화가
            # 그대로 제거하므로 잡음 재유입 없음.
            for c in re.findall(r"(?<![\w.])([A-Z])(?![\w.])", str(text or "")):
                low = c.lower()
                if low in exclude:
                    continue
                if (not check_disc or _discriminative(low)) and low not in units:
                    units.append(low)
            return units[:8]

        def add(cond_type: str, op: str, values, source: str,
                role: str = "discriminator", grade: str = "named",
                alt_group: str = "", alt_kind: str = "") -> None:
            # grade: 'named'=원문 판별 서술 수확 / 'fallback'=패턴 불발 시
            # 명사 덤핑 (컴파일 2.0 B-5 — 폴백 구분은 축 이름이 아니라
            # 컬럼으로: binding 자격쌍 무접촉, 평가기 하위호환).
            rows.append({
                "level": level, "branch_id": parent, "seq": seq,
                "then_code": code, "cond_type": cond_type,
                "dto_field": CRITERION_FIELD_BINDING.get(cond_type, "*tokens*"),
                "op": op,
                "value": json.dumps(values, ensure_ascii=False) if values is not None else "null",
                "source_text": _grounded_source(source, values), "version": "parser-v1",
                "role": role, "grade": grade,
                # [12회차-2 A안] 교대 원자 묶음 ID — 같은 alt_group 내
                # 조건은 평가기에서 **OR**(1개 참이면 그룹 충족).
                # 빈 문자열 = 진성 누적(AND) 조건.
                "alt_group": alt_group,
                # emit 경로(디버그 전용) — 그룹 정체성에 불참한다.
                "alt_kind": alt_kind,
            })

        # [P1-B] 조상 헤더 = 그룹 공통 자격층(role='qualifier') — 특정 형제의
        # 전유 금지가 원칙이지만 저장 키(then_code)상 코드마다 자기 조상
        # 구문을 싣는다. 평가기가 순위 합산에서 role='qualifier'를 제외하므로
        # 상대 우위는 생기지 않는다(전유 무력화). 잔반 꼬리 코드도 조상이
        # 있으면 싣는다 — head 있는 조건부 잔반(292151 '…derivatives ;
        # Other')이 이 층으로 bare를 면한다 (discriminator 창작 금지).
        if ancestor_text and not (_RESIDUAL_RX is not None
                                  and _RESIDUAL_RX.search(ancestor_text.lower())):
            q_units = _phrase_units(_NEG_VALUE.sub(" ", ancestor_text),
                                    check_disc=False)
            if q_units:
                add("product_identity", "has_token", q_units, ancestor_text,
                    role="qualifier")
        if is_residual:
            continue  # else 분기 — 판별 조건은 emit하지 않는다 (소거로 정의)

        emitted_types: set[str] = set()
        # 배제 조건은 taxonomy 탐지기와 독립으로 캡처한다 — 단, dash(중간)
        # 계층의 부정("Uncooked pasta, NOT STUFFED or otherwise prepared")은
        # 구성품 상태라 광역 풀 배제로 쓰면 밀키트의 'prepared' 같은 요리
        # 수준 토큰에 정답이 위반당한다(실측). 그래서 부정 캡처는 leaf
        # 세그먼트(';' 뒤 마지막)에서만, dash 세그먼트는 긍정 조건만 낸다.
        # [12회차 B-2] leaf 창도 WON 마스킹 경유(값 수확 억제 — 위와 동일)
        leaf_segment = (_COND_CLAUSE.sub(" ", _mask_optional_clauses(
            raw_segs[-1])).strip() if raw_segs else "")
        quant_neg_source = ""
        for neg in _NEG_VALUE.finditer(leaf_segment):
            # 정렬 후 절단 — _toks는 set이라 순회 순서가 PYTHONHASHSEED에
            # 따라 달라진다. [:4]를 먼저 하면 프로세스마다 배제 값 구성이
            # 바뀌어 같은 입력이 다른 테이블·다른 순위를 낸다 (실측: 같은
            # 캐시의 대구살이 단독 실행 0304 top1, 전량 실행 0303 top1).
            values = sorted(w for w in _toks(neg.group(1)) if w)[:4]
            if not values:
                continue
            head_words = neg.group(1).lower().split()
            if (head_words and head_words[0] in _QUANT_NEG_HEAD) or all(
                    v in _QUANT_NEG_TOKENS for v in values):
                # 수량 부정 → 배제 대신 quantitative_threshold로 라우팅
                # (taxonomy 탐지기가 못 잡는 경우의 안전망 — 아래 emit부).
                quant_neg_source = quant_neg_source or neg.group(0)
                continue
            # [9회차 [2]] 교차참조 배제절은 eliminator가 아니다 —
            # 'other than pencils of heading 9608'은 코드 간 경계 참조.
            # 그 어휘를 not_contains 값으로 실으면 자기 정체어(pencil)로
            # 자기 코드가 위반된다 (9609 -197 실측). heading/chapter+숫자
            # 동반 배제절은 배제 수확에서 제외 (staged _negated_tokens와
            # 동일 문법 규칙 — 규칙 대장 등재).
            if re.search(r"\bof\s+(?:heading|chapter)s?\b", neg.group(0),
                         re.I):
                continue
            add("exclusion_boundary", "not_contains", sorted(values), neg.group(0))
            emitted_types.add("exclusion_boundary")
        # [12회차 B-2] 값 수확 창에도 WON 마스킹 — _COND_CLAUSE가 쉼표에서
        # 멈춰 남긴 꼬리("…, or containing added fruit, nuts or cocoa")가
        # 조건 행으로 수확되면 선택 성분이 AND 질문이 되어 확정을 막는다
        # (0403 'nut','cocoa' 행 실측). 선택 성분은 질문이 아니다 — 행
        # 생성 자체를 억제한다(마스킹은 raw 세그먼트 기준·동일 길이
        # 공백이라 leaf/조상 분리·오프셋 전부 보존).
        clean = " ; ".join(s_wm for s_wm in (
            _COND_CLAUSE.sub(" ", _mask_optional_clauses(s_rm)).strip()
            for s_rm in raw_segs) if s_wm)
        positive_side = _NEG_VALUE.sub(" ", clean)
        # dash(중간) 세그먼트는 상태축 전용: 'Molluscs' 같은 dash 명사(류
        # 정의)가 조건 값이 되면 그 류의 전 형제가 같은 값으로 확정된다
        # (실측: 1605.5x 일곱 형제 전원 확정 — ingredient_class='molluscs'
        # 하나로). 명사류 값 추출은 leaf 세그먼트에서만.
        leaf_positive = _NEG_VALUE.sub(" ", leaf_segment)
        # [12회차-2 A안] 교대 원자 구간 선계산 — 값을 뽑은 match 위치가
        # 어느 원자에 속하는지로 alt_group을 붙인다(컴파일 시점 태깅).
        # 검색 창이 둘(상태축=positive_side / 명사축=leaf_positive)이라
        # 창별로 따로 계산하고, 그룹 ID는 코드 단위로 유일해야 하므로
        # 창 접두를 붙인다.
        # [12회차 3-수리] 그룹 정체성 = (코드, 교대 스팬 구간) — **단일
        # 기준 문자열(clean)** 위에서만 도출한다. 종전 결함: 창별
        # (positive_side / leaf_positive)로 따로 스팬을 뜨고 kind를 ID에
        # 섞어(`0710:pos0` vs `0710:leaf0`) 같은 괄호절의 원자가 경로마다
        # 다른 그룹이 됐다 — 그룹 간 AND라 OR이 걸리지 않았고, 태깅 코드
        # 1,948개 중 460개(24%)가 같은 결함 지형이었다. 두 창은 서로 다른
        # 좌표계라 오프셋 자체도 통약 불가이므로, 기준을 clean 하나로
        # 고정하고 **원자 텍스트 포함 관계**로 소속을 판정한다(오프셋
        # 구간의 의미를 좌표계 독립적으로 구현 — 수기 매핑 0).
        # 교대 도출용 기준 문자열은 **raw에서 별도 조립**한다: 값 수확
        # 스크럽(_COND_CLAUSE — 쉼표에서 멈춤)이 clean에서 'whether or
        # not' 앵커를 먼저 지워버려, 그 꼬리(", or containing added …
        # nuts or cocoa")의 or들이 교대로 오태깅된다(0403 g1 실측).
        # raw 세그먼트에 WON 절 전체(';'까지) 마스킹을 먼저 적용한 뒤
        # 값 스크럽을 얹는다 — 값 수확 경로(clean)는 불변.
        _segs_for_alt = [
            _COND_CLAUSE.sub(" ", _mask_optional_clauses(s_am)).strip()
            for s_am in raw_segs
        ]
        _clean_masked = " ; ".join(s_am for s_am in _segs_for_alt if s_am)
        _alt_atoms_std: list[tuple[str, ...]] = [
            (_clean_masked[_s_a:_e_a].strip().lower(), f"g{_g_a}")
            for _s_a, _e_a, _g_a in _alt_spans(_clean_masked)
        ]
        # [12회차 B-1] ';' 교대 — 계층 구분자 ' ; '는 raw_segs 분리로
        # 이미 소비됐고(파스 단계 분리 — 충돌 안전 설계), **leaf 세그먼트
        # 내부**의 ';'만 서술 열거다: 1905 "bread, pastry … wares;
        # communion wafers, … rice paper"의 A ∨ B. 스크럽이 만든 인공
        # ' ; '도 원위치가 서술 ';'였으므로 교대 경계로 정당하다.
        _leaf_seg = _COND_CLAUSE.sub(" ", _mask_optional_clauses(
            raw_segs[-1] if raw_segs else ""))
        if ";" in _leaf_seg:
            _semi_parts = [p_sm.strip(" ,.").lower()
                           for p_sm in _leaf_seg.split(";")]
            _semi_parts = [p_sm for p_sm in _semi_parts if p_sm]
            if len(_semi_parts) >= 2:
                for p_sm in _semi_parts:
                    _alt_atoms_std.append((p_sm, "s0"))

        def _alt_of(kind: str, pos: int, probe: str = "") -> str:
            """교대 그룹 ID — kind는 **디버그 전용**(ID 불참).

            probe: 이 행이 나온 원문 조각(매치 텍스트/값 구문). 기준
            문자열의 어느 교대 원자에 속하는지로 그룹을 정한다.
            """
            needle = str(probe or "").strip().lower()
            if not needle:
                return ""
            for _atom, _g_a in _alt_atoms_std:
                if not _atom:
                    continue
                # 방향 고정: **원자 ⊇ 매치**일 때만 소속. 역방향(매치가
                # 원자를 포함)은 매치가 여러 원자를 걸친 경우라 특정
                # 원자의 소속으로 볼 수 없다(과다 태깅 원인).
                if needle in _atom:
                    return f"{code}:{_g_a}"
            # [12회차 B-1] 토큰 단위 낙하 — 폴백 값은 스템·구문 압축
            # ('empty cachet suitable' ← "empty cachets of a kind
            # suitable…")이라 전체-포함이 구조적으로 실패한다. needle의
            # 전 토큰이 같은 원자에 부분문자열로 들어 있을 때만 소속
            # (토큰 AND — 방향 고정 원칙 유지).
            _n_toks = [w_at for w_at in needle.split() if len(w_at) >= 3]
            if _n_toks:
                for _atom, _g_a in _alt_atoms_std:
                    if _atom and all(w_at in _atom for w_at in _n_toks):
                        return f"{code}:{_g_a}"
            return ""

        def _alt_kind(kind: str) -> str:
            """emit 경로 표시 — 그룹 ID에서 분리된 디버그 필드."""
            return kind

        for entry in _TAXONOMY:
            cond_type = entry["criterion_type"]
            if cond_type in ("residual_other", "exclusion_boundary"):
                continue
            # [P1-A] R1 원형 복원 (b551573 → c594e41 사유 없는 회귀의 원복):
            # 상태축만 full 텍스트(dash의 'Frozen:' 헤더는 정당한 상태 조건),
            # 명사류(정체·종·재질)는 leaf 세그먼트만 — dash 명사(류 정의)가
            # 조건 값이 되면 그 류의 전 형제가 같은 값으로 확정된다(1605.5x
            # 전원 확정 실측). quantitative_threshold는 값 없는 게이트라
            # 조상 오염이 불가능하고 dash 헤더 수량 조건이 실재하므로
            # (160249 quant_gate 5코드 실측) full 텍스트를 유지한다.
            search_text = (positive_side
                           if cond_type in _STATE_TYPES
                           or cond_type == "quantitative_threshold"
                           else leaf_positive)
            match = entry["pattern"].search(search_text)
            if not match:
                continue
            if cond_type == "quantitative_threshold":
                add(cond_type, "quant_gate", None, clean)
                emitted_types.add(cond_type)
                continue
            # has_token 유형: 값 추출 창은 패턴 스타일에 따라 다르다 —
            # 상태·종류형(frozen/swine/infants)은 매치 단어 자체가 값이고,
            # 연산어형(containing/consisting of/put up in)은 뒤따르는
            # 목적어가 값이다 (연산어를 값으로 쓰면 모든 라벨에 오발동).
            if cond_type in ("material_composition", "intended_use_function",
                             "packaging_presentation"):
                # 창 80자: 40자는 "other aquatic inverteb…"를 중간 절단해
                # 구문 캡처가 'aquatic' 낱토큰으로 퇴화한다(1605 실측).
                # 구문 단위 캡처가 열거 경계로 나누므로 넓혀도 잡음은
                # _phrase_units의 스톱·판별 필터가 막는다.
                window = search_text[match.end():match.end() + 80]
                # 창 경계가 단어 중간을 자르면 파편 토큰('mea','of')이 값이
                # 된다(트리 원천 160249 실측: 'meat'→'mea'). 꼬리 미완 단어 제거.
                if len(window) == 80 and not window[-1].isspace():
                    window = window.rsplit(" ", 1)[0] if " " in window else window
                span_source = window.split(";")[0].split(".")[0]
                # [12회차-3] 축 경계 절단 — 값 창이 '다른 축의 연산어'를
                # 만나면 그 앞에서 끊는다. 0710 "Vegetables … uncooked or
                # cooked by steaming or boiling in water"에서 material
                # 창이 'cooked by …' 구간을 삼켜 'steaming'이 재질 값이
                # 되던 결손의 처방(0811 동형). 원천 taxonomy에 steam/boil
                # 어휘가 없어 값 자체로는 축을 못 가리므로, 어휘가 아니라
                # **연산어 경계**로 자른다(문법 규칙 — 수기 어휘 0,
                # ';'·'.' 절단과 동형 계보).
                for _e_b in _TAXONOMY:
                    if _e_b["criterion_type"] not in _STATE_TYPES:
                        continue
                    _m_b = _e_b["pattern"].search(span_source)
                    if _m_b and _m_b.start() > 0:
                        span_source = span_source[:_m_b.start()]
                # 근거 기록은 match+채택 창 전체 — 값은 창에서 뽑으면서
                # source_text에 match.group(0)만 적으면 값이 원문 근거와
                # 어긋난 행이 남는다("articles of leather"에서 값 ["article"]
                # ·근거 'leather' 실측). span_source는 match 직후 연속
                # 구간이라 이어붙이면 원문 그대로다. 값 추출 창(80자/상한 8)
                # 은 1605·1902·160249 실측 사연으로 불변.
                source_span = match.group(0) + span_source
            else:
                # [5회차 인계 — 상태 열거 공백] 상태축은 첫 매치만 값이 된다:
                # "fresh, chilled or frozen" 라벨에서 value=['fresh']뿐이라
                # frozen 제품이 그 코드와 못 만난다 (대구살 0304 실측 — 종전
                # 에는 material 행에 얹힌 'frozen'이 우연히 대신 맞았고, lane
                # 정리로 정직하게 소실). 수리 시도 2종 실측 기각: ①전 매치
                # 열거 — 상태 공유 코드 전반 +3(0714가 청양고추 탈취·bare
                # 재발) ②소수(멤버 절반 미만) 한정 열거 — 구조 역설: 정작
                # 필요한 ch03 frozen은 5/9 과반이라 제외되어 0304 미회복,
                # ch07 frozen은 2/14 소수라 0714가 열려 청양고추 탈취.
                # 상태 판별은 '토큰 등장'이 아니라 '상태 행렬(형제 상태
                # 집합 대비 자기 상태 집합)의 차분' 재설계가 필요 — B-3.
                span_source = match.group(0)
                source_span = match.group(0)
            # 값 상한 8: 법조문 열거("such as spaghetti, macaroni, noodles,
            # lasagne, gnocchi, ravioli, cannelloni")가 4에서 잘리면 정작
            # 판별력 있는 꼬리 단어(noodle)가 소실된다 — 1902 실측.
            # 배제(not_contains)는 차단 시맨틱이라 4 유지(보수).
            # [P1-B] 판별 값 = leaf − 조상 토큰 − 과반공유(기존 필터) 차분.
            # 상태축은 dash 헤더 소비가 정당하므로 조상 차분 제외.
            span_tokens = _phrase_units(
                span_source,
                exclude=(frozenset() if cond_type in _STATE_TYPES
                         else frozenset(ancestor_toks | _STATE_LEXICON)))
            if span_tokens:
                # [12회차-3] 축 배정 라우팅 — 값 토큰이 '공정/상태축이
                # 소유한 어휘'면 그 축으로 이관한다. 실측 결손 패턴:
                # 0710 "cooked by steaming or boiling in water"의
                # 'steaming'이 material_composition 값으로 실려(연산어형
                # 창 캡처의 부작용) 재질 질문이 공정 어휘를 묻는 행이
                # 됐다 — 0403 fermented·0811 steaming·1801 roasted 동형.
                # 소유 판정은 taxonomy 패턴 실매치(_STATE_TYPES 계열)로만
                # — 수기 목록 0. 'salt'(무기염 2825/382487)처럼 공정축
                # 패턴에 매치되지 않는 물질 어휘는 이관되지 않는다.
                if cond_type not in _STATE_TYPES:
                    _proc_vals: dict[str, list[str]] = {}
                    _kept_vals: list[str] = []
                    for _v_ax in span_tokens:
                        _owner = ""
                        for _e_ax in _TAXONOMY:
                            if _e_ax["criterion_type"] not in _STATE_TYPES:
                                continue
                            _m_ax = _e_ax["pattern"].fullmatch(str(_v_ax))
                            if _m_ax:
                                _owner = _e_ax["criterion_type"]
                                break
                        if _owner:
                            _proc_vals.setdefault(_owner, []).append(_v_ax)
                        else:
                            _kept_vals.append(_v_ax)
                    if _proc_vals:
                        for _ax_t, _vs in _proc_vals.items():
                            add(_ax_t, "has_token", sorted(_vs), source_span,
                                alt_group=_alt_of("leaf", match.start(),
                                                  probe=source_span),
                                alt_kind="leaf")
                            emitted_types.add(_ax_t)
                        span_tokens = _kept_vals
                if span_tokens:
                    _kind_a = ("pos" if (cond_type in _STATE_TYPES
                                         or cond_type
                                         == "quantitative_threshold")
                               else "leaf")
                    add(cond_type, "has_token", span_tokens, source_span,
                        alt_group=_alt_of(_kind_a, match.start(),
                                          probe=source_span),
                        alt_kind=_alt_kind(_kind_a))
                    emitted_types.add(cond_type)
        # [B-3] 상태 집합 qualifier — 라벨의 '전' 상태 매치를 집합으로
        # 실은 그룹 자격층. 4회차 기각 2종(전 매치 가산·소수 한정 가산)과
        # 달리 순위 가산이 아니라 '모순 자격 심사'(P3-b arm 기계의 일반화)
        # 전용이다: 제품 typed 상태가 형제 집합에 있는데 자기 집합에 없으면
        # confirmed 강등+proof 박탈(감점·전멸 없음). 대구살 실측: frozen
        # 제품에 0302(fresh·chilled만)가 정합인 척 경쟁하던 지대의 처방.
        state_set: list[str] = []
        state_srcs: list[str] = []
        for entry_s in _TAXONOMY:
            if entry_s["criterion_type"] not in _STATE_TYPES:
                continue
            for m_s in entry_s["pattern"].finditer(positive_side):
                tok_s = m_s.group(0)
                st_s = _stem(tok_s.lower())
                if st_s in _STATE_LEXICON and st_s not in state_set:
                    state_set.append(st_s)
                    state_srcs.append(tok_s)
        if state_set:
            # source 접두 'STATESET: ' — staged가 dash arm(입증 판정용)과
            # 라벨 집합(모순 심사용)을 구분하는 채널 표지. 합치면 자기
            # 라벨의 판별 상태(0710 frozen)가 'arm 공통'으로 오분류되어
            # 입증이 박탈된다 (실측: 잔반 0709 소거 승격 회귀).
            add("preservation_state", "has_token", sorted(state_set),
                "STATESET: " + ", ".join(state_srcs), role="qualifier")
        # [7회차-1] FORMSET — 라벨의 '전' 형태 매치 집합 (STATESET 대칭,
        # 모순 자격 심사 전용 — 형태 시소의 방어층. 떡볶이 잠금은 지각
        # form 세분/원천 보강 대기로 제외 — 커브피팅 금지, 승인 지침).
        form_set: list[str] = []
        form_srcs: list[str] = []
        for entry_f in _TAXONOMY:
            if entry_f["criterion_type"] != "physical_form":
                continue
            for m_f in entry_f["pattern"].finditer(positive_side):
                tok_f = m_f.group(0)
                st_f = _stem(tok_f.lower())
                if st_f in _FORM_LEXICON and st_f not in form_set:
                    form_set.append(st_f)
                    form_srcs.append(tok_f)
        if form_set and (os.environ.get("ASAP_FORMSET", "1")
                         or "1").strip() != "0":
            add("physical_form", "has_token", sorted(form_set),
                "FORMSET: " + ", ".join(form_srcs), role="qualifier")
        # [8회차-4] MATERIALSET — 라벨의 '전' 재질 매치 집합 (FORMSET
        # 대칭 · 모순 자격 심사 전용). 오답 확정 3건(종이컵→392410
        # plastics·생리대→56012110 cotton)의 귀속처.
        mat_set: list[str] = []
        mat_srcs: list[str] = []
        for entry_m in _TAXONOMY:
            if entry_m["criterion_type"] != "material_composition":
                continue
            for m_m in entry_m["pattern"].finditer(positive_side):
                tok_m = m_m.group(0)
                st_m = _stem(tok_m.lower())
                if st_m in _MATERIAL_LEXICON and st_m not in mat_set:
                    mat_set.append(st_m)
                    mat_srcs.append(tok_m)
        if mat_set and (os.environ.get("ASAP_MATERIALSET", "1")
                        or "1").strip() != "0":
            add("material_composition", "has_token", sorted(mat_set),
                "MATERIALSET: " + ", ".join(mat_srcs), role="qualifier")
        # 수량 부정에서 라우팅된 quant_gate — taxonomy 수량 탐지기는
        # positive_side(부정 스팬 제거 후)를 보므로 "not more than 20 %"는
        # 비교어가 지워진 채 숫자만 남아 못 잡는다. 이미 잡혔으면 중복
        # emit 금지 (quant_gate value=null 설계는 기존 그대로).
        if quant_neg_source and "quantitative_threshold" not in emitted_types:
            add("quantitative_threshold", "quant_gate", None, quant_neg_source)
            emitted_types.add("quantitative_threshold")
        # 정체축 미보유 라벨 -> product_identity 폴백
        # [P1-A] 폴백 명사도 leaf만 + 조상 차분 (R1 원형: 청양고추 R5의
        # 'fruit genu capsicum' 조상 구문이 여기 full 텍스트로 유입됐다)
        # [B2] 게이트 정밀화: '아무 유형도 안 잡힘'이 아니라 '정체축
        # (product_identity/species_source) 부재'가 기준 — 1905처럼 부차
        # 축(material 'similar product'·intended_use)만 잡히는 라벨은 정작
        # 정체 열거('Bread, pastry, cakes, biscuits')를 잃어 rice cake류가
        # 1905를 이길 값이 없었다 (설기·콩찰떡 실측, R3 1604와 같은 계보).
        if not (emitted_types & {"product_identity", "species_source"}):
            # [B2] lane 중복 금지: 이 코드의 축 행이 이미 소유한 값 토큰
            # (frozen 등 상태어)은 폴백이 재수확하지 않는다 — 중복 수확이
            # post-pass 구문 충돌을 일으켜 정작 축 행을 죽였다 (게이트
            # 확장 직후 실측: hs6 판별 1619→1522, 정체만 +209).
            own_vals: set = set()
            for r in rows:
                if r["then_code"] == code and r["op"] == "has_token":
                    try:
                        for v in json.loads(r["value"]) or []:
                            own_vals |= set(str(v).split())
                    except Exception:  # noqa: BLE001
                        continue
            nouns = _phrase_units(
                leaf_positive,
                exclude=frozenset(ancestor_toks | own_vals | _STATE_LEXICON))
            if nouns:
                # [보류] identity_fallback 분해 — product_identity 축은
                # 패턴 없는 폴백 전용이라 여기가 named 정체(Cheese/Pasta)의
                # 유일한 생산자다. 전면 교체 시 binding 자격쌍이 공집합화
                # (실측: fallback 4,575/named 0 — 면류 confirm 전멸 위험).
                # named/fallback 판별 기준은 dry-run diff로 검증 후 도입.
                # [12회차-2 A안] 교대 원자 분할 — 폴백 값이 여러 교대 원자에
                # 걸치면 **원자별로 행을 쪼개고** 같은 alt_group으로 묶는다
                # (1905: bread·pastry ∨ wafer·rice paper). 한 행에 다 실으면
                # AND 의미가 되어 교대가 누적으로 오컴파일된다 — 데모 D-2가
                # 잡아낸 결함의 본체. 위치는 leaf_positive 내 값 구문의
                # 실오프셋(컴파일 시점) — 문자열 사후 매칭 아님.
                _lp_low = leaf_positive.lower()
                _by_group: dict[str, list[str]] = {}
                for _n_a in nouns:
                    _pos_a = _lp_low.find(str(_n_a).split()[0].lower())
                    _g_a = _alt_of("leaf", _pos_a, probe=str(_n_a))
                    _by_group.setdefault(_g_a, []).append(_n_a)
                if len(_by_group) > 1:
                    for _g_a, _vs_a in _by_group.items():
                        add("product_identity", "has_token", _vs_a, clean,
                            grade="fallback", alt_group=_g_a,
                            alt_kind="fallback")
                else:
                    add("product_identity", "has_token", nouns, clean,
                        grade="fallback",
                        alt_group=next(iter(_by_group), ""),
                        alt_kind="fallback")
        # [Phase 1.5] 최후 상태어 보존 — 위 폴백까지 전멸한 코드 중 leaf
        # 라벨이 taxonomy 상태 매치 토큰(_VALUE_STOP 관용어) 1~2개로만
        # 구성된 경우('Used' 63051010 실측: 값 필터 소실 → bare). 관용구가
        # 라벨 일부로 등장하는 일반 케이스는 다른 값이 살아 있어 여기 오지
        # 않는다. 값은 leaf 원문 토큰 그대로 — 정합 검사 (c) 통과 보장.
        if not emitted_types and not any(r["then_code"] == code for r in rows):
            leaf_toks = sorted({
                w for w in (_stem(x) for x in _TOKEN.findall(leaf_positive.lower()))
                if len(w) >= 3})
            if leaf_toks and len(leaf_toks) <= 2 and all(
                    _discriminative(w) and w not in ancestor_toks
                    for w in leaf_toks):
                for entry in _TAXONOMY:
                    if entry["criterion_type"] in (
                            "residual_other", "exclusion_boundary",
                            "quantitative_threshold"):
                        continue
                    m = entry["pattern"].search(leaf_positive)
                    if not m:
                        continue
                    match_toks = {_stem(x) for x in
                                  _TOKEN.findall(m.group(0).lower())}
                    if set(leaf_toks) <= match_toks:
                        add(entry["criterion_type"], "has_token", leaf_toks,
                            leaf_positive.strip())
                        emitted_types.add(entry["criterion_type"])
                        break
    # ── 그룹 수준 값 정화 (post-pass) ──
    # "형제 과반이 값으로 공유하는 토큰"은 판별 자격이 없다 — 류 정의어
    # (mollusc 7/14), 법조 관용구(containing 10/10), 문법 잡토큰(and 9/9)이
    # 모두 이 한 규칙으로 죽는다 (전수 스캔 547건 실측). 코드별 고유 값
    # (stuffed: 190220 단독)은 살아남는다. 빈 조건은 행 자체를 제거.
    if rows:
        # [P1-B] 정화는 판별층(role='discriminator')에만 적용 — qualifier는
        # 공유가 본질(류 정의)이라 과반공유 박탈 대상이 아니다.
        value_share: dict[str, set] = {}
        for r in rows:
            if r["op"] != "has_token" or r.get("role") != "discriminator":
                continue
            try:
                for v in json.loads(r["value"]) or []:
                    value_share.setdefault(str(v).lower(), set()).add(r["then_code"])
            except Exception:
                continue
        # 분모는 '판별 값을 낸 코드' 수 — 정화 기준(형제 과반)이 측정되는
        # 모집단이다. 전체 행의 then_code로 세면 qualifier·배제 전용 행을 가진
        # 코드가 분모를 부풀려 limit_share가 올라가고, 그만큼 전역 정화가
        # 조용히 완화된다 (B1 원장 수확 도입 시 실측: 0303이 무관하게 값을
        # 추가 획득해 대구살 hs4 top1을 0304에서 탈취 — '전역 정화 기준 완화
        # 금지' 불변 제약의 우회 경로였다).
        n_codes = len({r["then_code"] for r in rows
                       if r["op"] == "has_token"
                       and r.get("role") == "discriminator"}) or 1
        limit_share = max(2, n_codes / 2)
        cleaned: list[dict[str, Any]] = []
        for r in rows:
            if r["op"] != "has_token" or r.get("role") != "discriminator":
                cleaned.append(r)
                continue
            try:
                vals = json.loads(r["value"]) or []
            except Exception:
                cleaned.append(r)
                continue
            kept = [
                v for v in vals
                if str(v).lower() not in _VALUE_STOP
                and len(value_share.get(str(v).lower(), ())) < limit_share
            ]
            if kept:
                r = dict(r)
                r["value"] = json.dumps(kept, ensure_ascii=False)
                cleaned.append(r)
        # [Phase 1.5→P1] 정화가 어느 비잔반 '코드'의 전 판별 행을 죽이면 그
        # 코드는 판별 질문 0(bare)이 된다 — 코드 국소 예외로 원문 근거가
        # 가장 강한 판별 행 1개만 원값 그대로 보존한다 (전역 정화 기준은
        # 불변: 그 코드의 판별 행이 하나라도 살면 발동하지 않는다).
        # 실측: hs4 1604의 유일 판별값 'fish'가 1603(Extracts of …, fish,
        # …)과 정확히 절반 공유되어 경계에서 전멸 — R3의 최다 빈출 헤딩
        # 무질문이 이 경로였다. 1605.5x류 류-정의 폭주는 조상(dash 헤더)
        # 차분이 추출 단계에서 이미 막으므로 여기서 재발하지 않는다.
        # '가장 강한' = 값 구문 총 길이 최대(구체 구문 우선), 동률이면
        # 법조 순서 앞. qualifier는 순위 기여 0이라 판별을 대신 못 한다.
        residual_set = {c for _s, c in residual_members}

        def _strength(r: dict[str, Any]) -> tuple:
            try:
                vals = json.loads(r["value"]) or []
            except Exception:  # noqa: BLE001
                vals = []
            return (sum(len(str(v)) for v in vals), -int(r["seq"]))

        disc_pre: dict[str, list] = {}
        for r in rows:
            if r["op"] == "has_token" and r.get("role") == "discriminator":
                disc_pre.setdefault(r["then_code"], []).append(r)
        disc_post = {r["then_code"] for r in cleaned
                     if r.get("role") == "discriminator"}
        for code_p, pre_rows in disc_pre.items():
            if code_p in disc_post or code_p in residual_set:
                continue
            cleaned.append(max(pre_rows, key=_strength))
        rows = cleaned
    # ── [B2] 형제-대조 축-조합 판별 ──
    # arm(dash 조상)이 그룹을 분할할 때, 판별자는 단독 토큰이 아니라
    # arm×leaf '조합'이다 (0102: leaf 'pure bred'는 buffalo 형제와 공유,
    # arm 'cattle'은 qualifier라 순위 불참 — 단독 토큰 차분의 사각).
    # 한 구문에 arm+leaf 토큰을 함께 요구하므로(평가기 _phrase_sets가 구문
    # 내 전 토큰 동시 존재 요구) arm 단독으론 성립 불가 — R5(조상 단독
    # 매치 승리)가 구조적으로 재발하지 않는다. 값 토큰은 전부 원문
    # (arm·leaf 실등장분) — 조합은 법조 구조(0102.21 = Cattle ∧ Pure-bred)
    # 의 기계화이지 값 창작이 아니다.
    if len(ordered) >= 2:
        residual_set_b2 = {c for _s, c in residual_members}
        phrase_owner: dict[str, set] = {}
        disc_rows_by_code: dict[str, list] = {}
        for r in rows:
            if r.get("role") == "discriminator" and r["op"] == "has_token":
                disc_rows_by_code.setdefault(r["then_code"], []).append(r)
                try:
                    for v in json.loads(r["value"]) or []:
                        phrase_owner.setdefault(str(v), set()).add(r["then_code"])
                except Exception:  # noqa: BLE001
                    continue
        # 형제별 전체 라벨 토큰 집합 — 쌍(pair) 공출현 고유성의 비교 기준
        toks_by_code: dict[str, set] = {}
        for code_t, label_t in ordered:
            toks_by_code[code_t] = {
                _stem(t) for t in _TOKEN.findall(
                    _COND_CLAUSE.sub(" ", str(label_t or "")).lower())
                if len(t) >= 3}
        for seq_c, (code_c, label_c) in enumerate(ordered):
            if code_c in residual_set_b2:
                continue  # 잔반의 몫은 거울 배제
            own_rows = disc_rows_by_code.get(code_c, [])
            own_phrases: list[str] = []
            for r in own_rows:
                try:
                    own_phrases += [str(v) for v in json.loads(r["value"]) or []]
                except Exception:  # noqa: BLE001
                    continue
            # 충전 대상 = 고유 판별 구문이 하나도 없는 코드 (전 구문이 형제와
            # 공유 = 쌍 모호, 또는 판별 행 0). 이미 고유 구문 보유면 무접촉
            # — diff가 부족 지대에 국한된다.
            if any(len(phrase_owner.get(p, ())) == 1 for p in own_phrases):
                continue
            own_toks = sorted(
                t for t in toks_by_code.get(code_c, ())
                if t not in _VALUE_STOP and t not in _QUANT_NEG_TOKENS)
            if len(own_toks) < 2:
                continue
            sib_sets = [s for c2, s in toks_by_code.items() if c2 != code_c]
            leaf_raw_c = [s.strip() for s in str(label_c or "").split(" ; ")
                          if s.strip()]
            leaf_toks_c = {_stem(t) for t in _TOKEN.findall(
                _COND_CLAUSE.sub(" ", leaf_raw_c[-1]).lower())} if leaf_raw_c else set()
            # 희소한 토큰 우선(형제 등장 수 오름차순) — 판별 쌍을 빨리 찾는다
            own_toks.sort(key=lambda t: sum(1 for s in sib_sets if t in s))
            combos: list[str] = []
            for i, a in enumerate(own_toks[:8]):
                for b in own_toks[i + 1:10]:
                    # 쌍 (a,b): 자기 라벨엔 둘 다 실등장(원문 조건 충족),
                    # 어떤 형제도 둘을 동시에 갖지 않으면 조합-판별이다.
                    # 최소 한 토큰은 leaf 소속이어야 한다 — 조상 전유 쌍은
                    # 그룹 자격만으로 이기는 R5 유형이라 금지((e)와 동일 기준).
                    if a not in leaf_toks_c and b not in leaf_toks_c:
                        continue
                    if not any(a in s and b in s for s in sib_sets):
                        combos.append(f"{a} {b}")
                        break
                if combos:
                    break
            # 쌍 탐색 불발 시 arm×leaf 폴백 — arm(dash 조상)이 그룹을 분할하면
            # arm 핵심어와 leaf 구문의 조합이 판별자다 (0102형 원형 규칙,
            # 쌍 고유성 판정이 관용구 공유로 막힌 코드의 커버 경로).
            if not combos:
                arm_c = ancestor_by_code.get(code_c, "")
                arm_partitions = len({ancestor_by_code.get(c2, "")
                                      for c2, _l2 in ordered}) >= 2
                if (arm_c and arm_partitions
                        and not (_RESIDUAL_RX is not None
                                 and _RESIDUAL_RX.search(arm_c.lower()))):
                    arm_toks = [w for w in (_stem(x) for x in
                                            _TOKEN.findall(arm_c.lower()))
                                if len(w) >= 3 and w not in _VALUE_STOP]
                    base = own_phrases[:2] or _cnen_units(
                        _NEG_VALUE.sub(" ", " ".join(leaf_raw_c[-1:])), 2)
                    arm_core = " ".join(arm_toks[:2])
                    for p in base:
                        head = " ".join(str(p).split()[:2])
                        if head and arm_core and not (set(arm_core.split())
                                                      & set(head.split())):
                            combos.append(f"{arm_core} {head}")
                            break
            if not combos:
                continue
            src_row = own_rows[0] if own_rows else None
            rows.append({
                "level": level, "branch_id": parent, "seq": seq_c,
                "then_code": code_c,
                "cond_type": (str(src_row["cond_type"]) if src_row
                              else "product_identity"),
                "dto_field": (str(src_row["dto_field"]) if src_row
                              else CRITERION_FIELD_BINDING.get(
                                  "product_identity", "*tokens*")),
                "op": "has_token",
                "value": json.dumps(combos[:2], ensure_ascii=False),
                "source_text": _grounded_source(str(label_c or ""), combos[:2]),
                "version": "parser-v1", "role": "discriminator",
                "grade": "named",
            })
    # ── [6회차 B] BTI 판례 어휘 수확 (cn8 레벨 전용, grade='precedent') ──
    # 당국 판정문의 Keywords 구문 → 해당 cn8의 판별 어휘. 2급 증거:
    # 평가기에서 precedent true는 확정(+50) 자격 없음(why=precedent_hit —
    # enc/alias 선례와 동일 기계), 지지(+3)만. 구문 단위·lane 필터는
    # 로더에서, 형제 과반 정화는 여기서 판례 풀 자체로 수행(본 post-pass
    # 분모를 오염시키지 않음 — B1의 n_codes 부풀림 교훈). 사건ID는
    # source_text 'BTI:<refs>' 서명으로 보존 — [A] 동점 해소의 원료.
    if level == "cn8":
        bti = _bti_index()
        cases_by_code = {c: bti.get(c, []) for c, _l in ordered}
        if any(cases_by_code.values()):
            phrase_codes: dict[str, set] = {}
            for c_b, cases in cases_by_code.items():
                for case in cases:
                    for ph in case["phrases"]:
                        phrase_codes.setdefault(ph, set()).add(c_b)
            n_bti_codes = len([c for c, cs in cases_by_code.items() if cs]) or 1
            residual_set_b = {c for _s, c in residual_members}
            for seq_b, (code_b, _lb) in enumerate(ordered):
                cases = cases_by_code.get(code_b) or []
                if not cases or code_b in residual_set_b:
                    continue  # 잔반의 판례 어휘는 판별이 아니라 소거 몫
                freq: dict[str, int] = {}
                refs_by_phrase: dict[str, list[str]] = {}
                for case in cases:
                    for ph in case["phrases"]:
                        # 형제 과반 정화 — 판례 보유 형제 절반 이상이 공유
                        # 하는 구문은 류 공통어라 판별 자격 없음
                        if len(phrase_codes.get(ph, ())) * 2 > n_bti_codes:
                            continue
                        freq[ph] = freq.get(ph, 0) + 1
                        refs_by_phrase.setdefault(ph, []).append(case["ref"])
                # (e) 원칙 동일 적용 — 구문 전 토큰이 자기 조상(dash) 전유면
                # 그룹 공통 자격이지 판별이 아니다 (판례 서술도 예외 없음)
                anc_b = {_stem(t) for t in _TOKEN.findall(
                    ancestor_by_code.get(code_b, "").lower())}
                top_ph = [ph for ph in sorted(freq, key=lambda x: (-freq[x], x))
                          if not (set(ph.split()) and set(ph.split()) <= anc_b)][:4]
                for ph in top_ph:
                    refs = list(dict.fromkeys(refs_by_phrase[ph]))[:4]
                    rows.append({
                        "level": level, "branch_id": parent, "seq": seq_b,
                        "then_code": code_b, "cond_type": "product_identity",
                        "dto_field": CRITERION_FIELD_BINDING.get(
                            "product_identity", "*tokens*"),
                        "op": "has_token",
                        "value": json.dumps([ph], ensure_ascii=False),
                        "source_text": _grounded_source(
                            f"BTI:{','.join(refs)}: {ph}", [ph]),
                        "version": "parser-v1", "role": "discriminator",
                        "grade": "precedent",
                    })
    # ── [B1] 법정 주(note) 수확 — condition_ledger 원장 소비 ──
    # 원천: pair_rows 파싱본(heading incl 94%/excl 71%). 라벨은 '무엇인가'만
    # 말하지만 주는 '무엇이 아닌가'를 말한다 — 소거 완결성의 원료.
    #   note_excl/rule_excl → exclusion_boundary(구문 단위, ≥2토큰: 1토큰
    #     광역 배제는 자기 정체를 배제하는 자충수 계보 — 02089030 실측)
    #   note_incl → qualifier(그룹 공통 자격층): 주의 포섭 서술은 그 코드의
    #     소속 정의라 순위 판별자가 아니다 (조상 헤더와 동격 — R5 계보).
    # 자기배제 가드: 배제 값이 그 코드 자신의 leaf 정체 토큰과 겹치면 기각
    # ("0307 does not cover MOLLUSCS prepared by…"의 mollusc은 0307의 정체).
    ledger = _condition_ledger()
    if ledger:
        for seq_n, (code_n, label_n) in enumerate(ordered):
            scoped = ledger.get(str(code_n))
            if not scoped:
                continue
            clean_n = _COND_CLAUSE.sub(" ", str(label_n or ""))
            own_toks = _toks(clean_n.rsplit(" ; ", 1)[-1])
            is_res_n = bool(_RESIDUAL_RX is not None and _RESIDUAL_RX.search(
                clean_n.rsplit(" ; ", 1)[-1].strip().lower()))
            # 배제 수확 (잔반 포함 — 잔반도 '무엇이 아닌지'는 말할 수 있다)
            exc_seen: list[str] = []
            for kind in ("note_excl", "rule_excl"):
                for text_n in scoped.get(kind, ())[:4]:
                    for m_n in _NOTE_EXCLUDE_RX.finditer(text_n):
                        for unit in _cnen_units(m_n.group(1), 2):
                            if len(unit.split()) < 2:
                                continue  # 1토큰 광역 배제 금지
                            if set(unit.split()) & own_toks:
                                continue  # 자기배제 가드
                            if all(t in _QUANT_NEG_TOKENS
                                   for t in unit.split()):
                                continue  # 수량·불용 문법은 quant lane 소유
                                          # (7804 'not exceeding' 실측 — 픽스 B 계보)
                            if unit not in exc_seen:
                                exc_seen.append(unit)
                                rows.append({
                                    "level": level, "branch_id": parent,
                                    "seq": seq_n, "then_code": code_n,
                                    "cond_type": "exclusion_boundary",
                                    "dto_field": CRITERION_FIELD_BINDING.get(
                                        "exclusion_boundary", "*tokens*"),
                                    "op": "not_contains",
                                    "value": json.dumps([unit], ensure_ascii=False),
                                    "source_text": _grounded_source(
                                        "NOTE: " + m_n.group(0), [unit]),
                                    "version": "parser-v1",
                                    "role": "discriminator", "grade": "named",
                                })
                    if len(exc_seen) >= 4:
                        break
            # 포섭 수확 → qualifier (잔반은 제외 — 잔반의 소속은 소거로 정의)
            if is_res_n:
                continue
            inc_seen: list[str] = []
            for text_n in scoped.get("note_incl", ())[:2]:
                for unit in _cnen_units(text_n, 3):
                    if unit and unit not in inc_seen:
                        inc_seen.append(unit)
            if inc_seen:
                rows.append({
                    "level": level, "branch_id": parent, "seq": seq_n,
                    "then_code": code_n, "cond_type": "product_identity",
                    "dto_field": CRITERION_FIELD_BINDING.get(
                        "product_identity", "*tokens*"),
                    "op": "has_token",
                    "value": json.dumps(inc_seen[:3], ensure_ascii=False),
                    "source_text": _grounded_source(
                        "NOTE: " + scoped["note_incl"][0], inc_seen[:3]),
                    "version": "parser-v1", "role": "qualifier", "grade": "named",
                })
    # [P1-C] 거울 배제 — named 형제의 leaf 판별자 '구문'을 잔반(Other)의
    # 배제 조건으로 싣는다 (role='eliminator', op=not_contains, 구문 단위
    # 그대로 — 낱토큰 분해 금지: "aquatic invertebrates"류 낱토큰 오발동
    # 계보와 동일한 병을 막는다). 잔반의 승리 경로: "형제들이 아닌 것으로
    # 판명"을 만들 증거 구조 — 제품이 named 판별자를 들면 잔반 위반(-100),
    # 아무 판별자도 안 들면 배제 충족(true)이 소거 판정의 근거가 된다.
    # 값은 정화 후 최종 판별 값의 거울이라 원문 실등장분이며(값 창작 없음),
    # source_text는 그 판별 행들의 근거 원문을 그대로 동반한다.
    if residual_members:
        # [P3] 거울의 범위는 '같은 arm(동일 조상)'의 named 형제로 한정한다 —
        # 잔반의 소거 범위는 자기 분기점(arm) 안이다. 평면 그룹 전체를
        # 실으면 ①타 arm의 상태값('frozen')이 잔반 자신을 위반시키고(자충수
        # 상태축판) ②동종 잔반('Other SHRIMPS')이 타 arm의 동종 판별자
        # ('shrimp')에 자기부정당한다 (030617 실측 2건). 상태축 판별값은
        # arm 무관하게 거울 대상이 아니다 (원리 2: 거울 배제는 정체 질문).
        disc_by_arm: dict[str, tuple[list[str], list[str]]] = {}
        for r in rows:
            if r.get("role") != "discriminator" or r["op"] != "has_token":
                continue
            if str(r.get("cond_type") or "") in _STATE_TYPES:
                continue
            if str(r.get("grade") or "") == "precedent":
                continue  # 판례(2급)는 거울 배제 자격 없음 — 위반 확정 금지
            arm = ancestor_by_code.get(str(r["then_code"]), "")
            phrases, sources = disc_by_arm.setdefault(arm, ([], []))
            try:
                vals = json.loads(r["value"]) or []
            except Exception:  # noqa: BLE001
                vals = []
            for v in vals:
                v = str(v)
                if v and v not in phrases:
                    phrases.append(v)
            src = str(r.get("source_text") or "")
            if src and src not in sources:
                sources.append(src)
        for seq_r, code_r in residual_members:
            arm = ancestor_by_code.get(code_r, "")
            mirror_phrases, mirror_sources = disc_by_arm.get(arm, ([], []))
            # 배제 캡 8: 기존 배제 4(보수)보다 넓다 — 거울은 'arm의 형제
            # 전부가 아님'의 판명이 목적이라 누락이 곧 오판정이기 때문.
            # 구문 단위라 낱토큰 광역 오발동은 구조적으로 없다.
            mirror_phrases = mirror_phrases[:8]
            if not mirror_phrases:
                continue  # arm에 named 판별자가 없으면 거울 없음
            rows.append({
                "level": level, "branch_id": parent, "seq": seq_r,
                "then_code": code_r, "cond_type": "exclusion_boundary",
                # [P2-1] 거울 배제는 정체 필드에 묻는다 (원리 2) — 광역
                # '*tokens*' 풀은 백과·페이지 잡음 토큰에 위반당한다
                # (청양고추 59 미승격 실측). 평가기 이중 가드와 한 쌍.
                "dto_field": CRITERION_FIELD_BINDING.get(
                    "product_identity", "*tokens*"),
                "op": "not_contains",
                "value": json.dumps(mirror_phrases, ensure_ascii=False),
                "source_text": _grounded_source(
                    " ; ".join(mirror_sources), mirror_phrases),
                "version": "parser-v1", "role": "eliminator", "grade": "named",
            })
    return rows


def _rows_from_tree(tree_path: str, allow_cn8: set | None) -> list[dict[str, Any]]:
    """Nomenclature 트리(JSONL) → 컴파일 입력 행 (h4/h6/h8 라벨 조립).

    cn_table combined_description의 '>' 경로 추측을 대체하는 명시 계층 원천.
    suffix 80 = 코드 라인, suffix 10/20 = dash 그룹 헤더(조상 조건). 각 레벨
    라벨 = [부모 레벨 이후의 그룹 헤더들 ; 자기 서술] — 헤더가 정확한 레벨
    에 붙으므로 enrich의 'Other' 누출류(경로 추측 오염)가 원천 차단된다.
    allow_cn8: cn_table에 실존하는 cn8만 통과(런타임 후보 공간과 정합 유지).
    """
    decl: dict[str, dict] = {}
    order: list[dict] = []
    with open(tree_path, encoding="utf-8") as f:
        for line in f:
            n = json.loads(line)
            order.append(n)
            if n.get("declarable"):
                # 같은 code10의 suffix 80은 유일 (실측)
                decl[n["code10"]] = n
    rows: list[dict[str, Any]] = []
    dropped = 0
    for n in order:
        if not n.get("declarable") or n["code10"][8:10] != "00":
            continue  # cn8 레벨만 — TARIC10 leaf는 90% 게이트 후 단계
        cn8 = n["cn8"]
        if allow_cn8 is not None and cn8 not in allow_cn8:
            dropped += 1
            continue
        heading = decl.get(cn8[:4] + "000000")
        h4 = heading["description"] if heading else ""
        n_head = len(heading["ancestor_conditions"]) if heading else 0
        sub = decl.get(cn8[:6] + "0000")
        if sub and sub["code10"] == n["code10"]:
            # cn8 노드가 subheading 그 자체 (하위 분해 없음)
            h6_heads = n["ancestor_conditions"][n_head:]
            h6 = " ; ".join([*h6_heads, n["description"]]).strip(" ;")
            h8 = ""
        elif sub:
            h6_heads = sub["ancestor_conditions"][n_head:]
            h6 = " ; ".join([*h6_heads, sub["description"]]).strip(" ;")
            h8_heads = n["ancestor_conditions"][len(sub["ancestor_conditions"]):]
            h8 = " ; ".join([*h8_heads, n["description"]]).strip(" ;")
        else:
            h6 = ""
            h8 = " ; ".join([*n["ancestor_conditions"][n_head:], n["description"]]).strip(" ;")
        rows.append({"cn8": cn8, "h4": h4, "h6": h6, "h8": h8, "combined": ""})
    if dropped:
        print(f"  (트리 cn8 중 cn_table 밖 {dropped}개 제외 — 후보 공간 정합)")
    return rows


_CNEN_INCLUDE_RX = re.compile(
    r"([A-Z][A-Za-z \-']{4,70}?)[,\s]+(?:is|are)\s+(?:also\s+)?(?:included|classified)\s+in\s+th(?:is|ese)\s+subheading",
)
_CNEN_EXCLUDE_RX = re.compile(
    r"(?:does not cover|excludes?|are not included|not covered by)[:\s]+([^.;]{4,90})",
    re.IGNORECASE,
)


_CNEN_STOP = frozenset({
    "and", "the", "for", "with", "this", "these", "subheading",
    "subheadings", "heading", "other", "such", "which", "their",
})


# ── [6회차 B] BTI 판례 어휘 원장 (원천 4호 — 당국 판정문, 임의 저작 0) ──
_BTI_PATH = Path(__file__).resolve().parents[4] / "data" / "bti_case_chunks.csv"
_BTI_CACHE: dict[str, list[dict]] | None = None


def _bti_index() -> dict[str, list[dict]]:
    """bti_case_chunks(ch16-21 정제본 9,063건) → {cn8: [사건]}.

    사건 = {ref, country, phrases(키워드 구문 — 정규화 스템)}. 부재 = no-op.
    [A 전제 ②] 사건 중복 제거: 동일 (cn8, 발급국, 구문 서명) 뭉치는 1건
    — 같은 신청상품군의 다국 복제·재발급이 반례 0 판정을 왜곡하지 않게
    (설계자 지시). case_summary 청크의 'Keywords:' 정형 라인만 소비.
    """
    global _BTI_CACHE
    if _BTI_CACHE is not None:
        return _BTI_CACHE
    import csv as _csv
    idx: dict[str, list[dict]] = {}
    seen: set = set()
    try:
        _csv.field_size_limit(10_000_000)
        with open(_BTI_PATH, encoding="utf-8", newline="") as f:
            for r in _csv.DictReader(f):
                if str(r.get("chunk_type") or "") != "case_summary":
                    continue
                cn8 = re.sub(r"\D", "", str(r.get("cn8") or ""))[:8]
                if len(cn8) != 8:
                    continue
                m = re.search(r"^Keywords:\s*(.+)$",
                              str(r.get("chunk_text") or ""), re.M)
                if not m:
                    continue
                phrases: list[str] = []
                for seg in m.group(1).split(";"):
                    toks = [_stem(w) for w in _TOKEN.findall(seg.lower())
                            if len(w) >= 3 and w not in _CNEN_STOP
                            and w not in _QUANT_NEG_TOKENS]
                    unit = " ".join(toks[:3])
                    if unit and unit not in phrases:
                        phrases.append(unit)
                if not phrases:
                    continue
                sig = (cn8, str(r.get("issuing_country") or ""),
                       frozenset(phrases))
                if sig in seen:
                    continue  # dedupe — 동일 상품군·발급국 뭉치
                seen.add(sig)
                idx.setdefault(cn8, []).append({
                    "ref": str(r.get("bti_reference") or ""),
                    "country": str(r.get("issuing_country") or ""),
                    "phrases": phrases,
                })
        # [코퍼스 회수 07-20] 미번역 사건 EN 폴백 — case_summary가 없어
        # 전량 탈락하던 영어 원문 판례의 회수(gyoza 36건 실측: IE 발급
        # goods_description_raw만 존재·인덱스 0건 → 190220 판례 어휘
        # 공백). 요약 'Keywords:'가 이미 잡은 ref는 건드리지 않고,
        # **ascii 영어 원문**의 goods_description_raw에서만 _cnen_units
        # 보수 캡 문법으로 구문 수확(비영어 원문은 번역 전사 계보 별도).
        # 무공백 연결('GyozasFrozen') 실물 → 카멜 경계 분할 후 수확.
        # ref→사건 역색인: 요약이 이미 잡은 사건에도 상품 서술 구문을
        # **증강 병합**한다 — 요약 Keywords가 상품명 어휘를 유실하는 실측
        # (gyoza 3건: 요약 실존·keywords에 gyoza 소실 → 소환 매칭 불가).
        by_ref = {c["ref"]: c for cs in idx.values() for c in cs}
        have_refs = set(by_ref)
        with open(_BTI_PATH, encoding="utf-8", newline="") as f:
            for r in _csv.DictReader(f):
                if str(r.get("chunk_type") or "") != "goods_description_raw":
                    continue
                ref = str(r.get("bti_reference") or "")
                if not ref:
                    continue
                cn8 = re.sub(r"\D", "", str(r.get("cn8") or ""))[:8]
                if len(cn8) != 8:
                    continue
                txt = str(r.get("chunk_text") or "")
                if not txt:
                    continue
                # EN 판정은 글자 단위 — '°C' 같은 기호가 전체 isascii를
                # 죽여 IE gyoza 사건이 통째 탈락하던 실측. 단어의 글자가
                # 전부 ascii(라틴 무액센트)면 영어 원문으로 본다.
                _letters = re.findall(r"[^\W\d_]+", txt)
                if not _letters or not all(w.isascii() for w in _letters):
                    continue
                txt = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", txt)
                phrases = _cnen_units(txt, 6)
                if not phrases:
                    continue
                if ref in have_refs:
                    # 기존 사건 증강 — 서술 구문 중 신규만 병합(캡 12)
                    case = by_ref[ref]
                    for ph in phrases:
                        if ph not in case["phrases"] and len(case["phrases"]) < 12:
                            case["phrases"].append(ph)
                    continue
                sig = (cn8, str(r.get("issuing_country") or ""),
                       frozenset(phrases))
                if sig in seen:
                    continue
                seen.add(sig)
                have_refs.add(ref)
                by_ref[ref] = {
                    "ref": ref,
                    "country": str(r.get("issuing_country") or ""),
                    "phrases": phrases,
                }
                idx.setdefault(cn8, []).append(by_ref[ref])
    except OSError:
        idx = {}
    _BTI_CACHE = idx
    return idx


def _cnen_units(text: str, cap: int) -> list[str]:
    """당국 저자 텍스트 → 구문 단위 값 (열거 경계로만 분할, ≤3토큰).

    CNEN·법정 주 공용 — 낱토큰 분해 금지 계보(원리 6)의 보수 캡 버전.
    형제 비교 문맥이 없는 원천이라 판별 필터 대신 캡으로 잡음을 막는다.
    """
    found: list[str] = []
    for seg in re.split(r"[,;:()]|\bor\b|\band\b", str(text or "")):
        toks = [_stem(w) for w in _TOKEN.findall(seg.lower())
                if len(w) >= 3 and w not in _CNEN_STOP]
        unit = " ".join(toks[:3])
        if unit and unit not in found:
            found.append(unit)
        if len(found) >= cap:
            break
    return found


def _cnen_rows(note_by_cn8: dict[str, str]) -> list[dict[str, Any]]:
    """CN 해설서(cn_explanatory_note) → 코드 단위 조건 수확.

    당국 저자 텍스트의 include 문장('Wild horses … are included in these
    subheadings')을 named 정체의 긍정 조건으로, 'does not cover/excludes'
    절을 배제 조건으로. 형제 비교 문맥이 없으므로 판별 필터 대신
    보수 캡: 코드당 각 2건, phrase ≤3 토큰.
    """
    out: list[dict[str, Any]] = []
    units = _cnen_units
    for cn8, note in note_by_cn8.items():
        if not note:
            continue
        # 값을 만든 매치 문장을 source로 동반 — note[:100] 고정 컷은 값이
        # 100자 이후 문장에서 수확되면 정합 (c) 위반이 된다 (값 등장 보장).
        inc_vals: list[tuple[str, str]] = []
        for m in _CNEN_INCLUDE_RX.finditer(note):
            inc_vals += [(v, m.group(0)) for v in units(m.group(1), 2)]
        exc_vals: list[tuple[str, str]] = []
        for m in _CNEN_EXCLUDE_RX.finditer(note):
            exc_vals += [(v, m.group(0)) for v in units(m.group(1), 2)]
        # 배제는 2토큰 이상 구문만 — 1토큰('meat') 광역 배제는 자기 정체를
        # 배제하는 자충수가 된다(02089030 실측: 사냥육에 not_contains meat).
        exc_vals = [(v, s) for v, s in exc_vals if len(v.split()) >= 2]
        for op, ctype, vals in (("has_token", "product_identity", inc_vals[:2]),
                                ("not_contains", "exclusion_boundary", exc_vals[:2])):
            for v, snippet in vals:
                out.append({
                    "level": "cn8", "branch_id": cn8[:6], "seq": 90,
                    "then_code": cn8, "cond_type": ctype,
                    "dto_field": CRITERION_FIELD_BINDING.get(ctype, "*tokens*"),
                    "op": op, "value": json.dumps([v], ensure_ascii=False),
                    "source_text": _grounded_source("CNEN: " + snippet, [v]),
                    "version": "parser-v1", "role": "discriminator", "grade": "named",
                })
    return out


def _main() -> int:  # pragma: no cover — designer-run CLI
    args = sys.argv[1:]
    apply_mode = "--apply" in args
    chapters: tuple[str, ...] = ()
    if "--chapters" in args:
        chapters = tuple(
            c.strip().zfill(2) for c in args[args.index("--chapters") + 1].split(",") if c.strip()
        )

    from sqlalchemy import text

    from db.db_session_manager import DbSessionManager

    manager = DbSessionManager.GetInstance()
    chapter_label: dict[str, str] = {}
    try:
        for row in manager.FetchRows(text('SELECT chapter, title, description FROM "cn_chapter_index"'), {}):
            d = dict(row)
            ch = re.sub(r"\D", "", str(d.get("chapter") or ""))[:2].zfill(2)
            if ch:
                chapter_label[ch] = f"{d.get('title') or ''} {d.get('description') or ''}"[:200]
    except Exception:  # noqa: BLE001
        pass
    from bussiness_logic.classification.offline.cn_predicate_llm_compiler import EnrichSubheadingLabels

    rows = [dict(r) for r in manager.FetchRows(text(
        "SELECT cn8, coalesce(heading_description,'') AS h4,"
        " coalesce(subheading_description,'') AS h6,"
        " coalesce(cn8_description,'') AS h8,"
        " coalesce(combined_description,'') AS combined FROM cn_table"), {})]
    # --tree-source [path]: Nomenclature 트리를 라벨 원천으로 (경로 추측 대체).
    # 미지정 시 기본 경로 DB/artifacts/nomenclature_tree.jsonl.
    if "--tree-source" in args:
        i = args.index("--tree-source")
        nxt = args[i + 1] if i + 1 < len(args) else ""
        tree_path = nxt if nxt and not nxt.startswith("--") else str(
            Path(__file__).resolve().parents[4] / "DB" / "artifacts" / "nomenclature_tree.jsonl")
        allow = {str(r.get("cn8") or "") for r in rows}
        rows = _rows_from_tree(tree_path, allow)
        print(f"트리 원천 컴파일: {tree_path} → {len(rows)}행")
    # --enrich-h6: dash 계층 포함 컴파일 (기본 OFF — 'not ... prepared' 배제가
    # 요리/구성품 상태 서열 미해결 상태에선 정답 면류를 위반시킬 위험 실측.
    # 극성·서열 처리와 함께 A/B로 도입한다.)
    elif "--enrich-h6" in args:
        rows = EnrichSubheadingLabels(rows)
    if chapters:
        rows = [r for r in rows if str(r.get("cn8") or "")[:2] in set(chapters)]
    groups = _build_groups(rows, chapter_label)

    out: list[dict[str, Any]] = []
    per_level: dict[str, int] = {}
    branches_covered: dict[str, set] = {}
    for level, parent, _parent_label, members in groups:
        decision_rows = CompileGroupDecisions(level, parent, members)
        out.extend(decision_rows)
        per_level[level] = per_level.get(level, 0) + len(decision_rows)
        if decision_rows:
            branches_covered.setdefault(level, set()).add(parent)
    # --cnen: CN 해설서 조건 수확 합류 (당국 저자 — 어휘 갭 4번째 후보)
    if "--cnen" in args:
        note_rows = manager.FetchRows(text(
            "SELECT cn8, cn_explanatory_note FROM cn_table"
            " WHERE coalesce(cn_explanatory_note,'') <> ''"), {})
        note_by_cn8 = {str(r["cn8"]): str(r["cn_explanatory_note"] or "") for r in (dict(x) for x in note_rows)}
        cnen = _cnen_rows(note_by_cn8)
        out.extend(cnen)
        per_level["cn8"] = per_level.get("cn8", 0) + len(cnen)
        print(f"CNEN 수확: {len(cnen)}행 (해설 보유 {len(note_by_cn8)}코드)")
    total_branches = {}
    for level, parent, _pl, _m in groups:
        total_branches[level] = total_branches.get(level, 0) + 1
    print(f"분기 그룹 {len(groups)}개 → 조건 행 {len(out)}개")
    for level in ("hs4", "hs6", "cn8"):
        covered = len(branches_covered.get(level, set()))
        print(f"  {level}: 조건 {per_level.get(level, 0)}개, 분기 커버 {covered}/{total_branches.get(level, 0)}")
    cond_types: dict[str, int] = {}
    for r in out:
        cond_types[r["cond_type"]] = cond_types.get(r["cond_type"], 0) + 1
    print(f"  조건 유형: {cond_types}")

    if apply_mode:
        with manager.OpenSession() as session:
            # [메인 그래프트 재이식 3차 — 동시 apply 봉쇄] 좀비 오염 사고 처방.
            _got = session.execute(text(
                "SELECT pg_try_advisory_lock(hashtext('branch_decision_index_apply'))"
            )).scalar()
            if not _got:
                raise RuntimeError(
                    '다른 apply가 진행 중(advisory lock 선점 실패) — 동시 실행 금지.')
            session.execute(text(
                'CREATE TABLE IF NOT EXISTS "branch_decision_index" ('
                "level text, branch_id text, seq int, then_code text,"
                "cond_type text, dto_field text, op text, value text,"
                "source_text text, version text,"
                " role text DEFAULT 'discriminator',"
                " grade text DEFAULT 'named')"))
            # [P1-B] 기존 테이블엔 CREATE IF NOT EXISTS가 컬럼을 못 더한다
            # — role 층(discriminator/qualifier/eliminator) 소급 추가.
            session.execute(text(
                'ALTER TABLE "branch_decision_index"'
                " ADD COLUMN IF NOT EXISTS role text DEFAULT 'discriminator'"))
            session.execute(text(
                'ALTER TABLE "branch_decision_index"'
                " ADD COLUMN IF NOT EXISTS grade text DEFAULT 'named'"))
            session.execute(text(
                'ALTER TABLE "branch_decision_index"'
                " ADD COLUMN IF NOT EXISTS alt_group text DEFAULT ''"))
            session.execute(text(
                'ALTER TABLE "branch_decision_index"'
                " ADD COLUMN IF NOT EXISTS alt_kind text DEFAULT ''"))
            # 반복 재기록으로 테이블이 부풀면 DELETE가 statement timeout에
            # 걸린다(실측 2회: 일괄 → ctid 청크 300s까지 실패). 다른 버전
            # 행이 없으면 TRUNCATE — 튜플 단위 작업이 없어 즉시 끝나고
            # 죽은 튜플 부풀림도 함께 청소된다. 락 대기는 10s에서 명확히
            # 끊는다(무한 대기 대신 원인 노출 — 백엔드 세션 점유 등).
            session.execute(text("SET LOCAL statement_timeout = '300s'"))
            session.execute(text("SET LOCAL lock_timeout = '10s'"))
            other_versions = session.execute(text(
                'SELECT count(*) FROM "branch_decision_index"'
                " WHERE version <> :v"), {"v": "parser-v1"}).scalar() or 0
            if other_versions == 0:
                session.execute(text('TRUNCATE TABLE "branch_decision_index"'))
            else:
                while True:
                    deleted = session.execute(text(
                        'DELETE FROM "branch_decision_index" WHERE ctid IN ('
                        'SELECT ctid FROM "branch_decision_index"'
                        " WHERE version = :v LIMIT 2000)"), {"v": "parser-v1"})
                    if (deleted.rowcount or 0) == 0:
                        break
            # 9,296행 개별 INSERT는 원거리 DB에서 순단에 취약(실측 1회
            # 실패) — 아래 execute_values 일괄 전송이 정본(구 insert_sql
            # executemany는 [12회차] 인프라 이행으로 소멸).
            # [12회차 3-수리·재발 방지] INSERT 파라미터 정규화 — add()를
            # 거치지 않고 rows/out에 직접 append하는 경로(법정 주·BTI·
            # 거울 배제·qualifier·quant·CNEN 등)는 신설 컬럼 키를 갖지
            # 않는다. executemany는 파라미터 그룹 하나만 키가 비어도
            # **배치 전량이 실패**하고(메인 실측: 첫 재컴파일 exit 0인데
            # 테이블 무변경) 조용히 넘어간다. 삽입 직전 한 번 채워서
            # 향후 신설 경로까지 자동 커버한다(상설 안전장치).
            _row_defaults = {"role": "discriminator", "grade": "named",
                             "alt_group": "", "alt_kind": ""}
            for _r_ins in out:
                for _k_ins, _v_ins in _row_defaults.items():
                    _r_ins.setdefault(_k_ins, _v_ins)
            # [메인 그래프트 재이식 3차 — 순단 내성] execute_values 단문+청크 커밋+재시도.
            from psycopg2.extras import execute_values
            _cols = ("level", "branch_id", "seq", "then_code", "cond_type",
                     "dto_field", "op", "value", "source_text", "version",
                     "role", "grade", "alt_group", "alt_kind")
            _ev_sql = ('INSERT INTO "branch_decision_index" ('
                       + ", ".join(_cols) + ") VALUES %s")
            session.commit()
            _retries = 0
            _start = 0
            while _start < len(out):
                try:
                    _chunk = [tuple(r.get(c) for c in _cols)
                              for r in out[_start:_start + 2000]]
                    _dbapi = session.connection().connection
                    with _dbapi.cursor() as _cur:
                        execute_values(_cur, _ev_sql, _chunk, page_size=500)
                    session.commit()
                    _start += 2000
                    print(f"   … INSERT {min(_start, len(out))}/{len(out)}", flush=True)
                except Exception as _ins_err:  # noqa: BLE001
                    _retries += 1
                    if _retries > 10:
                        raise
                    print(f"   ! 순단 감지({type(_ins_err).__name__}) — {_start}행부터 재개 ({_retries}/10)", flush=True)
                    try:
                        session.rollback()
                        session.close()
                    except Exception:  # noqa: BLE001
                        pass
                    import time as _t
                    _t.sleep(3)
        print(f"-> branch_decision_index에 {len(out)}행 기록")
    audit_dir = Path(__file__).resolve().parents[4] / "artifacts"
    audit_dir.mkdir(exist_ok=True)
    (audit_dir / "decision_table_audit.json").write_text(
        json.dumps({"groups": len(groups), "rows": len(out), "per_level": per_level,
                    "cond_types": cond_types}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
