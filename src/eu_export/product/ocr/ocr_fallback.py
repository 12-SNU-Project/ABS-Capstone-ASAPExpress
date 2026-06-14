"""Product detail image OCR fallback runner."""

import re
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field

from eu_export.product.ocr.paddle_ocr import ProductOcrEngine


DEFAULT_PRODUCT_OCR_IMAGE_ARTIFACT_ROOT_PATH = (
    Path("artifacts") / "product-ocr-fallback"
)
DEFAULT_PRODUCT_OCR_IMAGE_DOWNLOAD_TIMEOUT_SECONDS = 30
DEFAULT_PRODUCT_OCR_IMAGE_DOWNLOAD_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class ProductOcrImageResult(BaseModel):
    """OCR fallback 대상 이미지 하나의 처리 결과."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    imageUrl: str = Field(alias="image_url")
    imagePath: Optional[str] = Field(default=None, alias="image_path")
    ocrText: str = Field(default="", alias="ocr_text")
    error: Optional[str] = None


class ProductOcrFallbackRunner:
    """상품 상세 이미지 다운로드, artifact 저장, OCR 실행을 담당한다."""

    def __init__(
        self,
        ocrEngine: ProductOcrEngine,
        downloadUserAgent: str = DEFAULT_PRODUCT_OCR_IMAGE_DOWNLOAD_USER_AGENT,
    ) -> None:
        self._ocrEngine = ocrEngine
        self._downloadUserAgent = downloadUserAgent

    def Run(
        self,
        imageUrls: List[str],
        artifactRootPath: Path,
        productPageUrl: str,
        maxImageCount: int,
        downloadTimeoutSeconds: int,
    ) -> List[ProductOcrImageResult]:
        artifactDirectory = self._BuildArtifactDirectory(
            artifactRootPath,
            productPageUrl,
        )
        artifactDirectory.mkdir(parents=True, exist_ok=True)
        for artifactPath in artifactDirectory.glob("ocr-fallback-image-*"):
            if artifactPath.is_file():
                artifactPath.unlink(missing_ok=True)

        imageResults: List[ProductOcrImageResult] = []
        batchImageCount = max(1, maxImageCount)
        for batchStartIndex in range(0, len(imageUrls), batchImageCount):
            batchImageUrls = imageUrls[
                batchStartIndex : batchStartIndex + batchImageCount
            ]
            for batchOffset, imageUrl in enumerate(batchImageUrls, start=1):
                imageResult = self._ExtractImageText(
                    imageIndex=batchStartIndex + batchOffset,
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
        try:
            imageBytes = self._DownloadImage(imageUrl, downloadTimeoutSeconds)
            artifactPath = artifactDirectory / self._BuildImageFileName(
                imageIndex,
                imageUrl,
            )
            artifactPath.write_bytes(imageBytes)
            ocrText = self._ocrEngine.ExtractTextFromImage(imageBytes)
            if not isinstance(ocrText, str) or ocrText.strip() == "":
                artifactPath.unlink(missing_ok=True)
                return None
            return ProductOcrImageResult(
                imageUrl=imageUrl,
                imagePath=str(artifactPath),
                ocrText=ocrText,
            )
        except Exception as error:
            if artifactPath is not None:
                artifactPath.unlink(missing_ok=True)
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
            headers={"User-Agent": self._downloadUserAgent},
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
        if len(pathParts) >= 2 and pathParts[0] == "products":
            return "global-{0}".format(self._BuildSafePathName(pathParts[1]))
        if (
            len(pathParts) >= 3
            and pathParts[0] == "en"
            and pathParts[1] == "products"
        ):
            return "global-{0}".format(self._BuildSafePathName(pathParts[2]))
        return "unknown"

    def _BuildImageFileName(self, imageIndex: int, imageUrl: str) -> str:
        parsedUrl = urlparse(imageUrl)
        suffix = Path(parsedUrl.path).suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
            suffix = ".img"
        return "ocr-fallback-image-{0:02d}{1}".format(imageIndex, suffix)

    def _BuildSafePathName(self, value: str) -> str:
        safeValue = re.sub(r"[^0-9A-Za-z._-]+", "-", value).strip("-")
        return safeValue or "unknown"
