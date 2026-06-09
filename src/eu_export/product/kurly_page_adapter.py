"""Kurly domestic/global product page parser router."""

from __future__ import annotations

from typing import Any, List, Optional
from urllib.parse import urlparse

from eu_export.product.kurly_global import KurlyGlobalPageParser
from eu_export.product.kurly_market import KurlyPageParser
from eu_export.product.kurly_market_schema import (
    KurlyProductPage,
    ProductSummaryEvidence,
)


class KurlyPageAdapter:
    """URL host/path에 따라 국내 Kurly와 Kurly Global parser를 선택한다."""

    def __init__(
        self,
        domesticParser: Optional[KurlyPageParser] = None,
        globalParser: Optional[KurlyGlobalPageParser] = None,
    ) -> None:
        self._domesticParser = domesticParser or KurlyPageParser()
        self._globalParser = globalParser or KurlyGlobalPageParser()

    def IsSupportedProductPageUrl(self, url: str) -> bool:
        return (
            self._domesticParser.IsSupportedProductPageUrl(url)
            or self._globalParser.IsSupportedProductPageUrl(url)
        )

    def NormalizeTextLines(self, textLines: List[str]) -> List[str]:
        return self._domesticParser.NormalizeTextLines(textLines)

    def NormalizeProductNoticeLines(self, textLines: List[str]) -> List[str]:
        return self._domesticParser.NormalizeProductNoticeLines(textLines)

    def ParseCollectedTextLines(
        self,
        textLines: List[str],
        productNoticeLines: List[str],
        productPageUrl: Optional[str] = None,
    ) -> KurlyProductPage:
        return self._SelectParser(productPageUrl).ParseCollectedTextLines(
            textLines=textLines,
            productNoticeLines=productNoticeLines,
            productPageUrl=productPageUrl,
        )

    def PrepareRenderedPage(
        self,
        page: Any,
        scrollCount: int,
        scrollWaitMilliseconds: int,
    ) -> bool:
        if not self._globalParser.IsSupportedProductPageUrl(page.url):
            return False
        return self._globalParser.PrepareRenderedPage(
            page,
            scrollCount,
            scrollWaitMilliseconds,
        )

    def ReadProductSummaryEvidence(self, page: Any) -> Optional[ProductSummaryEvidence]:
        if not self._globalParser.IsSupportedProductPageUrl(page.url):
            return None
        return self._globalParser.ReadProductSummaryEvidence(page)

    def ReadProductNoticeText(self, page: Any) -> Optional[str]:
        if not self._globalParser.IsSupportedProductPageUrl(page.url):
            return None
        return self._globalParser.ReadProductNoticeText(page)

    def LooksProductDetailImageUrl(self, imageUrl: str) -> bool:
        parsedUrl = urlparse(imageUrl)
        hostName = parsedUrl.netloc.lower()
        path = parsedUrl.path.lower()

        if hostName == "img-cf.kurly.com" and "/goodsview/" in path:
            return True
        if hostName == "product-image.kurly.com":
            if "/product/description/" in path:
                return True
            return "/src/product/image/" in path and "%3e1010x" in path
        return False

    def _SelectParser(
        self,
        productPageUrl: Optional[str],
    ) -> KurlyPageParser | KurlyGlobalPageParser:
        if (
            productPageUrl is not None
            and self._globalParser.IsSupportedProductPageUrl(productPageUrl)
        ):
            return self._globalParser
        return self._domesticParser
