"""Product detail image OCR fallback runner."""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from eu_export.product.paddle_ocr import ProductOcrEngine


DEFAULT_PRODUCT_OCR_IMAGE_ARTIFACT_ROOT_PATH = (
    Path("artifacts") / "product-ocr-fallback"
)
DEFAULT_PRODUCT_OCR_IMAGE_DOWNLOAD_TIMEOUT_SECONDS = 30
DEFAULT_PRODUCT_OCR_IMAGE_DOWNLOAD_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


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

        imageResults: List[ProductOcrImageResult] = []
        for imageIndex, imageUrl in enumerate(
            imageUrls[:maxImageCount],
            start=1,
        ):
            imageResults.append(
                self._ExtractImageText(
                    imageIndex=imageIndex,
                    imageUrl=imageUrl,
                    artifactDirectory=artifactDirectory,
                    downloadTimeoutSeconds=downloadTimeoutSeconds,
                )
            )
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
    ) -> ProductOcrImageResult:
        try:
            imageBytes = self._DownloadImage(imageUrl, downloadTimeoutSeconds)
            artifactPath = artifactDirectory / self._BuildImageFileName(
                imageIndex,
                imageUrl,
            )
            artifactPath.write_bytes(imageBytes)
            ocrText = self._ocrEngine.ExtractTextFromImage(imageBytes)
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
        return "unknown"

    def _BuildImageFileName(self, imageIndex: int, imageUrl: str) -> str:
        parsedUrl = urlparse(imageUrl)
        suffix = Path(parsedUrl.path).suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
            suffix = ".img"
        return "ocr-fallback-image-{0:02d}{1}".format(imageIndex, suffix)
