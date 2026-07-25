"""Pre-classification route hints for CN candidate retrieval."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence

from bussiness_logic.utils.json_types import JsonValue


ChapterIndexRowsProvider = Callable[[], Sequence[Mapping[str, object]]]

# typed processing_state 판정 어휘 — CN 상태어(관세 레지스터)의 폐쇄 집합.
# 제품/챕터 하드코딩이 아니라 상태 축의 어휘 사전이다.
_RAW_STATE_WORDS = frozenset({
    "raw", "fresh", "frozen", "chilled", "minced", "dried", "live", "whole",
})
_PREPARED_STATE_WORDS = frozenset({
    "prepared", "cooked", "seasoned", "smoked", "roasted", "boiled", "fried",
    "steamed", "preserved", "processed", "instant",
})
# [챕터 게이트 재적용 · 07-23 설계자 "Domain_Router 읽게 한다며"] 식품
# 권위 라벨(식약처 표시 실물) 존재 검사 — 발동 신호. 앞선 원복(07-22)은
# hs4 하락 오귀속이었음이 실측 확정(그 런 blocked=[] — 게이트 미발동,
# 하락 원인=지터). search라 접두("옵션 1 ") 무관.
_FOOD_LABEL_PATTERN = re.compile(r"식품\s*의?\s*유형|원재료명")


def _stem_token(token: str) -> str:
    return token[:-1] if len(token) > 3 and token.endswith("s") and not token.endswith("ss") else token


@dataclass(frozen=True, slots=True)
class PreClassificationRouteInput:
    productName: str = ""
    shortDescription: str = ""
    factTexts: tuple[str, ...] = ()
    structuredFactTexts: tuple[str, ...] = ()
    # 지각층(PU)의 typed 상태 필드 — raw/prepared 판정에서 광역 텍스트
    # 정규식보다 우선한다(DTO field precedence). 빈 값 = DTO 침묵 = 폴백.
    processingState: str = ""
    containsSauceOrBroth: bool | None = None

    def BuildSearchText(self) -> str:
        return "\n".join(
            text
            for text in (
                self.productName,
                self.shortDescription,
                *self.factTexts,
                *self.structuredFactTexts,
            )
            if text.strip()
        )


@dataclass(frozen=True, slots=True)
class PreClassificationRoutingBasis:
    method: str
    matchedTerms: tuple[str, ...] = ()
    blockedReason: str = ""
    sourceTable: str = ""
    rowCount: int = 0

    def ToTrace(self) -> dict[str, JsonValue]:
        return {
            "method": self.method,
            "matched_terms": list(self.matchedTerms),
            "blocked_reason": self.blockedReason,
            "source_table": self.sourceTable,
            "row_count": self.rowCount,
        }


@dataclass(frozen=True, slots=True)
class PreClassificationRouteHint:
    candidateHs2: tuple[str, ...] = ()
    blockedHs2: tuple[str, ...] = ()
    domainScopes: tuple[str, ...] = ()
    preGateDomains: tuple[str, ...] = ()
    routingBasis: PreClassificationRoutingBasis = PreClassificationRoutingBasis(
        method="no_route_hint",
    )
    missingFacts: tuple[str, ...] = ()
    # Per-chapter score + matched-term evidence, in candidateHs2 order. Restores
    # the backup Route_dto ``candidate_chapters`` contract so the downstream
    # classifier can respect the router's ranking instead of flattening it.
    candidateChapterDetails: tuple[dict[str, JsonValue], ...] = ()
    # Score-free semantic routing contract. Legacy keyword routing leaves these
    # empty; the staged classifier then follows the existing score contract.
    selectedHs2: str = ""
    alternativeHs2: tuple[str, ...] = ()
    semanticDecision: dict[str, JsonValue] = field(default_factory=dict)

    def ToTrace(self) -> dict[str, JsonValue]:
        return {
            "allowed_hs2": list(self.candidateHs2),
            "blocked_hs2": list(self.blockedHs2),
            "domain_scopes": list(self.domainScopes),
            "pre_gate_domains": list(self.preGateDomains),
            "routing_basis": self.routingBasis.ToTrace(),
            "missing_facts": list(self.missingFacts),
            "candidate_chapter_details": list(self.candidateChapterDetails),
            "selected_hs2": self.selectedHs2,
            "alternative_hs2": list(self.alternativeHs2),
            "semantic_decision": dict(self.semanticDecision),
        }


@dataclass(frozen=True, slots=True)
class RouteRule:
    hs2: str
    domainScope: str
    pattern: re.Pattern[str]
    preGateDomains: tuple[str, ...] = ()


ROUTE_RULES: tuple[RouteRule, ...] = (
    RouteRule(
        hs2="19",
        domainScope="food",
        pattern=re.compile(r"라면|면류|유탕면|\bnoodles?\b|\bpasta\b", re.I),
    ),
    RouteRule(
        hs2="19",
        domainScope="food",
        pattern=re.compile(r"떡볶이|떡류|빵류|인절미|(?<!호)빵"),
    ),
    RouteRule(
        hs2="16",
        domainScope="food",
        pattern=re.compile(r"주꾸미|쭈꾸미|꼬막장|생선구이|멘보샤|가자미구이|구운 가자미"),
        preGateDomains=("animal_origin",),
    ),
    RouteRule(
        hs2="21",
        domainScope="food",
        pattern=re.compile(r"오징어\s*무국|무국|비빔장|soup|broth|stew", re.I),
    ),
    RouteRule(
        hs2="33",
        domainScope="cosmetics",
        pattern=re.compile(
            r"\b(cosmetic|skincare|cream|lotion|toner|essence|shampoo)\b|화장품|크림|로션|토너|에센스|샴푸",
            re.I,
        ),
    ),
)

PROCESSED_SIGNAL_PATTERN = re.compile(
    r"\b(prepared|processed|cooked|fried|seasoned|sauce)\b|가공|조리|볶음|구이|양념|소스",
    re.I,
)
RAW_INGREDIENT_SIGNAL_PATTERN = re.compile(
    r"\b(raw|uncooked|raw fish|raw seafood|raw material|raw ingredient|raw product|"
    r"frozen|fresh|diced|minced|fillet|필렛|필레|다진|생|생것|국산|냉동|냉장|"
    r"원물|원료)\b|대구|새우|오징어|꼬막|주꾸미|새우살|연어",
    re.I,
)
COOKED_SIGNAL_PATTERN = re.compile(
    r"\b(prepared|processed|cooked|fried|seasoned|sauce|tempura|stewed|roasted|grilled|braised|baked|boiled|"
    r"볶음|조리|구이|양념|소스|튀김|찜|조림)\b|가공",
    re.I,
)
RAW_ANIMAL_CHAPTER_PATTERN = re.compile(
    r"\b(fish|seafood|mollusc|octopus|squid|shrimp)\b|어류|수산물|연체동물|주꾸미|쭈꾸미|오징어|새우",
    re.I,
)

CHAPTER_DOMAIN_FALLBACK: dict[str, tuple[str, ...]] = {
    "01": ("animal_origin",),
    "02": ("food", "animal_origin"),
    "03": ("food", "animal_origin"),
    "04": ("food", "animal_origin"),
    "05": ("animal_origin",),
    "06": ("food",),
    "07": ("food",),
    "08": ("food",),
    "09": ("food",),
    "10": ("food",),
    "11": ("food",),
    "12": ("food",),
    "13": ("food",),
    "14": ("food",),
    "15": ("food",),
    "16": ("food", "animal_origin"),
    "17": ("food",),
    "18": ("food",),
    "19": ("food",),
    "20": ("food",),
    "21": ("food",),
    "22": ("food",),
    "23": ("food", "animal_origin"),
    "24": ("food",),
    "33": ("cosmetics",),
}

# [8회차-1 (가) 철거 → 11회차-2 §1-A 잔해 소멸] PRODUCT_FORM_TO_HS2
# (낙지볶음→16·국수→19·(?<!중)국→21 등) 전량 철거. 최중량 하드코딩이자
# 식품 hs2의 숨은 기둥이었다(합격선 3: 철거 후 회귀선 유지가 검증 대상).
# 형태→챕터 신호는 라우터 4층(중의 판별권 박탈·구문 흡수·조건부 자격·
# 사전 경유)과 cn_chapter_index 원천 어휘가 승계한다. 재유입 금지 —
# 규칙 대장(handoff/RULE_LEDGER.md) 대조 감사.

CONDIMENT_PRODUCT_NAME_PATTERN = re.compile(
    r"\b(condiment|seasoning sauce|sauce)\b|비빔장|양념장|소스|[가-힣]{1,16}장(?:\s|$)",
    re.I,
)
CONDIMENT_CONTEXT_PATTERN = re.compile(
    r"\b(condiment|seasoning|sauce)\b|비빔|양념|소스|조미",
    re.I,
)
CONDIMENT_PRODUCT_FORM_BONUS = 80.0

GENERIC_CHAPTER_KEYWORD_STOPLIST = {
    "animal",
    "edible",
    "included",
    "miscellaneous",
    "origin",
    "other",
    "prepared",
    "preparation",
    "preparations",
    "product",
    "products",
    "specified",
}


_DERIVED_KW_CACHE: dict | None = None


def _derived_chapter_keywords() -> dict[str, list[str]]:
    """Retired lexical-router compatibility hook.

    SemanticChapterRouter is the runtime authority. The removed workstation
    artifact must not silently add lexical terms when this legacy class is used
    by an old diagnostic caller.
    """
    global _DERIVED_KW_CACHE
    if _DERIVED_KW_CACHE is None:
        _DERIVED_KW_CACHE = {}
    return _DERIVED_KW_CACHE


class PreClassificationDomainRouter:
    """Small deterministic route DTO builder before Beam retrieval."""

    def __init__(
        self,
        chapterRowsProvider: ChapterIndexRowsProvider | None = None,
    ) -> None:
        self._chapterRowsProvider = chapterRowsProvider

    def Route(
        self,
        routeInput: PreClassificationRouteInput,
    ) -> PreClassificationRouteHint:
        searchText = routeInput.BuildSearchText()
        if not searchText.strip():
            return PreClassificationRouteHint()

        chapterRows = self._LoadChapterRows()
        if chapterRows:
            routeHint = self._RouteWithChapterIndex(
                searchText,
                chapterRows,
                processedOverride=self._dto_processed_override(
                    routeInput.processingState,
                    routeInput.containsSauceOrBroth,
                ),
            )
            if routeHint.candidateHs2:
                return routeHint

        return self._RouteWithRules(
            searchText,
            rowCount=len(chapterRows),
        )

    def _RouteWithRules(
        self,
        searchText: str,
        *,
        rowCount: int = 0,
    ) -> PreClassificationRouteHint:
        candidateHs2: list[str] = []
        domainScopes: list[str] = []
        preGateDomains: list[str] = []
        matchedTerms: list[str] = []
        matchedByChapter: dict[str, list[str]] = {}

        for rule in ROUTE_RULES:
            match = rule.pattern.search(searchText)
            if match is None:
                continue
            self._AppendUnique(candidateHs2, rule.hs2)
            self._AppendUnique(domainScopes, rule.domainScope)
            for domain in rule.preGateDomains:
                self._AppendUnique(preGateDomains, domain)
            self._AppendUnique(matchedTerms, match.group(0))
            matchedByChapter.setdefault(rule.hs2, []).append(match.group(0))

        blockedHs2: list[str] = []
        blockedReason = ""
        if (
            PROCESSED_SIGNAL_PATTERN.search(searchText)
            and RAW_ANIMAL_CHAPTER_PATTERN.search(searchText)
            and "16" in candidateHs2
        ):
            blockedHs2.append("03")
            blockedReason = "processed_animal_origin_food_prefers_prepared_chapter"

        missingFacts = (
            ("primary_ingredient_ratio",)
            if "animal_origin" in preGateDomains and "%" not in searchText
            else ()
        )
        return PreClassificationRouteHint(
            candidateHs2=tuple(candidateHs2),
            blockedHs2=tuple(blockedHs2),
            domainScopes=tuple(domainScopes),
            preGateDomains=tuple(preGateDomains),
            routingBasis=PreClassificationRoutingBasis(
                method=(
                    "deterministic_keyword_route"
                    if rowCount == 0
                    else "cn_chapter_index_no_match_fallback_keyword_route"
                ),
                matchedTerms=tuple(matchedTerms),
                blockedReason=blockedReason,
                sourceTable="cn_chapter_index" if rowCount else "",
                rowCount=rowCount,
            ),
            missingFacts=missingFacts,
            candidateChapterDetails=tuple(
                {
                    "chapter": chapter,
                    "score": float(len(matchedByChapter.get(chapter, []))),
                    "matched_terms": matchedByChapter.get(chapter, [])[:8],
                }
                for chapter in candidateHs2
            ),
        )

    def _RouteWithChapterIndex(
        self,
        searchText: str,
        chapterRows: Sequence[Mapping[str, object]],
        processedOverride: bool | None = None,
    ) -> PreClassificationRouteHint:
        processed = PROCESSED_SIGNAL_PATTERN.search(searchText) is not None
        # DTO 필드 우선순위(ASAP_ROUTER_RAW_PRECEDENCE, 기본 ON):
        # typed 상태가 raw/prepared를 명시하면 정규식 판정을 대체한다.
        if processedOverride is not None and (
            os.environ.get("ASAP_ROUTER_RAW_PRECEDENCE", "1") or "1"
        ).strip() != "0":
            processed = processedOverride
        bucketScope = self._BucketScopeEnabled()
        scores: dict[str, float] = {}
        scoreBreakdownByChapter: dict[str, dict[str, float]] = {}
        matchedByChapter: dict[str, list[str]] = {}
        blockedHs2: list[str] = []
        blockedReasons: list[str] = []
        domainScopes: list[str] = []
        preGateDomains: list[str] = []
        rowByChapter = {
            chapter: row
            for row in chapterRows
            for chapter in (self._ReadChapter(row),)
            if chapter
        }

        # [8회차-2] 라우터 4층 선계산 — 전부 결정론·원천 어휘(수기 0).
        # 층1 중의 토큰 판별권 박탈: 복수 챕터 keyword에 등장하는 토큰 =
        #   판별력 0 (형제-과반 정화의 라우터판). 전수 교차 기계 산출.
        # 층2 구문 흡수(보조·킬스위치): 타 챕터 매치 구문의 진부분집합인
        #   매치는 흡수(관측 기록).
        # 층3 조건부 자격: 중의 토큰 매치는 챕터-유일 토큰 동반 시만 기여.
        # 층4 관세청 사전 경유: 한글 원문 → 표준품명 사전(hs6) 공적
        #   disambiguator — 해당 챕터에 유일-동반 자격 부여.
        _l4_on = (os.environ.get("ASAP_ROUTER_L4", "1") or "1").strip() != "0"
        _absorb_on = (os.environ.get(
            "ASAP_ROUTER_PHRASE_ABSORB", "1") or "1").strip() != "0"
        _tokenOwners: dict[str, set] = {}
        _termOwners: dict[str, set] = {}
        _scopeOwners: dict[str, set] = {}
        _kwByChapter: dict[str, list[str]] = {}
        if _l4_on:
            # 소유 수 계산 전 '원료↔조제 가족' 접기 — 같은 종 어휘가 원료
            # 챕터(02/03…)와 조제 챕터(16…)에 정당 공유되는 구조를 중의로
            # 오판하면 식품 챕터가 대량 실격된다(새우살 03·16 12→4 실측).
            # 가족 관계는 cn_chapter_index의 prepared_food_redirect_chapters
            # 컬럼 원천으로 기계 도출 — 수기 0.
            _fam_parent: dict[str, str] = {}

            def _fam_find(c5: str) -> str:
                while _fam_parent.get(c5, c5) != c5:
                    c5 = _fam_parent.get(c5, c5)
                return c5

            for _row4 in chapterRows:
                _ch4 = self._ReadChapter(_row4)
                if not _ch4:
                    continue
                for _rd4 in self._SplitValues(
                        _row4.get("prepared_food_redirect_chapters")):
                    _rd4 = re.sub(r"\D", "", str(_rd4))[:2]
                    if len(_rd4) == 2:
                        _ra, _rb = _fam_find(_ch4), _fam_find(_rd4)
                        if _ra != _rb:
                            _fam_parent[_ra] = _rb
            _fam_rep = {}
            for _row4 in chapterRows:
                _ch4 = self._ReadChapter(_row4)
                if _ch4:
                    _fam_rep[_ch4] = _fam_find(_ch4)
            for _row4 in chapterRows:
                _ch4 = self._ReadChapter(_row4)
                if not _ch4:
                    continue
                _terms4 = self._FilterChapterKeywordTerms(
                    self._SplitValues(_row4.get("chapter_keywords")))
                _terms4 = list(dict.fromkeys(
                    [*_terms4, *_derived_chapter_keywords().get(_ch4, [])]))
                for _t4 in _terms4:
                    for _tok4 in str(_t4).lower().split():
                        _tokenOwners.setdefault(_tok4, set()).add(
                            _fam_rep.get(_ch4, _ch4))
                    if " " in str(_t4):
                        # 구문(2그램+) 소유 지도 — 구문 자체가 유일 가족
                        # 소유면 토큰 중의성과 무관하게 판별 자격(층3에서
                        # 'pencil lead'가 pencil·lead 각각의 중의로 살해
                        # 되던 결함의 처방 — 구문 우선 원칙의 층3판).
                        _termOwners.setdefault(
                            str(_t4).lower(), set()).add(
                            _fam_rep.get(_ch4, _ch4))
                _kwByChapter[_ch4] = self._TermMatches(_terms4, searchText)
                # [9회차 §1] 만능 토큰 소탕 — raw/prepared scope lane도
                # 동일 전수 교차. 'prepared'가 층1(키워드 lane 한정)을
                # 탈출해 전 챕터에 2~6점을 공급한 실측(낙지볶음 ch02/05/
                # 06/23)의 처방: 수기 스톱워드가 아니라 같은 소유-가족
                # 기계가 전 계급을 포획한다. processed '판정'(전역
                # boolean)은 무관 — 챕터별 점수 기여만 박탈.
                for _col1 in ("raw_scope_signals", "prepared_scope_signals"):
                    for _t1 in self._SplitValues(_row4.get(_col1)):
                        for _tok1 in str(_t1).lower().split():
                            _scopeOwners.setdefault(_tok1, set()).add(
                                _fam_rep.get(_ch4, _ch4))
            _ambiguous = {tok for tok, owners in _tokenOwners.items()
                          if len(owners) >= 2}
            _scope_universal = {tok for tok, owners in _scopeOwners.items()
                                if len(owners) >= 2}
            # 층2: 흡수 — 매치 구문 토큰집합의 진부분집합(타 챕터) 제거
            _absorbed: dict[str, list[str]] = {}
            if _absorb_on:
                _all_matches = [(ch2, m2, frozenset(m2.lower().split()))
                                for ch2, ms in _kwByChapter.items()
                                for m2 in ms]
                for ch2, m2, s2 in _all_matches:
                    for ch3, m3, s3 in _all_matches:
                        if ch2 != ch3 and s2 < s3:
                            _kwByChapter[ch2] = [
                                x for x in _kwByChapter[ch2] if x != m2]
                            _absorbed.setdefault(ch2, []).append(
                                f"absorbed:{m2}<{m3}")
                            break
            # 층4: 사전 경유 — 한글 원문 문자열의 사전 표제 exact 대응
            _dict_chapters: dict[str, str] = {}
            if (os.environ.get("ASAP_ROUTER_DICT", "1") or "1").strip() != "0":
                try:
                    from bussiness_logic.product.services.term_bridge import (
                        _exact_index, _load_dict, _norm_key)
                    _idx = _exact_index()
                    _rows_d = _load_dict()
                    for _seg in re.findall(r"[가-힣][가-힣\s]{1,20}", searchText):
                        for _key in (_norm_key(_seg), *(
                                _norm_key(w) for w in _seg.split())):
                            for _i_d in _idx.get(_key, []):
                                _hs6_d = re.sub(
                                    r"\D", "", str(_rows_d[_i_d].get("hs6") or ""))
                                if len(_hs6_d) >= 2:
                                    _dict_chapters.setdefault(
                                        _hs6_d[:2], _key)
                except Exception:  # noqa: BLE001 — 사전 부재 = 층4 no-op
                    _dict_chapters = {}
        else:
            _ambiguous = set()
            _scope_universal = set()
            _absorbed = {}
            _dict_chapters = {}

        _raw_side: set = set()
        _prep_side: set = set()
        for _row_p in chapterRows:
            _ch_p = self._ReadChapter(_row_p)
            _rds_p = [re.sub(r"\D", "", str(x))[:2] for x in self._SplitValues(
                _row_p.get("prepared_food_redirect_chapters"))]
            _rds_p = [x for x in _rds_p if len(x) == 2]
            if _ch_p and _rds_p:
                _raw_side.add(_ch_p)
                _prep_side.update(_rds_p)
        # 원물 판정 = redirect 보유 − 지목 차집합: 조제 챕터끼리의 사슬
        # (16→19;20;21)로 16·20·21이 보유 측에 들어가는 원천 구조 실측 —
        # '지목받은 챕터'는 조제 측이므로 원물 집합에서 제외한다.
        _raw_only = _raw_side - _prep_side

        for row in chapterRows:
            chapter = self._ReadChapter(row)
            if not chapter:
                continue

            keywordMatches = self._TermMatches(
                list(dict.fromkeys([
                    *self._FilterChapterKeywordTerms(
                        self._SplitValues(row.get("chapter_keywords")),
                    ),
                    *_derived_chapter_keywords().get(chapter, []),
                ])),
                searchText,
            )
            rawMatches = self._TermMatches(
                self._SplitValues(row.get("raw_scope_signals")),
                searchText,
            )
            preparedMatches = self._TermMatches(
                self._SplitValues(row.get("prepared_scope_signals")),
                searchText,
            )
            redirects = self._SplitValues(
                row.get("prepared_food_redirect_chapters"),
            )
            guardrailText = str(row.get("routing_guardrails") or "").lower()
            if (
                processed
                and redirects
                and "before raw ingredient chapter" in guardrailText
                and (keywordMatches or rawMatches)
                and not self._is_raw_ingredient_case(searchText)
            ):
                self._AppendUnique(
                    blockedReasons,
                    "processed_product_guardrail_redirect",
                )
                # redirect 보너스는 원료 챕터 행마다 +5씩 누적된다(02·03이
                # 같은 16을 가리키면 +10) — 쪽갈비 breakdown에서 16/19/20/21에
                # 일괄 +10이 뿌려진 원인. A/B용 게이트: =0이면 보너스 없이
                # blockedReasons 마킹만 남긴다. ASAP_ROUTER_GUARDRAIL_REDIRECT=0
                # A/B 실측(2026-07-14, 식품 22 쌍런)으로 기본 OFF 확정:
                # OFF 95/82/55/57 vs ON 86/73/45/48 — 원료 행마다 +5 누적이
                # 재첩국·꼬막장(21류)을 16류로 납치. =1로만 재활성.
                _redirect_bonus_on = (
                    os.environ.get("ASAP_ROUTER_GUARDRAIL_REDIRECT", "0") or "0"
                ).strip() == "1"
                for redirect in redirects:
                    redirectChapter = re.sub(r"\D", "", redirect)[:2].zfill(2)
                    if redirectChapter:
                        if _redirect_bonus_on:
                            self._AddScore(
                                scores,
                                scoreBreakdownByChapter,
                                chapter=redirectChapter,
                                amount=5.0,
                                source="guardrail_redirect",
                            )
                        matchedByChapter.setdefault(redirectChapter, []).append(
                            "prepared_food_redirect_bonus",
                        )
                if not bucketScope:
                    self._AppendUnique(blockedHs2, chapter)
                    continue
                # Bucket mode: the redirect bonus above stays as ranking
                # pressure, but the raw chapter keeps its own evidence score —
                # a "processed" page word must not erase the chapter from the
                # recall boundary (measured: organic pepper lost ch07 to 20).

            # 키워드 변형 중복 과금 방지: 'meat/offal/meat offal/edible meat/
            # meat edible'은 한 개념 군집인데 5회 과금되어 쪽갈비 ch02(25)가
            # ch16(16)을 뒤집었다(breakdown 실측). 토큰이 겹치는 매칭을 개념
            # 군집으로 병합해 군집당 1회만 센다. ASAP_ROUTER_KEYWORD_DEDUP=0 복귀.
            if (os.environ.get("ASAP_ROUTER_KEYWORD_DEDUP", "1") or "1").strip() != "0":
                concept_groups: list[set] = []
                deduped: list[str] = []
                for term in sorted(keywordMatches, key=lambda s: -len(s)):
                    toks = {w for w in re.findall(r"[a-z가-힣]+", term.lower()) if len(w) >= 2}
                    merged = False
                    for g in concept_groups:
                        if toks & g:
                            g |= toks
                            merged = True
                            break
                    if not merged:
                        concept_groups.append(set(toks))
                        deduped.append(term)
                keywordMatches = deduped
            # [8회차-2] 층1·3·4 적용 — 층2(흡수)는 선계산 반영분 사용.
            if _l4_on:
                if _absorb_on and chapter in _kwByChapter:
                    _abs_set = {a.split(":", 1)[1].split("<", 1)[0]
                                for a in _absorbed.get(chapter, [])}
                    keywordMatches = [
                        m for m in keywordMatches if m not in _abs_set]
                _unique_m = [
                    m for m in keywordMatches
                    if any(tok not in _ambiguous
                           for tok in m.lower().split())
                    or (" " in m
                        and len(_termOwners.get(m.lower(), ())) <= 1)]
                _ambig_m = [m for m in keywordMatches if m not in _unique_m]
                _dict_hit = chapter in _dict_chapters
                # 층3 조건부 자격: 중의 매치는 유일 동반 또는 사전 자격 시만
                if _unique_m or _dict_hit:
                    keywordMatches = _unique_m + _ambig_m
                else:
                    keywordMatches = []
                    if _ambig_m:
                        self._AppendUnique(
                            matchedByChapter.setdefault(chapter, []),
                            "ambiguous_only_disqualified:"
                            + ",".join(_ambig_m[:3]))
                for _a_rec in _absorbed.get(chapter, []):
                    self._AppendUnique(
                        matchedByChapter.setdefault(chapter, []), _a_rec)
            keywordScore = float(len(keywordMatches) * 4)
            # [9회차 §1] 다가족 공유 신호는 챕터 점수 기여 박탈 (매치
            # 기록·processed 판정은 유지). 서명 universal_scope_muted.
            if _l4_on:
                _raw_scored = [m for m in rawMatches
                               if any(tok not in _scope_universal
                                      for tok in m.lower().split())]
                _prep_scored = [m for m in preparedMatches
                                if any(tok not in _scope_universal
                                       for tok in m.lower().split())]
                _muted = [m for m in (*rawMatches, *preparedMatches)
                          if m not in _raw_scored and m not in _prep_scored]
                if _muted:
                    self._AppendUnique(
                        matchedByChapter.setdefault(chapter, []),
                        "universal_scope_muted:" + ",".join(
                            sorted(set(_muted))[:4]))
            else:
                _raw_scored, _prep_scored = rawMatches, preparedMatches
            rawScore = float(len(_raw_scored) * (1 if processed else 4))
            # [11회차-2 §1-A] formScore 소멸 — 원천이던 PRODUCT_FORM_TO_HS2
            # 는 8회차에 철거(빈 튜플)돼 이후 항상 0이었다. 최근 2런 58건
            # 서명 0(:prepared_aquatic_animal_product 등 reason 마커 0)
            # 확인 후 상수·소비부 3곳 동시 제거.
            score = keywordScore + rawScore
            if _l4_on and chapter in _dict_chapters:
                # [9회차 §3] 층4 상태 조건 — 사전은 원물 표제 중심이라
                # 조리품에서 구조적 raw 편향(dict:낙지→ch03 실측). 상품이
                # processed면 원물 챕터(redirect 보유 측)에는 gate 불부여,
                # 그 챕터의 redirect 조제 측으로 자격 재배정 — 수기 매핑
                # 없이 상태축×챕터 성질(redirect 컬럼) 대조 결정론.
                _dict_ok = not (processed and chapter in _raw_only)
                if _dict_ok:
                    score += 4.0
                    self._AddScore(
                        scores, scoreBreakdownByChapter, chapter=chapter,
                        amount=4.0, source="dictionary_gate")
                    self._AppendUnique(
                        matchedByChapter.setdefault(chapter, []),
                        f"dict:{_dict_chapters[chapter]}")
                else:
                    for _rd_d in self._SplitValues(
                            row.get("prepared_food_redirect_chapters")):
                        _rd_d = re.sub(r"\D", "", str(_rd_d))[:2]
                        if len(_rd_d) == 2:
                            self._AddScore(
                                scores, scoreBreakdownByChapter,
                                chapter=_rd_d, amount=4.0,
                                source="dictionary_gate_redirect")
                            self._AppendUnique(
                                matchedByChapter.setdefault(_rd_d, []),
                                f"dict_redirect:{_dict_chapters[chapter]}"
                                f":{chapter}->{_rd_d}")
            if processed:
                preparedScore = float(len(_prep_scored) * 2)
                score += preparedScore
            else:
                preparedScore = 0.0
            if chapter == "21" and self._HasCondimentProductForm(searchText):
                score += CONDIMENT_PRODUCT_FORM_BONUS
                self._AppendUnique(
                    matchedByChapter.setdefault(chapter, []),
                    "condiment_product_form_bonus",
                )
                self._AddScore(
                    scores,
                    scoreBreakdownByChapter,
                    chapter=chapter,
                    amount=CONDIMENT_PRODUCT_FORM_BONUS,
                    source="product_form_bonus",
                )
            if score <= 0:
                continue
            self._AddScore(
                scores,
                scoreBreakdownByChapter,
                chapter=chapter,
                amount=keywordScore,
                source="chapter_keywords",
            )
            self._AddScore(
                scores,
                scoreBreakdownByChapter,
                chapter=chapter,
                amount=rawScore,
                source="raw_scope",
            )
            self._AddScore(
                scores,
                scoreBreakdownByChapter,
                chapter=chapter,
                amount=preparedScore,
                source="prepared_scope",
            )
            matchedByChapter.setdefault(chapter, []).extend(
                keywordMatches + rawMatches + preparedMatches,
            )

        # [9회차 P2] 원료↔조제 동점의 이산 방향 규칙 — 법조 근거: 16류
        # 주1(육·어류 등의 '조제(prepared) 식료품'은 2류·3류가 아니라
        # 16류) 및 각 조제류 총설: 조리·조제 사실이 성립하면 조제류가
        # 원료류에 우선한다. redirect 가족 내 동점에서만 발동 — 조제
        # 신호(processed 판정: PROCESSED_SIGNAL_PATTERN + DTO typed
        # override) 존재 → 조제 측(redirect 대상) 선두, 부재 → 원료 측.
        # 코드순은 최후 폴백. 서명 redirect_tie:{prepared|raw}_first.
        def _tie_dir(chapter: str) -> int:
            if processed and chapter in _prep_side:
                return 0
            if (not processed) and chapter in _raw_only:
                return 0
            return 1

        # [9회차 §2] 동점의 숫자순 해소 금지 — 상태 모순 강등(이산).
        # DTO 상태가 cooked/prepared 계열(processed 판정)이면 원물 챕터는
        # 동점에서 패배한다. '원물' 판정은 수기 목록이 아니라 redirect
        # 컬럼 원천(_raw_side = prepared_food_redirect_chapters 보유 챕터)
        # — 16류 주1(조제 식료품은 원료류가 아니라 16류) 계보의 라우터판.
        # 코드순은 최후 폴백으로만 남는다(결정론 요건).
        def _raw_loss(chapter: str) -> int:
            return 1 if (processed and chapter in _raw_only) else 0

        # [10회차-1B] 동점 보조키: 최장 '정체 구문' 매치 우위 — 구문 우선
        # 원칙(층2)의 동점판. 떡볶이 실측: ch16 8.0('sauce' 유니그램) =
        # ch19 8.0('prepared rice meal' 구문) 동점 코드순 납치의 처방.
        # scope 계급(조리·상태 lane) 토큰만의 매치는 구문 길이 0 취급 —
        # 수기 어휘 0 (lane·구문 길이 전부 기계 사실).
        def _max_phrase(chapter: str) -> int:
            best = 0
            for _m_p in _kwByChapter.get(chapter, []):
                _tk_p = str(_m_p).lower().split()
                if all(tok in _scopeOwners for tok in _tk_p):
                    continue
                best = max(best, len(_tk_p))
            return best

        rankedChapters = sorted(
            scores, key=lambda chapter: (
                -scores[chapter], _raw_loss(chapter), _tie_dir(chapter),
                -_max_phrase(chapter), chapter))
        # [9회차 §2 보강] 유일-직격 챕터 창 입장권 — 정체 어휘('soup')를
        # '유일 소유'로 직격한 챕터가 범용 4점 동점군에 밀려 시작창(:5)
        # 밖으로 떨어지는 실측(재첩국 ch21 22위 → 2104 도달 불가)의 처방.
        # 점수 불변·순위 5위 삽입(입장권만 — BTI 소환·G1 계보). 자격은
        # 이산: 매치 중 유일-소유 토큰/구문 보유 ∧ §2 상태 강등 비대상.
        # 서명 window_ticket:{챕터}. 최대 1석 — 창의 잡음 방지 원칙 보존.
        if _l4_on:
            def _has_unique_hit(ch_w: str) -> str:
                # 자격 = '정체' 직격만 — 상태·조리 lane 어휘(_scopeOwners
                # 원천: raw/prepared scope signals)는 입장권 불가('cooked'가
                # ch20 직격 행세로 1석을 가로채 재첩국 ch21 'soup'를 다시
                # 밀어낸 실측). lane 판정은 원천 컬럼 기반 — 수기 0.
                for m_w in _kwByChapter.get(ch_w, []):
                    toks_w = str(m_w).lower().split()
                    if all(tok in _scopeOwners for tok in toks_w):
                        continue
                    if any(tok not in _ambiguous and tok not in _scopeOwners
                           for tok in toks_w) or (
                            len(toks_w) > 1 and len(
                                _termOwners.get(str(m_w).lower(), ())) <= 1):
                        return str(m_w)
                return ""
            _top5 = rankedChapters[:5]
            _ticket = next(
                (c_w for c_w in rankedChapters[5:]
                 if scores.get(c_w, 0) > 0 and not _raw_loss(c_w)
                 and _has_unique_hit(c_w)), "")
            if _ticket:
                rankedChapters = [*_top5[:4], _ticket,
                                  *[c for c in rankedChapters[4:]
                                    if c != _ticket]]
                self._AppendUnique(
                    matchedByChapter.setdefault(_ticket, []),
                    ("window_ticket_prep:" if _ticket in _prep_side
                     else "window_ticket:")
                    + _has_unique_hit(_ticket))
            # [기각 좌표] 창 '안' 조제 측 직격의 서명 일반화는 실측 기각
            # — 면류(우동전골·칼국수)의 'soup' 부수 힌트가 21 동점 교대로
            # 정답을 탈취(A/B 실측). 창밖 티켓(잃을 것 없는 구제)과 창안
            # 개입(경쟁 지형 교란)의 비대칭 — 전복미역국(창안 21, 병합
            # 서열 패배)은 병합 증거화(10회차)의 몫으로 귀속.
        # 서명: 동점 그룹에서 방향 규칙이 실제 순서를 바꾼 챕터에 표기
        for _i_r2, _ch_r2 in enumerate(rankedChapters):
            _peers = [c for c in scores
                      if scores[c] == scores[_ch_r2] and c != _ch_r2]
            if _peers and _tie_dir(_ch_r2) == 0 and any(
                    _tie_dir(c) == 1 and c < _ch_r2 for c in _peers):
                self._AppendUnique(
                    matchedByChapter.setdefault(_ch_r2, []),
                    "redirect_tie:"
                    + ("prepared_first" if processed else "raw_first"))
        # [챕터 게이트 · 07-23 재적용 — cn_chapter_index 정본 소비] 식품
        # 라벨 존재 시 후보 챕터를 domain_scope_candidates의 food 스코프
        # (02~24 실측)로 제한. 두 실물(라벨×테이블 컬럼) 교차·창작 0·점수
        # 무관(in/out). 실측 근거: 쪽갈비 'ribs'→ch72(철강) 8점·비빔밥
        # 84=12점 — 스코프 필터 부재로 비식품 챕터가 점수 진입. 잘린
        # 챕터는 blockedHs2 + 사유 기록(빈 blocked 기전 정상화). 게이트
        # 전멸 시 무적용(보수). ASAP_CHAPTER_GATE=0 복귀.
        if (os.environ.get("ASAP_CHAPTER_GATE", "1") or "1").strip() != "0" \
                and _FOOD_LABEL_PATTERN.search(searchText):
            foodSet = {
                self._ReadChapter(row) for row in chapterRows
                if "food" in self._ReadDomainScopes(
                    row, self._ReadChapter(row))
            }
            gatedIn = [c for c in rankedChapters if c in foodSet]
            if gatedIn:
                for c in rankedChapters[:5]:
                    if c not in foodSet and scores.get(c, 0.0) > 0:
                        self._AppendUnique(blockedHs2, c)
                        blockedReasons.append(f"domain_gate:food_label:{c}")
                rankedChapters = gatedIn
        candidateHs2 = tuple(rankedChapters[:5])
        matchedTerms: list[str] = []
        for chapter in candidateHs2:
            row = rowByChapter.get(chapter, {})
            for domain in self._ReadDomainScopes(row, chapter):
                self._AppendUnique(domainScopes, domain)
                if domain == "animal_origin":
                    self._AppendUnique(preGateDomains, domain)
            for preGate in self._SplitValues(row.get("pre_gate_domain_candidates")):
                self._AppendUnique(preGateDomains, preGate)
            for term in matchedByChapter.get(chapter, []):
                self._AppendUnique(matchedTerms, term)

        # Domain-bucket expansion: every chapter of the routed bucket(s) joins
        # the allowed boundary AFTER the scored top-5, so staged/beam keep the
        # keyword ranking but can no longer lose the answer chapter to it.
        # Scope source is per-row domain_scope_candidates (DB) with the static
        # chapter->domain fallback — no chapter list is hardcoded here.
        method = "cn_chapter_index_keyword_guardrail"
        if bucketScope and domainScopes:
            scopeSet = set(domainScopes)
            expanded = list(candidateHs2)
            for row in chapterRows:
                chapter = self._ReadChapter(row)
                if not chapter or chapter in expanded:
                    continue
                if scopeSet & set(self._ReadDomainScopes(row, chapter)):
                    expanded.append(chapter)
            candidateHs2 = tuple(expanded)
            method = "cn_chapter_index_bucket_scope"

        candidateChapterDetails = tuple(
            {
                "chapter": chapter,
                "score": round(scores.get(chapter, 0.0), 2),
                "matched_terms": list(dict.fromkeys(matchedByChapter.get(chapter, [])))[:8],
                "score_breakdown": {
                    source: round(amount, 2)
                    for source, amount in scoreBreakdownByChapter.get(chapter, {}).items()
                    if amount
                },
            }
            for chapter in candidateHs2
        )
        return PreClassificationRouteHint(
            candidateHs2=candidateHs2,
            blockedHs2=tuple(blockedHs2),
            domainScopes=tuple(domainScopes),
            preGateDomains=tuple(preGateDomains),
            routingBasis=PreClassificationRoutingBasis(
                method=method,
                matchedTerms=tuple(matchedTerms),
                blockedReason=";".join(blockedReasons),
                sourceTable="cn_chapter_index",
                rowCount=len(chapterRows),
            ),
            candidateChapterDetails=candidateChapterDetails,
            missingFacts=(
                ("primary_ingredient_ratio",)
                if "animal_origin" in preGateDomains and "%" not in searchText
                else ()
            ),
        )

    def _LoadChapterRows(self) -> tuple[Mapping[str, object], ...]:
        if self._chapterRowsProvider is None:
            return ()
        return tuple(self._chapterRowsProvider())

    @staticmethod
    def _ReadChapter(row: Mapping[str, object]) -> str:
        chapter = re.sub(r"\D", "", str(row.get("chapter") or ""))[:2]
        return chapter.zfill(2) if chapter else ""

    @staticmethod
    def _ReadDomainScopes(
        row: Mapping[str, object],
        chapter: str,
    ) -> tuple[str, ...]:
        domains = PreClassificationDomainRouter._SplitValues(
            row.get("domain_scope_candidates"),
        )
        if domains:
            return tuple(domains)
        return CHAPTER_DOMAIN_FALLBACK.get(chapter, ())

    @staticmethod
    def _SplitValues(value: object) -> list[str]:
        values: list[str] = []
        if value is None:
            return values
        if isinstance(value, (list, tuple, set)):
            for item in value:
                for nestedItem in PreClassificationDomainRouter._SplitValues(item):
                    if nestedItem not in values:
                        values.append(nestedItem)
            return values
        for item in str(value or "").replace("|", ";").replace(",", ";").split(";"):
            text = item.strip()
            if text and text not in values:
                values.append(text)
        return values

    @staticmethod
    def _TermMatches(terms: Sequence[str], haystack: str) -> list[str]:
        matches: list[str] = []
        normalized = re.sub(r"\s+", " ", haystack or "").lower()
        for term in terms:
            termNorm = re.sub(r"\s+", " ", str(term or "").strip().lower())
            if len(termNorm) < 2:
                continue
            if re.fullmatch(r"[a-z0-9][a-z0-9 /'&().-]*", termNorm, flags=re.I):
                pattern = r"(?<![a-z0-9])" + re.escape(termNorm) + r"(?![a-z0-9])"
                matched = re.search(pattern, normalized, flags=re.I) is not None
            else:
                matched = termNorm in normalized
            if matched and term not in matches:
                matches.append(term)
        return matches

    @staticmethod
    def _FilterChapterKeywordTerms(terms: Sequence[str]) -> list[str]:
        filtered: list[str] = []
        for term in terms:
            termNorm = re.sub(r"\s+", " ", str(term or "").strip().lower())
            if not termNorm:
                continue
            if " " not in termNorm and termNorm in GENERIC_CHAPTER_KEYWORD_STOPLIST:
                continue
            filtered.append(term)
        return filtered

    @staticmethod
    def _AppendUnique(values: list[str], value: str) -> None:
        if value and value not in values:
            values.append(value)

    @staticmethod
    def _AddScore(
        scores: dict[str, float],
        scoreBreakdownByChapter: dict[str, dict[str, float]],
        *,
        chapter: str,
        amount: float,
        source: str,
    ) -> None:
        if amount <= 0:
            return
        scores[chapter] = scores.get(chapter, 0.0) + amount
        breakdown = scoreBreakdownByChapter.setdefault(chapter, {})
        breakdown[source] = breakdown.get(source, 0.0) + amount

    @staticmethod
    def _HasCondimentProductForm(searchText: str) -> bool:
        productName = (searchText.splitlines() or [""])[0]
        return (
            CONDIMENT_PRODUCT_NAME_PATTERN.search(productName) is not None
            and CONDIMENT_CONTEXT_PATTERN.search(searchText) is not None
        )

    @staticmethod
    def _BucketScopeEnabled() -> bool:
        """WCO domain-bucket scope: allowed_hs2 = every chapter sharing the
        routed domain bucket (food/cosmetics/... from cn_chapter_index
        domain_scope_candidates), not just the keyword top-5. The keyword
        scores stay as RANKING pressure; the bucket is the recall boundary."""
        return (os.environ.get("ASAP_HS2_BUCKET_SCOPE", "1") or "").strip().lower() not in (
            "0", "false", "no", "off",
        )

    @staticmethod
    def _dto_processed_override(
        processingState: str,
        containsSauceOrBroth: bool | None,
    ) -> bool | None:
        """DTO 필드 우선순위 일반 규칙: typed 상태가 말하면 그걸 따른다.

        True=prepared 확정, False=raw 확정, None=DTO 침묵(정규식 폴백).
        '다진/냉동 대구살'이 마케팅 문구('건강 이유식')의 PROCESSED 정규식
        오발동으로 prepared 취급되던 것의 구조적 처방 — 제품별 분기 없음.
        """
        tokens = {
            _stem_token(w)
            for w in re.findall(r"[a-z]+", str(processingState or "").lower())
        }
        if tokens & _PREPARED_STATE_WORDS or containsSauceOrBroth is True:
            return True
        if tokens and tokens & _RAW_STATE_WORDS:
            return False
        return None

    @staticmethod
    def _is_raw_ingredient_case(searchText: str) -> bool:
        if RAW_ANIMAL_CHAPTER_PATTERN.search(searchText) is None:
            return False
        if COOKED_SIGNAL_PATTERN.search(searchText) is not None:
            return False
        return RAW_INGREDIENT_SIGNAL_PATTERN.search(searchText) is not None


def BuildPreClassificationRouteInput(
    *,
    productName: str,
    shortDescription: str,
    factTexts: Sequence[str],
    structuredProductFacts: Sequence[Mapping[str, object]],
    processingState: str = "",
    containsSauceOrBroth: bool | None = None,
) -> PreClassificationRouteInput:
    return PreClassificationRouteInput(
        processingState=processingState.strip(),
        containsSauceOrBroth=containsSauceOrBroth,
        productName=productName.strip(),
        shortDescription=shortDescription.strip(),
        factTexts=tuple(text.strip() for text in factTexts if text.strip()),
        structuredFactTexts=tuple(
            factText
            for fact in structuredProductFacts
            for factText in (_ReadStructuredFactText(fact),)
            if factText
        ),
    )


def _ReadStructuredFactText(fact: Mapping[str, object]) -> str:
    parts: list[str] = []
    for key in (
        "label",
        "field",
        "field_name",
        "name",
        "value",
        "value_text",
        "normalized_value",
        "text",
    ):
        value = fact.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return " ".join(parts)
