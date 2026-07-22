"""Shared LLM RuntimeAdapter builder for active agents/tools."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from bussiness_logic.app_config import LlmProfileName
from bussiness_logic.bridge.adapter import RuntimeAdapter
from bussiness_logic.bridge.factory import BuildRuntimeAdapter, RuntimeAdapterBuildError
from bussiness_logic.bridge.schema import RuntimeDescriptor
from bussiness_logic.bridge.selector import BuildLlmRuntimeConfigFromEnv
from bussiness_logic.bridge.selector import UnsupportedLlmRuntimeError


def BuildPipelineRuntimeAdapter(
    profileName: Optional[LlmProfileName] = None,
    *,
    requireAvailable: bool = True,
) -> RuntimeAdapter[RuntimeDescriptor]:
    """Build one configured runtime adapter for a pipeline LLM role."""

    projectRoot = Path(__file__).resolve().parents[3]
    envFile = projectRoot / ".env"
    runtimeConfig = BuildLlmRuntimeConfigFromEnv(
        envFilePath=envFile if envFile.exists() else None,
        projectRootPath=projectRoot,
        profileName=profileName,
    )
    return BuildRuntimeAdapter(runtimeConfig, requireAvailable=requireAvailable)


def BuildOptionalPipelineRuntimeAdapter(
    profileName: LlmProfileName,
) -> Optional[RuntimeAdapter[RuntimeDescriptor]]:
    """Return None when an explicitly optional Agent runtime is unavailable."""

    try:
        return BuildPipelineRuntimeAdapter(profileName)
    except (RuntimeAdapterBuildError, UnsupportedLlmRuntimeError):
        return None
