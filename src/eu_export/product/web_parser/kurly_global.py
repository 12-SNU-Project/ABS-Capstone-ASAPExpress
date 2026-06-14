"""Kurly Global / Kurly USA 상품 상세 adapter."""

from __future__ import annotations

from typing import Any, List, Optional
from urllib.parse import urlparse

from eu_export.product.web_parser.kurly_market import (
    ALL_PRODUCT_NOTICE_FIELD_LABELS,
    KurlyBasePageParser,
)
from eu_export.product.web_parser.kurly_market_schema import (
    KurlyProductDomain,
    KurlyProductPage,
    ProductSummaryEvidence,
)
from eu_export.utils import NormalizeWhitespace, NormalizeWhitespacePreservingLines


KURLY_GLOBAL_PRODUCT_NOTICE_FIELD_LABELS = list(
    dict.fromkeys(
        ALL_PRODUCT_NOTICE_FIELD_LABELS
        + [
            "원산지",
            "포장타입",
            "중량/용량",
            "판매단위",
            "알레르기정보",
            "소비기한(또는 유통기한)정보",
        ]
    )
)
KURLY_GLOBAL_FOOD_HINT_LABELS = {
    "원산지",
    "알레르기정보",
    "소비기한(또는 유통기한)정보",
    "식품의 유형",
    "원재료명",
    "영양성분",
}
KURLY_GLOBAL_COSMETICS_HINT_LABELS = {
    "내용물의 용량 또는 중량",
    "제품 주요 사양",
    "사용기한 또는 개봉 후 사용기간",
    "사용방법",
    "전성분",
    "모든 성분",
    "기능성 화장품",
    "제조국",
}


