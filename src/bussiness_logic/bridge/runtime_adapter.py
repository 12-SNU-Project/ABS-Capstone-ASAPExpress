"""Shared LLM RuntimeAdapter builder for active agents/tools."""

from __future__ import annotations

from pathlib import Path

from bussiness_logic.bridge.factory import BuildRuntimeAdapter
from bussiness_logic.bridge.probe import ProbeRuntimeDependency
from bussiness_logic.bridge.selector import (
    BuildDefaultLlmRuntimeConfig,
    BuildLlmRuntimeConfigFromEnv,
)


def BuildPipelineRuntimeAdapter() -> object:
    """Build RuntimeAdapter from project .env, falling back to default runtime."""

    projectRoot = Path(__file__).resolve().parents[3]
    envFile = projectRoot / ".env"
    try:
        runtimeConfig = BuildLlmRuntimeConfigFromEnv(
            envFilePath=envFile if envFile.exists() else None,
        )
    except Exception:
        runtimeConfig = BuildDefaultLlmRuntimeConfig()
    dependencyStatus = ProbeRuntimeDependency(runtimeConfig)
    return BuildRuntimeAdapter(runtimeConfig, dependencyStatus)
