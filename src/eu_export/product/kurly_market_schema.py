"""KurlyMarket product page collection schema."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class KurlyMarketProductDomain(str, Enum):
    """Kurly 상품고시정보 기준의 상품 domain."""

    FOOD = "food"
    COSMETICS = "cosmetics"
    AMBIGUOUS = "ambiguous"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class KurlyMarketProductNoticeField:
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
class KurlyMarketProductNoticeOptionRecord:
    """상품 옵션 하나에 정규화된 상품고시정보 field set."""

    optionName: Optional[str] = None
    fields: List[KurlyMarketProductNoticeField] = field(default_factory=list)
    rawText: str = ""

    def ToDict(self) -> Dict[str, object]:
        return {
            "option_name": self.optionName,
            "fields": [fieldRecord.ToDict() for fieldRecord in self.fields],
            "raw_text": self.rawText,
        }


@dataclass(frozen=True)
class KurlyMarketProductPageParseResult:
    """KurlyMarket 상품 상세 parser 결과."""

    productPageUrl: Optional[str] = None
    productDomain: KurlyMarketProductDomain = KurlyMarketProductDomain.UNKNOWN
    productName: Optional[str] = None
    shortDescription: Optional[str] = None
    brandName: Optional[str] = None
    packageType: Optional[str] = None
    saleUnit: Optional[str] = None
    productNoticeOptionNames: List[str] = field(default_factory=list)
    productNoticeFields: List[KurlyMarketProductNoticeField] = field(
        default_factory=list,
    )
    productNoticeOptions: List[KurlyMarketProductNoticeOptionRecord] = field(
        default_factory=list,
    )
    rawProductNoticeText: str = ""
    imageReferenceDetected: bool = False
    requiresOcrFallback: bool = False
    warnings: List[str] = field(default_factory=list)

    def ToDict(self) -> Dict[str, object]:
        return {
            "product_page_url": self.productPageUrl,
            "product_domain": self.productDomain.value,
            "product_name": self.productName,
            "short_description": self.shortDescription,
            "brand_name": self.brandName,
            "package_type": self.packageType,
            "sale_unit": self.saleUnit,
            "product_notice_option_names": list(self.productNoticeOptionNames),
            "product_notice_fields": [
                fieldRecord.ToDict() for fieldRecord in self.productNoticeFields
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
class KurlyMarketProductPageCollectionResult:
    """렌더링된 KurlyMarket 상품 페이지 수집 결과."""

    productPageUrl: str
    parsedProductPage: KurlyMarketProductPageParseResult
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
class KurlyMarketRenderedPageEvidence:
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
