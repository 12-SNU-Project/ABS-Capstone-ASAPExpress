"""LLM runtime dependency probe."""

import os
from importlib.util import find_spec
from pathlib import Path
from shutil import which
from typing import List, Optional

from eu_export.bridge.schema import (
    LocalLlmRuntimeConfig,
    LocalLlmRuntimeKind,
    RuntimeDependencyStatus,
)


DEFAULT_OMLX_MODULE_CANDIDATES = ["omlx", "mlx_lm", "mlx"]
DEFAULT_OLLAMA_COMMAND_CANDIDATES = ["ollama"]
DEFAULT_OMLX_ENDPOINT_URL = "http://127.0.0.1:8000"
DEFAULT_OLLAMA_ENDPOINT_URL = "http://localhost:11434"
DEFAULT_OPENAI_ENDPOINT_URL = "https://api.openai.com"
DEFAULT_OPENAI_API_KEY_ENV_NAMES = [
    "EU_EXPORT_OPENAI_API_KEY",
    "OPENAI_API_KEY",
]


class UnsupportedRuntimeProbeError(RuntimeError):
    """probe 구현이 없는 runtimeKind가 들어왔을 때 사용한다."""


def ProbeRuntimeDependency(
    runtimeConfig: LocalLlmRuntimeConfig,
) -> RuntimeDependencyStatus:
    """선택 runtime을 현재 환경에서 사용할 수 있는지 확인한다."""

    if runtimeConfig.runtimeKind == LocalLlmRuntimeKind.OMLX:
        return _ProbeModuleRuntime(
            runtimeConfig,
            _ReadStringListOption(
                runtimeConfig,
                "module_candidates",
                DEFAULT_OMLX_MODULE_CANDIDATES,
            ),
            DEFAULT_OMLX_ENDPOINT_URL,
        )

    if runtimeConfig.runtimeKind == LocalLlmRuntimeKind.OLLAMA:
        return _ProbeCommandRuntime(
            runtimeConfig,
            _ReadStringListOption(
                runtimeConfig,
                "command_candidates",
                DEFAULT_OLLAMA_COMMAND_CANDIDATES,
            ),
            DEFAULT_OLLAMA_ENDPOINT_URL,
        )

    if runtimeConfig.runtimeKind == LocalLlmRuntimeKind.OPENAI:
        return _ProbeApiKeyRuntime(
            runtimeConfig,
            DEFAULT_OPENAI_ENDPOINT_URL,
            DEFAULT_OPENAI_API_KEY_ENV_NAMES,
            "OpenAI API key setting is available.",
            "OpenAI API key setting is missing.",
        )

    raise UnsupportedRuntimeProbeError(
        "No runtime dependency probe is configured for: {0}".format(
            runtimeConfig.runtimeKind.value,
        )
    )


def _ProbeApiKeyRuntime(
    runtimeConfig: LocalLlmRuntimeConfig,
    defaultEndpointUrl: str,
    apiKeyEnvNames: List[str],
    availableMessage: str,
    missingMessage: str,
) -> RuntimeDependencyStatus:
    endpointUrl = runtimeConfig.endpointUrl or defaultEndpointUrl
    apiKey = _ReadApiKey(runtimeConfig, apiKeyEnvNames)

    if apiKey is not None:
        return RuntimeDependencyStatus(
            runtimeKind=runtimeConfig.runtimeKind,
            isAvailable=True,
            message=availableMessage,
            endpointUrl=endpointUrl,
            limitations=[
                "Dependency probe does not call the external API.",
                "Runtime availability only means an API key was configured.",
            ],
        )

    return RuntimeDependencyStatus(
        runtimeKind=runtimeConfig.runtimeKind,
        isAvailable=False,
        message=missingMessage,
        endpointUrl=endpointUrl,
        limitations=[
            "Set one of: {0}.".format(", ".join(apiKeyEnvNames)),
            "Alternatively pass extraOptions['api_key'] in LocalLlmRuntimeConfig.",
        ],
    )


