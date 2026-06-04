"""Movable blueprint-style graph items."""

from typing import Any, List, Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
    QWidget,
)

from eu_export.ui.ontology_graph.schema import CandidateGraphNode


class BlueprintEdgeItem(QGraphicsPathItem):
    """두 graph node 사이의 blueprint-style bezier edge."""

    def __init__(
        self,
        sourceItem: "BlueprintNodeItem",
        targetItem: "BlueprintNodeItem",
    ) -> None:
        super().__init__()
        self.sourceItem = sourceItem
        self.targetItem = targetItem
        self.setZValue(-20)
        self.setPen(QPen(QColor("#6fa8ff"), 2.0))
        self.UpdatePath()

    def UpdatePath(self) -> None:
        sourceRect = self.sourceItem.boundingRect()
        targetRect = self.targetItem.boundingRect()
        sourcePoint = self.sourceItem.scenePos() + QPointF(
            sourceRect.width(),
            sourceRect.height() / 2.0,
        )
        targetPoint = self.targetItem.scenePos() + QPointF(
            0.0,
            targetRect.height() / 2.0,
        )
        distance = max(90.0, abs(targetPoint.x() - sourcePoint.x()) * 0.45)
        path = QPainterPath(sourcePoint)
        path.cubicTo(
            sourcePoint + QPointF(distance, 0.0),
            targetPoint - QPointF(distance, 0.0),
            targetPoint,
        )
        self.setPath(path)


class BlueprintNodeItem(QGraphicsItem):
    """움직일 수 있는 후보 계층 node item."""

    WIDTH = 230.0
    HEIGHT = 104.0
    LEVEL_COLORS = {
        "hs2": ("#16223a", "#5bb6ff"),
        "hs4": ("#143335", "#4fd5c8"),
        "hs6": ("#3b3215", "#ffd166"),
        "cn8": ("#241f46", "#b28dff"),
    }

    def __init__(self, graphNode: CandidateGraphNode) -> None:
        super().__init__()
        self.graphNode = graphNode
        self.edgeItems: List[BlueprintEdgeItem] = []
        self.setPos(graphNode.x, graphNode.y)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges,
            True,
        )
        self.setAcceptHoverEvents(True)

    def boundingRect(self) -> QRectF:
        return QRectF(0.0, 0.0, self.WIDTH, self.HEIGHT)

    def paint(
        self,
        painter: QPainter,
        option: Any,
        widget: Optional[QWidget] = None,
    ) -> None:
        del option, widget
        backgroundColor, accentColor = self.LEVEL_COLORS.get(
            self.graphNode.codeLevel,
            ("#202432", "#7d8aa8"),
        )
        if self.graphNode.codeLevel == "cn8" and self.graphNode.score is not None:
            if self.graphNode.score >= 10.0:
                accentColor = "#58d68d"
            elif self.graphNode.score <= 3.0:
                accentColor = "#ff8a65"

        rect = self.boundingRect()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(
            QPen(
                QColor("#ffffff" if self.isSelected() else accentColor),
                2.6 if self.isSelected() else 1.8,
            )
        )
        painter.setBrush(QBrush(QColor(backgroundColor)))
        painter.drawRoundedRect(rect, 8.0, 8.0)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(accentColor)))
        painter.drawRoundedRect(QRectF(0.0, 0.0, self.WIDTH, 30.0), 8.0, 8.0)
        painter.drawRect(QRectF(0.0, 18.0, self.WIDTH, 12.0))

        titleFont = QFont("Menlo", 11)
        titleFont.setBold(True)
        painter.setFont(titleFont)
        painter.setPen(QPen(QColor("#0c1020")))
        painter.drawText(
            QRectF(12.0, 4.0, self.WIDTH - 24.0, 24.0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self.graphNode.title.split("\n")[0],
        )

        painter.setFont(QFont("Menlo", 10))
        painter.setPen(QPen(QColor("#d9e5ff")))
        codeText = self.graphNode.title.split("\n")[-1]
        if codeText != self.graphNode.title.split("\n")[0]:
            painter.drawText(
                QRectF(12.0, 34.0, self.WIDTH - 24.0, 18.0),
                Qt.AlignmentFlag.AlignLeft,
                codeText,
            )

        description = self.BuildDescriptionPreview(self.graphNode.description)
        painter.setFont(QFont("Arial", 9))
        painter.setPen(QPen(QColor("#aeb8d4")))
        painter.drawText(
            QRectF(12.0, 54.0, self.WIDTH - 24.0, 42.0),
            Qt.TextFlag.TextWordWrap,
            description,
        )

    def itemChange(
        self,
        change: QGraphicsItem.GraphicsItemChange,
        value: Any,
    ) -> Any:
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            for edgeItem in self.edgeItems:
                edgeItem.UpdatePath()
        return super().itemChange(change, value)

    def AddEdgeItem(self, edgeItem: BlueprintEdgeItem) -> None:
        self.edgeItems.append(edgeItem)

    def BuildDescriptionPreview(self, text: str) -> str:
        if len(text) <= 92:
            return text
        return text[:89].rstrip() + "..."


class BlueprintGraphView(QGraphicsView):
    """Blueprint-like graph canvas with pan and zoom."""

    def __init__(self, scene: QGraphicsScene) -> None:
        super().__init__(scene)
        self.isPanning = False
        self.lastPanPosition = QPointF()
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse,
        )
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(QBrush(QColor("#0b0f1a")))

    def wheelEvent(self, event: Any) -> None:
        zoomFactor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        self.scale(zoomFactor, zoomFactor)

    def mousePressEvent(self, event: Any) -> None:
        if event.button() in (
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.RightButton,
        ):
            self.isPanning = True
            self.lastPanPosition = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:
        if self.isPanning:
            delta = event.position() - self.lastPanPosition
            self.lastPanPosition = event.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x()),
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y()),
            )
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:
        if event.button() in (
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.RightButton,
        ):
            self.isPanning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawBackground(painter, rect)
        gridSize = 24
        painter.setPen(QPen(QColor("#151c2e"), 1))
        left = int(rect.left()) - (int(rect.left()) % gridSize)
        top = int(rect.top()) - (int(rect.top()) % gridSize)
        x = left
        while x < rect.right():
            painter.drawLine(x, rect.top(), x, rect.bottom())
            x += gridSize
        y = top
        while y < rect.bottom():
            painter.drawLine(rect.left(), y, rect.right(), y)
            y += gridSize

