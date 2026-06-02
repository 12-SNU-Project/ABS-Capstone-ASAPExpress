"""KurlyMarket 상품 상세 parser.

Collector와 HTML extractor는 전용 모듈에 있지만, 기존 import 경로 호환을
위해 이 모듈에서도 alias로 노출한다.
"""

import re
from typing import List, Optional
from urllib.parse import urlparse

from eu_export.product.kurly_market_collector import (
    KurlyMarketCollectionError,
    KurlyMarketProductPageCollector,
)
from eu_export.product.kurly_market_html import KurlyMarketHtmlTextExtractor
from eu_export.product.kurly_market_schema import (
    KurlyMarketProductDomain,
    KurlyMarketProductNoticeField,
    KurlyMarketProductNoticeOptionRecord,
    KurlyMarketProductPageParseResult,
)
from eu_export.utils import NormalizeWhitespace


__all__ = [
    "KurlyMarketBaseProductPageParser",
    "KurlyMarketCosmeticsProductPageParser",
    "KurlyMarketFoodProductPageParser",
    "KurlyMarketProductDomainDetector",
    "KurlyMarketProductPageParser",
    "KurlyMarketCollectionError",
    "KurlyMarketProductPageCollector",
    "KurlyMarketHtmlTextExtractor",
]


COSMETICS_PRODUCT_NOTICE_FIELD_LABELS = [
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
FOOD_PRODUCT_NOTICE_FIELD_LABELS = [
    "제품명",
    "식품의 유형",
    "생산자 및 소재지 (수입품의 경우 생산자, 수입자 및 제조국)",
    "생산자 및 소재지",
    "제조연월일, 소비기한 또는 품질유지기한",
    "포장단위별 내용물의 용량(중량), 수량",
    "포장단위별 내용물의 용량",
    "원재료명 (｢농수산물의 원산지 표시 등에 관한 법률｣에 따른 원산지 표시 포함) 및 함량(원재료 함량 표시대상 식품에 한함)",
    "원재료명",
    "영양성분 (영양성분 표시대상 식품에 한함)",
    "영양성분",
    "유전자변형식품에 해당하는 경우의 표시",
    "소비자 안전을 위한 주의사항 (｢식품 등의 표시ㆍ광고에 관한 법률 시행규칙｣ 제5조 및 [별표 2]에 따른 표시사항을 말함)",
    "소비자 안전을 위한 주의사항",
    "수입식품의 경우 “수입식품안전관리 특별법에 따른 수입신고를 필함”의 문구",
    "수입식품안전관리 특별법에 따른 수입신고를 필함",
    "소비자 상담 관련 전화번호",
]
ALL_PRODUCT_NOTICE_FIELD_LABELS = list(
    dict.fromkeys(
        COSMETICS_PRODUCT_NOTICE_FIELD_LABELS
        + FOOD_PRODUCT_NOTICE_FIELD_LABELS
    )
)
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


class KurlyMarketBaseProductPageParser:
    """Kurly Market 상품 상세 공통 parser."""

    def __init__(
        self,
        productDomain: KurlyMarketProductDomain = KurlyMarketProductDomain.UNKNOWN,
        productNoticeFieldLabels: Optional[List[str]] = None,
    ) -> None:
        self._productDomain = productDomain
        self._productNoticeFieldLabels = list(
            productNoticeFieldLabels or ALL_PRODUCT_NOTICE_FIELD_LABELS
        )

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
    ) -> KurlyMarketProductPageParseResult:
        textLines = KurlyMarketHtmlTextExtractor().ExtractTextLines(htmlText)
        return self.ParseTextLines(textLines, productPageUrl=productPageUrl)

    def ParseText(
        self,
        pageText: str,
        productPageUrl: Optional[str] = None,
    ) -> KurlyMarketProductPageParseResult:
        textLines = self.NormalizeTextLines(pageText.splitlines())
        return self.ParseTextLines(textLines, productPageUrl=productPageUrl)

    def ParseTextLines(
        self,
        textLines: List[str],
        productPageUrl: Optional[str] = None,
    ) -> KurlyMarketProductPageParseResult:
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
    ) -> KurlyMarketProductPageParseResult:
        normalizedLines = self.NormalizeTextLines(textLines)
        productName = self._ExtractProductName(normalizedLines)
        noticeLines = productNoticeLines or self._ExtractProductNoticeLines(
            normalizedLines,
        )
        noticeOptions = self._ExtractProductNoticeOptionRecords(noticeLines)
        noticeOptionNames = self._ExtractProductNoticeOptionNames(noticeOptions)
        noticeFields = self._BuildRepresentativeProductNoticeFields(noticeOptions)
        imageReferenceDetected = self._HasImageReference(noticeLines)
        warnings = self._BuildWarnings(
            normalizedLines,
            noticeLines,
            noticeFields,
        )

        return KurlyMarketProductPageParseResult(
            productPageUrl=productPageUrl,
            productDomain=self._productDomain,
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
            productNoticeOptions=noticeOptions,
            rawProductNoticeText="\n".join(noticeLines),
            imageReferenceDetected=imageReferenceDetected,
            requiresOcrFallback=(
                imageReferenceDetected or len(noticeFields) == 0
            ),
            warnings=warnings,
        )

    def NormalizeProductNoticeLines(self, textLines: List[str]) -> List[str]:
        normalizedLines = self.NormalizeTextLines(textLines)
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

    def NormalizeTextLines(self, textLines: List[str]) -> List[str]:
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
        noticeOptions: List[KurlyMarketProductNoticeOptionRecord],
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

    def _BuildRepresentativeProductNoticeFields(
        self,
        noticeOptions: List[KurlyMarketProductNoticeOptionRecord],
    ) -> List[KurlyMarketProductNoticeField]:
        fields: List[KurlyMarketProductNoticeField] = []
        seenFieldKeys: set[tuple[str, Optional[str]]] = set()
        for noticeOption in noticeOptions:
            for fieldRecord in noticeOption.fields:
                fieldKey = (fieldRecord.fieldName, fieldRecord.fieldValue)
                if fieldKey in seenFieldKeys:
                    continue
                seenFieldKeys.add(fieldKey)
                fields.append(fieldRecord)
        return fields

    def _ExtractProductNoticeOptionRecords(
        self,
        noticeLines: List[str],
    ) -> List[KurlyMarketProductNoticeOptionRecord]:
        optionRecords: List[KurlyMarketProductNoticeOptionRecord] = []
        currentOptionNames: List[str] = []
        currentFieldRecords: List[KurlyMarketProductNoticeField] = []
        currentRawLines: List[str] = []

        index = 0
        while index < len(noticeLines):
            line = noticeLines[index]
            fieldName = self._NormalizeProductNoticeFieldName(line)
            if fieldName is None:
                if currentFieldRecords and self._LooksProductNoticeOptionName(line):
                    optionRecords.extend(
                        self._BuildProductNoticeOptionRecords(
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
                KurlyMarketProductNoticeField(
                    fieldName=fieldName,
                    fieldValue=fieldValue,
                    requiresOcrFallback=self._NoticeValueRequiresOcr(fieldValue),
                    rawText="\n".join(rawLines),
                )
            )
            currentRawLines.extend(rawLines)

        if currentOptionNames or currentFieldRecords:
            optionRecords.extend(
                self._BuildProductNoticeOptionRecords(
                    currentOptionNames,
                    currentFieldRecords,
                    currentRawLines,
                )
            )

        return optionRecords

    def _BuildProductNoticeOptionRecords(
        self,
        optionNames: List[str],
        fields: List[KurlyMarketProductNoticeField],
        rawLines: List[str],
    ) -> List[KurlyMarketProductNoticeOptionRecord]:
        rawText = "\n".join(rawLines)
        if not optionNames:
            return [
                KurlyMarketProductNoticeOptionRecord(
                    optionName=None,
                    fields=list(fields),
                    rawText=rawText,
                )
            ]

        return [
            KurlyMarketProductNoticeOptionRecord(
                optionName=optionName,
                fields=list(fields),
                rawText=rawText,
            )
            for optionName in optionNames
        ]

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
        for label in self._productNoticeFieldLabels:
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
            self._productNoticeFieldLabels,
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
        noticeFields: List[KurlyMarketProductNoticeField],
    ) -> List[str]:
        warnings: List[str] = []
        if not textLines:
            warnings.append("page text is empty")
        if not noticeLines:
            warnings.append("product notice section not found")
        elif not noticeFields:
            warnings.append("product notice fields not parsed")
        return warnings


