"""Stored run debug artifact reader."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class RunDebugStore:
    root: Path

    def ReadRunDebug(
        self,
        runId: str,
        *,
        runDir: str | Path | None = None,
    ) -> dict[str, Any]:
        if not runId:
            return {}
        resolvedRunDir = self._ResolveRunDirectory(runId, runDir)
        if resolvedRunDir is None:
            return {}

        blackboardPath = resolvedRunDir / "blackboard.json"
        agentRunsPath = resolvedRunDir / "agent_runs.jsonl"
        hasBlackboard = blackboardPath.exists()
        hasAgentRuns = agentRunsPath.exists()
        if not hasBlackboard and not hasAgentRuns:
            return {}

        payload: dict[str, Any] = {
            "run_id": runId,
            "job_id": resolvedRunDir.name,
            "run_dir": str(resolvedRunDir),
        }
        if hasBlackboard:
            blackboard = json.loads(blackboardPath.read_text(encoding="utf-8"))
            payload["blackboard"] = blackboard
            runContext = blackboard.get("run_context") or {}
            if isinstance(runContext, dict) and runContext.get("run_id"):
                payload["run_id"] = str(runContext["run_id"])
        if hasAgentRuns:
            payload["agent_runs"] = ReadJsonLines(agentRunsPath)
        return payload

    def _ResolveRunDirectory(
        self,
        runId: str,
        runDir: str | Path | None,
    ) -> Path | None:
        root = self.root.resolve()
        if runDir is not None:
            candidate = Path(runDir).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                return None
            return candidate if candidate.is_dir() else None

        if not root.is_dir():
            return None

        matches: list[Path] = []
        for productDirectory in root.iterdir():
            if not productDirectory.is_dir():
                continue
            for jobDirectory in productDirectory.iterdir():
                if not jobDirectory.is_dir():
                    continue
                if jobDirectory.name == runId or self._HasRunId(jobDirectory, runId):
                    matches.append(jobDirectory)
                    if len(matches) > 1:
                        return None
        return matches[0] if matches else None

    @staticmethod
    def _HasRunId(runDirectory: Path, runId: str) -> bool:
        blackboardPath = runDirectory / "blackboard.json"
        if not blackboardPath.exists():
            return False
        try:
            blackboard = json.loads(blackboardPath.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        runContext = blackboard.get("run_context") or {}
        return isinstance(runContext, dict) and str(runContext.get("run_id") or "") == runId


def ReadJsonLines(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            records.append(json.loads(text))
        except json.JSONDecodeError:
            records.append({"raw": text})
    return records
