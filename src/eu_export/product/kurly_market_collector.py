"""KurlyMarket product page collection via Playwright."""

from typing import Any, List, Optional, Protocol
from urllib.parse import urljoin, urlparse

from eu_export.product.kurly_market_schema import (
    KurlyMarketProductPageCollectionResult,
    KurlyMarketProductPageParseResult,
    KurlyMarketRenderedPageEvidence,
)


DEFAULT_KURLY_MARKET_TIMEOUT_MILLISECONDS = 30000
DEFAULT_KURLY_MARKET_SCROLL_COUNT = 8
DEFAULT_KURLY_MARKET_SCROLL_WAIT_MILLISECONDS = 500
DEFAULT_KURLY_MARKET_VIEWPORT_WIDTH = 1440
DEFAULT_KURLY_MARKET_VIEWPORT_HEIGHT = 1600
DEFAULT_KURLY_MARKET_SCROLL_STEP_RATIO = 0.75
DEFAULT_KURLY_MARKET_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class KurlyMarketProductPageParserProtocol(Protocol):
    """Collector가 요구하는 KurlyMarket parser 최소 interface."""

    def IsSupportedProductPageUrl(self, url: str) -> bool:
        raise NotImplementedError

    def NormalizeTextLines(self, textLines: List[str]) -> List[str]:
        raise NotImplementedError

    def NormalizeProductNoticeLines(self, textLines: List[str]) -> List[str]:
        raise NotImplementedError

    def ParseCollectedTextLines(
        self,
        textLines: List[str],
        productNoticeLines: List[str],
        productPageUrl: Optional[str] = None,
    ) -> KurlyMarketProductPageParseResult:
        raise NotImplementedError


class KurlyMarketCollectionError(RuntimeError):
    """KurlyMarket 상품 페이지 수집이 실패했을 때 사용한다."""


