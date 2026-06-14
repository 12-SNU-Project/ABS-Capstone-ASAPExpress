"""Kurly product web parsing and collection components."""

from eu_export.product.web_parser.kurly_parser import (
    KurlyBasePageParser,
    KurlyCosmeticsPageParser,
    KurlyDomainDetector,
    KurlyFoodPageParser,
)
from eu_export.product.web_parser.kurly_domestic import KurlyDomesticPageParser
from eu_export.product.web_parser.kurly_global import KurlyGlobalPageParser
from eu_export.product.web_parser.kurly_market_collector import (
    KurlyCollectionError,
    KurlyPageCollector,
)
from eu_export.product.web_parser.kurly_market_schema import (
    KurlyCollectionResult,
    KurlyProductDomain,
    KurlyProductPage,
    ProductNoticeField,
    ProductNoticeOption,
    RenderedPageEvidence,
)
from eu_export.product.web_parser.kurly_page_adapter import KurlyPageAdapter

__all__ = [
    "KurlyBasePageParser",
    "KurlyCollectionError",
    "KurlyCollectionResult",
    "KurlyCosmeticsPageParser",
    "KurlyDomainDetector",
    "KurlyFoodPageParser",
    "KurlyGlobalPageParser",
    "KurlyPageAdapter",
    "KurlyPageCollector",
    "KurlyDomesticPageParser",
    "KurlyProductDomain",
    "KurlyProductPage",
    "ProductNoticeField",
    "ProductNoticeOption",
    "RenderedPageEvidence",
]
