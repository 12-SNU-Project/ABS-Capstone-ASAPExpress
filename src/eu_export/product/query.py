"""상품 웹 검색 전 입력 query를 분류하고 검색 계획을 만든다."""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List

from eu_export.utils import FindContainedTerms, IsUrlLike, NormalizeWhitespace


PACKAGING_PATTERN = re.compile(
    r"\b\d+(\.\d+)?\s?(g|kg|ml|l|oz|lb|ea|pcs|개|봉|팩|입|병|캔)\b",
    re.IGNORECASE,
)

FOOD_CATEGORY_TERMS = {
    "라면",
    "김치",
    "떡볶이",
    "과자",
    "비스킷",
    "쿠키",
    "소스",
    "고추장",
    "된장",
    "간장",
    "음료",
    "차",
    "즉석식품",
    "냉동식품",
    "만두",
    "파전",
    "부침개",
    "noodle",
    "ramen",
    "kimchi",
    "sauce",
    "snack",
    "cookie",
    "biscuit",
    "beverage",
    "tea",
    "frozen food",
    "dumpling",
    "pancake",
    "seafood pancake",
}

COSMETICS_CATEGORY_TERMS = {
    "화장품",
    "스킨",
    "로션",
    "크림",
    "세럼",
    "앰플",
    "토너",
    "선크림",
    "자외선차단제",
    "립스틱",
    "립틴트",
    "쿠션",
    "파운데이션",
    "샴푸",
    "컨디셔너",
    "클렌저",
    "클렌징",
    "마스크팩",
    "향수",
    "cosmetic",
    "cosmetics",
    "skin care",
    "skincare",
    "lotion",
    "cream",
    "serum",
    "ampoule",
    "toner",
    "sunscreen",
    "lipstick",
    "foundation",
    "shampoo",
    "cleanser",
    "perfume",
}

GENERIC_CATEGORY_TERMS = FOOD_CATEGORY_TERMS | COSMETICS_CATEGORY_TERMS

ATTRIBUTE_TERMS = {
    "냉동",
    "냉장",
    "상온",
    "매운",
    "매운맛",
    "순한맛",
    "비건",
    "유기농",
    "무설탕",
    "저당",
    "글루텐프리",
    "해물",
    "소고기",
    "돼지고기",
    "닭고기",
    "frozen",
    "chilled",
    "ambient",
    "spicy",
    "mild",
    "vegan",
    "organic",
    "sugar free",
    "low sugar",
    "gluten free",
    "seafood",
    "beef",
    "pork",
    "chicken",
    "moisturizing",
    "brightening",
    "anti aging",
    "spf",
    "leave-on",
    "rinse-off",
}

BRAND_HINT_TERMS = {
    "농심",
    "오뚜기",
    "삼양",
    "팔도",
    "cj",
    "bibigo",
    "nongshim",
    "ottogi",
    "samyang",
    "paldo",
    "올리브영",
    "뷰티컬리",
    "oliveyoung",
    "beauty kurly",
}


class ProductDomainHint(str, Enum):
    """후속 analyzer routing을 위한 상품 도메인 후보."""

    PROCESSED_FOOD = "processed_food"
    COSMETICS = "cosmetics"
    AMBIGUOUS = "ambiguous"
    UNKNOWN = "unknown"


class QueryType(str, Enum):
    """상품 정보 수집 단계의 사용자 입력 유형."""

    URL = "url"
    SPECIFIC_PRODUCT = "specific_product"
    GENERIC_CATEGORY = "generic_category"
    ATTRIBUTE_ENRICHED_CATEGORY = "attribute_enriched_category"
    BRAND_OR_SERIES = "brand_or_series"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class QueryAnalysisResult:
    """사용자 입력 query의 1차 분류 결과."""

    originalQuery: str
    normalizedQuery: str
    queryType: QueryType
    productDomainHint: ProductDomainHint
    searchProductDomains: List[ProductDomainHint]
    requiresWebSearch: bool
    requiresProductDetailPages: bool
    confidence: float
    reason: str
    extractedTerms: Dict[str, List[str]] = field(default_factory=dict)
    limitations: List[str] = field(default_factory=list)


