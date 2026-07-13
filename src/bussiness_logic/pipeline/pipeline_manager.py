"""Top-level export pipeline manager."""

from __future__ import annotations

import uuid
from pathlib import Path

from agents.blackboard import BlackboardStore
from bussiness_logic.artifact_paths import BuildSafeArtifactPathSegment
from bussiness_logic.pipeline.document_recommendation_pipeline import (
    DocumentRecommendationPipeline,
)
from bussiness_logic.pipeline.export_requirement_pipeline import (
    PIPELINE_OUTPUTS_ROOT,
    _BuildInternalRunId,
    _ResolveProductArtifactId,
)
from bussiness_logic.pipeline.hs_code_classification_pipeline import (
    HsCodeClassificationPipeline,
)
from bussiness_logic.pipeline.kurly_product_collection_pipeline import (
    KurlyProductCollectionPipeline,
)
from bussiness_logic.pipeline.pipeline_context import PipelineContext, ProgressCallback
from bussiness_logic.pipeline.pipeline_step import PipelineStep
from bussiness_logic.pipeline.user_input_preparation_pipeline import (
    UserInputPreparationPipeline,
)
from bussiness_logic.utils.json_types import JsonObject


class ExportPipelineManager:
    """Create the BlackboardStore and run the four export pipelines."""

    def __init__(self, *, pipelineOutputsRoot: Path = PIPELINE_OUTPUTS_ROOT) -> None:
        self._pipelineOutputsRoot = pipelineOutputsRoot

    def Run(
        self,
        *,
        query: str,
        facts: JsonObject,
        include_celex_excerpt: bool = False,
        progress_callback: ProgressCallback | None = None,
        job_id: str | None = None,
    ) -> dict[str, object]:
        effectiveJobId = job_id or f"job_{uuid.uuid4().hex[:10]}"
        context = PipelineContext(
            query=query,
            facts=dict(facts),
            store=self._CreateStore(
                query=query,
                facts=facts,
                effectiveJobId=effectiveJobId,
            ),
            includeCelexExcerpt=include_celex_excerpt,
            progressCallback=progress_callback,
        )
        for step in self._BuildSteps():
            step.Run(context)
            if context.shouldStop:
                break
        return context.BuildFinalResult()

    def _CreateStore(
        self,
        *,
        query: str,
        facts: JsonObject,
        effectiveJobId: str,
    ) -> BlackboardStore:
        safeJobId = BuildSafeArtifactPathSegment(effectiveJobId, fallback="")
        if safeJobId != effectiveJobId:
            raise ValueError("job_id must be a safe artifact path segment.")

        productArtifactId = _ResolveProductArtifactId(query, facts)
        runDirectory = self._pipelineOutputsRoot / productArtifactId / effectiveJobId
        return BlackboardStore.create(
            runtime_mode="webapp",
            run_id=_BuildInternalRunId(effectiveJobId),
            run_dir=runDirectory,
        )

    def _BuildSteps(self) -> list[PipelineStep]:
        pipelines = getattr(self, "_pipelines", None)
        if pipelines is not None:
            return [
                PipelineStep(type(pipeline).__name__, pipeline)
                for pipeline in pipelines
            ]
        return [
            PipelineStep("user_input_preparation", UserInputPreparationPipeline()),
            PipelineStep("kurly_product_collection", KurlyProductCollectionPipeline()),
            PipelineStep("hs_code_classification", HsCodeClassificationPipeline()),
            PipelineStep("document_recommendation", DocumentRecommendationPipeline()),
        ]
