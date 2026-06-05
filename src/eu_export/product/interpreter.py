"""LLM에 사용자 query를 SearchPlan JSON 후보로 해석하도록 요청한다."""

import json
from typing import Any, Dict

from eu_export.bridge import (
    LlmGenerationOptions,
    LlmRequest,
    LlmResponseFormat,
    RuntimeAdapter,
)
from eu_export.product.prompt import BuildSearchPlanSystemPrompt
from eu_export.product.query import QueryAnalysisResult
from eu_export.utils import ExtractJsonObject


class LlmQueryInterpreter:
    """휴리스틱 분석 결과를 참고자료로 전달해 SearchPlan JSON 후보를 만든다."""

    def __init__(self, runtimeAdapter: RuntimeAdapter[Any]) -> None:
        self._runtimeAdapter = runtimeAdapter

    def Interpret(
        self,
        rawQuery: str,
        analysisResult: QueryAnalysisResult,
    ) -> Dict[str, Any]:
        request = LlmRequest(
            systemPrompt=self.BuildSystemPrompt(),
            userPrompt=self.BuildUserPrompt(rawQuery, analysisResult),
            responseFormat=LlmResponseFormat.JSON_OBJECT,
            generationOptions=LlmGenerationOptions(
                temperature=0.0,
                maxTokens=800,
            ),
        )

        response = self._runtimeAdapter.Generate(request)
        return ExtractJsonObject(response.generatedText)

    def BuildSystemPrompt(self) -> str:
        return BuildSearchPlanSystemPrompt()

    def BuildUserPrompt(
        self,
        rawQuery: str,
        analysisResult: QueryAnalysisResult,
    ) -> str:
        heuristicData = {
            "original_query": analysisResult.originalQuery,
            "normalized_query": analysisResult.normalizedQuery,
            "query_type": analysisResult.queryType.value,
            "product_domain_hint": analysisResult.productDomainHint.value,
            "confidence": analysisResult.confidence,
            "reason": analysisResult.reason,
            "extracted_terms": analysisResult.extractedTerms,
            "limitations": analysisResult.limitations,
        }
        return "\n".join(
            [
                "User query:",
                rawQuery,
                "",
                "Heuristic analysis for reference only:",
                json.dumps(heuristicData, ensure_ascii=False, indent=2),
                "",
                "Create one SearchPlan JSON object.",
            ]
        )
