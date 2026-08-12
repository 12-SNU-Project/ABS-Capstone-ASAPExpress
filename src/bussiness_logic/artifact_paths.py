"""상품 및 파이프라인 artifact 경로 식별자 처리."""

from __future__ import annotations

import re
from urllib.parse import urlparse


def BuildSafeArtifactPathSegment(value: str, *, fallback: str = "unknown") -> str:
    """외부 식별자를 단일 디렉터리명으로 정규화한다."""
    safeValue = re.sub(r"[^0-9A-Za-z._-]+", "-", value).strip("-.")
    return safeValue or fallback


def ExtractProductIdFromUrl(productPageUrl: str | None) -> str:
    """지원 상품 URL에서 artifact 경로용 상품 ID를 추출한다."""
    if not productPageUrl:
        return "unknown"

    parsedUrl = urlparse(productPageUrl)
    pathParts = [part for part in parsedUrl.path.split("/") if part]
    if len(pathParts) >= 2 and pathParts[0] == "goods":
        return BuildSafeArtifactPathSegment(pathParts[1])
    if len(pathParts) >= 2 and pathParts[0] == "products":
        return "global-{0}".format(BuildSafeArtifactPathSegment(pathParts[1]))
    if (
        len(pathParts) >= 3
        and pathParts[0] == "en"
        and pathParts[1] == "products"
    ):
        return "global-{0}".format(BuildSafeArtifactPathSegment(pathParts[2]))
    return BuildSafeArtifactPathSegment(parsedUrl.path.strip("/"))
