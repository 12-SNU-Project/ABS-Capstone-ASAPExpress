"""Shared state for export pipeline execution."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from agents.blackboard import BlackboardStore
from bussiness_logic.pipeline.component_base import BasePipelineComponent, ComponentResult
from bussiness_logic.utils.json_types import JsonObject

ProgressCallback = Callable[[JsonObject], None]


def _ReadComponentRuns(store: BlackboardStore) -> list[JsonObject]:
    if not store.component_runs_path.exists():
        return []
    out: list[JsonObject] = []
    with store.component_runs_path.open(encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                out.append({"raw": line, "parse_error": "invalid_jsonl"})
    return out


@dataclass
class PipelineContext:
    query: str
    facts: JsonObject
    store: BlackboardStore
    includeCelexExcerpt: bool = False
    progressCallback: ProgressCallback | None = None
    rawInput: JsonObject = field(default_factory=dict)
    componentResults: list[JsonObject] = field(default_factory=list)
    shouldStop: bool = False

    def Emit(self, stage: str, status: str, **payload: object) -> None:
        if self.progressCallback is None:
            return
        try:
            self.progressCallback({
                "stage": stage,
                "status": status,
                "run_id": self.store.run_id,
                **payload,
            })
        except Exception:
            pass

    def ExecuteComponent(self, component: BasePipelineComponent) -> ComponentResult:
        self.Emit(component.component_name, "running", message=f"{component.stage} 실행 중")
        result = component.Execute(self.store)
        componentResult: JsonObject = {
            "component_name": component.component_name,
            "success": result.success,
            "error": result.error,
            "outputs_written": result.outputs_written,
        }
        self.componentResults.append(componentResult)
        self.Emit(
            component.component_name,
            "completed" if result.success else "failed",
            message=(
                f"{component.component_name} 완료"
                if result.success
                else f"{component.component_name} 실패"
            ),
            component_result=componentResult,
            partial_result=self.BuildPartialResult(),
        )
        if not result.success:
            self.shouldStop = True
        return result

    def BuildPartialResult(self) -> JsonObject:
        blackboardSnapshot = self.store.load()
        return {
            "blackboard": blackboardSnapshot,
            "candidate_code_set": (
                blackboardSnapshot.get("candidate_code_sets") or [None]
            )[-1],
            "document_package": (
                blackboardSnapshot.get("document_packages") or [None]
            )[-1],
            "component_results": list(self.componentResults),
            "component_runs": _ReadComponentRuns(self.store),
            "run_id": self.store.run_id,
            "run_dir": str(Path(self.store.run_dir)),
        }

    def BuildFinalResult(self) -> dict[str, object]:
        blackboard = self.store.load()
        documentPackage = (blackboard.get("document_packages") or [None])[-1]
        candidateCodeSet = (blackboard.get("candidate_code_sets") or [None])[-1]
        rawDocumentPackage = (
            documentPackage.get("raw_document_package")
            if isinstance(documentPackage, dict)
            else None
        )
        return {
            "store": self.store,
            "blackboard": blackboard,
            "raw_document_package": rawDocumentPackage,
            "document_package": documentPackage,
            "candidate_code_set": candidateCodeSet,
            "component_results": list(self.componentResults),
            "component_runs": _ReadComponentRuns(self.store),
            "run_id": self.store.run_id,
            "run_dir": str(Path(self.store.run_dir)),
        }
