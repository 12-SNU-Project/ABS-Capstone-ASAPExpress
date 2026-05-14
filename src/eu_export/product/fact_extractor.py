"""수집된 상품 출처 원문에서 HS/CN 후보 분류용 fact를 추출한다."""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from eu_export.product.fetcher import FetchedProductSource
from eu_export.product.query import ProductDomainHint
from eu_export.product.ranker import RankedProductSourceCandidate
from eu_export.product.source import (
    NormalizedProductInformation,
    ProductQuantity,
    ProductSourceRole,
)
from eu_export.utils import NormalizeWhitespace


QUANTITY_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?\s?(?:g|kg|mg|ml|mL|l|L|oz|lb|ea|pcs|개|봉|팩|입|병|캔|박스|포|매|장)\b",
    re.IGNORECASE,
)
PRICE_PATTERN = re.compile(r"(?P<amount>\d{1,3}(?:,\d{3})+|\d+)\s?원")
BRACKET_BRAND_PATTERN = re.compile(r"^\[([^\]]+)\]")
LATIN_INGREDIENT_PATTERN = re.compile(r"^[A-Za-z0-9 ,.'()/+-]+$")
FIELD_LABEL_TERMS = {
    "판매자",
    "판매단위",
    "중량/용량",
    "원산지",
    "제조국",
    "제조사",
    "제조원",
    "전성분",
    "성분",
    "원재료명",
    "원재료",
    "제형",
    "형태",
    "타입",
    "사용법",
    "사용방법",
    "보관방법",
    "보관",
    "포장타입",
}


@dataclass(frozen=True)
class ProductClassificationFactPackage:
    """CN 후보 분류 전에 사용할 상품 fact 묶음."""

    productInformation: NormalizedProductInformation
    classificationName: str
    classificationDescription: Optional[str] = None
    materialOrIngredientText: Optional[str] = None
    intendedUseText: Optional[str] = None
    physicalFormText: Optional[str] = None
    quantityText: Optional[str] = None
    sourceTexts: List[str] = field(default_factory=list)
    missingInformation: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)

    def ToDict(self) -> Dict[str, Any]:
        return {
            "product_information": self.productInformation.ToDict(),
            "classification_name": self.classificationName,
            "classification_description": self.classificationDescription,
            "material_or_ingredient_text": self.materialOrIngredientText,
            "intended_use_text": self.intendedUseText,
            "physical_form_text": self.physicalFormText,
            "quantity_text": self.quantityText,
            "source_texts": list(self.sourceTexts),
            "missing_information": list(self.missingInformation),
            "limitations": list(self.limitations),
        }


