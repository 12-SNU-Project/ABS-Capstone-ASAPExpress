"""상품 정보 수집 단계의 KurlyMarket wrapper."""

from typing import List, Optional

from eu_export.product.web_parser.kurly_market_collector import KurlyPageCollector
from eu_export.product.web_parser.kurly_market_schema import KurlyCollectionResult
from eu_export.product.ocr.ocr_fallback import (
    ProductOcrFallbackRunner,
    ProductOcrImageResult,
)
from eu_export.product.ocr.ocr_normalization import ProductOcrFactNormalizer
from eu_export.product.ocr.paddle_ocr import ProductOcrEngine
from eu_export.product.pipeline.pipeline_schema import (
    KurlyPipelineInput,
    KurlyPipelineResult,
    PipelineStep,
)


class KurlyProductPipeline:
    """KurlyMarket parser와 PaddleOCR fallback을 단계적으로 연결하는 wrapper."""

    def __init__(
        self,
        collector: KurlyPageCollector,
        ocrEngine: Optional[ProductOcrEngine] = None,
        ocrFactNormalizer: Optional[ProductOcrFactNormalizer] = None,
    ) -> None:
        self._collector = collector
        self._ocrEngine = ocrEngine
        self._ocrFactNormalizer = ocrFactNormalizer or ProductOcrFactNormalizer()

    def Run(
        self,
        pipelineInput: KurlyPipelineInput,
    ) -> KurlyPipelineResult:
        return self.Collect(pipelineInput)

    def Collect(
        self,
        pipelineInput: KurlyPipelineInput,
    ) -> KurlyPipelineResult:
        steps: List[PipelineStep] = []
        errors: List[str] = []

        self._collector.ValidateProductPageUrl(pipelineInput.productPageUrl)
        steps.append(
            PipelineStep(
                stepName="validate_product_page_url",
                message="supported KurlyMarket product page URL",
            )
        )

        renderedPageEvidence = self._collector.CollectRenderedPageEvidence(
            pipelineInput.productPageUrl,
        )
        steps.append(
            PipelineStep(
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
            PipelineStep(
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
                PipelineStep(
                    stepName="ocr_fallback",
                    message="skipped because runOcrFallback=False",
                )
            )

        combinedOcrText = ProductOcrFallbackRunner.BuildCombinedOcrText(
            ocrImageResults
        )
        ocrNormalizationResult = self._ocrFactNormalizer.Normalize(
            combinedOcrText,
            productDomain=collectionResult.parsedProductPage.productDomain.value,
        )
        steps.append(
            PipelineStep(
                stepName="normalize_ocr_text",
                message="raw_line_count={0}, fact_line_count={1}".format(
                    ocrNormalizationResult.rawLineCount,
                    ocrNormalizationResult.factLineCount,
                ),
            )
        )

        return KurlyPipelineResult(
            collectionResult=collectionResult,
            renderedPageEvidence=renderedPageEvidence,
            ocrImageResults=ocrImageResults,
            combinedOcrText=combinedOcrText,
            ocrNormalizationResult=ocrNormalizationResult,
            steps=steps,
            errors=errors,
        )

    def _RunOcrFallback(
        self,
        collectionResult: KurlyCollectionResult,
        pipelineInput: KurlyPipelineInput,
        steps: List[PipelineStep],
        errors: List[str],
    ) -> List[ProductOcrImageResult]:
        if not collectionResult.parsedProductPage.requiresOcrFallback:
            steps.append(
                PipelineStep(
                    stepName="ocr_fallback",
                    message="skipped because structured notice is sufficient",
                )
            )
            return []

        if self._ocrEngine is None:
            message = "OCR fallback requested but ProductOcrEngine is not configured"
            errors.append(message)
            steps.append(
                PipelineStep(
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

        batchImageCount = max(1, pipelineInput.maxOcrImageCount)
        candidateImageCount = len(collectionResult.ocrCandidateImageUrls)
        batchCount = (
            candidateImageCount + batchImageCount - 1
        ) // batchImageCount

        steps.append(
            PipelineStep(
                stepName="ocr_fallback",
                succeeded=not errors,
                message=(
                    "candidate_image_count={0}, batch_image_count={1}, "
                    "batch_count={2}, ocr_image_count={3}, error_count={4}"
                ).format(
                    candidateImageCount,
                    batchImageCount,
                    batchCount,
                    len(imageResults),
                    len(errors),
                ),
            )
        )
        return imageResults
