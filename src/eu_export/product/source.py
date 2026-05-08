"""상품 출처별 원천 데이터를 공통 상품정보로 정규화한다."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from eu_export.product.query import ProductDomainHint
from eu_export.search import SearchResultItem


class ProductSourceRole(str, Enum):
    """상품정보 출처가 후속 판단에서 맡는 역할."""

    DOMESTIC_PLATFORM = "domestic_platform"
    BRAND_GLOBAL_SITE = "brand_global_site"
    SEARCH_DISCOVERY = "search_discovery"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProductQuantity:
    """용량·중량·판매단위처럼 품목분류에 참고되는 수량 표현."""

    rawText: str
    value: Optional[float] = None
    unit: Optional[str] = None

    def ToDict(self) -> Dict[str, Any]:
        return {
            "raw_text": self.rawText,
            "value": self.value,
            "unit": self.unit,
        }

    @classmethod
    def FromDict(cls, data: Dict[str, Any]) -> "ProductQuantity":
        return cls(
            rawText=str(data.get("raw_text", "")),
            value=_ReadOptionalFloat(data.get("value")),
            unit=_ReadOptionalString(data.get("unit")),
        )


@dataclass(frozen=True)
class SourceDomainRule:
    """URL domain을 상품 출처 정책으로 매핑하는 규칙."""

    domainSuffix: str
    sourceProvider: str
    sourceRole: ProductSourceRole
    productDomainHint: ProductDomainHint = ProductDomainHint.UNKNOWN
    sourceCountry: Optional[str] = None
    language: Optional[str] = None

    def Matches(self, url: str) -> bool:
        hostName = ExtractHostName(url)
        normalizedSuffix = self.domainSuffix.lower().strip()
        return hostName == normalizedSuffix or hostName.endswith(
            "." + normalizedSuffix,
        )


@dataclass(frozen=True)
class ProductSourcePolicy:
    """허용 출처와 출처 역할을 결정하는 작은 정책 객체."""

    domainRules: List[SourceDomainRule] = field(default_factory=list)

    def Resolve(self, url: str) -> Optional[SourceDomainRule]:
        for domainRule in self.domainRules:
            if domainRule.Matches(url):
                return domainRule
        return None


@dataclass(frozen=True)
class NormalizedProductInformation:
    """HS/CN 후보 분류 전단계에서 공유하는 상품정보 규격."""

    sourceProvider: str
    sourceRole: ProductSourceRole
    productPageUrl: str
    productDomainHint: ProductDomainHint
    productName: str
    sourceCountry: Optional[str] = None
    language: Optional[str] = None
    brandName: Optional[str] = None
    sellerName: Optional[str] = None
    manufacturerName: Optional[str] = None
    categoryPath: List[str] = field(default_factory=list)
    quantities: List[ProductQuantity] = field(default_factory=list)
    ingredientDeclaration: Optional[str] = None
    inciList: List[str] = field(default_factory=list)
    originStatement: Optional[str] = None
    countryOfOrigin: Optional[str] = None
    countryOfManufacture: Optional[str] = None
    storageCondition: Optional[str] = None
    productDescription: Optional[str] = None
    imageUrls: List[str] = field(default_factory=list)
    priceAmount: Optional[float] = None
    priceCurrency: Optional[str] = None
    rawSearchTitle: Optional[str] = None
    rawSearchSnippet: Optional[str] = None
    rawSourceData: Dict[str, Any] = field(default_factory=dict)
    missingInformation: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)

    def ToDict(self) -> Dict[str, Any]:
        return {
            "source_provider": self.sourceProvider,
            "source_role": self.sourceRole.value,
            "product_page_url": self.productPageUrl,
            "product_domain_hint": self.productDomainHint.value,
            "product_name": self.productName,
            "source_country": self.sourceCountry,
            "language": self.language,
            "brand_name": self.brandName,
            "seller_name": self.sellerName,
            "manufacturer_name": self.manufacturerName,
            "category_path": list(self.categoryPath),
            "quantities": [quantity.ToDict() for quantity in self.quantities],
            "ingredient_declaration": self.ingredientDeclaration,
            "inci_list": list(self.inciList),
            "origin_statement": self.originStatement,
            "country_of_origin": self.countryOfOrigin,
            "country_of_manufacture": self.countryOfManufacture,
            "storage_condition": self.storageCondition,
            "product_description": self.productDescription,
            "image_urls": list(self.imageUrls),
            "price_amount": self.priceAmount,
            "price_currency": self.priceCurrency,
            "raw_search_title": self.rawSearchTitle,
            "raw_search_snippet": self.rawSearchSnippet,
            "raw_source_data": dict(self.rawSourceData),
            "missing_information": list(self.missingInformation),
            "limitations": list(self.limitations),
        }

    @classmethod
    def FromDict(cls, data: Dict[str, Any]) -> "NormalizedProductInformation":
        return cls(
            sourceProvider=str(data["source_provider"]),
            sourceRole=ProductSourceRole(data["source_role"]),
            productPageUrl=str(data["product_page_url"]),
            productDomainHint=ProductDomainHint(data["product_domain_hint"]),
            productName=str(data["product_name"]),
            sourceCountry=_ReadOptionalString(data.get("source_country")),
            language=_ReadOptionalString(data.get("language")),
            brandName=_ReadOptionalString(data.get("brand_name")),
            sellerName=_ReadOptionalString(data.get("seller_name")),
            manufacturerName=_ReadOptionalString(data.get("manufacturer_name")),
            categoryPath=_ReadStringList(data.get("category_path")),
            quantities=[
                ProductQuantity.FromDict(quantity)
                for quantity in data.get("quantities", [])
                if isinstance(quantity, dict)
            ],
            ingredientDeclaration=_ReadOptionalString(
                data.get("ingredient_declaration"),
            ),
            inciList=_ReadStringList(data.get("inci_list")),
            originStatement=_ReadOptionalString(data.get("origin_statement")),
            countryOfOrigin=_ReadOptionalString(data.get("country_of_origin")),
            countryOfManufacture=_ReadOptionalString(
                data.get("country_of_manufacture"),
            ),
            storageCondition=_ReadOptionalString(data.get("storage_condition")),
            productDescription=_ReadOptionalString(data.get("product_description")),
            imageUrls=_ReadStringList(data.get("image_urls")),
            priceAmount=_ReadOptionalFloat(data.get("price_amount")),
            priceCurrency=_ReadOptionalString(data.get("price_currency")),
            rawSearchTitle=_ReadOptionalString(data.get("raw_search_title")),
            rawSearchSnippet=_ReadOptionalString(data.get("raw_search_snippet")),
            rawSourceData=dict(data.get("raw_source_data", {})),
            missingInformation=_ReadStringList(data.get("missing_information")),
            limitations=_ReadStringList(data.get("limitations")),
        )


class SearchResultProductNormalizer:
    """검색 결과 URL 후보를 공통 상품정보 record로 변환한다."""

    def __init__(self, sourcePolicy: ProductSourcePolicy) -> None:
        self._sourcePolicy = sourcePolicy

    def Normalize(self, searchResultItem: SearchResultItem) -> NormalizedProductInformation:
        domainRule = self._sourcePolicy.Resolve(searchResultItem.url)
        if domainRule is None:
            return self._BuildUnknownSourceRecord(searchResultItem)

        return NormalizedProductInformation(
            sourceProvider=domainRule.sourceProvider,
            sourceRole=domainRule.sourceRole,
            productPageUrl=searchResultItem.url,
            productDomainHint=domainRule.productDomainHint,
            productName=NormalizeSearchTitle(searchResultItem.title),
            sourceCountry=domainRule.sourceCountry,
            language=domainRule.language,
            productDescription=NormalizeSnippet(searchResultItem.snippet),
            rawSearchTitle=searchResultItem.title,
            rawSearchSnippet=searchResultItem.snippet,
            rawSourceData={
                "search_provider": searchResultItem.sourceProvider,
                "query": searchResultItem.query,
                "rank": searchResultItem.rank,
            },
            missingInformation=BuildSearchResultMissingInformation(
                domainRule.productDomainHint,
            ),
            limitations=[
                "Search result snippets are discovery evidence only.",
                "Product detail page or official product API data is required before classification use.",
            ],
        )

    def _BuildUnknownSourceRecord(
        self,
        searchResultItem: SearchResultItem,
    ) -> NormalizedProductInformation:
        return NormalizedProductInformation(
            sourceProvider=searchResultItem.sourceProvider,
            sourceRole=ProductSourceRole.SEARCH_DISCOVERY,
            productPageUrl=searchResultItem.url,
            productDomainHint=ProductDomainHint.UNKNOWN,
            productName=NormalizeSearchTitle(searchResultItem.title),
            productDescription=NormalizeSnippet(searchResultItem.snippet),
            rawSearchTitle=searchResultItem.title,
            rawSearchSnippet=searchResultItem.snippet,
            rawSourceData={
                "search_provider": searchResultItem.sourceProvider,
                "query": searchResultItem.query,
                "rank": searchResultItem.rank,
            },
            missingInformation=[
                "source role confirmation",
                "product domain confirmation",
                "product detail page data",
            ],
            limitations=[
                "Source domain is not mapped to a trusted product source policy.",
            ],
        )


def BuildDefaultProductSourcePolicy() -> ProductSourcePolicy:
    """현재 수집 대상 플랫폼과 글로벌 브랜드 출처 후보를 정의한다."""

    return ProductSourcePolicy(
        domainRules=[
            SourceDomainRule(
                domainSuffix="global.oliveyoung.com",
                sourceProvider="oliveyoung_global",
                sourceRole=ProductSourceRole.DOMESTIC_PLATFORM,
                productDomainHint=ProductDomainHint.COSMETICS,
                sourceCountry="KR",
                language="en",
            ),
            SourceDomainRule(
                domainSuffix="oliveyoung.co.kr",
                sourceProvider="oliveyoung_korea",
                sourceRole=ProductSourceRole.DOMESTIC_PLATFORM,
                productDomainHint=ProductDomainHint.COSMETICS,
                sourceCountry="KR",
                language="ko",
            ),
            SourceDomainRule(
                domainSuffix="kurly.com",
                sourceProvider="kurly",
                sourceRole=ProductSourceRole.DOMESTIC_PLATFORM,
                productDomainHint=ProductDomainHint.AMBIGUOUS,
                sourceCountry="KR",
                language="ko",
            ),
        ]
    )


def NormalizeSearchTitle(title: str) -> str:
    normalizedTitle = " ".join(title.strip().split())
    if normalizedTitle == "":
        return "unknown product"
    return normalizedTitle


def NormalizeSnippet(snippet: str) -> Optional[str]:
    normalizedSnippet = " ".join(snippet.strip().split())
    if normalizedSnippet == "":
        return None
    return normalizedSnippet


def ExtractHostName(url: str) -> str:
    parsedUrl = urlparse(url.strip())
    hostName = parsedUrl.netloc if parsedUrl.netloc != "" else parsedUrl.path
    return hostName.split("/")[0].lower()


def BuildSearchResultMissingInformation(
    productDomainHint: ProductDomainHint,
) -> List[str]:
    commonMissingInformation = [
        "brand name",
        "net quantity or packaging size",
        "country of origin",
        "country of manufacture",
    ]

    if productDomainHint == ProductDomainHint.COSMETICS:
        return commonMissingInformation + [
            "INCI list",
            "product function or cosmetic category",
            "manufacturer or responsible party information",
        ]

    if productDomainHint == ProductDomainHint.PROCESSED_FOOD:
        return commonMissingInformation + [
            "ingredient declaration",
            "ingredient percentages where relevant",
            "storage condition",
        ]

    return commonMissingInformation + [
        "product domain confirmation",
        "ingredient declaration or INCI list",
    ]


def _ReadStringList(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _ReadOptionalString(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    normalizedValue = value.strip()
    if normalizedValue == "":
        return None
    return normalizedValue


def _ReadOptionalFloat(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (float, int)):
        return float(value)
    return None
