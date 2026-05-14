"""Playwright와 OCR을 이용해 상품 출처 페이지를 인메모리로 수집한다."""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from eu_export.product.query import ProductDomainHint
from eu_export.product.source import (
    ExtractHostName,
    ProductSourcePolicy,
    ProductSourceRole,
)
from eu_export.utils import NormalizeWhitespace


DEFAULT_BEAUTY_KURLY_SCROLL_URL = "https://www.kurly.com/beauty-benefit"
DEFAULT_FETCH_TIMEOUT_MILLISECONDS = 30000
DEFAULT_SCROLL_COUNT = 8
DEFAULT_SCROLL_WAIT_MILLISECONDS = 500
DEFAULT_VIEWPORT_WIDTH = 1440
DEFAULT_VIEWPORT_HEIGHT = 1600
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class ProductSourceFetchError(RuntimeError):
    """상품 출처 페이지 수집이 실패했을 때 사용한다."""


class ProductOcrError(RuntimeError):
    """OCR engine 초기화 또는 추론이 실패했을 때 사용한다."""


class ProductOcrEngine(ABC):
    """스크린샷 bytes에서 OCR 텍스트를 추출하는 adapter interface."""

    @abstractmethod
    def ExtractTextFromImage(self, imageBytes: bytes) -> str:
        raise NotImplementedError