def _ProbeModuleRuntime(
    runtimeConfig: LocalLlmRuntimeConfig,
    moduleCandidates: List[str],
    defaultEndpointUrl: str,
) -> RuntimeDependencyStatus:
    endpointUrl = runtimeConfig.endpointUrl or defaultEndpointUrl

    if runtimeConfig.executablePath is not None:
        executablePath = _ResolveExecutablePath(runtimeConfig.executablePath)
        if executablePath is not None:
            return RuntimeDependencyStatus(
                runtimeKind=runtimeConfig.runtimeKind,
                isAvailable=True,
                message="Runtime executable is available.",
                executablePath=executablePath,
                endpointUrl=endpointUrl,
            )

    for moduleName in moduleCandidates:
        if find_spec(moduleName) is None:
            continue

        return RuntimeDependencyStatus(
            runtimeKind=runtimeConfig.runtimeKind,
            isAvailable=True,
            message="Runtime Python module is importable.",
            moduleName=moduleName,
            endpointUrl=endpointUrl,
            limitations=[
                "Module availability does not prove that the local runtime server is running.",
            ],
        )

    return RuntimeDependencyStatus(
        runtimeKind=runtimeConfig.runtimeKind,
        isAvailable=False,
        message="No runtime Python module candidate is importable.",
        endpointUrl=endpointUrl,
        limitations=[
            "Dependency probe does not attempt model generation.",
            "Install or expose one of: {0}".format(", ".join(moduleCandidates)),
        ],
    )


def _ProbeCommandRuntime(
    runtimeConfig: LocalLlmRuntimeConfig,
    commandCandidates: List[str],
    defaultEndpointUrl: str,
) -> RuntimeDependencyStatus:
    endpointUrl = runtimeConfig.endpointUrl or defaultEndpointUrl

    if runtimeConfig.executablePath is not None:
        executablePath = _ResolveExecutablePath(runtimeConfig.executablePath)
        if executablePath is not None:
            return RuntimeDependencyStatus(
                runtimeKind=runtimeConfig.runtimeKind,
                isAvailable=True,
                message="Runtime command is available.",
                executablePath=executablePath,
                endpointUrl=endpointUrl,
            )

    for commandName in commandCandidates:
        executablePath = which(commandName)
        if executablePath is None:
            continue

        return RuntimeDependencyStatus(
            runtimeKind=runtimeConfig.runtimeKind,
            isAvailable=True,
            message="Runtime command is available.",
            executablePath=executablePath,
            endpointUrl=endpointUrl,
            limitations=[
                "Command availability does not prove that the local runtime server is running.",
            ],
        )

    return RuntimeDependencyStatus(
        runtimeKind=runtimeConfig.runtimeKind,
        isAvailable=False,
        message="No runtime command candidate is available on PATH.",
        endpointUrl=endpointUrl,
        limitations=[
            "Dependency probe does not attempt model generation.",
            "Install or expose one of: {0}".format(", ".join(commandCandidates)),
        ],
    )


def _ResolveExecutablePath(executablePath: str) -> Optional[str]:
    pathCandidate = Path(executablePath)
    if pathCandidate.exists():
        return str(pathCandidate)

    resolvedPath = which(executablePath)
    if resolvedPath is not None:
        return resolvedPath

    return None


def _ReadApiKey(
    runtimeConfig: LocalLlmRuntimeConfig,
    apiKeyEnvNames: List[str],
) -> Optional[str]:
    optionValue = runtimeConfig.extraOptions.get("api_key")
    if isinstance(optionValue, str) and optionValue.strip() != "":
        return optionValue.strip()

    for envName in apiKeyEnvNames:
        envValue = os.environ.get(envName)
        if envValue is not None and envValue.strip() != "":
            return envValue.strip()

    return None


def _ReadStringListOption(
    runtimeConfig: LocalLlmRuntimeConfig,
    optionName: str,
    defaultValue: List[str],
) -> List[str]:
    optionValue = runtimeConfig.extraOptions.get(optionName)
    if optionValue is None:
        return list(defaultValue)

    if not isinstance(optionValue, list):
        return list(defaultValue)

    return [
        item
        for item in optionValue
        if isinstance(item, str) and item.strip() != ""
    ]
