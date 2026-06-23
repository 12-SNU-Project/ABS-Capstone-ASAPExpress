"""Product detail image OCR fallback runner."""

import re
from pathlib import Path
from time import perf_counter
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field

from bussiness_logic.artifact_paths import ExtractProductIdFromUrl
from bussiness_logic.product.ocr.paddle_ocr import (
    BuildOcrRegionCrop,
    ProductOcrEngine,
    ProductOcrTextRegion,
    ProductOcrTileTextResult,
    ProductStructuredOcrResult,
)


DEFAULT_PRODUCT_OCR_IMAGE_ARTIFACT_ROOT_PATH = (
    Path("artifacts") / "product-ocr-fallback"
)
DEFAULT_PRODUCT_OCR_IMAGE_DOWNLOAD_TIMEOUT_SECONDS = 30
DEFAULT_PRODUCT_OCR_IMAGE_DOWNLOAD_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
OCR_SCREENING_FOOD_DETAIL_LABELS = (
    "제품명",
    "식품유형",
    "식품의 유형",
    "원재료",
    "원료명",
    "내용량",
    "보관방법",
    "소비기한",
    "유통기한",
    "품목보고",
    "포장재질",
)
OCR_SCREENING_NUTRITION_LABELS = (
    "영양정보",
    "영양성분",
    "나트륨",
    "탄수화물",
    "당류",
    "지방",
    "트랜스지방",
    "포화지방",
    "콜레스테롤",
    "단백질",
)
OCR_SCREENING_QUANTITY_PATTERN = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:mg|g|kg|ml|l|%|kcal|㎎|㎏|㎖)",
    re.IGNORECASE,
)


