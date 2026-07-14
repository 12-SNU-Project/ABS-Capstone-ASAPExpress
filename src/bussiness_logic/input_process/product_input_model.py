"""Product input DTO shared by input preparation and legacy classification."""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, computed_field

from bussiness_logic.utils import NormalizeWhiteSpace, NormalizeWhitespaceLines


FOOD_DOMAIN_SCOPE = "food_16_21"
COSMETICS_DOMAIN_SCOPE = "cosmetics_33"
PRODUCT_DOMAIN_SCOPE_MAP = {
    "food": [FOOD_DOMAIN_SCOPE],
    "cosmetics": [COSMETICS_DOMAIN_SCOPE],
    "ambiguous": [FOOD_DOMAIN_SCOPE, COSMETICS_DOMAIN_SCOPE],
    "unknown": [FOOD_DOMAIN_SCOPE, COSMETICS_DOMAIN_SCOPE],
}
WEAK_SUPPLEMENTAL_FACT_MARKERS = {
    "풍미",
    "향분말",
    "향료",
    "함유",
    "주의사항",
}
EXCLUDED_CLASSIFICATION_FACT_MARKERS = {
    "혼입",
    "혼입가능",
    "혼입 가능",
    "같은 제조시설",
    "같은 제조 시설",
    "제조시설에서 제조",
    "사용한 제품과 같은",
    "알레르기",
    "allergen",
    "allergy",
    "may contain",
    "same facility",
    "same manufacturing",
}


class ProductClassificationInput(BaseModel):
    """상품 수집 결과를 분류 입력에 맞게 정규화한 DTO."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    productPageUrl: Optional[str] = Field(default=None, alias="product_page_url")
    productName: Optional[str] = Field(default=None, alias="product_name")
    productDomain: str = Field(default="unknown", alias="product_domain")
    domainScopes: List[str] = Field(default_factory=list, alias="domain_scopes")
    shortDescription: Optional[str] = Field(default=None, alias="short_description")
    brandName: Optional[str] = Field(default=None, alias="brand_name")
    packageType: Optional[str] = Field(default=None, alias="package_type")
    saleUnit: Optional[str] = Field(default=None, alias="sale_unit")
    noticeFieldTexts: List[str] = Field(
        default_factory=list,
        alias="notice_field_texts",
    )
    noticeOptionNames: List[str] = Field(
        default_factory=list,
        alias="notice_option_names",
    )
    productNoticeText: str = Field(
        default="",
        alias="product_notice_text",
        exclude=True,
    )
    normalizedOcrFactTexts: List[str] = Field(
        default_factory=list,
        alias="normalized_ocr_fact_texts",
    )
    structuredProductFacts: List[Dict[str, object]] = Field(
        default_factory=list,
        alias="structured_product_facts",
    )
    unresolvedProductFacts: List[Dict[str, object]] = Field(
        default_factory=list,
        alias="unresolved_product_facts",
    )
    productFactConflicts: List[object] = Field(
        default_factory=list,
        alias="product_fact_conflicts",
    )
    excludedOcrTextPreview: str = Field(
        default="",
        alias="excluded_ocr_text_preview",
        exclude=True,
    )
    ocrText: str = Field(default="", alias="ocr_text", exclude=True)

    def BuildPrimarySearchText(self) -> str:
        return self._BuildSearchTextFromParts(
            [
                self.productName or "",
                self.brandName or "",
            ]
        )

    def BuildSecondarySearchText(self) -> str:
        secondaryOcrFactTexts = [
            factText
            for factText in self.normalizedOcrFactTexts
            if self._ShouldUseAsSecondaryClassificationFactText(factText)
        ]
        secondaryNoticeTexts = [
            noticeText
            for noticeText in self._SplitSupplementalFactTexts(
                self.productNoticeText,
            )
            if self._ShouldUseAsSecondaryClassificationFactText(noticeText)
        ]
        return self._BuildSearchTextFromParts(
            [
                self.packageType or "",
                self.saleUnit or "",
                *self.noticeOptionNames,
                *self.noticeFieldTexts,
                *secondaryNoticeTexts,
                *secondaryOcrFactTexts,
            ]
        )

    def BuildWeakSearchText(self) -> str:
        weakOcrFactTexts = [
            factText
            for factText in self.normalizedOcrFactTexts
            if self._ShouldUseAsWeakClassificationFactText(factText)
        ]
        weakNoticeTexts = [
            noticeText
            for noticeText in self._SplitSupplementalFactTexts(
                self.productNoticeText,
            )
            if self._ShouldUseAsWeakClassificationFactText(noticeText)
        ]
        return self._BuildSearchTextFromParts(
            [
                *weakNoticeTexts,
                *weakOcrFactTexts,
            ]
        )

    def BuildSearchText(self) -> str:
        rawParts = [
            self.BuildPrimarySearchText(),
            self.BuildSecondarySearchText(),
            self.BuildWeakSearchText()
            or (
                ""
                if self.normalizedOcrFactTexts
                else self._BuildRawOcrClassificationFallbackText()
            ),
        ]
        return self._BuildSearchTextFromParts(rawParts)

    def BuildSemanticSearchText(self) -> str:
        semanticText = self._BuildSearchTextFromParts(
            [
                self.BuildPrimarySearchText(),
                self.BuildSecondarySearchText(),
            ]
        )
        return semanticText or self.BuildSearchText()

    def _BuildSearchTextFromParts(self, rawParts: Sequence[str]) -> str:
        parts = [
            part
            for part in rawParts
            if isinstance(part, str) and part.strip() != ""
        ]
        return NormalizeWhitespaceLines("\n".join(parts))

    def _SplitSupplementalFactTexts(self, text: str) -> List[str]:
        normalizedText = NormalizeWhitespaceLines(text)
        return [
            line
            for line in normalizedText.splitlines()
            if line.strip() != ""
        ]

    def _BuildRawOcrClassificationFallbackText(self) -> str:
        return self._BuildSearchTextFromParts(
            [
                line
                for line in self._SplitSupplementalFactTexts(self.ocrText)
                if not self._IsExcludedClassificationFactText(line)
            ]
        )

    def _ShouldUseAsSecondaryClassificationFactText(self, factText: str) -> bool:
        return (
            not self._IsExcludedClassificationFactText(factText)
            and not self._IsWeakSupplementalFactText(factText)
        )

    def _ShouldUseAsWeakClassificationFactText(self, factText: str) -> bool:
        return (
            not self._IsExcludedClassificationFactText(factText)
            and self._IsWeakSupplementalFactText(factText)
        )

    def _IsExcludedClassificationFactText(self, factText: str) -> bool:
        normalizedText = NormalizeWhiteSpace(factText).lower()
        return any(
            marker in normalizedText
            for marker in EXCLUDED_CLASSIFICATION_FACT_MARKERS
        )

    def _IsWeakSupplementalFactText(self, factText: str) -> bool:
        normalizedText = NormalizeWhiteSpace(factText).lower()
        return any(
            marker in normalizedText
            for marker in WEAK_SUPPLEMENTAL_FACT_MARKERS
        )

    @computed_field(alias="product_notice_text_length")
    @property
    def productNoticeTextLength(self) -> int:
        return len(self.productNoticeText)

    @computed_field(alias="ocr_text_length")
    @property
    def ocrTextLength(self) -> int:
        return len(self.ocrText)

    @computed_field(alias="normalized_ocr_fact_count")
    @property
    def normalizedOcrFactCount(self) -> int:
        return len(self.normalizedOcrFactTexts)

    @computed_field(alias="search_text_length")
    @property
    def searchTextLength(self) -> int:
        return len(self.BuildSearchText())
