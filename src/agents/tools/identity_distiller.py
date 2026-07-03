"""Distill compact commodity identity from product and encyclopedia evidence."""

from __future__ import annotations

import re

from agents.pipeline_dto import EncyclopediaEvidenceSet, IdentityHintSet


TOKEN_PATTERN = re.compile(r"[0-9A-Za-z가-힣]+")
MOLLUSC_PATTERN = re.compile(r"주꾸미|쭈꾸미|오징어|꼬막|mollusc|octopus|squid", re.I)
NOODLE_PATTERN = re.compile(r"라면|면류|유탕면|국수|noodle|pasta", re.I)
BAKERY_PATTERN = re.compile(r"빵|인절미|떡|bread|bakery|rice cake", re.I)
SOUP_PATTERN = re.compile(r"국|탕|찌개|soup|broth|stew", re.I)
SAUCE_PATTERN = re.compile(r"소스|양념|장|sauce|seasoning|condiment", re.I)
COSMETIC_PATTERN = re.compile(r"화장품|크림|로션|샴푸|cosmetic|cream|lotion|shampoo", re.I)
PROCESSED_PATTERN = re.compile(r"볶음|구이|조리|가공|양념|fried|cooked|prepared|seasoned", re.I)


class IdentityDistillerService:
    def BuildHints(
        self,
        *,
        identityHintId: str,
        productId: str,
        productName: str,
        shortDescription: str,
        classificationText: str,
        encyclopediaEvidence: EncyclopediaEvidenceSet,
    ) -> IdentityHintSet:
        text = "\n".join(
            [
                productName,
                shortDescription,
                classificationText,
                *(
                    f"{entry.title} {entry.description}"
                    for entry in encyclopediaEvidence.entries
                ),
            ],
        )
        ingredientClass = self._IngredientClass(text)
        foodForm = self._FoodForm(text)
        processingState = "processed_or_prepared" if PROCESSED_PATTERN.search(text) else "unknown"
        identityTerms = self._Terms(productName, limit=12)
        compositionTerms = self._Terms(classificationText, limit=20)
        processingTerms = tuple(
            term
            for term in ("볶음", "구이", "조리", "가공", "양념", "fried", "cooked", "prepared")
            if term.lower() in text.lower()
        )
        normalizedDescription = " ".join(
            term
            for term in (ingredientClass, foodForm, processingState)
            if term and term != "unknown"
        )
        return IdentityHintSet(
            identityHintId=identityHintId,
            productId=productId,
            commercialIdentity=productName or shortDescription,
            ingredientClass=ingredientClass,
            foodForm=foodForm,
            processingState=processingState,
            normalizedTariffDescription=normalizedDescription,
            identityTerms=identityTerms,
            compositionTerms=compositionTerms,
            processingTerms=processingTerms,
            confidence=0.6 if identityTerms else 0.2,
        )

    @staticmethod
    def _IngredientClass(text: str) -> str:
        if MOLLUSC_PATTERN.search(text):
            return "mollusc"
        if NOODLE_PATTERN.search(text):
            return "cereal"
        if BAKERY_PATTERN.search(text):
            return "cereal"
        if COSMETIC_PATTERN.search(text):
            return "cosmetic"
        return "other"

    @staticmethod
    def _FoodForm(text: str) -> str:
        if NOODLE_PATTERN.search(text):
            return "noodle"
        if BAKERY_PATTERN.search(text):
            return "bread_pastry"
        if SOUP_PATTERN.search(text):
            return "soup"
        if SAUCE_PATTERN.search(text):
            return "sauce"
        if COSMETIC_PATTERN.search(text):
            return "cosmetic"
        return "other"

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
