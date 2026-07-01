"""Pre-classification route hints for CN candidate retrieval."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Sequence

from agents.pipeline_dto import JsonValue


@dataclass(frozen=True, slots=True)
class PreClassificationRouteInput:
    productName: str = ""
    shortDescription: str = ""
    factTexts: tuple[str, ...] = ()
    structuredFactTexts: tuple[str, ...] = ()

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

    def ToTrace(self) -> dict[str, JsonValue]:
        return {
            "method": self.method,
            "matched_terms": list(self.matchedTerms),
            "blocked_reason": self.blockedReason,
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

    def ToTrace(self) -> dict[str, JsonValue]:
        return {
            "candidate_hs2": list(self.candidateHs2),
            "blocked_hs2": list(self.blockedHs2),
            "domain_scopes": list(self.domainScopes),
            "pre_gate_domains": list(self.preGateDomains),
            "routing_basis": self.routingBasis.ToTrace(),
            "missing_facts": list(self.missingFacts),
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
RAW_ANIMAL_CHAPTER_PATTERN = re.compile(
    r"\b(fish|seafood|mollusc|octopus|squid|shrimp)\b|어류|수산물|연체동물|주꾸미|쭈꾸미|오징어|새우",
    re.I,
)


class PreClassificationDomainRouter:
    """Small deterministic route DTO builder before Beam retrieval."""

    def Route(
        self,
        routeInput: PreClassificationRouteInput,
    ) -> PreClassificationRouteHint:
        searchText = routeInput.BuildSearchText()
        if not searchText.strip():
            return PreClassificationRouteHint()

        candidateHs2: list[str] = []
        domainScopes: list[str] = []
        preGateDomains: list[str] = []
        matchedTerms: list[str] = []

        for rule in ROUTE_RULES:
            match = rule.pattern.search(searchText)
            if match is None:
                continue
            self._AppendUnique(candidateHs2, rule.hs2)
            self._AppendUnique(domainScopes, rule.domainScope)
            for domain in rule.preGateDomains:
                self._AppendUnique(preGateDomains, domain)
            self._AppendUnique(matchedTerms, match.group(0))

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
                method="deterministic_keyword_route",
                matchedTerms=tuple(matchedTerms),
                blockedReason=blockedReason,
            ),
            missingFacts=missingFacts,
        )

    @staticmethod
    def _AppendUnique(values: list[str], value: str) -> None:
        if value and value not in values:
            values.append(value)


def BuildPreClassificationRouteInput(
    *,
    productName: str,
    shortDescription: str,
    factTexts: Sequence[str],
    structuredProductFacts: Sequence[Mapping[str, object]],
) -> PreClassificationRouteInput:
    return PreClassificationRouteInput(
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