class KurlyMarketProductPageCollector:
    """Playwright로 KurlyMarket 상품 페이지를 제한 스크롤해 수집한다."""

    def __init__(
        self,
        parser: Optional[KurlyMarketProductPageParserProtocol] = None,
        headless: bool = True,
        timeoutMilliseconds: int = DEFAULT_KURLY_MARKET_TIMEOUT_MILLISECONDS,
        scrollCount: int = DEFAULT_KURLY_MARKET_SCROLL_COUNT,
        scrollWaitMilliseconds: int = DEFAULT_KURLY_MARKET_SCROLL_WAIT_MILLISECONDS,
    ) -> None:
        if timeoutMilliseconds <= 0:
            raise ValueError("timeoutMilliseconds must be greater than 0.")
        if scrollCount < 0:
            raise ValueError("scrollCount must be greater than or equal to 0.")
        if scrollWaitMilliseconds < 0:
            raise ValueError(
                "scrollWaitMilliseconds must be greater than or equal to 0."
            )

        self._parser = parser or self._BuildDefaultParser()
        self._headless = headless
        self._timeoutMilliseconds = timeoutMilliseconds
        self._scrollCount = scrollCount
        self._scrollWaitMilliseconds = scrollWaitMilliseconds

    def Collect(self, productPageUrl: str) -> KurlyMarketProductPageCollectionResult:
        self.ValidateProductPageUrl(productPageUrl)
        renderedPageEvidence = self.CollectRenderedPageEvidence(productPageUrl)
        return self.BuildCollectionResult(renderedPageEvidence)

    def ValidateProductPageUrl(self, productPageUrl: str) -> None:
        if not self._parser.IsSupportedProductPageUrl(productPageUrl):
            raise KurlyMarketCollectionError(
                "unsupported KurlyMarket product page URL: {0}".format(
                    productPageUrl,
                )
            )

    def CollectRenderedPageEvidence(
        self,
        productPageUrl: str,
    ) -> KurlyMarketRenderedPageEvidence:
        self.ValidateProductPageUrl(productPageUrl)

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise KurlyMarketCollectionError(
                "playwright is required for KurlyMarketProductPageCollector."
            ) from error

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=self._headless)
                try:
                    context = browser.new_context(
                        user_agent=DEFAULT_KURLY_MARKET_USER_AGENT,
                        viewport={
                            "width": DEFAULT_KURLY_MARKET_VIEWPORT_WIDTH,
                            "height": DEFAULT_KURLY_MARKET_VIEWPORT_HEIGHT,
                        },
                    )
                    try:
                        page = context.new_page()
                        page.route("**/*", self._BlockUnnecessaryResource)
                        page.goto(
                            productPageUrl,
                            wait_until="domcontentloaded",
                            timeout=self._timeoutMilliseconds,
                        )
                        self._ScrollUntilProductNoticeLoaded(page)
                        visibleText = self._ReadVisibleText(page)
                        productNoticeText = self._ReadProductNoticeText(page)
                        productDetailImageUrls = self._ReadProductDetailImageUrls(
                            page,
                        )
                    finally:
                        context.close()
                finally:
                    browser.close()
        except Exception as error:
            raise KurlyMarketCollectionError(
                "failed to collect KurlyMarket product page: {0}".format(error)
            ) from error

        return KurlyMarketRenderedPageEvidence(
            productPageUrl=productPageUrl,
            visibleText=visibleText,
            productNoticeText=productNoticeText,
            productDetailImageUrls=productDetailImageUrls,
        )

    def BuildCollectionResult(
        self,
        renderedPageEvidence: KurlyMarketRenderedPageEvidence,
    ) -> KurlyMarketProductPageCollectionResult:
        textLines = self._parser.NormalizeTextLines(
            renderedPageEvidence.visibleText.splitlines()
        )
        productNoticeLines = self._parser.NormalizeProductNoticeLines(
            renderedPageEvidence.productNoticeText.splitlines(),
        )
        parsedProductPage = self._parser.ParseCollectedTextLines(
            textLines=textLines,
            productNoticeLines=productNoticeLines,
            productPageUrl=renderedPageEvidence.productPageUrl,
        )
        ocrCandidateImageUrls = self._BuildOcrCandidateImageUrls(
            parsedProductPage,
            renderedPageEvidence.productDetailImageUrls,
        )
        warnings = self._BuildCollectionWarnings(
            parsedProductPage,
            renderedPageEvidence.productDetailImageUrls,
            ocrCandidateImageUrls,
        )

        return KurlyMarketProductPageCollectionResult(
            productPageUrl=renderedPageEvidence.productPageUrl,
            parsedProductPage=parsedProductPage,
            visibleTextLineCount=len(textLines),
            productNoticeTextLineCount=len(productNoticeLines),
            productDetailImageUrls=renderedPageEvidence.productDetailImageUrls,
            ocrCandidateImageUrls=ocrCandidateImageUrls,
            warnings=warnings,
        )

    def _BuildDefaultParser(self) -> KurlyMarketProductPageParserProtocol:
        from eu_export.product.kurly_market import KurlyMarketProductPageParser

        return KurlyMarketProductPageParser()

    def _BlockUnnecessaryResource(self, route: Any) -> None:
        if route.request.resource_type in ("media", "font"):
            route.abort()
            return
        route.continue_()

    def _ScrollUntilProductNoticeLoaded(self, page: Any) -> None:
        scrollStep = max(
            1,
            int(
                DEFAULT_KURLY_MARKET_VIEWPORT_HEIGHT
                * DEFAULT_KURLY_MARKET_SCROLL_STEP_RATIO
            ),
        )
        noticeFound = False
        for _ in range(self._scrollCount):
            bodyText = self._ReadVisibleText(page)
            if "상품고시정보" in bodyText:
                noticeFound = True
            if noticeFound and "WHY KURLY" in bodyText:
                return

            page.evaluate("(step) => window.scrollBy(0, step)", scrollStep)
            if self._scrollWaitMilliseconds > 0:
                page.wait_for_timeout(self._scrollWaitMilliseconds)

    def _ReadVisibleText(self, page: Any) -> str:
        try:
            value = page.locator("body").inner_text(
                timeout=self._timeoutMilliseconds,
            )
        except Exception:
            return ""
        if not isinstance(value, str):
            return ""
        return value

    def _ReadProductNoticeText(self, page: Any) -> str:
        try:
            value = page.evaluate(
                """
                () => {
                    const normalize = (text) => (
                        text || ""
                    ).replace(/\\s+/g, " ").trim();
                    const mainRoot = document.body;
                    const lines = [];
                    const pushLine = (text) => {
                        const line = normalize(text);
                        if (!line) {
                            return;
                        }
                        if (lines.length > 0 && lines[lines.length - 1] === line) {
                            return;
                        }
                        lines.push(line);
                    };
                    const readText = (element) => normalize(
                        element.innerText || element.textContent || ""
                    );
                    const isStopText = (text) => (
                        text === "WHY KURLY"
                        || text.startsWith("상품 후기")
                        || text.startsWith("고객 후기")
                        || text.startsWith("상품 리뷰")
                        || text.startsWith("고객 리뷰")
                        || text.startsWith("상품 문의")
                        || text.startsWith("고객행복센터")
                    );
                    const headingCandidates = Array.from(
                        mainRoot.querySelectorAll("h2,h3,h4,h5,[role='heading']")
                    );
                    const noticeHeadingFromSemanticNodes = (
                        headingCandidates.find((element) => {
                            const text = readText(element);
                            return text === "상품고시정보"
                                || text.startsWith("상품고시정보");
                        })
                    );
                    const noticeHeading = noticeHeadingFromSemanticNodes || (
                        Array.from(
                            mainRoot.querySelectorAll(
                                "button,a,span,strong,p,dt,th,div"
                            )
                        )
                            .filter((element) => {
                                const text = readText(element);
                                return text === "상품고시정보"
                                    || text.startsWith("상품고시정보");
                            })
                            .sort((left, right) => (
                                readText(left).length - readText(right).length
                            ))[0]
                    );
                    if (!noticeHeading) {
                        return "";
                    }
                    pushLine(readText(noticeHeading));

                    const blockSelector = [
                        "h2",
                        "h3",
                        "h4",
                        "h5",
                        "li",
                        "p",
                        "dt",
                        "dd",
                        "th",
                        "td",
                        "div"
                    ].join(",");
                    const hasChildBlock = (node) => !!node.querySelector(
                        blockSelector
                    );
                    const allNodes = Array.from(
                        mainRoot.querySelectorAll(blockSelector)
                    );
                    let collecting = false;
                    for (const node of allNodes) {
                        if (node === noticeHeading) {
                            collecting = true;
                            continue;
                        }
                        if (!collecting) {
                            continue;
                        }
                        const text = readText(node);
                        if (!text) {
                            continue;
                        }
                        if (isStopText(text)) {
                            break;
                        }
                        const tagName = node.tagName.toLowerCase();
                        if (tagName === "div" && hasChildBlock(node)) {
                            continue;
                        }
                        pushLine(text);
                    }
                    return lines.join("\\n");
                }
                """
            )
        except Exception:
            return ""
        if not isinstance(value, str):
            return ""
        return value

    def _ReadProductDetailImageUrls(self, page: Any) -> List[str]:
        values = page.evaluate(
            """
            () => {
                const readUrlValues = (element) => [
                    element.currentSrc || "",
                    element.src || "",
                    element.getAttribute("src") || "",
                    element.getAttribute("data-src") || "",
                    element.getAttribute("data-original") || "",
                    element.getAttribute("data-lazy") || "",
                    element.getAttribute("srcset") || ""
                ];
                return Array.from(document.querySelectorAll("img"))
                    .flatMap((element) => readUrlValues(element))
                    .filter((value) => value && value.trim() !== "");
            }
            """
        )
        if not isinstance(values, list):
            return []

        imageUrls: List[str] = []
        seenUrls: set[str] = set()
        for value in values:
            if not isinstance(value, str):
                continue
            for imageUrl in self._ExpandImageUrlValue(page.url, value):
                if imageUrl in seenUrls:
                    continue
                if not self._LooksProductDetailImageUrl(imageUrl):
                    continue
                seenUrls.add(imageUrl)
                imageUrls.append(imageUrl)
        return imageUrls

    def _ExpandImageUrlValue(self, baseUrl: str, value: str) -> List[str]:
        imageUrls: List[str] = []
        for token in value.split(","):
            candidate = token.strip().split(" ")[0].strip()
            if candidate == "":
                continue
            imageUrls.append(urljoin(baseUrl, candidate))
        return imageUrls

    def _LooksProductDetailImageUrl(self, imageUrl: str) -> bool:
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

    def _BuildOcrCandidateImageUrls(
        self,
        parsedProductPage: KurlyMarketProductPageParseResult,
        productDetailImageUrls: List[str],
    ) -> List[str]:
        if not parsedProductPage.requiresOcrFallback:
            return []
        return list(productDetailImageUrls)

    def _BuildCollectionWarnings(
        self,
        parsedProductPage: KurlyMarketProductPageParseResult,
        productDetailImageUrls: List[str],
        ocrCandidateImageUrls: List[str],
    ) -> List[str]:
        warnings = list(parsedProductPage.warnings)
        if not productDetailImageUrls:
            warnings.append("product detail image URLs not found")
        if parsedProductPage.requiresOcrFallback and not ocrCandidateImageUrls:
            warnings.append(
                "OCR fallback is required but no OCR candidate image URLs were found"
            )
        return warnings
