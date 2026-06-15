"""UI-facing pipeline service and run registry."""

from __future__ import annotations

import json
import hashlib
import threading
import time
import traceback
from collections.abc import Callable, Iterator, Mapping
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


PipelineCallable = Callable[..., dict[str, Any]]


class PipelineRunRequest(BaseModel):
    """Pipeline 실행 요청 DTO."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    query: str
    facts: dict[str, Any] = Field(default_factory=dict)
    includeCelexExcerpt: bool = Field(
        default=False,
        alias="include_celex_excerpt",
    )


class PipelineRunResult(BaseModel):
    """UI가 기본으로 소비하는 pipeline 결과 DTO."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    runId: str = Field(alias="run_id")
    runDir: str = Field(default="", alias="run_dir")
    auditRef: dict[str, Any] = Field(default_factory=dict, alias="audit_ref")
    candidateCodeSet: Optional[dict[str, Any]] = Field(
        default=None,
        alias="candidate_code_set",
    )
    documentPackage: Optional[dict[str, Any]] = Field(
        default=None,
        alias="document_package",
    )
    decision: Optional[dict[str, Any]] = None
    agentResults: list[dict[str, Any]] = Field(
        default_factory=list,
        alias="agent_results",
    )
    userQuestions: list[dict[str, Any]] = Field(
        default_factory=list,
        alias="user_questions",
    )

    @classmethod
    def FromPipelineOutput(
        cls,
        pipelineOutput: Mapping[str, Any],
    ) -> "PipelineRunResult":
        runId = str(pipelineOutput.get("run_id") or "")
        runDir = str(pipelineOutput.get("run_dir") or "")
        blackboard = pipelineOutput.get("blackboard") or {}
        decision = pipelineOutput.get("decision")
        documentPackage = pipelineOutput.get("document_package")
        userQuestionIds = set()
        if isinstance(decision, Mapping):
            userQuestionIds = set(decision.get("user_questions") or [])
        userQuestions = [
            dict(question)
            for question in blackboard.get("user_questions", [])
            if isinstance(question, Mapping)
            and question.get("status") == "open"
            and (
                not userQuestionIds
                or question.get("question_id") in userQuestionIds
            )
        ]
        return cls(
            run_id=runId,
            run_dir=runDir,
            audit_ref={
                "run_id": runId,
                "run_dir": runDir,
                "blackboard_available": bool(pipelineOutput.get("blackboard")),
                "agent_run_count": len(pipelineOutput.get("agent_runs") or []),
            },
            candidate_code_set=pipelineOutput.get("candidate_code_set"),
            document_package=(
                {
                    key: value
                    for key, value in documentPackage.items()
                    if key != "raw_document_package"
                }
                if isinstance(documentPackage, Mapping)
                else documentPackage
            ),
            decision=decision,
            agent_results=list(pipelineOutput.get("agent_results") or []),
            user_questions=userQuestions,
        )

    def ToUiDict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)