class KurlyGlobalPageParser(KurlyBasePageParser):
    """kurlyglobal.com Shopify 상품 페이지 parser."""

    def __init__(self) -> None:
        super().__init__(
            productDomain=KurlyProductDomain.UNKNOWN,
            productNoticeFieldLabels=KURLY_GLOBAL_PRODUCT_NOTICE_FIELD_LABELS,
        )

    def IsSupportedProductPageUrl(self, url: str) -> bool:
        parsedUrl = urlparse(url)
        hostName = parsedUrl.netloc.lower()
        return hostName.endswith("kurlyglobal.com") and (
            parsedUrl.path.startswith("/products/")
            or parsedUrl.path.startswith("/en/products/")
        )

    def PrepareRenderedPage(
        self,
        page: Any,
        scrollCount: int,
        scrollWaitMilliseconds: int,
    ) -> bool:
        self._ClickProductTab(page, "상품설명")
        self._LimitedScroll(page, scrollCount, scrollWaitMilliseconds)
        self._ClickProductTab(page, "상세정보")
        self._LimitedScroll(page, max(1, scrollCount // 2), scrollWaitMilliseconds)
        return True

    def ReadProductSummaryEvidence(self, page: Any) -> ProductSummaryEvidence:
        try:
            value = page.evaluate(
                """
                () => {
                    const normalize = (text) => (
                        text || ""
                    ).replace(/\\s+/g, " ").trim();
                    const readMeta = (selector) => normalize(
                        document.querySelector(selector)?.getAttribute("content") || ""
                    );
                    const productTitle = normalize(
                        document.querySelector("h1.product__title")?.innerText || ""
                    );
                    const vendor = normalize(
                        document.querySelector("[id^='Vendor-']")?.innerText || ""
                    );
                    return {
                        product_name: productTitle,
                        short_description: readMeta("meta[property='og:description']"),
                        brand_name: vendor
                    };
                }
                """
            )
        except Exception:
            return ProductSummaryEvidence()
        if not isinstance(value, dict):
            return ProductSummaryEvidence()
        return ProductSummaryEvidence.model_validate(value)

    def ReadProductNoticeText(self, page: Any) -> str:
        tableText = self._ReadProductInfoTableText(page)
        if tableText:
            return tableText
        return self._ReadJsonLdDescription(page)

    def LooksProductDetailImageUrl(self, imageUrl: str) -> bool:
        parsedUrl = urlparse(imageUrl)
        hostName = parsedUrl.netloc.lower()
        path = parsedUrl.path.lower()
        if hostName == "img-cf.kurly.com" and "/goodsview/" in path:
            return True
        return False

    def ParseCollectedTextLines(
        self,
        textLines: List[str],
        productNoticeLines: List[str],
        productPageUrl: Optional[str] = None,
    ) -> KurlyProductPage:
        parsedProductPage = super().ParseCollectedTextLines(
            textLines=textLines,
            productNoticeLines=productNoticeLines,
            productPageUrl=productPageUrl,
        )
        detectedDomain = self._DetectProductDomain(productNoticeLines)
        noticeFieldValues = {
            field.fieldName: field.fieldValue
            for field in parsedProductPage.productNoticeFields
            if field.fieldValue is not None
        }
        return parsedProductPage.model_copy(
            update={
                "productDomain": detectedDomain,
                "packageType": parsedProductPage.packageType
                or noticeFieldValues.get("포장타입"),
                "saleUnit": parsedProductPage.saleUnit
                or noticeFieldValues.get("판매단위"),
            }
        )

    def _ClickProductTab(self, page: Any, tabName: str) -> None:
        try:
            page.get_by_text(tabName, exact=True).first.click(timeout=3000)
            page.wait_for_timeout(400)
        except Exception:
            return

    def _LimitedScroll(
        self,
        page: Any,
        scrollCount: int,
        scrollWaitMilliseconds: int,
    ) -> None:
        for _ in range(max(0, scrollCount)):
            page.evaluate(
                "() => window.scrollBy(0, Math.floor(window.innerHeight * 0.85))"
            )
            if scrollWaitMilliseconds > 0:
                page.wait_for_timeout(scrollWaitMilliseconds)

    def _ReadProductInfoTableText(self, page: Any) -> str:
        try:
            rows = page.evaluate(
                """
                () => {
                    const normalize = (text) => (
                        text || ""
                    ).replace(/\\s+/g, " ").trim();
                    const productRoot = (
                        document.querySelector("[id^='MainProduct-']")
                        || document.querySelector("main")
                        || document.body
                    );
                    return Array.from(productRoot.querySelectorAll("table tr"))
                        .map((row) => Array.from(
                            row.querySelectorAll("th,td")
                        ).map((cell) => normalize(
                            cell.innerText || cell.textContent || ""
                        )).filter(Boolean))
                        .filter((cells) => cells.length >= 2);
                }
                """
            )
        except Exception:
            return ""
        if not isinstance(rows, list):
            return ""

        lines: List[str] = []
        for row in rows:
            if not isinstance(row, list) or len(row) < 2:
                continue
            label = NormalizeWhitespace(str(row[0]))
            value = NormalizeWhitespace(" ".join(str(item) for item in row[1:]))
            if label == "" or value == "":
                continue
            lines.extend([label, value])
        return NormalizeWhitespacePreservingLines("\n".join(lines))

    def _ReadJsonLdDescription(self, page: Any) -> str:
        try:
            value = page.evaluate(
                """
                () => {
                    const productJson = Array.from(
                        document.querySelectorAll("script[type='application/ld+json']")
                    ).map((node) => {
                        try {
                            return JSON.parse(node.textContent || "{}");
                        } catch {
                            return null;
                        }
                    }).find((item) => (
                        item && String(item["@type"] || "").includes("Product")
                    ));
                    return productJson?.description || "";
                }
                """
            )
        except Exception:
            return ""
        if not isinstance(value, str):
            return ""
        return NormalizeWhitespacePreservingLines(value)

    def _DetectProductDomain(
        self,
        productNoticeLines: List[str],
    ) -> KurlyProductDomain:
        foodScore = self._CountLabelHits(
            productNoticeLines,
            KURLY_GLOBAL_FOOD_HINT_LABELS,
        )
        cosmeticsScore = self._CountLabelHits(
            productNoticeLines,
            KURLY_GLOBAL_COSMETICS_HINT_LABELS,
        )
        if foodScore == 0 and cosmeticsScore == 0:
            return KurlyProductDomain.UNKNOWN
        if foodScore == cosmeticsScore:
            return KurlyProductDomain.AMBIGUOUS
        if foodScore > cosmeticsScore:
            return KurlyProductDomain.FOOD
        return KurlyProductDomain.COSMETICS

    def _CountLabelHits(self, lines: List[str], labels: set[str]) -> int:
        labelSet = {self._NormalizeComparableText(label) for label in labels}
        score = 0
        for line in lines:
            comparableLine = self._NormalizeComparableText(line)
            if comparableLine in labelSet:
                score += 1
        return score

    def _NormalizeComparableText(self, value: str) -> str:
        return NormalizeWhitespace(value).lower().replace(" ", "")
