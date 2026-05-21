"""BeautyKurly 상품 상세 page collector/parser."""

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from eu_export.utils import NormalizeWhitespace


PRODUCT_NOTICE_FIELD_LABELS = [
    "내용물의 용량 또는 중량",
    "제품 주요 사양 (피부타입, 색상(호, 번) 등)",
    "제품 주요 사양",
    "사용기한 또는 개봉 후 사용기간",
    "사용기한 또는 개봉 후 사용기간(개봉 후 사용기간을 기재할 경우에는 제조연월일을 병행표기)",
    "사용방법",
    "화장품제조업자, 화장품책임판매업자 및 맞춤형화장품판매업자",
    "화장품제조업자",
    "화장품책임판매업자",
    "제조국",
    "｢화장품법｣에 따라 기재ㆍ표시하여야 하는 모든 성분",
    "화장품법에 따라 기재",
    "모든 성분",
    "전성분",
    "｢화장품법｣에 따른 기능성 화장품",
    "기능성 화장품",
    "사용할 때의 주의사항",
    "품질보증기준",
    "소비자 상담 관련 전화번호",
]
PRODUCT_NOTICE_STOP_MARKERS = {
    "WHY KURLY",
    "상품 후기",
    "고객 후기",
    "상품 리뷰",
    "고객 리뷰",
    "상품 문의",
    "고객행복센터",
}
PRODUCT_NOTICE_IMAGE_REFERENCE_TERMS = {
    "상품설명 및 상품이미지 참조",
    "상품 이미지 참조",
    "상품이미지 참조",
    "상품설명 참조",
    "제품 포장 참조",
    "제품의 포장",
    "최신 정보는 제품의 포장",
    "최신정보는 제품 포장",
}
SUMMARY_FIELD_LABELS = {
    "배송",
    "판매자",
    "포장타입",
    "판매단위",
    "중량/용량",
    "원산지",
}
TITLE_SUFFIX_PATTERN = re.compile(r"\s*-\s*(마켓컬리|컬리)\s*$")
BRACKET_BRAND_PATTERN = re.compile(r"^\[([^\]]+)\]")
DEFAULT_BEAUTY_KURLY_TIMEOUT_MILLISECONDS = 30000
DEFAULT_BEAUTY_KURLY_SCROLL_COUNT = 8
DEFAULT_BEAUTY_KURLY_SCROLL_WAIT_MILLISECONDS = 500
DEFAULT_BEAUTY_KURLY_VIEWPORT_WIDTH = 1440
DEFAULT_BEAUTY_KURLY_VIEWPORT_HEIGHT = 1600
DEFAULT_BEAUTY_KURLY_SCROLL_STEP_RATIO = 0.75
DEFAULT_BEAUTY_KURLY_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class BeautyKurlyCollectionError(RuntimeError):
    """BeautyKurly 상품 페이지 수집이 실패했을 때 사용한다."""


@dataclass(frozen=True)
class BeautyKurlyProductNoticeField:
    """상품고시정보 label-value record."""

    fieldName: str
    fieldValue: Optional[str] = None
    requiresOcrFallback: bool = False
    rawText: str = ""

    def ToDict(self) -> Dict[str, object]:
        return {
            "field_name": self.fieldName,
            "field_value": self.fieldValue,
            "requires_ocr_fallback": self.requiresOcrFallback,
            "raw_text": self.rawText,
        }


@dataclass(frozen=True)
class BeautyKurlyProductNoticeGroup:
    """하나 이상의 상품 옵션에 대응되는 상품고시정보 field group."""

    optionNames: List[str] = field(default_factory=list)
    fields: List[BeautyKurlyProductNoticeField] = field(default_factory=list)
    rawText: str = ""

    def ToDict(self) -> Dict[str, object]:
        return {
            "option_names": list(self.optionNames),
            "fields": [fieldRecord.ToDict() for fieldRecord in self.fields],
            "raw_text": self.rawText,
        }


