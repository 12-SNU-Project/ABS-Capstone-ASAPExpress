"""상품 정보 수집 단계의 generic pipeline과 KurlyMarket wrapper."""

from abc import ABC, abstractmethod
from typing import Generic, List, Optional, TypeVar

from eu_export.product.kurly_market_collector import KurlyMarketProductPageCollector
from eu_export.product.kurly_market_schema import KurlyMarketProductPageCollectionResult
from eu_export.product.ocr_fallback import (
    ProductOcrFallbackRunner,
    ProductOcrImageResult,
)
from eu_export.product.paddle_ocr import ProductOcrEngine
from eu_export.product.pipeline_schema import (
    KurlyMarketProductSourcePipelineInput,
    KurlyMarketProductSourcePipelineResult,
    KurlyMarketProductSourcePipelineStep,
)

PipelineInputT = TypeVar("PipelineInputT")
PipelineOutputT = TypeVar("PipelineOutputT")


class Pipeline(ABC, Generic[PipelineInputT, PipelineOutputT]):
    """입력 하나를 받아 결과 하나를 반환하는 pipeline interface."""

    @abstractmethod
    def Run(self, pipelineInput: PipelineInputT) -> PipelineOutputT:
        raise NotImplementedError


class KurlyMarketProductSourcePipeline(
    Pipeline[
        KurlyMarketProductSourcePipelineInput,
        KurlyMarketProductSourcePipelineResult,
    ],
):
    """KurlyMarket parser와 PaddleOCR fallback을 단계적으로 연결하는 wrapper."""

    def __init__(
        self,
        collector: KurlyMarketProductPageCollector,
        ocrEngine: Optional[ProductOcrEngine] = None,
    ) -> None:
        self._collector = collector
        self._ocrEngine = ocrEngine

    def Run(
        self,
        pipelineInput: KurlyMarketProductSourcePipelineInput,
    ) -> KurlyMarketProductSourcePipelineResult:
        return self.Collect(pipelineInput)

    def Collect(
        self,
        pipelineInput: KurlyMarketProductSourcePipelineInput,
    ) -> KurlyMarketProductSourcePipelineResult:
        steps: List[KurlyMarketProductSourcePipelineStep] = []
        errors: List[str] = []

        self._collector.ValidateProductPageUrl(pipelineInput.productPageUrl)
        steps.append(
            KurlyMarketProductSourcePipelineStep(
                stepName="validate_product_page_url",
                message="supported KurlyMarket product page URL",
            )
        )

        renderedPageEvidence = self._collector.CollectRenderedPageEvidence(
            pipelineInput.productPageUrl,
        )
        steps.append(
            KurlyMarketProductSourcePipelineStep(
                stepName="collect_rendered_page_evidence",
                message=(
                    "visible_text_length={0}, product_notice_text_length={1}, "
                    "product_detail_image_url_count={2}"
                ).format(
                    len(renderedPageEvidence.visibleText),
                    len(renderedPageEvidence.productNoticeText),
                    len(renderedPageEvidence.productDetailImageUrls),
                ),
            )
        )

        collectionResult = self._collector.BuildCollectionResult(renderedPageEvidence)
        steps.append(
            KurlyMarketProductSourcePipelineStep(
                stepName="parse_product_page_evidence",
                message=(
                    "product_notice_field_count={0}, "
                    "requires_ocr_fallback={1}, "
                    "ocr_candidate_image_url_count={2}"
                ).format(
                    len(collectionResult.parsedProductPage.productNoticeFields),
                    collectionResult.parsedProductPage.requiresOcrFallback,
                    len(collectionResult.ocrCandidateImageUrls),
                ),
            )
        )

        ocrImageResults: List[ProductOcrImageResult] = []
        if pipelineInput.runOcrFallback:
            ocrImageResults = self._RunOcrFallback(
                collectionResult=collectionResult,
                pipelineInput=pipelineInput,
                steps=steps,
                errors=errors,
            )
        else:
            steps.append(
                KurlyMarketProductSourcePipelineStep(
                    stepName="ocr_fallback",
                    message="skipped because runOcrFallback=False",
                )
            )

        return KurlyMarketProductSourcePipelineResult(
            collectionResult=collectionResult,
            renderedPageEvidence=renderedPageEvidence,
            ocrImageResults=ocrImageResults,
            combinedOcrText=ProductOcrFallbackRunner.BuildCombinedOcrText(
                ocrImageResults
            ),
            steps=steps,
            errors=errors,
        )

    def _RunOcrFallback(
        self,
        collectionResult: KurlyMarketProductPageCollectionResult,
        pipelineInput: KurlyMarketProductSourcePipelineInput,
        steps: List[KurlyMarketProductSourcePipelineStep],
        errors: List[str],
    ) -> List[ProductOcrImageResult]:
        if not collectionResult.parsedProductPage.requiresOcrFallback:
            steps.append(
                KurlyMarketProductSourcePipelineStep(
                    stepName="ocr_fallback",
                    message="skipped because structured notice is sufficient",
                )
            )
            return []

        if self._ocrEngine is None:
            message = "OCR fallback requested but ProductOcrEngine is not configured"
            errors.append(message)
            steps.append(
                KurlyMarketProductSourcePipelineStep(
                    stepName="ocr_fallback",
                    succeeded=False,
                    message=message,
                )
            )
            return []

        ocrFallbackRunner = ProductOcrFallbackRunner(self._ocrEngine)
        imageResults = ocrFallbackRunner.Run(
            imageUrls=collectionResult.ocrCandidateImageUrls,
            artifactRootPath=pipelineInput.artifactRootPath,
            productPageUrl=collectionResult.productPageUrl,
            maxImageCount=pipelineInput.maxOcrImageCount,
            downloadTimeoutSeconds=pipelineInput.downloadTimeoutSeconds,
        )
        errors.extend(
            imageResult.error
            for imageResult in imageResults
            if imageResult.error is not None
        )

        skippedImageCount = (
            len(collectionResult.ocrCandidateImageUrls)
            - pipelineInput.maxOcrImageCount
        )
        if skippedImageCount > 0:
            errors.append("skipped OCR candidate images: {0}".format(skippedImageCount))

        steps.append(
            KurlyMarketProductSourcePipelineStep(
                stepName="ocr_fallback",
                succeeded=not errors,
                message="ocr_image_count={0}, error_count={1}".format(
                    len(imageResults),
                    len(errors),
                ),
            )
        )
        return imageResults