class RunRegistry:
    """Thread-safe run state and event buffer."""

    def __init__(self) -> None:
        self._runs: dict[str, dict[str, Any]] = {}
        self._condition = threading.Condition(threading.Lock())

    def CreateRun(
        self,
        runId: str,
        *,
        query: str,
        facts: Mapping[str, Any],
        status: str = "queued",
        events: list[dict[str, Any]] | None = None,
        reuseActive: bool = False,
    ) -> str:
        requestSignature = self._BuildRequestSignature(query, facts)
        with self._condition:
            if reuseActive:
                activeRunId = self._FindActiveRunBySignatureLocked(requestSignature)
                if activeRunId:
                    return activeRunId
            self._runs[runId] = {
                "status": status,
                "query": query,
                "request_signature": requestSignature,
                "facts": self._CompactRawInput(facts),
                "events": [],
            }
            for event in events or []:
                self._AppendEventLocked(runId, event)
            self._condition.notify_all()
            return runId

    def UpdateRun(self, runId: str, **updates: Any) -> None:
        with self._condition:
            run = self._runs.setdefault(runId, {"events": []})
            if isinstance(updates.get("facts"), Mapping):
                updates["facts"] = self._CompactRawInput(updates["facts"])
            run.update(updates)
            self._condition.notify_all()

    def FindActiveRun(
        self,
        *,
        query: str,
        facts: Mapping[str, Any],
    ) -> str | None:
        requestSignature = self._BuildRequestSignature(query, facts)
        with self._condition:
            return self._FindActiveRunBySignatureLocked(requestSignature)

    def AppendEvent(self, runId: str, event: Mapping[str, Any]) -> None:
        with self._condition:
            self._AppendEventLocked(runId, event)
            self._condition.notify_all()

    def ReadSnapshot(self, runId: str) -> dict[str, Any] | None:
        with self._condition:
            run = self._runs.get(runId)
            if run is None:
                return None
            snapshot = dict(run)
            snapshot["events"] = list(run.get("events") or [])
            partialResult = run.get("partial_result")
            if isinstance(partialResult, dict):
                snapshot["partial_result"] = dict(partialResult)
            result = run.get("result")
            if isinstance(result, dict):
                snapshot["result"] = dict(result)
            return snapshot

    def BuildUiResult(self, runId: str) -> dict[str, Any]:
        snapshot = self.ReadSnapshot(runId)
        if snapshot is None:
            return {}
        resultData = dict(snapshot.get("result") or snapshot.get("partial_result") or {})
        resultData["job_id"] = runId
        resultData["job_status"] = snapshot.get("status")
        resultData["events"] = snapshot.get("events") or []
        resultData["facts"] = snapshot.get("facts") or {}
        if snapshot.get("error"):
            resultData["error"] = snapshot.get("error")
            resultData["traceback"] = snapshot.get("traceback")
        return resultData

    def StreamEvents(
        self,
        runId: str,
        *,
        startIndex: int = 0,
        heartbeatSeconds: float = 15.0,
    ) -> Iterator[str]:
        eventIndex = max(0, startIndex)
        while True:
            with self._condition:
                self._condition.wait_for(
                    lambda: runId not in self._runs
                    or self._HasPendingEvent(runId, eventIndex)
                    or self._IsTerminal(runId),
                    timeout=heartbeatSeconds,
                )
                run = self._runs.get(runId)
                runMissing = run is None
                events = [] if runMissing else list(run.get("events") or [])
                status = "" if runMissing else str(run.get("status") or "")

            if runMissing:
                yield self._FormatSse(
                    "error",
                    {"message": "run_not_found", "run_id": runId},
                )
                return

            while eventIndex < len(events):
                yield self._FormatSse(
                    "pipeline_event",
                    events[eventIndex],
                    eventId=str(eventIndex),
                )
                eventIndex += 1

            if status in {"completed", "failed"} and eventIndex >= len(events):
                yield self._FormatSse(
                    "run_complete",
                    {"run_id": runId, "status": status},
                )
                return

            yield ": heartbeat\n\n"

    def _AppendEventLocked(self, runId: str, event: Mapping[str, Any]) -> None:
        run = self._runs.setdefault(runId, {"events": []})
        eventData = self._CompactEvent(event)
        eventData.setdefault("ts", time.strftime("%H:%M:%S"))
        run.setdefault("events", []).append(eventData)
        partialResult = eventData.get("partial_result")
        if isinstance(partialResult, dict):
            run["partial_result"] = partialResult

    def _HasPendingEvent(self, runId: str, eventIndex: int) -> bool:
        run = self._runs.get(runId)
        return bool(run is not None and len(run.get("events") or []) > eventIndex)

    def _IsTerminal(self, runId: str) -> bool:
        run = self._runs.get(runId)
        return bool(run is not None and run.get("status") in {"completed", "failed"})

    def _BuildRequestSignature(self, query: str, facts: Mapping[str, Any]) -> str:
        payload = {
            "query": query,
            "facts": dict(facts),
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _FindActiveRunBySignatureLocked(self, requestSignature: str) -> str | None:
        for runId, run in self._runs.items():
            if run.get("status") not in {"queued", "running"}:
                continue
            if run.get("request_signature") == requestSignature:
                return runId
        return None

    def _CompactEvent(self, event: Mapping[str, Any]) -> dict[str, Any]:
        eventData = dict(event)
        rawInput = eventData.get("raw_input")
        if isinstance(rawInput, Mapping):
            eventData["raw_input"] = self._CompactRawInput(rawInput)
        partialResult = eventData.get("partial_result")
        if isinstance(partialResult, Mapping):
            eventData["partial_result"] = self._CompactPipelineResult(partialResult)
        return eventData

    def _CompactRawInput(self, rawInput: Mapping[str, Any]) -> dict[str, Any]:
        compact = {
            key: value
            for key, value in rawInput.items()
            if key
            not in {
                "ocr_text",
                "ingredient_list",
                "classification_input_fact_texts",
                "classification_fact_texts",
            }
        }
        for textListKey in (
            "ocr_text",
            "ingredient_list",
            "classification_input_fact_texts",
            "classification_fact_texts",
        ):
            if textListKey not in rawInput:
                continue
            textList = rawInput.get(textListKey) or []
            if isinstance(textList, list):
                compact[f"{textListKey}_count"] = len(textList)
                compact[f"{textListKey}_char_count"] = sum(
                    len(str(item)) for item in textList
                )
                if textListKey in {
                    "classification_input_fact_texts",
                    "classification_fact_texts",
                }:
                    compact[textListKey] = [
                        str(item)[:500] for item in textList[:24]
                    ]

        composition = rawInput.get("composition")
        if isinstance(composition, list) and len(composition) > 24:
            compact["composition"] = composition[:24]
            compact["composition_count"] = len(composition)
        inputReconstruction = rawInput.get("input_reconstruction")
        if isinstance(inputReconstruction, Mapping):
            compact["input_reconstruction"] = self._CompactInputReconstruction(
                inputReconstruction,
            )
        return compact

    def _CompactPipelineResult(self, pipelineResult: Mapping[str, Any]) -> dict[str, Any]:
        blackboard = pipelineResult.get("blackboard")
        compact = {
            key: value
            for key, value in pipelineResult.items()
            if key
            not in {
                "blackboard",
                "agent_runs",
                "raw_document_package",
                "events",
                "facts",
            }
        }
        if isinstance(blackboard, Mapping):
            productEvidenceSummary = self._BuildProductEvidenceSummary(blackboard)
            if productEvidenceSummary:
                compact["product_evidence_summary"] = productEvidenceSummary
            userQuestions = self._BuildOpenUserQuestions(
                blackboard,
                compact.get("decision"),
            )
            if userQuestions:
                compact["user_questions"] = userQuestions
        documentPackage = compact.get("document_package")
        if isinstance(documentPackage, Mapping):
            compact["document_package"] = {
                key: value
                for key, value in documentPackage.items()
                if key != "raw_document_package"
            }
        return compact

    def _CompactInputReconstruction(
        self,
        inputReconstruction: Mapping[str, Any],
    ) -> dict[str, Any]:
        compact = dict(inputReconstruction)
        for textListKey in ("classification_input_fact_texts", "classification_fact_texts"):
            if textListKey not in inputReconstruction:
                continue
            textList = inputReconstruction.get(textListKey) or []
            if isinstance(textList, list):
                compact[textListKey] = [str(item)[:500] for item in textList[:24]]
                compact[f"{textListKey}_count"] = len(textList)
                compact[f"{textListKey}_char_count"] = sum(
                    len(str(item)) for item in textList
                )
        return compact

    def _BuildProductEvidenceSummary(
        self,
        blackboard: Mapping[str, Any],
    ) -> dict[str, Any]:
        productEvidenceState = blackboard.get("product_evidence_state") or {}
        if not isinstance(productEvidenceState, Mapping):
            return {}
        observedFacts = productEvidenceState.get("observed_facts") or {}
        if not isinstance(observedFacts, Mapping):
            observedFacts = {}
        ocrText = observedFacts.get("ocr_text") or []
        composition = observedFacts.get("composition") or []
        inferredFacts = productEvidenceState.get("inferred_facts") or []
        return {
            "product_id": productEvidenceState.get("product_id"),
            "product_name": observedFacts.get("product_name"),
            "ocr_text_count": len(ocrText) if isinstance(ocrText, list) else 0,
            "composition_count": len(composition) if isinstance(composition, list) else 0,
            "inferred_fact_count": (
                len(inferredFacts) if isinstance(inferredFacts, list) else 0
            ),
            "unknowns": productEvidenceState.get("unknowns") or [],
        }

    def _BuildOpenUserQuestions(
        self,
        blackboard: Mapping[str, Any],
        decision: Any,
    ) -> list[dict[str, Any]]:
        userQuestionIds = set()
        if isinstance(decision, Mapping):
            userQuestionIds = set(decision.get("user_questions") or [])
        return [
            dict(question)
            for question in blackboard.get("user_questions", [])
            if isinstance(question, Mapping)
            and question.get("status") == "open"
            and (
                not userQuestionIds
                or question.get("question_id") in userQuestionIds
            )
        ]

    def _FormatSse(
        self,
        eventName: str,
        payload: Mapping[str, Any],
        eventId: str | None = None,
    ) -> str:
        eventIdLine = "id: {0}\n".format(eventId) if eventId is not None else ""
        return "{0}event: {1}\ndata: {2}\n\n".format(
            eventIdLine,
            eventName,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        )


class PipelineRunService:
    """Pipeline execution facade for UI/API layers."""

    def __init__(
        self,
        registry: RunRegistry,
        pipelineCallable: PipelineCallable,
    ) -> None:
        self._registry = registry
        self._pipelineCallable = pipelineCallable

    def StartBackgroundRun(self, runId: str, request: PipelineRunRequest) -> None:
        thread = threading.Thread(
            target=self.Run,
            args=(runId, request),
            daemon=True,
        )
        thread.start()

    def Run(self, runId: str, request: PipelineRunRequest) -> None:
        self._registry.UpdateRun(
            runId,
            status="running",
            started_at=time.time(),
            query=request.query,
            facts=dict(request.facts),
        )
        try:
            pipelineOutput = self._pipelineCallable(
                query=request.query,
                facts=dict(request.facts),
                include_celex_excerpt=request.includeCelexExcerpt,
                progress_callback=lambda event: self._registry.AppendEvent(
                    runId,
                    event,
                ),
            )
            pipelineOutput = self._StripRuntimeObjects(pipelineOutput)
            result = PipelineRunResult.FromPipelineOutput(pipelineOutput).ToUiDict()
            self._registry.UpdateRun(
                runId,
                status="completed",
                finished_at=time.time(),
                result=result,
                partial_result=result,
            )
            self._registry.AppendEvent(
                runId,
                {
                    "stage": "Pipeline",
                    "status": "completed",
                    "message": "전체 파이프라인 완료",
                    "run_id": result.get("run_id"),
                    "partial_result": result,
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._registry.UpdateRun(
                runId,
                status="failed",
                finished_at=time.time(),
                error=str(exc),
                traceback=traceback.format_exc(),
            )
            self._registry.AppendEvent(
                runId,
                {
                    "stage": "Pipeline",
                    "status": "failed",
                    "message": str(exc),
                },
            )

    def _StripRuntimeObjects(self, pipelineOutput: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in dict(pipelineOutput).items()
            if key != "store"
        }
