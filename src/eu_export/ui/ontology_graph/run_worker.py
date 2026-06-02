"""Qt worker for URL-based candidate graph execution."""

from PySide6.QtCore import QThread, Signal

from eu_export.ui.ontology_graph.pipeline_runner import CandidateGraphPipelineRunner


class CandidateGraphRunWorker(QThread):
    """URL 실행 pipeline을 GUI thread 밖에서 수행한다."""

    Completed = Signal(object)
    Failed = Signal(str)

    def __init__(self, productPageUrl: str, runOcrFallback: bool) -> None:
        super().__init__()
        self.productPageUrl = productPageUrl
        self.runOcrFallback = runOcrFallback

    def run(self) -> None:
        try:
            result = CandidateGraphPipelineRunner().RunProductUrl(
                self.productPageUrl,
                self.runOcrFallback,
            )
        except Exception as error:
            self.Failed.emit(str(error))
            return
        self.Completed.emit(result)