class KurlyMarketCosmeticsProductPageParser(KurlyMarketBaseProductPageParser):
    """Kurly 화장품 상품고시정보 parser."""

    def __init__(self) -> None:
        super().__init__(
            productDomain=KurlyMarketProductDomain.COSMETICS,
            productNoticeFieldLabels=COSMETICS_PRODUCT_NOTICE_FIELD_LABELS,
        )


class KurlyMarketFoodProductPageParser(KurlyMarketBaseProductPageParser):
    """Kurly 식품 상품고시정보 parser."""

    def __init__(self) -> None:
        super().__init__(
            productDomain=KurlyMarketProductDomain.FOOD,
            productNoticeFieldLabels=FOOD_PRODUCT_NOTICE_FIELD_LABELS,
        )


class KurlyMarketProductDomainDetector:
    """상품고시정보 label hit를 기반으로 Kurly 상품 domain을 추정한다."""

    def Detect(self, productNoticeLines: List[str]) -> KurlyMarketProductDomain:
        foodScore = self._CountLabelHits(
            productNoticeLines,
            FOOD_PRODUCT_NOTICE_FIELD_LABELS,
        )
        cosmeticsScore = self._CountLabelHits(
            productNoticeLines,
            COSMETICS_PRODUCT_NOTICE_FIELD_LABELS,
        )

        if foodScore == 0 and cosmeticsScore == 0:
            return KurlyMarketProductDomain.UNKNOWN
        if foodScore == cosmeticsScore:
            return KurlyMarketProductDomain.AMBIGUOUS
        if foodScore > cosmeticsScore:
            return KurlyMarketProductDomain.FOOD
        return KurlyMarketProductDomain.COSMETICS

    def _CountLabelHits(
        self,
        productNoticeLines: List[str],
        fieldLabels: List[str],
    ) -> int:
        score = 0
        for line in productNoticeLines:
            if self._MatchesAnyLabel(line, fieldLabels):
                score += 1
        return score

    def _MatchesAnyLabel(self, line: str, fieldLabels: List[str]) -> bool:
        comparableLine = line.lower().replace(" ", "")
        for fieldLabel in fieldLabels:
            comparableLabel = fieldLabel.lower().replace(" ", "")
            if comparableLine == comparableLabel:
                return True
            if comparableLine.startswith(comparableLabel):
                return True
        return False


