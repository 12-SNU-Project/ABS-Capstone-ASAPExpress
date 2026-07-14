"""Distill compact commodity identity from encyclopedia evidence."""

from __future__ import annotations

import re

from bussiness_logic.pipeline.model.pipeline_dto import (
    DistilledIdentityFacts,
    EncyclopediaEvidenceSet,
)


TOKEN_PATTERN = re.compile(r"[0-9A-Za-z가-힣]+")
PRODUCT_FORM_SIGNAL_PATTERN = re.compile(
    r"noodle|pasta|bread|pastry|cake|sauce|soup|broth|stew|condiment|beverage|cosmetic|cream|lotion|shampoo|면|국수|빵|소스|국|탕|찌개|음료|화장품|크림|로션|샴푸",
    re.I,
)
PROCESSING_SIGNAL_PATTERN = re.compile(
    r"prepared|processed|cooked|fried|roasted|seasoned|marinated|preserved|dried|smoked|frozen|chilled|가공|조리|볶음|구이|양념|냉동|건조|훈제",
    re.I,
)


class IdentityDistillerService:
    def BuildFacts(
        self,
        *,
        distilledIdentityId: str,
        productId: str,
        encyclopediaEvidence: EncyclopediaEvidenceSet,
    ) -> DistilledIdentityFacts:
        text = self._EvidenceText(encyclopediaEvidence)
        identityTerms = self._Terms(text, limit=16)
        return DistilledIdentityFacts(
            distilledIdentityId=distilledIdentityId,
            productId=productId,
            sourceEncyclopediaEvidenceId=encyclopediaEvidence.encyclopediaEvidenceId,
            commercialIdentity=self._CommercialIdentity(encyclopediaEvidence),
            normalizedDescription=" ".join(identityTerms[:12]),
            identityTerms=identityTerms,
            productFormSignalTerms=self._SignalTerms(text, PRODUCT_FORM_SIGNAL_PATTERN),
            processingSignalTerms=self._SignalTerms(text, PROCESSING_SIGNAL_PATTERN),
            sourceTitles=tuple(entry.title for entry in encyclopediaEvidence.entries),
            sourceDescriptions=tuple(entry.description for entry in encyclopediaEvidence.entries),
            sourceLinks=tuple(entry.link for entry in encyclopediaEvidence.entries),
            qualityStatus=encyclopediaEvidence.qualityStatus,
        )

    @staticmethod
    def _EvidenceText(encyclopediaEvidence: EncyclopediaEvidenceSet) -> str:
        return "\n".join(
            f"{entry.title} {entry.description}"
            for entry in encyclopediaEvidence.entries
        )

    @staticmethod
    def _CommercialIdentity(encyclopediaEvidence: EncyclopediaEvidenceSet) -> str:
        for entry in encyclopediaEvidence.entries:
            if entry.title.strip():
                return entry.title.strip()
        return ""

    @staticmethod
    def _Terms(text: str, *, limit: int) -> tuple[str, ...]:
        out: list[str] = []
        for token in TOKEN_PATTERN.findall(text):
            normalized = token.strip()
            if len(normalized) < 2 or normalized in out:
                continue
            out.append(normalized)
            if len(out) >= limit:
                break
        return tuple(out)

    @staticmethod
    def _SignalTerms(text: str, pattern: re.Pattern[str], *, limit: int = 12) -> tuple[str, ...]:
        out: list[str] = []
        for match in pattern.finditer(text):
            term = match.group(0).strip()
            if term and term.lower() not in {item.lower() for item in out}:
                out.append(term)
            if len(out) >= limit:
                break
        return tuple(out)
