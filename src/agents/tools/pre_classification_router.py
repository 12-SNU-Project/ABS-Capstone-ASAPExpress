"""Pre-classification route hints for CN candidate retrieval."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from agents.pipeline_dto import JsonValue


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

    def ToTrace(self) -> dict[str, JsonValue]:
        return {
            "allowed_hs2": list(self.candidateHs2),
            "blocked_hs2": list(self.blockedHs2),
            "domain_scopes": list(self.domainScopes),
            "pre_gate_domains": list(self.preGateDomains),
            "routing_basis": self.routingBasis.ToTrace(),
            "missing_facts": list(self.missingFacts),
            "candidate_chapter_details": list(self.candidateChapterDetails),
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

PRODUCT_FORM_TO_HS2: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (
        re.compile(
            r"\b(stir[- ]?fried|fried|cooked|seasoned|prepared)\b.{0,40}\b(octopus|squid|mollusc|cockle|shrimp|prawn|crustacean|fish|seafood)\b"
            r"|\b(octopus|squid|mollusc|cockle|shrimp|prawn|crustacean|fish|seafood)\b.{0,40}\b(stir[- ]?fried|fried|cooked|seasoned|prepared)\b"
            r"|낙지.{0,12}볶음|주꾸미.{0,12}볶음|쭈꾸미.{0,12}볶음|오징어.{0,12}볶음|새우.{0,12}볶음|꼬막.{0,12}(장|무침|볶음)",
            re.I,
        ),
        "16",
        "prepared_aquatic_animal_product",
    ),
    (
        re.compile(r"\b(noodle|ramen|pasta|macaroni|spaghetti)\b|라면|유탕면|국수|면류|파스타", re.I),
        "19",
        "cereal_noodle_preparation",
    ),
    (
        re.compile(r"\b(sauce|seasoning|condiment|soup|broth|stock)\b|소스|양념|조미|스프|미역국|(?<!중)국|탕|찌개|육수", re.I),
        "21",
        "miscellaneous_edible_preparation",
    ),
    (
        re.compile(r"\b(sausage|ham|surimi)\b|소시지|햄|어묵|맛살|멘보샤", re.I),
        "16",
        "meat_fish_crustacean_preparation",
    ),
    (
        re.compile(r"\b(dumpling|mandu|stuffed pasta|stuffed noodles)\b|만두|물만두|군만두", re.I),
        "19",
        "stuffed_pasta_cereal_preparation",
    ),
    (
        re.compile(r"\b(jam|pickle|fruit preparation|vegetable preparation)\b|잼|절임|피클|과실가공|채소가공", re.I),
        "20",
        "vegetable_fruit_preparation",
    ),
    (
        re.compile(r"\b(beverage|drink|juice|tea)\b|음료|주스|차음료", re.I),
        "22",
        "beverage",
    ),
    (
        re.compile(r"\b(deodorant|antiperspirant|roll[- ]?on|cosmetic|skincare|perfume|lotion|shampoo|toner|essence)\b|데오드란트|데오도란트|롤온|화장품|스킨케어|향수|로션|샴푸|토너|에센스", re.I),
        "33",
        "cosmetic_toilet_preparation",
    ),
)

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

        for row in chapterRows:
            chapter = self._ReadChapter(row)
            if not chapter:
                continue

            keywordMatches = self._TermMatches(
                self._FilterChapterKeywordTerms(
                    self._SplitValues(row.get("chapter_keywords")),
                ),
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
            formMatches = [
                f"{match.group(0)}:{reason}"
                for pattern, targetChapter, reason in PRODUCT_FORM_TO_HS2
                for match in (pattern.search(searchText),)
                if match is not None and targetChapter == chapter
            ]

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
                _redirect_bonus_on = (
                    os.environ.get("ASAP_ROUTER_GUARDRAIL_REDIRECT", "1") or "1"
                ).strip() != "0"
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
            keywordScore = float(len(keywordMatches) * 4)
            rawScore = float(len(rawMatches) * (1 if processed else 4))
            formScore = float(len(formMatches) * 8)
            score = keywordScore + rawScore + formScore
            if processed:
                preparedScore = float(len(preparedMatches) * 2)
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
            self._AddScore(
                scores,
                scoreBreakdownByChapter,
                chapter=chapter,
                amount=formScore,
                source="product_form",
            )
            matchedByChapter.setdefault(chapter, []).extend(
                keywordMatches + rawMatches + preparedMatches + formMatches,
            )

        rankedChapters = sorted(scores, key=lambda chapter: (-scores[chapter], chapter))
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
