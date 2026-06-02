"""Product source pipeline schema."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from eu_export.product.kurly_market_schema import (
    KurlyMarketProductPageCollectionResult,
    KurlyMarketRenderedPageEvidence,
)
from eu_export.product.ocr_fallback import (
    DEFAULT_PRODUCT_OCR_IMAGE_ARTIFACT_ROOT_PATH,
    DEFAULT_PRODUCT_OCR_IMAGE_DOWNLOAD_TIMEOUT_SECONDS,
    ProductOcrImageResult,
)


@dataclass(frozen=True)
class KurlyMarketProductSourcePipelineInput:
    """KurlyMarket 수집 wrapper 입력."""

    productPageUrl: str
    runOcrFallback: bool = False
    artifactRootPath: Path = DEFAULT_PRODUCT_OCR_IMAGE_ARTIFACT_ROOT_PATH
    maxOcrImageCount: int = 20
    downloadTimeoutSeconds: int = DEFAULT_PRODUCT_OCR_IMAGE_DOWNLOAD_TIMEOUT_SECONDS


@dataclass(frozen=True)
class KurlyMarketProductSourcePipelineStep:
    """wrapper가 실행한 단계 하나의 상태."""

    stepName: str
    succeeded: bool = True
    message: str = ""

    def ToDict(self) -> Dict[str, object]:
        return {
            "step_name": self.stepName,
            "succeeded": self.succeeded,
            "message": self.message,
        }


@dataclass(frozen=True)
class KurlyMarketProductSourcePipelineResult:
    """KurlyMarket parsing과 선택적 OCR fallback을 묶은 결과."""

    collectionResult: KurlyMarketProductPageCollectionResult
    renderedPageEvidence: Optional[KurlyMarketRenderedPageEvidence] = None
    ocrImageResults: List[ProductOcrImageResult] = field(default_factory=list)
    combinedOcrText: str = ""
    steps: List[KurlyMarketProductSourcePipelineStep] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def ToDict(self) -> Dict[str, object]:
        return {
            "collection_result": self.collectionResult.ToDict(),
            "rendered_page_evidence": self._BuildRenderedPageEvidenceSummary(),
            "ocr_image_results": [
                imageResult.ToDict() for imageResult in self.ocrImageResults
            ],
            "combined_ocr_text": self.combinedOcrText,
            "steps": [step.ToDict() for step in self.steps],
            "errors": list(self.errors),
        }

    def _BuildRenderedPageEvidenceSummary(self) -> Optional[Dict[str, object]]:
        if self.renderedPageEvidence is None:
            return None
        return {
            "product_page_url": self.renderedPageEvidence.productPageUrl,
            "visible_text_length": len(self.renderedPageEvidence.visibleText),
            "product_notice_text_length": len(
                self.renderedPageEvidence.productNoticeText
            ),
            "product_detail_image_url_count": len(
                self.renderedPageEvidence.productDetailImageUrls
            ),
        }
