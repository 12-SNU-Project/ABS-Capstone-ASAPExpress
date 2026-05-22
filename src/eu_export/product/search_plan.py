"""상품 query 분석과 SearchPlan 생성 계약."""

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from eu_export.bridge import (
    LlmGenerationOptions,
    LlmRequest,
    LlmResponseFormat,
    RuntimeAdapter,
)
from eu_export.utils import (
    ExtractJsonObject,
    FindContainedTerms,
    IsUrlLike,
    NormalizeWhitespace,
    ReadNumberInRange,
    ReadOptionalStringList,
    ReadRequiredBool,
    ReadRequiredString,
    ReadStringList,
)


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

class ProductDomainHint(str, Enum):
    PROCESSED_FOOD = "가공식품"
    COSMETICS = "화장품"
    AMBIGUOUS = "공동 키워드 포함"
    UNKNOWN = "분류 불가"

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
    detectedFoodTerms: list[str]
    detectedCosmeticsTerms: list[str]
    detectedAttributeTerms: list[str]


class QueryAnalyzer:
    """상품 검색 query를 rule 기반으로 1차 분류한다."""

    def Analyze(self, rawQuery: str) -> QueryAnalysisResult:
        normalizedQuery = NormalizeWhitespace(rawQuery)
        if normalizedQuery == "":
            return QueryAnalysisResult(
                originalQuery=rawQuery,
                normalizedQuery=normalizedQuery,
                queryType=QueryType.AMBIGUOUS,
                detectedFoodTerms=[],
                detectedCosmeticsTerms=[],
                detectedAttributeTerms=[]
            )
    
        extractedTerms = self._ExtractKeywords(normalizedQuery)
        
        queryType, reason = self._ClassifyQueryType(normalizedQuery, extractedTerms)
        productDomainHint = self._InferProductDomain(extractedTerms)

        return QueryAnalysisResult(
            originalQuery=rawQuery,
            normalizedQuery=normalizedQuery,
            queryType=queryType,
            detectedFoodTerms=[t for t in extractedTerms["food_terms"]],
            detectedCosmeticsTerms=[t for t in extractedTerms["cosmetic_trems"]],
            detectedAttributeTerms=[t for t in extractedTerms["attribute_terms"]]
        )

    def _ExtractKeywords(self, normalizedQuery: str) -> Dict[str, List[str]]:
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
        }

    def _ClassifyQueryType(
        self,
        normalizedQuery: str,
        extractedTerms: Dict[str, List[str]],
    ) -> tuple[QueryType, str]:
        loweredQuery = normalizedQuery.lower()
        tokenCount = len(normalizedQuery.split())
        categoryTerms = extractedTerms.get("category_terms", [])
        attributeTerms = extractedTerms.get("attribute_terms", [])
        brandHintTerms = extractedTerms.get("brand_hint_terms", [])

        if IsUrlLike(normalizedQuery):
            return QueryType.URL, "query is a URL or URL-like domain"

        if categoryTerms and attributeTerms:
            return (
                QueryType.ATTRIBUTE_ENRICHED_CATEGORY,
                "query contains both category and product attribute terms",
            )

        if PACKAGING_PATTERN.search(loweredQuery):
            return (
                QueryType.SPECIFIC_PRODUCT,
                "query contains package size or quantity marker",
            )

        if brandHintTerms and categoryTerms:
            return (
                QueryType.SPECIFIC_PRODUCT,
                "query contains brand hint and category term",
            )

        if brandHintTerms and tokenCount <= 2:
            return (
                QueryType.BRAND_OR_SERIES,
                "query looks like a brand or product series",
            )

        if categoryTerms and tokenCount <= 2:
            return (
                QueryType.GENERIC_CATEGORY,
                "query is a short generic product category",
            )

        if tokenCount >= 2:
            return (
                QueryType.SPECIFIC_PRODUCT,
                "query has multiple product-like terms but needs source verification",
            )

        return (
            QueryType.AMBIGUOUS,
            "query is too short or lacks recognizable product signals",
        )

    def _InferProductDomain(
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

    def _BuildLimitations(self, queryType: QueryType) -> List[str]:
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


SEARCH_PLAN_JSON_FIELDS = [
    "original_query",
    "normalized_query",
    "query_type",
    "product_domain_hint",
    "search_product_domains",
    "search_queries",
    "preferred_source_types",
    "requires_web_search",
    "requires_product_detail_pages",
    "confidence",
    "reason",
    "limitations",
]
MAX_SEARCH_QUERY_COUNT = 5


def BuildAllowedQueryTypeText() -> str:
    return ", ".join(queryType.value for queryType in QueryType)


def BuildAllowedProductDomainHintText() -> str:
    return ", ".join(productDomainHint.value for productDomainHint in ProductDomainHint)


def BuildSearchPlanFieldText() -> str:
    return ", ".join(SEARCH_PLAN_JSON_FIELDS)


@dataclass(frozen=True)
class SearchPlan:
    """상품 정보 수집을 위한 1차 검색 계획."""

    originalQuery: str
    normalizedQuery: str
    queryType: QueryType
    productDomainHint: ProductDomainHint
    searchProductDomains: List[ProductDomainHint]
    searchQueries: List[str]
    preferredSourceTypes: List[str]
    requiresWebSearch: bool
    requiresProductDetailPages: bool
    confidence: float
    reason: str
    limitations: List[str] = field(default_factory=list)


def BuildSearchPlanSystemPrompt() -> str:
    return "\n".join(
        [
            "You are a query planning component for a Korea-to-EU regulated product export support system.",
            "Convert the user's product search query into one SearchPlan JSON object.",
            "Return only valid JSON. Do not return markdown or explanations.",
            "Allowed query_type values: {0}.".format(BuildAllowedQueryTypeText()),
            "Allowed product_domain_hint values: {0}.".format(
                BuildAllowedProductDomainHintText(),
            ),
            "Required fields: {0}.".format(BuildSearchPlanFieldText()),
            "Do not determine HS, CN, TARIC, legal requirements, certification requirements, or document requirements.",
            "Only create a web search plan for collecting product information.",
            "Use product_domain_hint only for routing: processed_food, cosmetics, ambiguous, or unknown.",
            "search_product_domains must contain only concrete search targets: processed_food and/or cosmetics.",
            "If product_domain_hint is ambiguous or unknown but the query is searchable, search both processed_food and cosmetics.",
            "If the query is ambiguous or does not require web search, search_product_domains must be an empty list.",
        ]
    )


class LlmQueryInterpreter:
    """휴리스틱 분석 결과를 참고자료로 전달해 SearchPlan JSON 후보를 만든다."""

    def __init__(self, runtimeAdapter: RuntimeAdapter[Any]) -> None:
        self._runtimeAdapter = runtimeAdapter

    def Interpret(
        self,
        rawQuery: str,
        analysisResult: QueryAnalysisResult,
    ) -> Dict[str, Any]:
        request = LlmRequest(
            systemPrompt=self.BuildSystemPrompt(),
            userPrompt=self.BuildUserPrompt(rawQuery, analysisResult),
            responseFormat=LlmResponseFormat.JSON_OBJECT,
            generationOptions=LlmGenerationOptions(
                temperature=0.0,
                maxTokens=800,
            ),
        )

        response = self._runtimeAdapter.Generate(request)
        return ExtractJsonObject(response.generatedText)

    def BuildSystemPrompt(self) -> str:
        return BuildSearchPlanSystemPrompt()

    def BuildUserPrompt(
        self,
        rawQuery: str,
        analysisResult: QueryAnalysisResult,
    ) -> str:
        heuristicData = {
                analysisResult.originalQuery,
                analysisResult.normalizedQuery,
                analysisResult.queryType,
            }
        return "\n".join(
            [
                "User query:",
                rawQuery,
                "",
                "Heuristic analysis for reference only:",
                json.dumps(heuristicData, ensure_ascii=False, indent=2),
                "",
                "Create one SearchPlan JSON object.",
            ]
        )

