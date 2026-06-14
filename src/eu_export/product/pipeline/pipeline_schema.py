"""Product source pipeline schema."""

from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, computed_field

from eu_export.product.web_parser.kurly_market_schema import (
    KurlyCollectionResult,
    RenderedPageEvidence,
)
from eu_export.product.ocr.ocr_fallback import (
    DEFAULT_PRODUCT_OCR_IMAGE_ARTIFACT_ROOT_PATH,
    DEFAULT_PRODUCT_OCR_IMAGE_DOWNLOAD_TIMEOUT_SECONDS,
    ProductOcrImageResult,
)
from eu_export.product.ocr.ocr_normalization import ProductOcrFactNormalizationResult


class KurlyPipelineInput(BaseModel):
    """KurlyMarket 수집 wrapper 입력."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    productPageUrl: str
    runOcrFallback: bool = False
    artifactRootPath: Path = DEFAULT_PRODUCT_OCR_IMAGE_ARTIFACT_ROOT_PATH
    maxOcrImageCount: int = Field(
        default=20,
        description="OCR fallback image batch size. All candidate images are processed in batches.",
    )
    downloadTimeoutSeconds: int = DEFAULT_PRODUCT_OCR_IMAGE_DOWNLOAD_TIMEOUT_SECONDS


class PipelineStep(BaseModel):
    """wrapper가 실행한 단계 하나의 상태."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    stepName: str = Field(alias="step_name")
    succeeded: bool = True
    message: str = ""


class KurlyPipelineResult(BaseModel):
    """KurlyMarket parsing과 선택적 OCR fallback을 묶은 결과."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    collectionResult: KurlyCollectionResult = Field(exclude=True)
    renderedPageEvidence: Optional[RenderedPageEvidence] = Field(
        default=None,
        exclude=True,
    )
    ocrImageResults: List[ProductOcrImageResult] = Field(
        default_factory=list,
        exclude=True,
    )
    combinedOcrText: str = Field(default="", alias="combined_ocr_text")
    ocrNormalizationResult: ProductOcrFactNormalizationResult = Field(
        default_factory=ProductOcrFactNormalizationResult,
        alias="ocr_normalization",
    )
    steps: List[PipelineStep] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)

    @computed_field(alias="product_page_url")
    @property
    def productPageUrl(self) -> str:
        return self.collectionResult.productPageUrl

    @computed_field(alias="parsed_product_page")
    @property
    def parsedProductPage(self) -> Dict[str, object]:
        return self.collectionResult.parsedProductPage.model_dump(
            mode="json",
            by_alias=True,
        )

    @computed_field(alias="collection_summary")
    @property
    def collectionSummary(self) -> Dict[str, object]:
        return {
            "product_page_url": self.collectionResult.productPageUrl,
            "visible_text_line_count": self.collectionResult.visibleTextLineCount,
            "product_notice_text_line_count": (
                self.collectionResult.productNoticeTextLineCount
            ),
            "product_detail_image_url_count": len(
                self.collectionResult.productDetailImageUrls,
            ),
            "ocr_candidate_image_url_count": len(
                self.collectionResult.ocrCandidateImageUrls,
            ),
            "warnings": list(self.collectionResult.warnings),
        }

    @computed_field(alias="rendered_page_evidence_summary")
    @property
    def renderedPageEvidenceSummary(self) -> Optional[Dict[str, object]]:
        if self.renderedPageEvidence is None:
            return None
        return self.renderedPageEvidence.model_dump(mode="json", by_alias=True)

    @computed_field(alias="ocr_summary")
    @property
    def ocrSummary(self) -> Dict[str, object]:
        successfulImageResults = [
            imageResult
            for imageResult in self.ocrImageResults
            if imageResult.error is None and imageResult.ocrText.strip() != ""
        ]
        structuredTableImageResults = [
            imageResult
            for imageResult in successfulImageResults
            if imageResult.structuredOcr.usedStructuredTables
        ]
        return {
            "image_result_count": len(self.ocrImageResults),
            "successful_image_count": len(successfulImageResults),
            "failed_image_count": (
                len(self.ocrImageResults) - len(successfulImageResults)
            ),
            "structured_table_image_count": len(structuredTableImageResults),
            "structured_table_count": sum(
                len(imageResult.structuredOcr.tables)
                for imageResult in successfulImageResults
            ),
            "raw_tile_text_count": sum(
                len(imageResult.structuredOcr.rawTileTexts)
                for imageResult in successfulImageResults
            ),
            "raw_text_length": sum(
                len(imageResult.structuredOcr.rawText)
                for imageResult in successfulImageResults
            ),
            "combined_text_length": len(self.combinedOcrText),
            "normalized_fact_count": self.ocrNormalizationResult.factLineCount,
            "raw_line_count": self.ocrNormalizationResult.rawLineCount,
            "normalization": self.ocrNormalizationResult.model_dump(
                mode="json",
                by_alias=True,
            ),
            "image_artifacts": [
                {
                    "index": imageIndex,
                    "image_path": (
                        str(imageResult.imagePath)
                        if imageResult.imagePath is not None
                        else None
                    ),
                    "text_length": len(imageResult.ocrText),
                    "used_structured_tables": (
                        imageResult.structuredOcr.usedStructuredTables
                    ),
                    "structured_table_count": len(imageResult.structuredOcr.tables),
                    "structured_fallback_reason": (
                        imageResult.structuredOcr.fallbackReason
                    ),
                    "text_merge_mode": imageResult.structuredOcr.textMergeMode,
                    "raw_tile_text_count": len(
                        imageResult.structuredOcr.rawTileTexts
                    ),
                    "raw_text_length": len(imageResult.structuredOcr.rawText),
                    "error": imageResult.error,
                }
                for imageIndex, imageResult in enumerate(
                    self.ocrImageResults,
                    start=1,
                )
                if imageResult.imagePath is not None
                and imageResult.ocrText.strip() != ""
            ],
        }
