"""Main PySide6 window for ontology candidate graph UI."""

import json
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGraphicsScene,
    QHBoxLayout,
    QCheckBox,
    QLabel,
    QListWidget,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from eu_export.ui.ontology_graph.detail_text import CandidateGraphDetailTextBuilder
from eu_export.ui.ontology_graph.graph_data import CandidateGraphLoader
from eu_export.ui.ontology_graph.graph_items import (
    BlueprintEdgeItem,
    BlueprintGraphView,
    BlueprintNodeItem,
)
from eu_export.ui.ontology_graph.run_worker import CandidateGraphRunWorker
from eu_export.ui.ontology_graph.schema import (
    CandidateGraphProduct,
    CandidateGraphRunResult,
)


class CandidateGraphWindow(QMainWindow):
    """후보 계층 그래프 main window."""

    def __init__(self, summaryPath: Path) -> None:
        super().__init__()
        self.summaryPath = summaryPath
        self.products: List[CandidateGraphProduct] = []
        self.runResults: List[Optional[CandidateGraphRunResult]] = []
        self.nodeItemsById: Dict[str, BlueprintNodeItem] = {}
        self.currentWorker: Optional[CandidateGraphRunWorker] = None
        self.detailTextBuilder = CandidateGraphDetailTextBuilder()
        self.scene = QGraphicsScene(self)
        self.graphView = BlueprintGraphView(self.scene)
        self.productList = QListWidget()
        self.detailPanel = QTextEdit()
        self.summaryPathLabel = QLabel()
        self.urlEdit = QLineEdit()
        self.runButton = QPushButton("시작")
        self.ocrCheckBox = QCheckBox("OCR fallback 실행")
        self.runStatusLabel = QLabel()
        self.BuildWindow()
        self.LoadSummary(summaryPath)

    def BuildWindow(self) -> None:
        self.setWindowTitle("ASAP Export Candidate Graph")
        self.resize(1440, 860)
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #0d111c; color: #dbe7ff; }
            QLabel { color: #b9c7e6; }
            QListWidget {
                background: #111827; border: 1px solid #26324a;
                color: #dbe7ff; padding: 6px;
            }
            QListWidget::item { padding: 8px; }
            QListWidget::item:selected { background: #27456d; }
            QPushButton {
                background: #1f6feb; border: 0; color: white;
                padding: 8px 10px; border-radius: 4px;
            }
            QPushButton:hover { background: #2f81f7; }
            QTextEdit {
                background: #0b1220; border: 1px solid #26324a;
                color: #dbe7ff; font-family: Menlo; font-size: 12px;
            }
            """
        )
        openAction = QAction("Open Summary", self)
        openAction.triggered.connect(self.OpenSummaryFile)
        self.menuBar().addAction(openAction)

        centralWidget = QWidget()
        mainLayout = QHBoxLayout(centralWidget)
        mainLayout.setContentsMargins(12, 12, 12, 12)
        mainLayout.setSpacing(12)

        mainLayout.addWidget(self.BuildLeftPanel())
        mainLayout.addWidget(self.graphView, stretch=1)
        mainLayout.addWidget(self.BuildRightPanel())
        self.setCentralWidget(centralWidget)
        self.scene.selectionChanged.connect(self.UpdateSelectedNodeDetail)

    def BuildLeftPanel(self) -> QWidget:
        panel = QFrame()
        panel.setFixedWidth(330)
        layout = QVBoxLayout(panel)
        title = QLabel("상품 링크 실행")
        title.setFont(QFont("Arial", 15, QFont.Weight.Bold))
        self.urlEdit.setPlaceholderText("https://www.kurly.com/goods/...")
        self.ocrCheckBox.setChecked(True)
        self.runStatusLabel.setWordWrap(True)
        self.runButton.clicked.connect(self.RunProductUrl)
        self.summaryPathLabel.setWordWrap(True)
        self.summaryPathLabel.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse,
        )
        openButton = QPushButton("Summary JSON 열기")
        openButton.clicked.connect(self.OpenSummaryFile)
        fitButton = QPushButton("그래프 맞춤")
        fitButton.clicked.connect(self.FitGraph)

        layout.addWidget(title)
        layout.addWidget(self.urlEdit)
        layout.addWidget(self.ocrCheckBox)
        layout.addWidget(self.runButton)
        layout.addWidget(self.runStatusLabel)
        layout.addSpacing(12)
        layout.addWidget(QLabel("기존 summary artifact"))
        layout.addWidget(self.summaryPathLabel)
        layout.addWidget(openButton)
        layout.addWidget(fitButton)
        layout.addSpacing(12)
        layout.addWidget(QLabel("후보 산출 결과"))
        layout.addWidget(self.productList, stretch=1)
        self.productList.currentRowChanged.connect(self.RenderProductGraph)
        return panel

    def BuildRightPanel(self) -> QWidget:
        panel = QFrame()
        panel.setFixedWidth(380)
        layout = QVBoxLayout(panel)
        title = QLabel("선택 노드 상세")
        title.setFont(QFont("Arial", 15, QFont.Weight.Bold))
        self.detailPanel.setReadOnly(True)
        self.detailPanel.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        layout.addWidget(title)
        layout.addWidget(self.detailPanel, stretch=1)
        return panel

    def LoadSummary(self, summaryPath: Path) -> None:
        self.productList.clear()
        self.scene.clear()
        self.nodeItemsById = {}
        try:
            self.products = CandidateGraphLoader().Load(summaryPath)
        except FileNotFoundError:
            self.products = []
            self.runResults = []
            self.summaryPathLabel.setText(
                "summary 없음: {0}\nURL을 입력하고 시작을 누르세요.".format(
                    summaryPath,
                )
            )
            self.detailPanel.setPlainText("상품 URL 실행 결과를 기다리는 중입니다.")
            return
        except json.JSONDecodeError as error:
            self.products = []
            self.runResults = []
            self.summaryPathLabel.setText("JSON 파싱 실패: {0}".format(summaryPath))
            self.detailPanel.setPlainText(str(error))
            return

        self.summaryPath = summaryPath
        self.runResults = [None for _ in self.products]
        self.summaryPathLabel.setText("입력: {0}".format(summaryPath))
        for product in self.products:
            self.productList.addItem(
                "{0}\n{1} candidates".format(
                    product.productName,
                    len(product.candidateCodes),
                )
            )
        if self.products:
            self.productList.setCurrentRow(0)
        else:
            self.scene.clear()
            self.detailPanel.setPlainText("표시할 후보 상품이 없습니다.")

    def RunProductUrl(self) -> None:
        productPageUrl = self.urlEdit.text().strip()
        if productPageUrl == "":
            self.runStatusLabel.setText("상품 URL을 입력하세요.")
            return

        self.runButton.setEnabled(False)
        self.runStatusLabel.setText("실행 중: 상품 수집/OCR/후보 산출을 진행합니다.")
        self.currentWorker = CandidateGraphRunWorker(
            productPageUrl,
            self.ocrCheckBox.isChecked(),
        )
        self.currentWorker.Completed.connect(self.HandleRunCompleted)
        self.currentWorker.Failed.connect(self.HandleRunFailed)
        self.currentWorker.finished.connect(self.HandleRunFinished)
        self.currentWorker.start()

    def HandleRunCompleted(self, result: CandidateGraphRunResult) -> None:
        self.products = [result.graphProduct]
        self.runResults = [result]
        self.productList.clear()
        self.productList.addItem(
            "{0}\n{1} candidates".format(
                result.graphProduct.productName,
                len(result.graphProduct.candidateCodes),
            )
        )
        self.productList.setCurrentRow(0)
        self.runStatusLabel.setText(
            "완료: 후보 {0}개를 산출했습니다.".format(
                len(result.graphProduct.candidateCodes),
            )
        )

    def HandleRunFailed(self, message: str) -> None:
        self.runStatusLabel.setText("실패: {0}".format(message))
        self.detailPanel.setPlainText(
            "상품 링크 실행 중 오류가 발생했습니다.\n\n{0}".format(message),
        )

    def HandleRunFinished(self) -> None:
        self.runButton.setEnabled(True)
        self.currentWorker = None

    def OpenSummaryFile(self) -> None:
        filePath, _ = QFileDialog.getOpenFileName(
            self,
            "Open ontology smoke summary",
            str(self.summaryPath.parent),
            "JSON Files (*.json);;All Files (*)",
        )
        if filePath:
            self.LoadSummary(Path(filePath))

    def RenderProductGraph(self, productIndex: int) -> None:
        self.scene.clear()
        self.nodeItemsById = {}
        if productIndex < 0 or productIndex >= len(self.products):
            return
        product = self.products[productIndex]

        for graphNode in product.nodes:
            nodeItem = BlueprintNodeItem(graphNode)
            self.scene.addItem(nodeItem)
            self.nodeItemsById[graphNode.nodeId] = nodeItem

        for graphEdge in product.edges:
            sourceItem = self.nodeItemsById.get(graphEdge.sourceNodeId)
            targetItem = self.nodeItemsById.get(graphEdge.targetNodeId)
            if sourceItem is None or targetItem is None:
                continue
            edgeItem = BlueprintEdgeItem(sourceItem, targetItem)
            sourceItem.AddEdgeItem(edgeItem)
            targetItem.AddEdgeItem(edgeItem)
            self.scene.addItem(edgeItem)

        self.scene.setSceneRect(
            self.scene.itemsBoundingRect().adjusted(-120, -120, 120, 120),
        )
        self.detailPanel.setPlainText(
            self.detailTextBuilder.BuildProductOverviewText(
                product,
                self.ReadRunResult(productIndex),
            ),
        )
        self.FitGraph()

    def FitGraph(self) -> None:
        rect = self.scene.itemsBoundingRect()
        if rect.isNull():
            return
        self.graphView.fitInView(
            rect.adjusted(-80, -80, 80, 80),
            Qt.AspectRatioMode.KeepAspectRatio,
        )

    def UpdateSelectedNodeDetail(self) -> None:
        selectedItems = self.scene.selectedItems()
        nodeItems = [
            item
            for item in selectedItems
            if isinstance(item, BlueprintNodeItem)
        ]
        if not nodeItems:
            productIndex = self.productList.currentRow()
            if 0 <= productIndex < len(self.products):
                self.detailPanel.setPlainText(
                    self.detailTextBuilder.BuildProductOverviewText(
                        self.products[productIndex],
                        self.ReadRunResult(productIndex),
                    ),
                )
            return
        self.detailPanel.setPlainText(
            self.detailTextBuilder.BuildNodeDetailText(nodeItems[0].graphNode),
        )

    def ReadRunResult(
        self,
        productIndex: int,
    ) -> Optional[CandidateGraphRunResult]:
        if productIndex < 0 or productIndex >= len(self.runResults):
            return None
        return self.runResults[productIndex]

