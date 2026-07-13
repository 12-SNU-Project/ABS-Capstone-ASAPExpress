"""Run document recommendation after classification candidates exist."""

from __future__ import annotations

from bussiness_logic.document.document_component import DocumentComponent
from bussiness_logic.pipeline.pipeline_context import PipelineContext
from bussiness_logic.utils.json_types import JsonObject


class DocumentRecommendationPipeline:
    def Run(self, context: PipelineContext) -> None:
        partial = context.BuildPartialResult()
        if self._ShouldSkip(partial):
            context.Emit(
                "Document_Component",
                "skipped",
                message="분류 후보가 없어 문서 추천을 건너뜁니다.",
                partial_result=partial,
            )
            return
        context.ExecuteComponent(
            DocumentComponent(include_celex_excerpt=context.includeCelexExcerpt),
        )

    @staticmethod
    def _ShouldSkip(partial: JsonObject) -> bool:
        latestCandidateSet = partial.get("candidate_code_set")
        return (
            isinstance(latestCandidateSet, dict)
            and bool(latestCandidateSet.get("classification_status"))
            and not latestCandidateSet.get("candidates")
        )
