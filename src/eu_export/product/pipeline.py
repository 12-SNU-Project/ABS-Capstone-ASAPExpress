"""사용자 query를 검증된 SearchPlan으로 변환하는 planning pipeline."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from eu_export.bridge import RuntimeGenerationError
from eu_export.product.interpreter import LlmQueryInterpreter
from eu_export.product.plan import SearchPlan
from eu_export.product.query import QueryAnalysisResult, QueryAnalyzer
from eu_export.product.validator import SearchPlanValidator
from eu_export.utils import JsonObjectExtractionError


@dataclass(frozen=True)
class QueryPlanningResult:
    """SearchPlan 생성 pipeline의 성공/실패 결과."""

    isSuccess: bool
    rawQuery: str
    analysisResult: QueryAnalysisResult
    candidateData: Dict[str, Any] = field(default_factory=dict)
    searchPlan: Optional[SearchPlan] = None
    errors: List[str] = field(default_factory=list)


class QueryPlanningPipeline:
    """휴리스틱 분석, LLM 해석, SearchPlan 검증을 하나의 흐름으로 묶는다."""

    def __init__(
        self,
        queryAnalyzer: QueryAnalyzer,
        queryInterpreter: LlmQueryInterpreter,
        searchPlanValidator: SearchPlanValidator,
    ) -> None:
        self._queryAnalyzer = queryAnalyzer
        self._queryInterpreter = queryInterpreter
        self._searchPlanValidator = searchPlanValidator

    def Plan(self, rawQuery: str) -> QueryPlanningResult:
        analysisResult = self._queryAnalyzer.Analyze(rawQuery)

        try:
            candidateData = self._queryInterpreter.Interpret(rawQuery, analysisResult)
        except RuntimeGenerationError as error:
            return QueryPlanningResult(
                isSuccess=False,
                rawQuery=rawQuery,
                analysisResult=analysisResult,
                errors=["runtime generation failed: {0}".format(error)],
            )
        except JsonObjectExtractionError as error:
            return QueryPlanningResult(
                isSuccess=False,
                rawQuery=rawQuery,
                analysisResult=analysisResult,
                errors=["json extraction failed: {0}".format(error)],
            )

        validationResult = self._searchPlanValidator.Validate(candidateData)
        if not validationResult.isValid or validationResult.searchPlan is None:
            return QueryPlanningResult(
                isSuccess=False,
                rawQuery=rawQuery,
                analysisResult=analysisResult,
                candidateData=candidateData,
                errors=list(validationResult.errors),
            )

        return QueryPlanningResult(
            isSuccess=True,
            rawQuery=rawQuery,
            analysisResult=analysisResult,
            candidateData=candidateData,
            searchPlan=validationResult.searchPlan,
        )
