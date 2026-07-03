"""Minimal execution wrapper for pipeline components."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from agents.blackboard import BlackboardStore, now_iso
from bussiness_logic.utils.json_types import JsonObject


@dataclass
class ComponentResult:
    """Lightweight return value from BasePipelineComponent.execute()."""
    success: bool
    component_run_id: str = ""
    error: str | None = None
    outputs_written: list[str] = field(default_factory=list)


class BasePipelineComponent:
    """Abstract base — subclasses set class attrs and implement ``run``."""

    # ---- Subclass MUST set these ----
    component_name: str = ""
    stage: str = ""

    # ---- Subclass MAY set these ----
    llm_model: str | None = None       # None for deterministic services

    def __init__(self):
        if not self.component_name or not self.stage:
            raise ValueError(
                f"{type(self).__name__} must set class attrs component_name and stage"
            )
        self._ResetTrace()

    # ------------------------------------------------------------------ trace
    def _ResetTrace(self) -> None:
        self._inputs_read: list[str] = []
        self._outputs_written: list[str] = []
        self._ontology_reads: list[JsonObject] = []
        self._reasoning_chunks: list[str] = []

    def ReadBlackBoard(self, blackboard_object_id: str) -> None:
        """Record a Blackboard object id that this run read."""
        if blackboard_object_id and blackboard_object_id not in self._inputs_read:
            self._inputs_read.append(blackboard_object_id)

    def WriteBlackBoard(self, blackboard_object_id: str) -> None:
        """Record a Blackboard object id that this run wrote."""
        if blackboard_object_id and blackboard_object_id not in self._outputs_written:
            self._outputs_written.append(blackboard_object_id)

    def CreateCiteSource(
        self,
        source_table: str,
        source_id: str,
        snippet: str = "",
        reason: str = "",
        level: str | None = None,
    ) -> JsonObject:
        """Append one EvidenceCitation to ontology_reads."""
        c: JsonObject = {
            "source_table": source_table,
            "source_id": source_id,
        }
        if level is not None:
            c["level"] = level
        if snippet:
            c["snippet"] = snippet
        if reason:
            c["reason"] = reason
        self._ontology_reads.append(c)
        return c

    def reason(self, chunk: str) -> None:
        """Keep local compatibility with older components; not persisted."""
        if chunk:
            self._reasoning_chunks.append(chunk.strip())

    def RecordPrompt(self, prompt_excerpt: str) -> None:
        """Deprecated no-op. Prompt text must not be persisted."""
        _ = prompt_excerpt

    def RecordTokenUsage(self, tokens_in: int, tokens_out: int) -> None:
        """Deprecated no-op. Token counters are not part of pipeline DTOs."""
        _ = (tokens_in, tokens_out)

    # ------------------------------------------------------------------ exec
    def Execute(self, store: BlackboardStore) -> ComponentResult:
        """Wrap ``run`` and persist only minimal component status."""
        self._ResetTrace()
        component_run_id = store.next_id("cr")
        started = now_iso()
        t0 = time.monotonic()
        error: str | None = None
        try:
            self.Run(store)
            success = True
        except Exception as e:  # noqa: BLE001
            error = f"{type(e).__name__}: {e}"
            success = False
        finished = now_iso()
        duration_ms = int((time.monotonic() - t0) * 1000)

        component_run = {
            "object_type": "ComponentRun",
            "created_by": self.component_name,
            "created_at": started,
            "component_run_id": component_run_id,
            "component_name": self.component_name,
            "stage": self.stage,
            "inputs_read": list(self._inputs_read),
            "outputs_written": list(self._outputs_written),
            "ontology_reads": list(self._ontology_reads),
            "started_at": started,
            "finished_at": finished,
            "duration_ms": duration_ms,
            "llm_model": self.llm_model,
            "error": error,
        }
        component_run = {k: v for k, v in component_run.items() if v is not None}
        store.log_component_run(component_run)

        return ComponentResult(
            success=success,
            component_run_id=component_run_id,
            error=error,
            outputs_written=list(self._outputs_written),
        )

    # ------------------------------------------------------------------ override
    def Run(self, store: BlackboardStore) -> None:
        """Subclass entrypoint. Read inputs, cite core rows, reason, write outputs."""
        raise NotImplementedError