class KurlyMarketProductPageParser:
    """상품고시정보 domain을 감지해 식품/화장품 parser로 분기한다."""

    def __init__(
        self,
        domainDetector: Optional[KurlyMarketProductDomainDetector] = None,
        foodParser: Optional[KurlyMarketFoodProductPageParser] = None,
        cosmeticsParser: Optional[KurlyMarketCosmeticsProductPageParser] = None,
        fallbackParser: Optional[KurlyMarketBaseProductPageParser] = None,
    ) -> None:
        self._domainDetector = domainDetector or KurlyMarketProductDomainDetector()
        self._foodParser = foodParser or KurlyMarketFoodProductPageParser()
        self._cosmeticsParser = (
            cosmeticsParser or KurlyMarketCosmeticsProductPageParser()
        )
        self._fallbackParser = fallbackParser or KurlyMarketBaseProductPageParser()

    def IsSupportedProductPageUrl(self, url: str) -> bool:
        return self._fallbackParser.IsSupportedProductPageUrl(url)

    def ParseHtml(
        self,
        htmlText: str,
        productPageUrl: Optional[str] = None,
    ) -> KurlyMarketProductPageParseResult:
        textLines = KurlyMarketHtmlTextExtractor().ExtractTextLines(htmlText)
        return self.ParseTextLines(textLines, productPageUrl=productPageUrl)

    def ParseText(
        self,
        pageText: str,
        productPageUrl: Optional[str] = None,
    ) -> KurlyMarketProductPageParseResult:
        textLines = self.NormalizeTextLines(pageText.splitlines())
        return self.ParseTextLines(textLines, productPageUrl=productPageUrl)

    def ParseTextLines(
        self,
        textLines: List[str],
        productPageUrl: Optional[str] = None,
    ) -> KurlyMarketProductPageParseResult:
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
    ) -> KurlyMarketProductPageParseResult:
        normalizedTextLines = self.NormalizeTextLines(textLines)
        normalizedNoticeLines = productNoticeLines or (
            self._fallbackParser._ExtractProductNoticeLines(normalizedTextLines)
        )
        parser = self._SelectParser(normalizedNoticeLines)
        return parser.ParseCollectedTextLines(
            textLines=normalizedTextLines,
            productNoticeLines=normalizedNoticeLines,
            productPageUrl=productPageUrl,
        )

    def NormalizeProductNoticeLines(self, textLines: List[str]) -> List[str]:
        return self._fallbackParser.NormalizeProductNoticeLines(textLines)

    def NormalizeTextLines(self, textLines: List[str]) -> List[str]:
        return self._fallbackParser.NormalizeTextLines(textLines)

    def DetectProductDomain(
        self,
        productNoticeLines: List[str],
    ) -> KurlyMarketProductDomain:
        return self._domainDetector.Detect(productNoticeLines)

    def _SelectParser(
        self,
        productNoticeLines: List[str],
    ) -> KurlyMarketBaseProductPageParser:
        productDomain = self.DetectProductDomain(productNoticeLines)
        if productDomain == KurlyMarketProductDomain.FOOD:
            return self._foodParser
        if productDomain == KurlyMarketProductDomain.COSMETICS:
            return self._cosmeticsParser
        return self._fallbackParser
