from dataclasses import dataclass, field
from typing import List

from eu_export.product.query import ProductDomainHint, QueryType


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