class PaddleOcrEngine(ProductOcrEngine):
    """PaddleOCR 기반 OCR adapter."""

    def __init__(
        self,
        lang: str = "korean",
        device: Optional[str] = None,
        useDocOrientationClassify: bool = False,
        useDocUnwarping: bool = False,
        useTextlineOrientation: bool = False,
        extraOptions: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._lang = lang
        self._device = device
        self._useDocOrientationClassify = useDocOrientationClassify
        self._useDocUnwarping = useDocUnwarping
        self._useTextlineOrientation = useTextlineOrientation
        self._extraOptions = dict(extraOptions or {})
        self._ocr: Any = None

    def ExtractTextFromImage(self, imageBytes: bytes) -> str:
        image = self._DecodeImageBytes(imageBytes)
        ocr = self._ReadOcr()

        if hasattr(ocr, "predict"):
            result = ocr.predict(image)
        elif hasattr(ocr, "ocr"):
            result = ocr.ocr(image, cls=self._useTextlineOrientation)
        else:
            raise ProductOcrError("PaddleOCR object does not expose predict or ocr.")

        return "\n".join(self._ExtractResultTexts(result))

    def _ReadOcr(self) -> Any:
        if self._ocr is not None:
            return self._ocr

        try:
            from paddleocr import PaddleOCR
        except ImportError as error:
            raise ProductOcrError(
                "paddleocr package is required for PaddleOcrEngine."
            ) from error

        self._ocr = self._CreatePaddleOcr(PaddleOCR)
        return self._ocr

    def _CreatePaddleOcr(self, paddleOcrClass: Any) -> Any:
        options: Dict[str, Any] = {
            "lang": self._lang,
            "use_doc_orientation_classify": self._useDocOrientationClassify,
            "use_doc_unwarping": self._useDocUnwarping,
            "use_textline_orientation": self._useTextlineOrientation,
            **self._extraOptions,
        }
        if self._device is not None:
            options["device"] = self._device

        try:
            return paddleOcrClass(**options)
        except TypeError:
            legacyOptions: Dict[str, Any] = {
                "lang": self._lang,
                "use_angle_cls": self._useTextlineOrientation,
                **self._extraOptions,
            }
            return paddleOcrClass(**legacyOptions)

    def _DecodeImageBytes(self, imageBytes: bytes) -> Any:
        try:
            import cv2
            import numpy as np
        except ImportError as error:
            raise ProductOcrError(
                "PaddleOcrEngine requires numpy and cv2 to decode screenshot bytes."
            ) from error

        imageArray = np.frombuffer(imageBytes, dtype=np.uint8)
        image = cv2.imdecode(imageArray, cv2.IMREAD_COLOR)
        if image is None:
            raise ProductOcrError("failed to decode screenshot bytes for OCR.")

        return image

    def _ExtractResultTexts(self, result: Any) -> List[str]:
        texts: List[str] = []
        self._CollectTextValues(result, texts)
        return [NormalizeWhitespace(text) for text in texts if NormalizeWhitespace(text)]

    def _CollectTextValues(self, value: Any, texts: List[str]) -> None:
        if value is None:
            return

        if isinstance(value, dict):
            self._CollectTextValuesFromDict(value, texts)
            return

        if isinstance(value, (list, tuple)):
            self._CollectTextValuesFromSequence(value, texts)
            return

        jsonValue = getattr(value, "json", None)
        if isinstance(jsonValue, dict):
            self._CollectTextValuesFromDict(jsonValue, texts)
            return

        if hasattr(value, "to_dict"):
            try:
                dictValue = value.to_dict()
            except Exception:
                dictValue = None
            if isinstance(dictValue, dict):
                self._CollectTextValuesFromDict(dictValue, texts)

    def _CollectTextValuesFromDict(
        self,
        value: Dict[str, Any],
        texts: List[str],
    ) -> None:
        for key in ["rec_texts", "texts"]:
            textValues = value.get(key)
            if isinstance(textValues, list):
                texts.extend(
                    item for item in textValues if isinstance(item, str)
                )

        textValue = value.get("text")
        if isinstance(textValue, str):
            texts.append(textValue)

        resultValue = value.get("res")
        if isinstance(resultValue, dict):
            self._CollectTextValuesFromDict(resultValue, texts)

    def _CollectTextValuesFromSequence(
        self,
        value: Any,
        texts: List[str],
    ) -> None:
        if self._LooksLegacyOcrLine(value):
            textValue = value[1][0]
            if isinstance(textValue, str):
                texts.append(textValue)
            return

        for item in value:
            self._CollectTextValues(item, texts)

    def _LooksLegacyOcrLine(self, value: Any) -> bool:
        return (
            isinstance(value, (list, tuple))
            and len(value) >= 2
            and isinstance(value[1], (list, tuple))
            and len(value[1]) >= 1
            and isinstance(value[1][0], str)
        )


@dataclass(frozen=True)
class FetchedProductSource:
    """Playwright가 수집한 상품 출처 원문 데이터."""

    productPageUrl: str
    sourceProvider: str
    sourceRole: ProductSourceRole
    productDomainHint: ProductDomainHint
    title: Optional[str] = None
    visibleText: str = ""
    ocrText: Optional[str] = None
    html: str = ""
    imageUrls: List[str] = field(default_factory=list)
    linkUrls: List[str] = field(default_factory=list)
    headingTexts: List[str] = field(default_factory=list)
    structuredData: List[Dict[str, Any]] = field(default_factory=list)
    screenshotBytes: Optional[bytes] = None
    rawFetchData: Dict[str, Any] = field(default_factory=dict)
    limitations: List[str] = field(default_factory=list)

    def ToDict(self) -> Dict[str, Any]:
        return {
            "product_page_url": self.productPageUrl,
            "source_provider": self.sourceProvider,
            "source_role": self.sourceRole.value,
            "product_domain_hint": self.productDomainHint.value,
            "title": self.title,
            "visible_text": self.visibleText,
            "ocr_text": self.ocrText,
            "html_length": len(self.html),
            "image_urls": list(self.imageUrls),
            "link_urls": list(self.linkUrls),
            "heading_texts": list(self.headingTexts),
            "structured_data": list(self.structuredData),
            "screenshot_size_bytes": (
                len(self.screenshotBytes)
                if self.screenshotBytes is not None
                else None
            ),
            "raw_fetch_data": dict(self.rawFetchData),
            "limitations": list(self.limitations),
        }


class ProductSourceFetcher:
    """상품 URL 또는 컬렉션 URL을 열고 visible text, link, image, OCR 후보를 수집한다."""

    def __init__(
        self,
        sourcePolicy: ProductSourcePolicy,
        ocrEngine: Optional[ProductOcrEngine] = None,
        headless: bool = True,
        timeoutMilliseconds: int = DEFAULT_FETCH_TIMEOUT_MILLISECONDS,
        scrollCount: int = DEFAULT_SCROLL_COUNT,
        scrollWaitMilliseconds: int = DEFAULT_SCROLL_WAIT_MILLISECONDS,
        includeScreenshot: bool = True,
    ) -> None:
        if timeoutMilliseconds <= 0:
            raise ValueError("timeoutMilliseconds must be greater than 0.")
        if scrollCount < 0:
            raise ValueError("scrollCount must be greater than or equal to 0.")
        if scrollWaitMilliseconds < 0:
            raise ValueError(
                "scrollWaitMilliseconds must be greater than or equal to 0."
            )

        self._sourcePolicy = sourcePolicy
        self._ocrEngine = ocrEngine
        self._headless = headless
        self._timeoutMilliseconds = timeoutMilliseconds
        self._scrollCount = scrollCount
        self._scrollWaitMilliseconds = scrollWaitMilliseconds
        self._includeScreenshot = includeScreenshot

    def FetchUrl(self, url: str) -> FetchedProductSource:
        normalizedUrl = self._NormalizeUrl(url)
        syncPlaywright = self._LoadSyncPlaywright()
        sourceProvider, sourceRole, productDomainHint = self._ResolveSource(
            normalizedUrl,
        )
        limitations = self._BuildInitialLimitations()

        try:
            with syncPlaywright() as playwright:
                browser = playwright.chromium.launch(headless=self._headless)
                print("browser loaded")
                page = browser.new_context(
                    user_agent=DEFAULT_USER_AGENT,
                    viewport={
                        "width": DEFAULT_VIEWPORT_WIDTH,
                        "height": DEFAULT_VIEWPORT_HEIGHT,
                    }
                )
                page = browser.new_page()
                print("goto")
                page.goto(
                    normalizedUrl,
                    wait_until="commit",
                    timeout=self._timeoutMilliseconds,
                )
                print("scroll")
                # self._WaitForNetworkIdle(page)
                self._ScrollPage(page)

                title = self._ReadTitle(page)
                visibleText = self._ReadVisibleText(page)
                html = page.content()
                imageUrls = self._ReadElementUrls(page, "img", "currentSrc", "src")
                linkUrls = self._ReadElementUrls(page, "a", "href")
                headingTexts = self._ReadHeadingTexts(page)
                structuredData = self._ReadStructuredData(page)
                screenshotBytes = self._ReadScreenshot(page)
                ocrText = self._ReadOcrText(screenshotBytes, limitations)

                browser.close()
        except Exception as error:
            raise ProductSourceFetchError(
                "failed to fetch product source page: {0}".format(error)
            ) from error

        return FetchedProductSource(
            productPageUrl=normalizedUrl,
            sourceProvider=sourceProvider,
            sourceRole=sourceRole,
            productDomainHint=productDomainHint,
            title=title,
            visibleText=visibleText,
            ocrText=ocrText,
            html=html,
            imageUrls=imageUrls,
            linkUrls=linkUrls,
            headingTexts=headingTexts,
            structuredData=structuredData,
            screenshotBytes=screenshotBytes,
            rawFetchData={
                "fetcher": "playwright",
                "scroll_count": self._scrollCount,
                "timeout_milliseconds": self._timeoutMilliseconds,
            },
            limitations=limitations,
        )

    def _LoadSyncPlaywright(self) -> Any:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise ProductSourceFetchError(
                "Playwright is required for ProductSourceFetcher. "
                "Install it in the active conda environment before running fetch."
            ) from error

        return sync_playwright

    def _ResolveSource(
        self,
        url: str,
    ) -> tuple[str, ProductSourceRole, ProductDomainHint]:
        domainRule = self._sourcePolicy.Resolve(url)
        if domainRule is None:
            return (
                ExtractHostName(url),
                ProductSourceRole.UNKNOWN,
                ProductDomainHint.UNKNOWN,
            )

        return (
            domainRule.sourceProvider,
            domainRule.sourceRole,
            domainRule.productDomainHint,
        )

    def _WaitForNetworkIdle(self, page: Any) -> None:
        try:
            page.wait_for_load_state("networkidle", timeout=self._timeoutMilliseconds)
        except Exception:
            pass

    def _ScrollPage(self, page: Any) -> None:
        for _ in range(self._scrollCount):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            if self._scrollWaitMilliseconds > 0:
                page.wait_for_timeout(self._scrollWaitMilliseconds)

    def _ReadTitle(self, page: Any) -> Optional[str]:
        title = NormalizeWhitespace(page.title())
        if title == "":
            return None
        return title

    def _ReadVisibleText(self, page: Any) -> str:
        try:
            return page.locator("body").inner_text(timeout=self._timeoutMilliseconds)
        except Exception:
            return ""

    def _ReadElementUrls(
        self,
        page: Any,
        selector: str,
        primaryAttributeName: str,
        fallbackAttributeName: Optional[str] = None,
    ) -> List[str]:
        script = """
            ([attributeName, fallbackAttributeName]) => Array.from(document.querySelectorAll("%s"))
                .map((element) => element[attributeName] || (fallbackAttributeName ? element[fallbackAttributeName] : ""))
                .filter((value) => value && value.trim() !== "")
        """ % selector
        values = page.evaluate(script, [primaryAttributeName, fallbackAttributeName])
        if not isinstance(values, list):
            return []

        normalizedUrls: List[str] = []
        seenUrls: set[str] = set()
        for value in values:
            if not isinstance(value, str):
                continue
            normalizedUrl = urljoin(page.url, value.strip())
            if normalizedUrl in seenUrls:
                continue
            seenUrls.add(normalizedUrl)
            normalizedUrls.append(normalizedUrl)

        return normalizedUrls

    def _ReadHeadingTexts(self, page: Any) -> List[str]:
        values = page.evaluate(
            """
            () => Array.from(document.querySelectorAll("h1,h2,h3"))
                .map((element) => element.innerText || "")
                .filter((value) => value && value.trim() !== "")
            """
        )
        if not isinstance(values, list):
            return []

        headingTexts: List[str] = []
        seenTexts: set[str] = set()
        for value in values:
            if not isinstance(value, str):
                continue
            normalizedValue = NormalizeWhitespace(value)
            if normalizedValue == "" or normalizedValue in seenTexts:
                continue
            seenTexts.add(normalizedValue)
            headingTexts.append(normalizedValue)

        return headingTexts

    def _ReadStructuredData(self, page: Any) -> List[Dict[str, Any]]:
        values = page.evaluate(
            """
            () => Array.from(document.querySelectorAll('script[type="application/ld+json"]'))
                .map((element) => element.textContent || "")
                .filter((value) => value && value.trim() !== "")
            """
        )
        if not isinstance(values, list):
            return []

        structuredData: List[Dict[str, Any]] = []
        for value in values:
            if not isinstance(value, str):
                continue
            structuredData.extend(self._ParseStructuredDataText(value))

        return structuredData

    def _ParseStructuredDataText(self, value: str) -> List[Dict[str, Any]]:
        try:
            parsedValue = json.loads(value)
        except json.JSONDecodeError:
            return []

        if isinstance(parsedValue, dict):
            return [parsedValue]
        if isinstance(parsedValue, list):
            return [item for item in parsedValue if isinstance(item, dict)]

        return []

    def _ReadScreenshot(self, page: Any) -> Optional[bytes]:
        if not self._includeScreenshot and self._ocrEngine is None:
            return None

        return page.screenshot(full_page=True)

    def _ReadOcrText(
        self,
        screenshotBytes: Optional[bytes],
        limitations: List[str],
    ) -> Optional[str]:
        if self._ocrEngine is None:
            limitations.append(
                "OCR engine is not configured; image-only specification blocks may be missing."
            )
            return None

        if screenshotBytes is None:
            limitations.append("Screenshot is unavailable; OCR was skipped.")
            return None

        ocrText = NormalizeWhitespace(
            self._ocrEngine.ExtractTextFromImage(screenshotBytes),
        )
        if ocrText == "":
            limitations.append("OCR engine returned empty text.")
            return None

        return ocrText

    def _BuildInitialLimitations(self) -> List[str]:
        return [
            "Fetched page content is source evidence for human review, not a final classification basis by itself.",
        ]

    def _NormalizeUrl(self, url: str) -> str:
        normalizedUrl = url.strip()
        if normalizedUrl == "":
            raise ProductSourceFetchError("url must not be empty.")

        if normalizedUrl.startswith("http://") or normalizedUrl.startswith(
            "https://",
        ):
            return normalizedUrl

        return "https://" + normalizedUrl
