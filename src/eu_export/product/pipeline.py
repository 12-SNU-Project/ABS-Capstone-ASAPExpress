"""상품 정보 수집 단계의 generic pipeline과 KurlyMarket wrapper."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Generic, List, Optional, TypeVar
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from eu_export.product.kurly_market import (
    KurlyMarketProductPageCollectionResult,
    KurlyMarketProductPageCollector,
    KurlyMarketRenderedPageEvidence,
)
from eu_export.product.paddle_ocr import ProductOcrEngine

PipelineInputT = TypeVar("PipelineInputT")
PipelineOutputT = TypeVar("PipelineOutputT")
DEFAULT_PRODUCT_OCR_IMAGE_ARTIFACT_ROOT_PATH = (
    Path("artifacts") / "product-ocr-fallback"
)
DEFAULT_PRODUCT_OCR_IMAGE_DOWNLOAD_TIMEOUT_SECONDS = 30
DEFAULT_PRODUCT_OCR_IMAGE_DOWNLOAD_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class Pipeline(ABC, Generic[PipelineInputT, PipelineOutputT]):
    """입력 하나를 받아 결과 하나를 반환하는 pipeline interface."""

    @abstractmethod
    def Run(self, pipelineInput: PipelineInputT) -> PipelineOutputT:
        raise NotImplementedError


@dataclass(frozen=True)
class ProductOcrImageResult:
    """OCR fallback 대상 이미지 하나의 처리 결과."""

    imageUrl: str
    imagePath: Optional[str] = None
    ocrText: str = ""
    error: Optional[str] = None

    def ToDict(self) -> Dict[str, object]:
        return {
            "image_url": self.imageUrl,
            "image_path": self.imagePath,
            "ocr_text": self.ocrText,
            "error": self.error,
        }


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
            combinedOcrText=self._BuildCombinedOcrText(ocrImageResults),
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

        ocrEngine = self._ocrEngine
        imageUrls = collectionResult.ocrCandidateImageUrls[
            : pipelineInput.maxOcrImageCount
        ]
        artifactDirectory = self._BuildArtifactDirectory(
            pipelineInput.artifactRootPath,
            collectionResult.productPageUrl,
        )
        artifactDirectory.mkdir(parents=True, exist_ok=True)

        imageResults: List[ProductOcrImageResult] = []
        for imageIndex, imageUrl in enumerate(imageUrls, start=1):
            imageResult = self._ExtractImageText(
                ocrEngine=ocrEngine,
                imageIndex=imageIndex,
                imageUrl=imageUrl,
                artifactDirectory=artifactDirectory,
                downloadTimeoutSeconds=pipelineInput.downloadTimeoutSeconds,
            )
            imageResults.append(imageResult)
            if imageResult.error is not None:
                errors.append(imageResult.error)

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

    def _ExtractImageText(
        self,
        ocrEngine: ProductOcrEngine,
        imageIndex: int,
        imageUrl: str,
        artifactDirectory: Path,
        downloadTimeoutSeconds: int,
    ) -> ProductOcrImageResult:
        try:
            imageBytes = self._DownloadImage(imageUrl, downloadTimeoutSeconds)
            artifactDirectory.mkdir(parents=True, exist_ok=True)
            artifactPath = artifactDirectory / self._BuildImageFileName(
                imageIndex,
                imageUrl,
            )
            artifactPath.write_bytes(imageBytes)
            ocrText = ocrEngine.ExtractTextFromImage(imageBytes)
            return ProductOcrImageResult(
                imageUrl=imageUrl,
                imagePath=str(artifactPath),
                ocrText=ocrText,
            )
        except Exception as error:
            return ProductOcrImageResult(
                imageUrl=imageUrl,
                error="OCR fallback failed for image {0}: {1}".format(
                    imageUrl,
                    error,
                ),
            )

    def _DownloadImage(
        self,
        imageUrl: str,
        downloadTimeoutSeconds: int,
    ) -> bytes:
        request = Request(
            imageUrl,
            headers={"User-Agent": DEFAULT_PRODUCT_OCR_IMAGE_DOWNLOAD_USER_AGENT},
        )
        with urlopen(request, timeout=downloadTimeoutSeconds) as response:
            return response.read()

    def _BuildArtifactDirectory(
        self,
        artifactRootPath: Path,
        productPageUrl: str,
    ) -> Path:
        return artifactRootPath / self._ExtractProductId(productPageUrl)

    def _ExtractProductId(self, productPageUrl: str) -> str:
        parsedUrl = urlparse(productPageUrl)
        pathParts = [pathPart for pathPart in parsedUrl.path.split("/") if pathPart]
        if len(pathParts) >= 2 and pathParts[0] == "goods":
            return pathParts[1]
        return "unknown"

    def _BuildImageFileName(self, imageIndex: int, imageUrl: str) -> str:
        parsedUrl = urlparse(imageUrl)
        suffix = Path(parsedUrl.path).suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
            suffix = ".img"
        return "ocr-fallback-image-{0:02d}{1}".format(imageIndex, suffix)

    def _BuildCombinedOcrText(
        self,
        imageResults: List[ProductOcrImageResult],
    ) -> str:
        return "\n".join(
            imageResult.ocrText
            for imageResult in imageResults
            if imageResult.ocrText
        )
