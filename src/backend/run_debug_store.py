"""Stored run debug artifact reader."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class RunDebugStore:
    root: Path

    def ReadRunDebug(self, runId: str) -> dict[str, Any]:
        if not runId:
            return {}
        runDir = self.root / runId
        blackboardPath = runDir / "blackboard.json"
        agentRunsPath = runDir / "agent_runs.jsonl"
        hasBlackboard = blackboardPath.exists()
        hasAgentRuns = agentRunsPath.exists()
        if not hasBlackboard and not hasAgentRuns:
            return {}

        payload: dict[str, Any] = {
            "run_id": runId,
            "run_dir": str(runDir),
        }
        if hasBlackboard:
            payload["blackboard"] = json.loads(blackboardPath.read_text(encoding="utf-8"))
        if hasAgentRuns:
            payload["agent_runs"] = ReadJsonLines(agentRunsPath)
        return payload


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