@dataclass(frozen=True)
class BeautyKurlyProductNoticeOptionRecord:
    """상품 옵션 하나에 정규화된 상품고시정보 field set."""

    optionName: Optional[str] = None
    fields: List[BeautyKurlyProductNoticeField] = field(default_factory=list)
    rawText: str = ""

    def ToDict(self) -> Dict[str, object]:
        return {
            "option_name": self.optionName,
            "fields": [fieldRecord.ToDict() for fieldRecord in self.fields],
            "raw_text": self.rawText,
        }


@dataclass(frozen=True)
class BeautyKurlyProductPageParseResult:
    """BeautyKurly 상품 상세 parser 결과."""

    productPageUrl: Optional[str] = None
    productName: Optional[str] = None
    shortDescription: Optional[str] = None
    brandName: Optional[str] = None
    packageType: Optional[str] = None
    saleUnit: Optional[str] = None
    productNoticeOptionNames: List[str] = field(default_factory=list)
    productNoticeFields: List[BeautyKurlyProductNoticeField] = field(
        default_factory=list,
    )
    productNoticeGroups: List[BeautyKurlyProductNoticeGroup] = field(
        default_factory=list,
    )
    productNoticeOptions: List[BeautyKurlyProductNoticeOptionRecord] = field(
        default_factory=list,
    )
    rawProductNoticeText: str = ""
    imageReferenceDetected: bool = False
    requiresOcrFallback: bool = False
    warnings: List[str] = field(default_factory=list)

    def ToDict(self) -> Dict[str, object]:
        return {
            "product_page_url": self.productPageUrl,
            "product_name": self.productName,
            "short_description": self.shortDescription,
            "brand_name": self.brandName,
            "package_type": self.packageType,
            "sale_unit": self.saleUnit,
            "product_notice_option_names": list(self.productNoticeOptionNames),
            "product_notice_fields": [
                fieldRecord.ToDict() for fieldRecord in self.productNoticeFields
            ],
            "product_notice_groups": [
                noticeGroup.ToDict() for noticeGroup in self.productNoticeGroups
            ],
            "product_notice_options": [
                noticeOption.ToDict()
                for noticeOption in self.productNoticeOptions
            ],
            "raw_product_notice_text": self.rawProductNoticeText,
            "image_reference_detected": self.imageReferenceDetected,
            "requires_ocr_fallback": self.requiresOcrFallback,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class BeautyKurlyProductPageCollectionResult:
    """렌더링된 BeautyKurly 상품 페이지 수집 결과."""

    productPageUrl: str
    parsedProductPage: BeautyKurlyProductPageParseResult
    visibleTextLineCount: int
    productNoticeTextLineCount: int
    productDetailImageUrls: List[str] = field(default_factory=list)
    ocrCandidateImageUrls: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def ToDict(self) -> Dict[str, object]:
        return {
            "product_page_url": self.productPageUrl,
            "parsed_product_page": self.parsedProductPage.ToDict(),
            "visible_text_line_count": self.visibleTextLineCount,
            "product_notice_text_line_count": self.productNoticeTextLineCount,
            "product_detail_image_urls": list(self.productDetailImageUrls),
            "ocr_candidate_image_urls": list(self.ocrCandidateImageUrls),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class BeautyKurlyRenderedPageEvidence:
    """Playwright 렌더링 이후 parser에 넘길 원천 증거."""

    productPageUrl: str
    visibleText: str = ""
    productNoticeText: str = ""
    productDetailImageUrls: List[str] = field(default_factory=list)

    def ToDict(self) -> Dict[str, object]:
        return {
            "product_page_url": self.productPageUrl,
            "visible_text": self.visibleText,
            "product_notice_text": self.productNoticeText,
            "product_detail_image_urls": list(self.productDetailImageUrls),
        }


class BeautyKurlyProductPageCollector:
    """Playwright로 BeautyKurly 상품 페이지를 제한 스크롤해 수집한다."""

    def __init__(
        self,
        parser: Optional["BeautyKurlyProductPageParser"] = None,
        headless: bool = True,
        timeoutMilliseconds: int = DEFAULT_BEAUTY_KURLY_TIMEOUT_MILLISECONDS,
        scrollCount: int = DEFAULT_BEAUTY_KURLY_SCROLL_COUNT,
        scrollWaitMilliseconds: int = DEFAULT_BEAUTY_KURLY_SCROLL_WAIT_MILLISECONDS,
    ) -> None:
        if timeoutMilliseconds <= 0:
            raise ValueError("timeoutMilliseconds must be greater than 0.")
        if scrollCount < 0:
            raise ValueError("scrollCount must be greater than or equal to 0.")
        if scrollWaitMilliseconds < 0:
            raise ValueError(
                "scrollWaitMilliseconds must be greater than or equal to 0."
            )

        self._parser = parser or BeautyKurlyProductPageParser()
        self._headless = headless
        self._timeoutMilliseconds = timeoutMilliseconds
        self._scrollCount = scrollCount
        self._scrollWaitMilliseconds = scrollWaitMilliseconds

    def Collect(self, productPageUrl: str) -> BeautyKurlyProductPageCollectionResult:
        self.ValidateProductPageUrl(productPageUrl)
        renderedPageEvidence = self.CollectRenderedPageEvidence(productPageUrl)
        return self.BuildCollectionResult(renderedPageEvidence)

    def ValidateProductPageUrl(self, productPageUrl: str) -> None:
        if not self._parser.IsSupportedProductPageUrl(productPageUrl):
            raise BeautyKurlyCollectionError(
                "unsupported BeautyKurly product page URL: {0}".format(
                    productPageUrl,
                )
            )

    def CollectRenderedPageEvidence(
        self,
        productPageUrl: str,
    ) -> BeautyKurlyRenderedPageEvidence:
        self.ValidateProductPageUrl(productPageUrl)

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise BeautyKurlyCollectionError(
                "playwright is required for BeautyKurlyProductPageCollector."
            ) from error

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=self._headless)
                try:
                    context = browser.new_context(
                        user_agent=DEFAULT_BEAUTY_KURLY_USER_AGENT,
                        viewport={
                            "width": DEFAULT_BEAUTY_KURLY_VIEWPORT_WIDTH,
                            "height": DEFAULT_BEAUTY_KURLY_VIEWPORT_HEIGHT,
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
            raise BeautyKurlyCollectionError(
                "failed to collect BeautyKurly product page: {0}".format(error)
            ) from error

        return BeautyKurlyRenderedPageEvidence(
            productPageUrl=productPageUrl,
            visibleText=visibleText,
            productNoticeText=productNoticeText,
            productDetailImageUrls=productDetailImageUrls,
        )

    def BuildCollectionResult(
        self,
        renderedPageEvidence: BeautyKurlyRenderedPageEvidence,
    ) -> BeautyKurlyProductPageCollectionResult:
        textLines = self._parser._NormalizeTextLines(
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

        return BeautyKurlyProductPageCollectionResult(
            productPageUrl=renderedPageEvidence.productPageUrl,
            parsedProductPage=parsedProductPage,
            visibleTextLineCount=len(textLines),
            productNoticeTextLineCount=len(productNoticeLines),
            productDetailImageUrls=renderedPageEvidence.productDetailImageUrls,
            ocrCandidateImageUrls=ocrCandidateImageUrls,
            warnings=warnings,
        )

    def _BlockUnnecessaryResource(self, route: Any) -> None:
        if route.request.resource_type in ("media", "font"):
            route.abort()
            return
        route.continue_()

    def _ScrollUntilProductNoticeLoaded(self, page: Any) -> None:
        scrollStep = max(
            1,
            int(
                DEFAULT_BEAUTY_KURLY_VIEWPORT_HEIGHT
                * DEFAULT_BEAUTY_KURLY_SCROLL_STEP_RATIO
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
            return "/product/description/" in path

        return False

    def _BuildOcrCandidateImageUrls(
        self,
        parsedProductPage: BeautyKurlyProductPageParseResult,
        productDetailImageUrls: List[str],
    ) -> List[str]:
        if not parsedProductPage.requiresOcrFallback:
            return []
        return list(productDetailImageUrls)

    def _BuildCollectionWarnings(
        self,
        parsedProductPage: BeautyKurlyProductPageParseResult,
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


class BeautyKurlyProductPageParser:
    """BeautyKurly 상품 상세 HTML/text에서 분류용 기초 정보를 추출한다."""

    def IsSupportedProductPageUrl(self, url: str) -> bool:
        parsedUrl = urlparse(url)
        hostName = parsedUrl.netloc.lower()
        return hostName.endswith("kurly.com") and parsedUrl.path.startswith(
            "/goods/",
        )

    def ParseHtml(
        self,
        htmlText: str,
        productPageUrl: Optional[str] = None,
    ) -> BeautyKurlyProductPageParseResult:
        textLines = BeautyKurlyHtmlTextExtractor().ExtractTextLines(htmlText)
        return self.ParseTextLines(textLines, productPageUrl=productPageUrl)

    def ParseText(
        self,
        pageText: str,
        productPageUrl: Optional[str] = None,
    ) -> BeautyKurlyProductPageParseResult:
        textLines = self._NormalizeTextLines(pageText.splitlines())
        return self.ParseTextLines(textLines, productPageUrl=productPageUrl)

    def ParseTextLines(
        self,
        textLines: List[str],
        productPageUrl: Optional[str] = None,
    ) -> BeautyKurlyProductPageParseResult:
        return self.ParseCollectedTextLines(
            textLines=textLines,
            productNoticeLines=[],
            productPageUrl=productPageUrl,
        )

    def ParseCollectedTextLines(
        self,
        textLines: List[str],
        productNoticeLines: List[str],
        productPageUrl: Optional[str] = None,
    ) -> BeautyKurlyProductPageParseResult:
        normalizedLines = self._NormalizeTextLines(textLines)
        productName = self._ExtractProductName(normalizedLines)
        noticeLines = productNoticeLines or self._ExtractProductNoticeLines(
            normalizedLines,
        )
        noticeGroups = self._ExtractProductNoticeGroups(noticeLines)
        noticeOptions = self._BuildProductNoticeOptionRecords(noticeGroups)
        noticeOptionNames = self._ExtractProductNoticeOptionNames(noticeOptions)
        noticeFields = self._FlattenProductNoticeFields(noticeGroups)
        imageReferenceDetected = self._HasImageReference(noticeLines)
        warnings = self._BuildWarnings(
            normalizedLines,
            noticeLines,
            noticeFields,
        )

        return BeautyKurlyProductPageParseResult(
            productPageUrl=productPageUrl,
            productName=productName,
            shortDescription=self._ExtractShortDescription(
                normalizedLines,
                productName,
            ),
            brandName=self._ExtractBrandName(productName),
            packageType=self._ExtractSummaryField(normalizedLines, "포장타입"),
            saleUnit=self._ExtractSummaryField(normalizedLines, "판매단위"),
            productNoticeOptionNames=noticeOptionNames,
            productNoticeFields=noticeFields,
            productNoticeGroups=noticeGroups,
            productNoticeOptions=noticeOptions,
            rawProductNoticeText="\n".join(noticeLines),
            imageReferenceDetected=imageReferenceDetected,
            requiresOcrFallback=(
                imageReferenceDetected or len(noticeFields) == 0
            ),
            warnings=warnings,
        )

    def NormalizeProductNoticeLines(self, textLines: List[str]) -> List[str]:
        normalizedLines = self._NormalizeTextLines(textLines)
        noticeLines: List[str] = []
        for line in normalizedLines:
            if line == "상품고시정보" or line.startswith("상품고시정보"):
                continue
            if any(line.startswith(marker) for marker in PRODUCT_NOTICE_STOP_MARKERS):
                break
            if line == "*":
                continue
            noticeLines.append(line)
        return noticeLines

    def _NormalizeTextLines(self, textLines: List[str]) -> List[str]:
        normalizedLines: List[str] = []
        for textLine in textLines:
            normalizedLine = NormalizeWhitespace(textLine)
            if normalizedLine == "":
                continue
            if normalizedLines and normalizedLines[-1] == normalizedLine:
                continue
            normalizedLines.append(normalizedLine)
        return normalizedLines

    def _ExtractProductName(self, textLines: List[str]) -> Optional[str]:
        for line in textLines:
            if " - 마켓컬리" in line or " - 컬리" in line:
                normalizedTitle = TITLE_SUFFIX_PATTERN.sub("", line)
                if normalizedTitle != "":
                    return normalizedTitle

        for line in textLines:
            if line.startswith("[") and "]" in line and len(line) >= 4:
                return line

        return None

    def _ExtractShortDescription(
        self,
        textLines: List[str],
        productName: Optional[str],
    ) -> Optional[str]:
        if productName is None:
            return None

        for index, line in enumerate(textLines):
            if line != productName:
                continue
            if index + 1 >= len(textLines):
                return None
            candidate = textLines[index + 1]
            if candidate in SUMMARY_FIELD_LABELS:
                return None
            if self._LooksPriceOrRate(candidate):
                return None
            return candidate

        return None

    def _ExtractBrandName(self, productName: Optional[str]) -> Optional[str]:
        if productName is None:
            return None
        brandMatch = BRACKET_BRAND_PATTERN.search(productName)
        if brandMatch is None:
            return None
        return NormalizeWhitespace(brandMatch.group(1))

    def _ExtractSummaryField(
        self,
        textLines: List[str],
        fieldName: str,
    ) -> Optional[str]:
        for index, line in enumerate(textLines):
            if line != fieldName:
                continue
            valueLines = self._ReadFollowingValueLines(textLines, index + 1)
            if valueLines:
                return NormalizeWhitespace(" ".join(valueLines))
        return None

    def _ReadFollowingValueLines(
        self,
        textLines: List[str],
        startIndex: int,
    ) -> List[str]:
        valueLines: List[str] = []
        for line in textLines[startIndex:]:
            if line in SUMMARY_FIELD_LABELS:
                break
            if line.startswith("상품설명") or line.startswith("상세정보"):
                break
            if self._LooksPriceOrRate(line):
                break
            valueLines.append(line)
            if len(valueLines) >= 2:
                break
        return valueLines

    def _LooksPriceOrRate(self, line: str) -> bool:
        return line.endswith("원") or line.endswith("%")

    def _ExtractProductNoticeLines(self, textLines: List[str]) -> List[str]:
        startIndex: Optional[int] = None
        for index, line in enumerate(textLines):
            if line == "상품고시정보" or line.startswith("상품고시정보"):
                startIndex = index + 1
                break

        if startIndex is None:
            return []

        noticeLines: List[str] = []
        for line in textLines[startIndex:]:
            if any(line.startswith(marker) for marker in PRODUCT_NOTICE_STOP_MARKERS):
                break
            if line == "*":
                continue
            noticeLines.append(line)
        return noticeLines

    def _ExtractProductNoticeOptionNames(
        self,
        noticeOptions: List[BeautyKurlyProductNoticeOptionRecord],
    ) -> List[str]:
        optionNames: List[str] = []
        seenOptionNames: set[str] = set()
        for noticeOption in noticeOptions:
            if noticeOption.optionName is None:
                continue
            if noticeOption.optionName in seenOptionNames:
                continue
            seenOptionNames.add(noticeOption.optionName)
            optionNames.append(noticeOption.optionName)
        return optionNames

    def _BuildProductNoticeOptionRecords(
        self,
        noticeGroups: List[BeautyKurlyProductNoticeGroup],
    ) -> List[BeautyKurlyProductNoticeOptionRecord]:
        optionRecords: List[BeautyKurlyProductNoticeOptionRecord] = []
        for noticeGroup in noticeGroups:
            if not noticeGroup.optionNames:
                optionRecords.append(
                    BeautyKurlyProductNoticeOptionRecord(
                        optionName=None,
                        fields=list(noticeGroup.fields),
                        rawText=noticeGroup.rawText,
                    )
                )
                continue

            for optionName in noticeGroup.optionNames:
                optionRecords.append(
                    BeautyKurlyProductNoticeOptionRecord(
                        optionName=optionName,
                        fields=list(noticeGroup.fields),
                        rawText=noticeGroup.rawText,
                    )
                )

        return optionRecords

    def _FlattenProductNoticeFields(
        self,
        noticeGroups: List[BeautyKurlyProductNoticeGroup],
    ) -> List[BeautyKurlyProductNoticeField]:
        fields: List[BeautyKurlyProductNoticeField] = []
        for noticeGroup in noticeGroups:
            fields.extend(noticeGroup.fields)
        return fields

    def _ExtractProductNoticeGroups(
        self,
        noticeLines: List[str],
    ) -> List[BeautyKurlyProductNoticeGroup]:
        groups: List[BeautyKurlyProductNoticeGroup] = []
        currentOptionNames: List[str] = []
        currentFieldRecords: List[BeautyKurlyProductNoticeField] = []
        currentRawLines: List[str] = []

        index = 0
        while index < len(noticeLines):
            line = noticeLines[index]
            fieldName = self._NormalizeProductNoticeFieldName(line)
            if fieldName is None:
                if currentFieldRecords and self._LooksProductNoticeOptionName(line):
                    groups.append(
                        self._BuildProductNoticeGroup(
                            currentOptionNames,
                            currentFieldRecords,
                            currentRawLines,
                        )
                    )
                    currentOptionNames = []
                    currentFieldRecords = []
                    currentRawLines = []

                if self._LooksProductNoticeOptionName(line):
                    currentOptionNames.append(line)
                    currentRawLines.append(line)
                index += 1
                continue

            valueLines: List[str] = []
            inlineValue = self._SplitInlineNoticeValue(line, fieldName)
            if inlineValue is not None:
                valueLines.append(inlineValue)

            index += 1
            while index < len(noticeLines):
                nextLine = noticeLines[index]
                if self._NormalizeProductNoticeFieldName(nextLine) is not None:
                    break
                if (
                    currentFieldRecords
                    and self._LooksProductNoticeOptionName(nextLine)
                ):
                    break
                valueLines.append(nextLine)
                index += 1

            fieldValue = NormalizeWhitespace(" ".join(valueLines))
            if fieldValue == "":
                fieldValue = None

            rawLines = [line] + valueLines
            currentFieldRecords.append(
                BeautyKurlyProductNoticeField(
                    fieldName=fieldName,
                    fieldValue=fieldValue,
                    requiresOcrFallback=self._NoticeValueRequiresOcr(fieldValue),
                    rawText="\n".join(rawLines),
                )
            )
            currentRawLines.extend(rawLines)

        if currentOptionNames or currentFieldRecords:
            groups.append(
                self._BuildProductNoticeGroup(
                    currentOptionNames,
                    currentFieldRecords,
                    currentRawLines,
                )
            )

        return groups

    def _BuildProductNoticeGroup(
        self,
        optionNames: List[str],
        fields: List[BeautyKurlyProductNoticeField],
        rawLines: List[str],
    ) -> BeautyKurlyProductNoticeGroup:
        return BeautyKurlyProductNoticeGroup(
            optionNames=list(optionNames),
            fields=list(fields),
            rawText="\n".join(rawLines),
        )

    def _LooksProductNoticeOptionName(self, line: str) -> bool:
        if self._NormalizeProductNoticeFieldName(line) is not None:
            return False
        if self._NoticeValueRequiresOcr(line):
            return False
        if line.startswith("[") and "]" in line:
            return True
        return False

    def _NormalizeProductNoticeFieldName(self, line: str) -> Optional[str]:
        comparableLine = line.lower().replace(" ", "")
        for label in PRODUCT_NOTICE_FIELD_LABELS:
            comparableLabel = label.lower().replace(" ", "")
            if comparableLine == comparableLabel:
                return label
            if comparableLine.startswith(comparableLabel):
                return label
        return None

    def _SplitInlineNoticeValue(
        self,
        line: str,
        fieldName: str,
    ) -> Optional[str]:
        normalizedLine = NormalizeWhitespace(line)
        normalizedFieldName = NormalizeWhitespace(fieldName)
        if normalizedLine == normalizedFieldName:
            return None

        candidateLabels = sorted(
            PRODUCT_NOTICE_FIELD_LABELS,
            key=lambda label: len(NormalizeWhitespace(label)),
            reverse=True,
        )
        for candidateLabel in candidateLabels:
            if self._NormalizeProductNoticeFieldName(candidateLabel) != fieldName:
                continue
            normalizedCandidate = NormalizeWhitespace(candidateLabel)
            if normalizedLine.startswith(normalizedCandidate):
                remainder = normalizedLine[len(normalizedCandidate) :].strip(
                    " :：·-"
                )
                return remainder or None

        return None

    def _HasImageReference(self, noticeLines: List[str]) -> bool:
        return any(self._NoticeValueRequiresOcr(line) for line in noticeLines)

    def _NoticeValueRequiresOcr(self, value: Optional[str]) -> bool:
        if value is None:
            return False
        return any(term in value for term in PRODUCT_NOTICE_IMAGE_REFERENCE_TERMS)

    def _BuildWarnings(
        self,
        textLines: List[str],
        noticeLines: List[str],
        noticeFields: List[BeautyKurlyProductNoticeField],
    ) -> List[str]:
        warnings: List[str] = []
        if not textLines:
            warnings.append("page text is empty")
        if not noticeLines:
            warnings.append("product notice section not found")
        elif not noticeFields:
            warnings.append("product notice fields not parsed")
        return warnings

class BeautyKurlyHtmlTextExtractor(HTMLParser):
    """HTML을 block 단위 text line으로 변환한다."""

    _BLOCK_TAGS = {
        "article",
        "br",
        "dd",
        "div",
        "dt",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "li",
        "main",
        "p",
        "section",
        "td",
        "th",
        "title",
        "tr",
        "ul",
    }
    _SKIP_TAGS = {"script", "style", "noscript"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: List[str] = []
        self._skipDepth = 0

    def ExtractTextLines(self, htmlText: str) -> List[str]:
        self._parts = []
        self._skipDepth = 0
        self.feed(htmlText)
        self.close()
        return self._BuildTextLines()

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        loweredTag = tag.lower()
        if loweredTag in self._SKIP_TAGS:
            self._skipDepth += 1
            return
        if self._skipDepth > 0:
            return
        if loweredTag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        loweredTag = tag.lower()
        if loweredTag in self._SKIP_TAGS:
            self._skipDepth = max(0, self._skipDepth - 1)
            return
        if self._skipDepth > 0:
            return
        if loweredTag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skipDepth > 0:
            return
        if data.strip() == "":
            return
        self._parts.append(data)

    def _BuildTextLines(self) -> List[str]:
        text = "".join(self._parts)
        return [
            normalizedLine
            for normalizedLine in (
                NormalizeWhitespace(line) for line in text.splitlines()
            )
            if normalizedLine != ""
        ]
