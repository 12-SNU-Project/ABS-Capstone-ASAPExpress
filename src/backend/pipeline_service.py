"""UI-facing pipeline service and run registry."""

from __future__ import annotations

import json
import hashlib
import threading
import time
import traceback
from collections.abc import Callable, Iterator, Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.api_contract import (
    AdminRunDebugResponse,
    DocumentPackageCollectionResponse,
    DocumentPackageDetailResponse,
    PipelineEventPayload,
    RunCompleteSsePayload,
    RunNotFoundSsePayload,
)
from backend.pipeline_projection import PipelineResultProjector


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


class RunRegistry:
    """Thread-safe run state and event buffer."""

    def __init__(self) -> None:
        self._runs: dict[str, dict[str, Any]] = {}
        self._condition = threading.Condition(threading.Lock())
        self._projector = PipelineResultProjector()

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
                "facts": self._projector.CompactInputFacts(facts),
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
                updates["facts"] = self._projector.CompactInputFacts(updates["facts"])
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
            return self._SnapshotCopyLocked(run)

    def ReadSnapshotByIdentifier(self, identifier: str) -> tuple[str, dict[str, Any]] | None:
        with self._condition:
            if identifier in self._runs:
                return identifier, self._SnapshotCopyLocked(self._runs[identifier])
            for jobId, run in self._runs.items():
                resultData = self._ResultData(run)
                if str(resultData.get("run_id") or "") == identifier:
                    return jobId, self._SnapshotCopyLocked(run)
        return None

    def BuildUiResult(self, runId: str) -> dict[str, Any]:
        snapshot = self.ReadSnapshot(runId)
        if snapshot is None:
            return {}
        return self._projector.BuildUiResult(snapshot, runId)

    def BuildDocumentPackageCollection(self, runId: str) -> dict[str, Any]:
        snapshotEntry = self.ReadSnapshotByIdentifier(runId)
        if snapshotEntry is None:
            return {}
        jobId, snapshot = snapshotEntry
        resultData = self._ResultData(snapshot)
        packages = self._DocumentPackagesFromSnapshot(snapshot, resultData)
        return DocumentPackageCollectionResponse(
            job_id=jobId,
            run_id=resultData.get("run_id"),
            total=len(packages),
            packages=packages,
        ).ToDict()

    def BuildDocumentPackageDetail(
        self,
        runId: str,
        packageId: str,
    ) -> dict[str, Any]:
        snapshotEntry = self.ReadSnapshotByIdentifier(runId)
        if snapshotEntry is None:
            return {}
        jobId, snapshot = snapshotEntry
        resultData = self._ResultData(snapshot)
        packages = self._DocumentPackagesFromSnapshot(snapshot, resultData)
        for package in packages:
            if packageId in {
                str(package.get("document_package_id") or ""),
                str(package.get("taric10") or ""),
            }:
                return DocumentPackageDetailResponse(
                    job_id=jobId,
                    run_id=resultData.get("run_id"),
                    document_package=package,
                ).ToDict()
        return {}

    def _DocumentPackagesFromSnapshot(
        self,
        snapshot: Mapping[str, Any],
        resultData: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        packages = self._projector.ExtractDocumentPackages(resultData)
        if packages:
            return packages
        snapshotPackages = snapshot.get("document_packages")
        if not isinstance(snapshotPackages, list):
            return []
        return [
            self._projector.PublicDocumentPackage(package)
            for package in snapshotPackages
            if isinstance(package, Mapping)
        ]

    def BuildAdminDebugResult(self, runId: str) -> dict[str, Any]:
        snapshotEntry = self.ReadSnapshotByIdentifier(runId)
        if snapshotEntry is None:
            return {}
        jobId, snapshot = snapshotEntry
        resultData = self._ResultData(snapshot)
        return AdminRunDebugResponse(
            job_id=jobId,
            job_status=snapshot.get("status"),
            run_id=resultData.get("run_id"),
            run_dir=resultData.get("run_dir"),
            events=snapshot.get("events") or [],
            public_result=self._projector.BuildUiResult(snapshot, jobId),
        ).ToDict()

    def BuildPipelineResultProjection(
        self,
        pipelineOutput: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self._projector.BuildPipelineResultProjection(pipelineOutput)

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
                    RunNotFoundSsePayload(
                        message="No run exists for the requested run_id.",
                        run_id=runId,
                    ).ToDict(),
                )
                return

            while eventIndex < len(events):
                yield self._FormatSse(
                    "pipeline_event",
                    PipelineEventPayload.model_validate(events[eventIndex]).ToDict(),
                    eventId=str(eventIndex),
                )
                eventIndex += 1

            if status in {"completed", "failed"} and eventIndex >= len(events):
                yield self._FormatSse(
                    "run_complete",
                    RunCompleteSsePayload(
                        run_id=runId,
                        status=status,
                    ).ToDict(),
                )
                return

            yield ": heartbeat\n\n"

    def _AppendEventLocked(self, runId: str, event: Mapping[str, Any]) -> None:
        run = self._runs.setdefault(runId, {"events": []})
        eventData = self._projector.CompactEvent(event)
        eventData.setdefault("ts", time.strftime("%H:%M:%S"))
        run.setdefault("events", []).append(eventData)
        partialResult = eventData.get("partial_result")
        if isinstance(partialResult, dict):
            documentPackages = partialResult.pop("document_packages", None)
            if isinstance(documentPackages, list):
                run["document_packages"] = documentPackages
            run["partial_result"] = partialResult

    def _SnapshotCopyLocked(self, run: Mapping[str, Any]) -> dict[str, Any]:
        snapshot = dict(run)
        snapshot["events"] = list(run.get("events") or [])
        partialResult = run.get("partial_result")
        if isinstance(partialResult, dict):
            snapshot["partial_result"] = dict(partialResult)
        result = run.get("result")
        if isinstance(result, dict):
            snapshot["result"] = dict(result)
        return snapshot

    def _ResultData(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        result = snapshot.get("result")
        if isinstance(result, Mapping):
            return dict(result)
        partialResult = snapshot.get("partial_result")
        if isinstance(partialResult, Mapping):
            return dict(partialResult)
        return {}

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
                job_id=runId,
                progress_callback=lambda event: self._registry.AppendEvent(
                    runId,
                    event,
                ),
            )
            pipelineOutput = self._StripRuntimeObjects(pipelineOutput)
            result = self._registry.BuildPipelineResultProjection(pipelineOutput)
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
