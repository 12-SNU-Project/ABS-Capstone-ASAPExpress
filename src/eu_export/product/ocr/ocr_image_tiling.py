"""OCR 입력 이미지의 고해상도 타일 분할 helper."""

from typing import Any, List, Optional


class ProductOcrImageTilePlanner:
    """긴 상품 상세 이미지를 표 경계 손실이 적은 타일로 나눈다."""

    def __init__(
        self,
        useImageTiling: bool = True,
        useProjectionTiling: bool = True,
        maxTileHeightPixels: int = 2400,
        tileOverlapPixels: int = 240,
    ) -> None:
        self._useImageTiling = useImageTiling
        self._useProjectionTiling = useProjectionTiling
        self._maxTileHeightPixels = max(512, maxTileHeightPixels)
        self._tileOverlapPixels = max(0, tileOverlapPixels)

    def BuildTiles(self, image: Any) -> List[tuple[Optional[int], Any]]:
        if not self._useImageTiling:
            return [(None, image)]

        imageHeight = int(getattr(image, "shape", [0])[0] or 0)
        if imageHeight <= self._maxTileHeightPixels:
            return [(None, image)]

        if self._useProjectionTiling:
            projectionTiles = self._BuildProjectionBasedTiles(image, imageHeight)
            if projectionTiles:
                return projectionTiles

        return self._BuildFixedOverlapTiles(image, imageHeight)

    def _BuildFixedOverlapTiles(
        self,
        image: Any,
        imageHeight: int,
    ) -> List[tuple[Optional[int], Any]]:
        stride = self._maxTileHeightPixels - self._tileOverlapPixels
        if stride <= 0:
            return [(None, image)]

        tiles: List[tuple[Optional[int], Any]] = []
        startY = 0
        tileIndex = 1
        while startY < imageHeight:
            endY = min(startY + self._maxTileHeightPixels, imageHeight)
            tiles.append((tileIndex, image[startY:endY, :]))
            if endY >= imageHeight:
                break
            startY = max(0, endY - self._tileOverlapPixels)
            tileIndex += 1
        return tiles

    def _BuildProjectionBasedTiles(
        self,
        image: Any,
        imageHeight: int,
    ) -> List[tuple[Optional[int], Any]]:
        whitespaceBands = self._FindHorizontalWhitespaceBands(image)
        if not whitespaceBands:
            return []

        cutPoints = self._BuildProjectionCutPoints(whitespaceBands, imageHeight)
        if not cutPoints:
            return []

        tiles: List[tuple[Optional[int], Any]] = []
        previousCutPoint = 0
        for tileIndex, cutPoint in enumerate([*cutPoints, imageHeight], start=1):
            tileStart = max(
                0,
                previousCutPoint - (self._tileOverlapPixels if previousCutPoint else 0),
            )
            tileEnd = min(
                imageHeight,
                cutPoint
                + (self._tileOverlapPixels if cutPoint < imageHeight else 0),
            )
            if tileEnd > tileStart:
                tiles.append((tileIndex, image[tileStart:tileEnd, :]))
            previousCutPoint = cutPoint
        return tiles

    def _FindHorizontalWhitespaceBands(self, image: Any) -> List[tuple[int, int]]:
        try:
            import cv2
            import numpy as np
        except ImportError:
            return []

        grayImage = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _, binaryImage = cv2.threshold(
            grayImage,
            0,
            255,
            cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
        )
        rowDensity = np.mean(binaryImage > 0, axis=1)
        whitespaceThreshold = 0.003
        minimumBandHeight = 24
        whitespaceBands: List[tuple[int, int]] = []
        bandStart: Optional[int] = None
        for rowIndex, density in enumerate(rowDensity):
            if float(density) <= whitespaceThreshold:
                if bandStart is None:
                    bandStart = rowIndex
                continue
            if bandStart is not None and rowIndex - bandStart >= minimumBandHeight:
                whitespaceBands.append((bandStart, rowIndex))
            bandStart = None

        if bandStart is not None and len(rowDensity) - bandStart >= minimumBandHeight:
            whitespaceBands.append((bandStart, len(rowDensity)))
        return whitespaceBands

    def _BuildProjectionCutPoints(
        self,
        whitespaceBands: List[tuple[int, int]],
        imageHeight: int,
    ) -> List[int]:
        cutPoints: List[int] = []
        currentStart = 0
        minimumTileHeight = max(512, self._maxTileHeightPixels // 3)
        searchWindow = max(240, self._tileOverlapPixels * 2)
        while currentStart + self._maxTileHeightPixels < imageHeight:
            targetCut = currentStart + self._maxTileHeightPixels
            candidateCut = self._FindNearestWhitespaceCutPoint(
                whitespaceBands,
                targetCut=targetCut,
                minimumCut=currentStart + minimumTileHeight,
                maximumCut=min(imageHeight - 1, targetCut + searchWindow),
                searchWindow=searchWindow,
            )
            if candidateCut is None or candidateCut <= currentStart:
                return []
            cutPoints.append(candidateCut)
            currentStart = candidateCut
        return cutPoints

    def _FindNearestWhitespaceCutPoint(
        self,
        whitespaceBands: List[tuple[int, int]],
        targetCut: int,
        minimumCut: int,
        maximumCut: int,
        searchWindow: int,
    ) -> Optional[int]:
        candidateCenters = [
            (bandStart + bandEnd) // 2
            for bandStart, bandEnd in whitespaceBands
            if minimumCut <= (bandStart + bandEnd) // 2 <= maximumCut
            and abs(((bandStart + bandEnd) // 2) - targetCut) <= searchWindow
        ]
        if not candidateCenters:
            return None
        return min(candidateCenters, key=lambda center: abs(center - targetCut))
