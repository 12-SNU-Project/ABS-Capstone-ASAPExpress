"""LLM이 생성한 SearchPlan 후보를 검증한다."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from eu_export.product.plan import MAX_SEARCH_QUERY_COUNT, SEARCH_PLAN_JSON_FIELDS, SearchPlan
from eu_export.product.query import ProductDomainHint, QueryType
from eu_export.utils import (
    IsUrlLike,
    ReadNumberInRange,
    ReadOptionalStringList,
    ReadRequiredBool,
    ReadRequiredString,
    ReadStringList,
)


@dataclass(frozen=True)
class SearchPlanValidationResult:
    """SearchPlan 후보 검증 결과."""

    isValid: bool
    searchPlan: Optional[SearchPlan] = None
    errors: List[str] = field(default_factory=list)


class SearchPlanValidator:
    """LLM JSON을 다음 pipeline 단계로 넘기기 전에 강제 검증한다."""

    def Validate(self, candidateData: Dict[str, Any]) -> SearchPlanValidationResult:
        errors: List[str] = []
        self.ValidateRequiredFields(candidateData, errors)

        originalQuery = ReadRequiredString(
            candidateData,
            "original_query",
            errors,
        )
        normalizedQuery = ReadRequiredString(
            candidateData,
            "normalized_query",
            errors,
        )
        queryType = self.ReadQueryType(candidateData, errors)
        productDomainHint = self.ReadProductDomainHint(candidateData, errors)
        searchQueries = ReadStringList(candidateData, "search_queries", errors)
        preferredSourceTypes = ReadStringList(
            candidateData,
            "preferred_source_types",
            errors,
        )
        requiresWebSearch = ReadRequiredBool(
            candidateData,
            "requires_web_search",
            errors,
        )
        requiresProductDetailPages = ReadRequiredBool(
            candidateData,
            "requires_product_detail_pages",
            errors,
        )
        confidence = ReadNumberInRange(candidateData, "confidence", 0.0, 1.0, errors)
        reason = ReadRequiredString(candidateData, "reason", errors)
        limitations = ReadOptionalStringList(candidateData, "limitations", errors)

        if errors or queryType is None or productDomainHint is None:
            return SearchPlanValidationResult(isValid=False, errors=errors)

        semanticErrors = self.ValidateSemantics(
            queryType,
            normalizedQuery,
            searchQueries,
            requiresWebSearch,
            requiresProductDetailPages,
        )
        if semanticErrors:
            return SearchPlanValidationResult(isValid=False, errors=semanticErrors)

        return SearchPlanValidationResult(
            isValid=True,
            searchPlan=SearchPlan(
                originalQuery=originalQuery,
                normalizedQuery=normalizedQuery,
                queryType=queryType,
                productDomainHint=productDomainHint,
                searchQueries=searchQueries,
                preferredSourceTypes=preferredSourceTypes,
                requiresWebSearch=requiresWebSearch,
                requiresProductDetailPages=requiresProductDetailPages,
                confidence=confidence,
                reason=reason,
                limitations=limitations,
            ),
        )

    def ValidateSemantics(
        self,
        queryType: QueryType,
        normalizedQuery: str,
        searchQueries: List[str],
        requiresWebSearch: bool,
        requiresProductDetailPages: bool,
    ) -> List[str]:
        errors: List[str] = []

        if queryType == QueryType.AMBIGUOUS:
            if requiresWebSearch:
                errors.append("ambiguous plan must not require web search")
            if requiresProductDetailPages:
                errors.append(
                    "ambiguous plan must not require product detail page collection"
                )
            if searchQueries:
                errors.append("ambiguous plan must not contain search queries")
            return errors

        if normalizedQuery == "":
            errors.append("normalized_query must not be empty unless ambiguous")

        if queryType == QueryType.URL:
            if requiresWebSearch:
                errors.append("url plan must not require web search")
            if not requiresProductDetailPages:
                errors.append("url plan must require product detail page collection")
            if len(searchQueries) != 1:
                errors.append("url plan must contain exactly one search query")
            elif not IsUrlLike(searchQueries[0]):
                errors.append("url plan search query must be URL-like")
            return errors

        if len(searchQueries) < 1:
            errors.append("non-url plan must contain at least one search query")
        if len(searchQueries) > MAX_SEARCH_QUERY_COUNT:
            errors.append("search_queries must contain at most 5 items")

        return errors

    def ValidateRequiredFields(
        self,
        candidateData: Dict[str, Any],
        errors: List[str],
    ) -> None:
        for fieldName in SEARCH_PLAN_JSON_FIELDS:
            if fieldName not in candidateData:
                errors.append("missing required field: {0}".format(fieldName))

    def ReadQueryType(
        self,
        candidateData: Dict[str, Any],
        errors: List[str],
    ) -> Optional[QueryType]:
        value = candidateData.get("query_type")
        if not isinstance(value, str):
            errors.append("query_type must be a string")
            return None

        try:
            return QueryType(value)
        except ValueError:
            errors.append("query_type is not supported: {0}".format(value))
            return None

    def ReadProductDomainHint(
        self,
        candidateData: Dict[str, Any],
        errors: List[str],
    ) -> Optional[ProductDomainHint]:
        value = candidateData.get("product_domain_hint")
        if not isinstance(value, str):
            errors.append("product_domain_hint must be a string")
            return None

        try:
            return ProductDomainHint(value)
        except ValueError:
            errors.append("product_domain_hint is not supported: {0}".format(value))
            return None