class QueryAnalyzer:
    """상품 검색 query를 rule 기반으로 1차 분류한다."""

    def Analyze(self, rawQuery: str) -> QueryAnalysisResult:
        normalizedQuery = NormalizeWhitespace(rawQuery)
        if normalizedQuery == "":
            return QueryAnalysisResult(
                originalQuery=rawQuery,
                normalizedQuery=normalizedQuery,
                queryType=QueryType.AMBIGUOUS,
                productDomainHint=ProductDomainHint.UNKNOWN,
                searchProductDomains=[],
                requiresWebSearch=False,
                requiresProductDetailPages=False,
                confidence=0.0,
                reason="query is empty after normalization",
                limitations=["Ask the user for a product name or URL."],
            )

        extractedTerms = self.ExtractTerms(normalizedQuery)
        queryType, confidence, reason = self.Classify(normalizedQuery, extractedTerms)
        productDomainHint = self.InferProductDomain(extractedTerms)
        requiresWebSearch = self.InferRequiresWebSearch(queryType)

        return QueryAnalysisResult(
            originalQuery=rawQuery,
            normalizedQuery=normalizedQuery,
            queryType=queryType,
            productDomainHint=productDomainHint,
            searchProductDomains=self.InferSearchProductDomains(
                productDomainHint,
                requiresWebSearch,
            ),
            requiresWebSearch=requiresWebSearch,
            requiresProductDetailPages=self.InferRequiresProductDetailPages(queryType),
            confidence=confidence,
            reason=reason,
            extractedTerms=extractedTerms,
            limitations=self.BuildLimitations(queryType),
        )

    def ExtractTerms(self, normalizedQuery: str) -> Dict[str, List[str]]:
        return {
            "category_terms": FindContainedTerms(
                normalizedQuery,
                GENERIC_CATEGORY_TERMS,
            ),
            "food_terms": FindContainedTerms(
                normalizedQuery,
                FOOD_CATEGORY_TERMS,
            ),
            "cosmetics_terms": FindContainedTerms(
                normalizedQuery,
                COSMETICS_CATEGORY_TERMS,
            ),
            "attribute_terms": FindContainedTerms(
                normalizedQuery,
                ATTRIBUTE_TERMS,
            ),
            "brand_hint_terms": FindContainedTerms(
                normalizedQuery,
                BRAND_HINT_TERMS,
            ),
        }

    def Classify(
        self,
        normalizedQuery: str,
        extractedTerms: Dict[str, List[str]],
    ) -> tuple[QueryType, float, str]:
        loweredQuery = normalizedQuery.lower()
        tokenCount = len(normalizedQuery.split())
        categoryTerms = extractedTerms.get("category_terms", [])
        attributeTerms = extractedTerms.get("attribute_terms", [])
        brandHintTerms = extractedTerms.get("brand_hint_terms", [])

        if IsUrlLike(normalizedQuery):
            return QueryType.URL, 0.98, "query is a URL or URL-like domain"

        if categoryTerms and attributeTerms:
            return (
                QueryType.ATTRIBUTE_ENRICHED_CATEGORY,
                0.82,
                "query contains both category and product attribute terms",
            )

        if PACKAGING_PATTERN.search(loweredQuery):
            return (
                QueryType.SPECIFIC_PRODUCT,
                0.86,
                "query contains package size or quantity marker",
            )

        if brandHintTerms and categoryTerms:
            return (
                QueryType.SPECIFIC_PRODUCT,
                0.78,
                "query contains brand hint and category term",
            )

        if brandHintTerms and tokenCount <= 2:
            return (
                QueryType.BRAND_OR_SERIES,
                0.72,
                "query looks like a brand or product series",
            )

        if categoryTerms and tokenCount <= 2:
            return (
                QueryType.GENERIC_CATEGORY,
                0.76,
                "query is a short generic product category",
            )

        if tokenCount >= 2:
            return (
                QueryType.SPECIFIC_PRODUCT,
                0.62,
                "query has multiple product-like terms but needs source verification",
            )

        return (
            QueryType.AMBIGUOUS,
            0.35,
            "query is too short or lacks recognizable product signals",
        )

    def InferProductDomain(
        self,
        extractedTerms: Dict[str, List[str]],
    ) -> ProductDomainHint:
        foodTerms = extractedTerms.get("food_terms", [])
        cosmeticsTerms = extractedTerms.get("cosmetics_terms", [])

        if foodTerms and cosmeticsTerms:
            return ProductDomainHint.AMBIGUOUS
        if foodTerms:
            return ProductDomainHint.PROCESSED_FOOD
        if cosmeticsTerms:
            return ProductDomainHint.COSMETICS
        return ProductDomainHint.UNKNOWN

    def InferRequiresWebSearch(self, queryType: QueryType) -> bool:
        if queryType in (QueryType.URL, QueryType.AMBIGUOUS):
            return False

        return True

    def InferRequiresProductDetailPages(self, queryType: QueryType) -> bool:
        return queryType in (
            QueryType.URL,
            QueryType.SPECIFIC_PRODUCT,
            QueryType.ATTRIBUTE_ENRICHED_CATEGORY,
        )

    def InferSearchProductDomains(
        self,
        productDomainHint: ProductDomainHint,
        requiresWebSearch: bool,
    ) -> List[ProductDomainHint]:
        if not requiresWebSearch:
            return []

        if productDomainHint == ProductDomainHint.PROCESSED_FOOD:
            return [ProductDomainHint.PROCESSED_FOOD]

        if productDomainHint == ProductDomainHint.COSMETICS:
            return [ProductDomainHint.COSMETICS]

        return [
            ProductDomainHint.PROCESSED_FOOD,
            ProductDomainHint.COSMETICS,
        ]

    def BuildLimitations(self, queryType: QueryType) -> List[str]:
        if queryType == QueryType.URL:
            return ["URL content still needs product fact extraction and validation."]

        if queryType == QueryType.GENERIC_CATEGORY:
            return [
                "Generic category queries may not identify a single product.",
                "Ask for brand or product page if search results are broad.",
            ]

        if queryType == QueryType.AMBIGUOUS:
            return ["Ask the user for brand, product name, or URL."]

        return ["Search result evidence is required before product facts are accepted."]
