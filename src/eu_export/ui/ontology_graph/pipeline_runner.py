"""Product URL execution service for ontology graph UI."""

from eu_export.ui.ontology_graph.config import (
    DEFAULT_ONTOLOGY_ROOT_PATH,
    DEFAULT_PRODUCT_GRAPH_ARTIFACT_ROOT_PATH,
    DEFAULT_UI_KURLY_TIMEOUT_SECONDS,
    DEFAULT_UI_MAX_OCR_IMAGE_COUNT,
    DEFAULT_UI_TOP_K,
    PROJECT_ROOT_PATH,
)
from eu_export.ui.ontology_graph.graph_data import CandidateGraphLoader
from eu_export.ui.ontology_graph.schema import CandidateGraphRunResult


class CandidateGraphPipelineRunner:
    """상품 URL에서 수집/OCR/후보 산출을 실행해 GUI graph 데이터로 변환한다."""

    def RunProductUrl(
        self,
        productPageUrl: str,
        runOcrFallback: bool,
    ) -> CandidateGraphRunResult:
        from eu_export.ontology import (
            CnCandidateRetriever,
            ProductClassificationInputNormalizer,
        )
        from eu_export.product import (
            KurlyMarketProductPageCollector,
            KurlyMarketProductSourcePipeline,
            KurlyMarketProductSourcePipelineInput,
            PaddleOcrEngine,
        )

        normalizedUrl = productPageUrl.strip()
        if normalizedUrl == "":
            raise ValueError("상품 URL을 입력해야 합니다.")

        collector = KurlyMarketProductPageCollector(
            headless=True,
            timeoutMilliseconds=DEFAULT_UI_KURLY_TIMEOUT_SECONDS * 1000,
        )
        ocrEngine = PaddleOcrEngine() if runOcrFallback else None
        productSourcePipeline = KurlyMarketProductSourcePipeline(
            collector=collector,
            ocrEngine=ocrEngine,
        )
        pipelineResult = productSourcePipeline.Run(
            KurlyMarketProductSourcePipelineInput(
                productPageUrl=normalizedUrl,
                runOcrFallback=runOcrFallback,
                artifactRootPath=DEFAULT_PRODUCT_GRAPH_ARTIFACT_ROOT_PATH,
                maxOcrImageCount=DEFAULT_UI_MAX_OCR_IMAGE_COUNT,
            )
        )
        pipelineResultData = pipelineResult.ToDict()
        productInput = (
            ProductClassificationInputNormalizer().BuildFromKurlyPipelineResult(
                pipelineResult,
            )
        )
        candidates = CnCandidateRetriever(
            ontologyRootPath=DEFAULT_ONTOLOGY_ROOT_PATH,
            projectRootPath=PROJECT_ROOT_PATH,
        ).FindCandidates(productInput, topK=DEFAULT_UI_TOP_K)
        candidatesData = [candidate.ToDict() for candidate in candidates]
        graphProduct = CandidateGraphLoader().BuildProductGraph(
            {
                "product_input": productInput.ToDict(),
                "candidates": candidatesData,
            }
        )
        return CandidateGraphRunResult(
            productPageUrl=normalizedUrl,
            productInputData=productInput.ToDict(),
            pipelineResultData=pipelineResultData,
            candidatesData=candidatesData,
            graphProduct=graphProduct,
            errors=list(pipelineResultData.get("errors", [])),
        )