class ProductFactExtractor:
    """상품 상세 페이지의 visible text와 OCR 텍스트를 공통 상품 fact로 정규화한다."""

    def Extract(
        self,
        fetchedSource: FetchedProductSource,
        candidate: Optional[RankedProductSourceCandidate] = None,
    ) -> ProductClassificationFactPackage:
        sourceText = self._BuildSourceText(fetchedSource)
        sourceLines = self._BuildSourceLines(fetchedSource)
        productDomainHint = self._ResolveProductDomainHint(fetchedSource, candidate)
        productName = self._ExtractProductName(fetchedSource, candidate)
        brandName = self._ExtractBrandName(productName, fetchedSource)
        quantities = self._ExtractQuantities(sourceText)
        ingredientDeclaration = self._ExtractIngredientDeclaration(sourceLines)
        inciList = self._ExtractInciList(ingredientDeclaration)
        originStatement = self._ExtractOriginStatement(sourceLines)
        countryOfOrigin = self._InferCountryCode(originStatement)
        countryOfManufacture = self._InferCountryCode(
            self._ExtractManufactureCountryStatement(sourceLines),
        )
        storageCondition = self._ExtractFirstFieldValue(
            sourceLines,
            ["보관방법", "보관", "포장타입", "storage"],
        )
        productDescription = self._ExtractProductDescription(
            productName,
            fetchedSource,
            sourceLines,
        )
        priceAmount = self._ExtractPriceAmount(sourceText)
        missingInformation = self._BuildMissingInformation(
            productDomainHint,
            brandName,
            quantities,
            ingredientDeclaration,
            inciList,
            originStatement,
            countryOfManufacture,
        )
        limitations = self._BuildLimitations(fetchedSource)

        productInformation = NormalizedProductInformation(
            sourceProvider=self._ResolveSourceProvider(fetchedSource, candidate),
            sourceRole=self._ResolveSourceRole(fetchedSource, candidate),
            productPageUrl=fetchedSource.productPageUrl,
            productDomainHint=productDomainHint,
            productName=productName,
            sourceCountry=None,
            language="ko",
            brandName=brandName,
            sellerName=self._ExtractFirstFieldValue(sourceLines, ["판매자", "seller"]),
            manufacturerName=self._ExtractFirstFieldValue(
                sourceLines,
                ["제조사", "제조원", "manufacturer"],
            ),
            categoryPath=self._BuildCategoryPath(fetchedSource),
            quantities=quantities,
            ingredientDeclaration=ingredientDeclaration,
            inciList=inciList,
            originStatement=originStatement,
            countryOfOrigin=countryOfOrigin,
            countryOfManufacture=countryOfManufacture,
            storageCondition=storageCondition,
            productDescription=productDescription,
            imageUrls=list(fetchedSource.imageUrls),
            priceAmount=priceAmount,
            priceCurrency="KRW" if priceAmount is not None else None,
            rawSearchTitle=(
                candidate.rawSearchTitle
                if candidate is not None
                else fetchedSource.title
            ),
            rawSearchSnippet=(
                candidate.rawSearchSnippet
                if candidate is not None
                else None
            ),
            rawSourceData=self._BuildRawSourceData(fetchedSource, candidate),
            missingInformation=missingInformation,
            limitations=limitations,
        )

        return ProductClassificationFactPackage(
            productInformation=productInformation,
            classificationName=productName,
            classificationDescription=productDescription,
            materialOrIngredientText=ingredientDeclaration,
            intendedUseText=self._ExtractIntendedUseText(sourceLines),
            physicalFormText=self._ExtractPhysicalFormText(sourceLines),
            quantityText=self._BuildQuantityText(quantities),
            sourceTexts=self._BuildSourceTextExcerpts(fetchedSource),
            missingInformation=missingInformation,
            limitations=limitations,
        )

    def _ResolveProductDomainHint(
        self,
        fetchedSource: FetchedProductSource,
        candidate: Optional[RankedProductSourceCandidate],
    ) -> ProductDomainHint:
        if candidate is not None and candidate.productDomainHint in (
            ProductDomainHint.COSMETICS,
            ProductDomainHint.PROCESSED_FOOD,
        ):
            return candidate.productDomainHint

        if fetchedSource.productDomainHint in (
            ProductDomainHint.COSMETICS,
            ProductDomainHint.PROCESSED_FOOD,
        ):
            return fetchedSource.productDomainHint

        sourceText = self._BuildSourceText(fetchedSource).lower()
        if any(
            term in sourceText
            for term in ["뷰티", "화장품", "스킨", "세럼", "크림", "클렌저", "전성분"]
        ):
            return ProductDomainHint.COSMETICS
        if any(term in sourceText for term in ["원재료명", "식품", "알레르기"]):
            return ProductDomainHint.PROCESSED_FOOD

        return fetchedSource.productDomainHint

    def _ResolveSourceProvider(
        self,
        fetchedSource: FetchedProductSource,
        candidate: Optional[RankedProductSourceCandidate],
    ) -> str:
        if candidate is not None:
            return candidate.sourceProvider
        return fetchedSource.sourceProvider

    def _ResolveSourceRole(
        self,
        fetchedSource: FetchedProductSource,
        candidate: Optional[RankedProductSourceCandidate],
    ) -> ProductSourceRole:
        if candidate is not None:
            return candidate.sourceRole
        return fetchedSource.sourceRole

    def _ExtractProductName(
        self,
        fetchedSource: FetchedProductSource,
        candidate: Optional[RankedProductSourceCandidate],
    ) -> str:
        structuredName = self._ExtractStructuredDataString(
            fetchedSource,
            "name",
        )
        if structuredName is not None:
            return structuredName

        for headingText in fetchedSource.headingTexts:
            if self._LooksProductName(headingText):
                return headingText

        if candidate is not None and candidate.rawSearchTitle is not None:
            return NormalizeWhitespace(candidate.rawSearchTitle)

        if fetchedSource.title is not None:
            return NormalizeWhitespace(fetchedSource.title)

        return "unknown product"

    def _ExtractBrandName(
        self,
        productName: str,
        fetchedSource: FetchedProductSource,
    ) -> Optional[str]:
        structuredBrand = self._ExtractStructuredBrand(fetchedSource)
        if structuredBrand is not None:
            return structuredBrand

        brandMatch = BRACKET_BRAND_PATTERN.search(productName)
        if brandMatch is not None:
            return NormalizeWhitespace(brandMatch.group(1))

        return None

    def _ExtractStructuredBrand(
        self,
        fetchedSource: FetchedProductSource,
    ) -> Optional[str]:
        for structuredItem in fetchedSource.structuredData:
            brandValue = structuredItem.get("brand")
            if isinstance(brandValue, str):
                return NormalizeWhitespace(brandValue)
            if isinstance(brandValue, dict):
                nameValue = brandValue.get("name")
                if isinstance(nameValue, str):
                    return NormalizeWhitespace(nameValue)

        return None

    def _ExtractStructuredDataString(
        self,
        fetchedSource: FetchedProductSource,
        fieldName: str,
    ) -> Optional[str]:
        for structuredItem in fetchedSource.structuredData:
            value = structuredItem.get(fieldName)
            if isinstance(value, str) and NormalizeWhitespace(value) != "":
                return NormalizeWhitespace(value)

        return None

    def _ExtractQuantities(self, sourceText: str) -> List[ProductQuantity]:
        quantities: List[ProductQuantity] = []
        seenValues: set[str] = set()
        for match in QUANTITY_PATTERN.finditer(sourceText):
            rawText = NormalizeWhitespace(match.group(0))
            if rawText in seenValues:
                continue
            seenValues.add(rawText)
            quantities.append(ProductQuantity(rawText=rawText))

        return quantities

    def _ExtractIngredientDeclaration(self, sourceLines: List[str]) -> Optional[str]:
        return self._ExtractFirstFieldValue(
            sourceLines,
            ["전성분", "성분", "원재료명", "원재료", "ingredients", "ingredient"],
            maxContinuationLines=3,
        )

    def _ExtractInciList(self, ingredientDeclaration: Optional[str]) -> List[str]:
        if ingredientDeclaration is None:
            return []
        if LATIN_INGREDIENT_PATTERN.match(ingredientDeclaration) is None:
            return []

        return [
            NormalizeWhitespace(item)
            for item in ingredientDeclaration.split(",")
            if NormalizeWhitespace(item) != ""
        ]

    def _ExtractOriginStatement(self, sourceLines: List[str]) -> Optional[str]:
        return self._ExtractFirstFieldValue(
            sourceLines,
            ["원산지", "제조국 또는 원산지", "country of origin"],
            maxContinuationLines=2,
        )

    def _ExtractManufactureCountryStatement(
        self,
        sourceLines: List[str],
    ) -> Optional[str]:
        return self._ExtractFirstFieldValue(
            sourceLines,
            ["제조국", "제조국가", "country of manufacture", "made in"],
            maxContinuationLines=2,
        )

    def _ExtractFirstFieldValue(
        self,
        sourceLines: List[str],
        labels: List[str],
        maxContinuationLines: int = 1,
    ) -> Optional[str]:
        normalizedLabels = [label.lower().replace(" ", "") for label in labels]
        for index, line in enumerate(sourceLines):
            comparableLine = line.lower().replace(" ", "")
            for label, comparableLabel in zip(labels, normalizedLabels):
                if comparableLabel not in comparableLine:
                    continue
                value = self._ReadInlineFieldValue(line, label)
                if value is not None:
                    return value
                return self._ReadFollowingFieldValue(
                    sourceLines,
                    index,
                    maxContinuationLines,
                )

        return None

    def _ReadInlineFieldValue(self, line: str, label: str) -> Optional[str]:
        loweredLine = line.lower()
        loweredLabel = label.lower()
        labelIndex = loweredLine.find(loweredLabel)
        if labelIndex < 0:
            return None

        remainder = line[labelIndex + len(label):].strip(" :：·-")
        if remainder == "":
            return None
        return NormalizeWhitespace(remainder)

    def _ReadFollowingFieldValue(
        self,
        sourceLines: List[str],
        startIndex: int,
        maxContinuationLines: int,
    ) -> Optional[str]:
        collectedLines: List[str] = []
        for offset in range(1, maxContinuationLines + 1):
            nextIndex = startIndex + offset
            if nextIndex >= len(sourceLines):
                break
            nextLine = sourceLines[nextIndex]
            if nextLine == "":
                continue
            if collectedLines and self._LooksFieldLabelLine(nextLine):
                break
            collectedLines.append(nextLine)

        if not collectedLines:
            return None
        return NormalizeWhitespace(" ".join(collectedLines))

    def _ExtractProductDescription(
        self,
        productName: str,
        fetchedSource: FetchedProductSource,
        sourceLines: List[str],
    ) -> Optional[str]:
        structuredDescription = self._ExtractStructuredDataString(
            fetchedSource,
            "description",
        )
        if structuredDescription is not None:
            return structuredDescription

        for line in sourceLines:
            if line == productName:
                continue
            if len(line) >= 12 and not self._LooksMenuLine(line):
                return line

        return None

    def _ExtractPriceAmount(self, sourceText: str) -> Optional[float]:
        priceMatch = PRICE_PATTERN.search(sourceText)
        if priceMatch is None:
            return None
        return float(priceMatch.group("amount").replace(",", ""))

    def _BuildMissingInformation(
        self,
        productDomainHint: ProductDomainHint,
        brandName: Optional[str],
        quantities: List[ProductQuantity],
        ingredientDeclaration: Optional[str],
        inciList: List[str],
        originStatement: Optional[str],
        countryOfManufacture: Optional[str],
    ) -> List[str]:
        missingInformation: List[str] = []
        if brandName is None:
            missingInformation.append("brand name")
        if not quantities:
            missingInformation.append("net quantity or packaging size")
        if originStatement is None:
            missingInformation.append("country of origin")
        if countryOfManufacture is None:
            missingInformation.append("country of manufacture")

        if productDomainHint == ProductDomainHint.COSMETICS:
            if ingredientDeclaration is None and not inciList:
                missingInformation.append("INCI list or full ingredient declaration")
            missingInformation.append("cosmetic function confirmation")
        elif productDomainHint == ProductDomainHint.PROCESSED_FOOD:
            if ingredientDeclaration is None:
                missingInformation.append("ingredient declaration")
            missingInformation.append("storage condition and food category confirmation")
        else:
            missingInformation.append("product domain confirmation")

        return missingInformation

    def _BuildLimitations(self, fetchedSource: FetchedProductSource) -> List[str]:
        limitations = list(fetchedSource.limitations)
        limitations.append(
            "Extracted facts are preliminary and must be reviewed before CN classification."
        )
        if fetchedSource.ocrText is None:
            limitations.append(
                "OCR text is unavailable; image-only product specifications may be missing."
            )
        return limitations

    def _BuildRawSourceData(
        self,
        fetchedSource: FetchedProductSource,
        candidate: Optional[RankedProductSourceCandidate],
    ) -> Dict[str, Any]:
        return {
            "fetched_source": {
                "title": fetchedSource.title,
                "html_length": len(fetchedSource.html),
                "visible_text_length": len(fetchedSource.visibleText),
                "ocr_text_length": (
                    len(fetchedSource.ocrText)
                    if fetchedSource.ocrText is not None
                    else 0
                ),
                "image_url_count": len(fetchedSource.imageUrls),
                "link_url_count": len(fetchedSource.linkUrls),
                "structured_data": list(fetchedSource.structuredData),
            },
            "candidate": candidate.ToDict() if candidate is not None else None,
        }

    def _ExtractIntendedUseText(self, sourceLines: List[str]) -> Optional[str]:
        return self._ExtractFirstFieldValue(
            sourceLines,
            ["사용법", "사용방법", "용도", "기능", "효능", "features"],
            maxContinuationLines=3,
        )

    def _ExtractPhysicalFormText(self, sourceLines: List[str]) -> Optional[str]:
        return self._ExtractFirstFieldValue(
            sourceLines,
            ["제형", "형태", "타입", "texture", "form"],
            maxContinuationLines=2,
        )

    def _BuildQuantityText(self, quantities: List[ProductQuantity]) -> Optional[str]:
        if not quantities:
            return None
        return ", ".join(quantity.rawText for quantity in quantities)

    def _BuildCategoryPath(self, fetchedSource: FetchedProductSource) -> List[str]:
        return [
            headingText
            for headingText in fetchedSource.headingTexts[:5]
            if not self._LooksProductName(headingText)
        ]

    def _BuildSourceText(self, fetchedSource: FetchedProductSource) -> str:
        parts = [fetchedSource.title or "", fetchedSource.visibleText]
        if fetchedSource.ocrText is not None:
            parts.append(fetchedSource.ocrText)
        return "\n".join(parts)

    def _BuildSourceLines(self, fetchedSource: FetchedProductSource) -> List[str]:
        return [
            NormalizeWhitespace(line)
            for line in self._BuildSourceText(fetchedSource).splitlines()
            if NormalizeWhitespace(line) != ""
        ]

    def _BuildSourceTextExcerpts(
        self,
        fetchedSource: FetchedProductSource,
    ) -> List[str]:
        excerpts: List[str] = []
        for text in [
            fetchedSource.title,
            fetchedSource.visibleText,
            fetchedSource.ocrText,
        ]:
            if not isinstance(text, str):
                continue
            normalizedText = NormalizeWhitespace(text)
            if normalizedText == "":
                continue
            excerpts.append(normalizedText[:1000])

        return excerpts

    def _LooksProductName(self, text: str) -> bool:
        if len(text) < 4:
            return False
        if self._LooksMenuLine(text):
            return False
        return True

    def _LooksMenuLine(self, text: str) -> bool:
        return text in {"상품설명", "상세정보", "후기", "문의", "장바구니 담기"}

    def _LooksFieldLabelLine(self, text: str) -> bool:
        normalizedText = text.replace(" ", "")
        return any(
            normalizedText == label.replace(" ", "")
            for label in FIELD_LABEL_TERMS
        )

    def _InferCountryCode(self, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None

        loweredValue = value.lower()
        if any(term in loweredValue for term in ["대한민국", "한국", "korea", "kr"]):
            return "KR"
        if any(term in loweredValue for term in ["중국", "china", "cn"]):
            return "CN"
        if any(term in loweredValue for term in ["프랑스", "france", "fr"]):
            return "FR"
        if any(term in loweredValue for term in ["미국", "usa", "united states", "us"]):
            return "US"
        if any(term in loweredValue for term in ["일본", "japan", "jp"]):
            return "JP"

        return None