class ProductOcrImageResult(BaseModel):
    """OCR fallback 대상 이미지 하나의 처리 결과."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    imageUrl: str = Field(alias="image_url")
    imagePath: Optional[str] = Field(default=None, alias="image_path")
    imagePaths: List[str] = Field(default_factory=list, alias="image_paths")
    ocrText: str = Field(default="", alias="ocr_text")
    structuredOcr: ProductStructuredOcrResult = Field(
        default_factory=ProductStructuredOcrResult,
        alias="structured_ocr",
    )
    processingTimes: Dict[str, float] = Field(
        default_factory=dict,
        alias="processing_times",
    )
    error: Optional[str] = None


class ProductOcrTextQualityEvaluator:
    """숫자/기호만 남은 OCR 결과를 artifact 보존 대상에서 제외한다."""

    def __init__(self, minimumMeaningfulCharacterCount: int = 3) -> None:
        self._minimumMeaningfulCharacterCount = max(
            1,
            minimumMeaningfulCharacterCount,
        )
        self._meaningfulCharacterPattern = re.compile(r"[A-Za-z가-힣]")

    def HasInformativeResult(
        self,
        structuredOcrResult: ProductStructuredOcrResult,
    ) -> bool:
        return any(
            self.HasInformativeText(text)
            for text in [
                structuredOcrResult.structuredText,
                structuredOcrResult.rawText,
            ]
        )

    def HasInformativeTile(
        self,
        structuredOcrResult: ProductStructuredOcrResult,
        tileIndex: Optional[int],
    ) -> bool:
        return any(
            self.HasInformativeText(text)
            for text in [
                self._BuildTileTableText(structuredOcrResult, tileIndex),
                self._BuildTileRawText(structuredOcrResult, tileIndex),
            ]
        )

    def HasInformativeText(self, text: str) -> bool:
        meaningfulCharacters = self._meaningfulCharacterPattern.findall(text or "")
        return len(meaningfulCharacters) >= self._minimumMeaningfulCharacterCount

    def _BuildTileTableText(
        self,
        structuredOcrResult: ProductStructuredOcrResult,
        tileIndex: Optional[int],
    ) -> str:
        return "\n".join(
            table.plainText
            for table in structuredOcrResult.tables
            if table.tileIndex == tileIndex
        )

    def _BuildTileRawText(
        self,
        structuredOcrResult: ProductStructuredOcrResult,
        tileIndex: Optional[int],
    ) -> str:
        return "\n".join(
            rawTileText.text
            for rawTileText in structuredOcrResult.rawTileTexts
            if rawTileText.tileIndex == tileIndex
        )


class ProductOcrImageDownloader:
    """OCR 대상 이미지 bytes를 가져오는 입력 adapter."""

    def __init__(
        self,
        downloadUserAgent: str = DEFAULT_PRODUCT_OCR_IMAGE_DOWNLOAD_USER_AGENT,
    ) -> None:
        self._downloadUserAgent = downloadUserAgent

    def Download(self, imageUrl: str, downloadTimeoutSeconds: int) -> bytes:
        request = Request(
            imageUrl,
            headers={"User-Agent": self._downloadUserAgent},
        )
        with urlopen(request, timeout=downloadTimeoutSeconds) as response:
            return response.read()


class ProductOcrArtifactStore:
    """OCR 입력 이미지 artifact 저장과 정리를 담당한다."""

    def PrepareArtifactDirectory(
        self,
        artifactRootPath: Path,
        productPageUrl: str,
    ) -> Path:
        artifactDirectory = self._BuildArtifactDirectory(
            artifactRootPath,
            productPageUrl,
        )
        artifactDirectory.mkdir(parents=True, exist_ok=True)
        for artifactPath in artifactDirectory.glob("ocr-fallback-image-*"):
            if artifactPath.is_file():
                artifactPath.unlink(missing_ok=True)
        return artifactDirectory

    def WriteImage(
        self,
        artifactDirectory: Path,
        imageIndex: int,
        imageUrl: str,
        imageBytes: bytes,
    ) -> Path:
        artifactPath = artifactDirectory / self._BuildImageFileName(
            imageIndex,
            imageUrl,
        )
        artifactPath.write_bytes(imageBytes)
        return artifactPath

    def ReplaceImageWithInformativeTiles(
        self,
        artifactPath: Path,
        imageIndex: int,
        imageUrl: str,
        imageTiles: Sequence[Tuple[Optional[int], bytes]],
        structuredOcrResult: ProductStructuredOcrResult,
        textQualityEvaluator: ProductOcrTextQualityEvaluator,
    ) -> List[Path]:
        if len(imageTiles) == 1 and imageTiles[0][0] is None:
            if textQualityEvaluator.HasInformativeResult(structuredOcrResult):
                return [artifactPath]
            return []

        retainedTilePaths: List[Path] = []
        artifactDirectory = artifactPath.parent
        for tileIndex, tileBytes in imageTiles:
            if not textQualityEvaluator.HasInformativeTile(
                structuredOcrResult,
                tileIndex,
            ):
                continue
            retainedTilePaths.append(
                self.WriteTileImage(
                    artifactDirectory=artifactDirectory,
                    imageIndex=imageIndex,
                    imageUrl=imageUrl,
                    tileIndex=tileIndex,
                    imageBytes=tileBytes,
                )
            )
        return retainedTilePaths

    def WriteTileImage(
        self,
        artifactDirectory: Path,
        imageIndex: int,
        imageUrl: str,
        tileIndex: Optional[int],
        imageBytes: bytes,
    ) -> Path:
        tilePath = artifactDirectory / self._BuildTileImageFileName(
            imageIndex,
            imageUrl,
            tileIndex,
        )
        tilePath.write_bytes(imageBytes)
        return tilePath

    def _BuildArtifactDirectory(
        self,
        artifactRootPath: Path,
        productPageUrl: str,
    ) -> Path:
        return artifactRootPath / ExtractProductIdFromUrl(productPageUrl)

    def _BuildImageFileName(self, imageIndex: int, imageUrl: str) -> str:
        parsedUrl = urlparse(imageUrl)
        suffix = Path(parsedUrl.path).suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
            suffix = ".img"
        return "ocr-fallback-image-{0:02d}{1}".format(imageIndex, suffix)

    def _BuildTileImageFileName(
        self,
        imageIndex: int,
        imageUrl: str,
        tileIndex: Optional[int],
    ) -> str:
        tileNumber = tileIndex if tileIndex is not None else 1
        return "ocr-fallback-image-{0:02d}-tile-{1:02d}.jpg".format(
            imageIndex,
            tileNumber,
        )

    def _BuildSafePathName(self, value: str) -> str:
        safeValue = re.sub(r"[^0-9A-Za-z._-]+", "-", value).strip("-")
        return safeValue or "unknown"


class ProductOcrFallbackRunner:
    """상품 상세 이미지 다운로드, artifact 저장, OCR 실행을 담당한다."""

    def __init__(
        self,
        ocrEngine: ProductOcrEngine,
        downloadUserAgent: str = DEFAULT_PRODUCT_OCR_IMAGE_DOWNLOAD_USER_AGENT,
        imageDownloader: Optional[ProductOcrImageDownloader] = None,
        artifactStore: Optional[ProductOcrArtifactStore] = None,
        textQualityEvaluator: Optional[ProductOcrTextQualityEvaluator] = None,
        screeningEngine: Optional[ProductOcrEngine] = None,
    ) -> None:
        self._ocrEngine = ocrEngine
        self._screeningEngine = screeningEngine
        self._imageDownloader = imageDownloader or ProductOcrImageDownloader(
            downloadUserAgent,
        )
        self._artifactStore = artifactStore or ProductOcrArtifactStore()
        self._textQualityEvaluator = (
            textQualityEvaluator or ProductOcrTextQualityEvaluator()
        )

    def Run(
        self,
        imageUrls: List[str],
        artifactRootPath: Path,
        productPageUrl: str,
        maxImageCount: int,
        downloadTimeoutSeconds: int,
    ) -> List[ProductOcrImageResult]:
        artifactDirectory = self._artifactStore.PrepareArtifactDirectory(
            artifactRootPath=artifactRootPath,
            productPageUrl=productPageUrl,
        )

        imageResults: List[ProductOcrImageResult] = []
        selectedImageUrls = imageUrls[: max(0, maxImageCount)]
        for imageIndex, imageUrl in enumerate(selectedImageUrls, start=1):
            imageResult = self._ExtractImageText(
                imageIndex=imageIndex,
                imageUrl=imageUrl,
                artifactDirectory=artifactDirectory,
                downloadTimeoutSeconds=downloadTimeoutSeconds,
            )
            if imageResult is not None:
                imageResults.append(imageResult)

        return imageResults

    @staticmethod
    def BuildCombinedOcrText(imageResults: List[ProductOcrImageResult]) -> str:
        return "\n".join(
            imageResult.ocrText
            for imageResult in imageResults
            if imageResult.ocrText
        )

    def _ExtractImageText(
        self,
        imageIndex: int,
        imageUrl: str,
        artifactDirectory: Path,
        downloadTimeoutSeconds: int,
    ) -> Optional[ProductOcrImageResult]:
        artifactPath: Optional[Path] = None
        processingTimes: Dict[str, float] = {}
        try:
            startedAt = perf_counter()
            imageBytes = self._imageDownloader.Download(
                imageUrl,
                downloadTimeoutSeconds,
            )
            processingTimes["download"] = perf_counter() - startedAt
            artifactPath = self._artifactStore.WriteImage(
                artifactDirectory=artifactDirectory,
                imageIndex=imageIndex,
                imageUrl=imageUrl,
                imageBytes=imageBytes,
            )
            screeningResult: Optional[ProductStructuredOcrResult] = None
            screeningRegions: List[ProductOcrTextRegion] = []
            if self._screeningEngine is not None:
                try:
                    startedAt = perf_counter()
                    screeningResult, screeningRegions = (
                        self._screeningEngine.ExtractStructuredTextWithRegionsFromImage(
                            imageBytes,
                        )
                    )
                    processingTimes["raw_ocr"] = perf_counter() - startedAt
                except Exception:
                    screeningResult = None

            shouldRunStructuredOcr, screeningSummary = (
                self._EvaluateStructuredOcrCandidate(
                    screeningResult.text if screeningResult is not None else "",
                )
            )
            if screeningResult is not None and not shouldRunStructuredOcr:
                structuredOcrResult = screeningResult.model_copy(
                    update={
                        "fallbackReason": None,
                        "textMergeMode": "screened_raw_only",
                        "warnings": [
                            *screeningResult.warnings,
                            "structured_ocr_skipped_by_screening {0}".format(
                                screeningSummary,
                            ),
                        ],
                    }
                )
            else:
                structuredInputBytes = imageBytes
                roiBounds: Optional[Tuple[int, int, int, int]] = None
                if screeningRegions:
                    startedAt = perf_counter()
                    regionCrop = BuildOcrRegionCrop(
                        imageBytes,
                        screeningRegions,
                        OCR_SCREENING_NUTRITION_LABELS,
                    )
                    processingTimes["roi_build"] = perf_counter() - startedAt
                    if regionCrop is not None:
                        structuredInputBytes, roiBounds = regionCrop
                startedAt = perf_counter()
                structuredOcrResult = (
                    self._ocrEngine.ExtractStructuredTextFromImage(
                        structuredInputBytes,
                    )
                )
                processingTimes["structured_ocr"] = perf_counter() - startedAt
                if screeningResult is not None:
                    structuredOcrResult = self._MergeStructuredAndScreeningOcr(
                        structuredOcrResult,
                        screeningResult,
                        screeningSummary=screeningSummary,
                        roiBounds=roiBounds,
                    )
            ocrText = structuredOcrResult.text
            if (
                not isinstance(ocrText, str)
                or not self._textQualityEvaluator.HasInformativeResult(
                    structuredOcrResult,
                )
            ):
                return None
            imageTiles = (
                [(None, imageBytes)]
                if screeningResult is not None
                else self._ocrEngine.BuildArtifactImageTiles(imageBytes)
            )
            artifactPaths = self._artifactStore.ReplaceImageWithInformativeTiles(
                artifactPath=artifactPath,
                imageIndex=imageIndex,
                imageUrl=imageUrl,
                imageTiles=imageTiles,
                structuredOcrResult=structuredOcrResult,
                textQualityEvaluator=self._textQualityEvaluator,
            )
            if not artifactPaths:
                return None
            return ProductOcrImageResult(
                imageUrl=imageUrl,
                imagePath=str(artifactPaths[0]),
                imagePaths=[str(path) for path in artifactPaths],
                ocrText=ocrText,
                structuredOcr=structuredOcrResult,
                processingTimes={
                    key: round(value, 3)
                    for key, value in processingTimes.items()
                },
            )
        except Exception as error:
            return ProductOcrImageResult(
                imageUrl=imageUrl,
                processingTimes={
                    key: round(value, 3)
                    for key, value in processingTimes.items()
                },
                error="OCR fallback failed for image {0}: {1}".format(
                    imageUrl,
                    error,
                ),
            )

    def _MergeStructuredAndScreeningOcr(
        self,
        structuredResult: ProductStructuredOcrResult,
        screeningResult: ProductStructuredOcrResult,
        *,
        screeningSummary: str,
        roiBounds: Optional[Tuple[int, int, int, int]],
    ) -> ProductStructuredOcrResult:
        rawText = screeningResult.rawText or screeningResult.text
        rawTileTexts = (
            screeningResult.rawTileTexts
            or [ProductOcrTileTextResult(text=rawText)]
            if rawText
            else []
        )
        roiWarning = (
            "structured_ocr_roi_applied bounds={0},{1},{2},{3}".format(
                *roiBounds,
            )
            if roiBounds is not None
            else "structured_ocr_roi_unavailable"
        )
        warnings = list(
            dict.fromkeys(
                [
                    *screeningResult.warnings,
                    *structuredResult.warnings,
                    "structured_ocr_screening {0}".format(screeningSummary),
                    roiWarning,
                ]
            )
        )
        if not structuredResult.usedStructuredTables:
            return screeningResult.model_copy(
                update={
                    "fallbackReason": structuredResult.fallbackReason,
                    "textMergeMode": "screened_raw_only",
                    "warnings": warnings,
                }
            )

        mergedText = structuredResult.structuredText
        if rawText:
            mergedText = "[structured_tables]\n{0}\n\n[raw_ocr_tiles]\n{1}".format(
                structuredResult.structuredText,
                rawText,
            )
        return structuredResult.model_copy(
            update={
                "text": mergedText,
                "rawText": rawText,
                "rawTileTexts": rawTileTexts,
                "textMergeMode": "structured_plus_screening_raw",
                "warnings": warnings,
            }
        )

    def _EvaluateStructuredOcrCandidate(
        self,
        text: str,
    ) -> Tuple[bool, str]:
        normalizedText = re.sub(r"\s+", "", (text or "").lower())
        meaningfulCharacterCount = len(re.findall(r"[A-Za-z가-힣]", normalizedText))
        nutritionMatchCount = sum(
            label.replace(" ", "") in normalizedText
            for label in OCR_SCREENING_NUTRITION_LABELS
        )
        foodDetailMatchCount = sum(
            label.replace(" ", "") in normalizedText
            for label in OCR_SCREENING_FOOD_DETAIL_LABELS
        )
        quantityMatchCount = len(
            OCR_SCREENING_QUANTITY_PATTERN.findall(text or "")
        )
        isCandidate = meaningfulCharacterCount >= 40 and (
            (
                nutritionMatchCount >= 3
                and quantityMatchCount >= 3
            )
            or (
                nutritionMatchCount >= 2
                and foodDetailMatchCount >= 3
                and quantityMatchCount >= 4
            )
        )
        return isCandidate, (
            "nutrition_labels={0} food_detail_labels={1} "
            "quantities={2} meaningful_characters={3}"
        ).format(
            nutritionMatchCount,
            foodDetailMatchCount,
            quantityMatchCount,
            meaningfulCharacterCount,
        )
