"""현재 OS에 맞는 기본 LLM 런타임 선택 로직."""

import os
import platform
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from eu_export.bridge.schema import (
    LlmRuntimeConfig,
    LlmRuntimeKind,
    OperatingSystemKind,
)

DEFAULT_GOOGLE_AI_STUDIO_ENDPOINT_URL = (
    "https://generativelanguage.googleapis.com/v1beta/openai"
)
DEFAULT_GOOGLE_AI_STUDIO_CHAT_COMPLETIONS_PATH = "/chat/completions"


class UnsupportedLlmRuntimeError(RuntimeError):
    """현재 OS에 대해 기본 로컬 LLM 런타임을 결정할 수 없을 때 사용한다."""


def DetectOperatingSystem(osName: Optional[str] = None) -> OperatingSystemKind:
    """platform.system() 값을 프로젝트 내부 OS enum으로 정규화한다."""

    detectedOsName = osName if osName is not None else platform.system()

    if detectedOsName == "Darwin":
        return OperatingSystemKind.MACOS
    if detectedOsName == "Windows":
        return OperatingSystemKind.WINDOWS
    if detectedOsName == "Linux":
        return OperatingSystemKind.LINUX
    return OperatingSystemKind.UNKNOWN


def SelectDefaultRuntimeKind(
    operatingSystemKind: OperatingSystemKind,
) -> LlmRuntimeKind:
    """OS별 기본 로컬 LLM 런타임을 선택한다."""

    if operatingSystemKind == OperatingSystemKind.MACOS:
        return LlmRuntimeKind.OMLX
    if operatingSystemKind == OperatingSystemKind.WINDOWS:
        return LlmRuntimeKind.OLLAMA

    raise UnsupportedLlmRuntimeError(
        "No default local LLM runtime is configured for OS: {0}".format(
            operatingSystemKind.value,
        )
    )


def BuildDefaultLlmRuntimeConfig(
    osName: Optional[str] = None,
    modelName: Optional[str] = None,
) -> LlmRuntimeConfig:
    """현재 OS를 기준으로 기본 로컬 LLM 런타임 설정을 만든다."""

    operatingSystemKind = DetectOperatingSystem(osName)
    runtimeKind = SelectDefaultRuntimeKind(operatingSystemKind)
    return LlmRuntimeConfig(
        runtimeKind=runtimeKind,
        modelName=modelName,
    )


def BuildLlmRuntimeConfigFromEnv(
    envFilePath: Optional[str | Path] = ".env",
    environment: Optional[Mapping[str, str]] = None,
    osName: Optional[str] = None,
) -> LlmRuntimeConfig:
    """환경 변수와 .env 값을 LlmRuntimeConfig로 분배한다."""

    envValues = _ReadMergedEnvValues(envFilePath, environment)
    runtimeName = _ReadEnvValue(envValues, "EU_EXPORT_LLM_RUNTIME")

    if runtimeName is None:
        return BuildDefaultLlmRuntimeConfig(
            osName=osName,
            modelName=_ReadEnvValue(envValues, "EU_EXPORT_LLM_MODEL"),
        )

    normalizedRuntimeName = runtimeName.strip().lower()
    if normalizedRuntimeName == LlmRuntimeKind.OPENAI.value:
        return _BuildOpenAiRuntimeConfigFromEnv(envValues)
    if normalizedRuntimeName == LlmRuntimeKind.OMLX.value:
        return _BuildLocalRuntimeConfigFromEnv(
            LlmRuntimeKind.OMLX,
            envValues,
            "EU_EXPORT_OMLX_ENDPOINT_URL",
        )
    if normalizedRuntimeName == LlmRuntimeKind.OLLAMA.value:
        return _BuildLocalRuntimeConfigFromEnv(
            LlmRuntimeKind.OLLAMA,
            envValues,
            "EU_EXPORT_OLLAMA_ENDPOINT_URL",
        )

    raise UnsupportedLlmRuntimeError(
        "Unsupported LLM runtime from environment: {0}".format(runtimeName)
    )


def _BuildOpenAiRuntimeConfigFromEnv(
    envValues: Mapping[str, str],
) -> LlmRuntimeConfig:
    providerName = (
        _ReadEnvValue(envValues, "EU_EXPORT_LLM_PROVIDER") or "openai"
    ).strip()
    normalizedProviderName = providerName.lower()

    extraOptions = _BuildCommonExtraOptions(envValues)
    extraOptions["provider"] = normalizedProviderName

    if normalizedProviderName in {"google_ai_studio", "google", "gemini"}:
        apiKey = _ReadFirstEnvValue(
            envValues,
            [
                "EU_EXPORT_GOOGLE_AI_STUDIO_API_KEY",
                "GEMINI_API_KEY",
            ],
        )
        if apiKey is not None:
            extraOptions["api_key"] = apiKey
        extraOptions["chat_completions_path"] = (
            DEFAULT_GOOGLE_AI_STUDIO_CHAT_COMPLETIONS_PATH
        )

        return LlmRuntimeConfig(
            runtimeKind=LlmRuntimeKind.OPENAI,
            modelName=_ReadFirstEnvValue(
                envValues,
                [
                    "EU_EXPORT_GOOGLE_AI_STUDIO_MODEL",
                    "EU_EXPORT_LLM_MODEL",
                ],
            ),
            endpointUrl=(
                _ReadEnvValue(
                    envValues,
                    "EU_EXPORT_GOOGLE_AI_STUDIO_ENDPOINT_URL",
                )
                or DEFAULT_GOOGLE_AI_STUDIO_ENDPOINT_URL
            ),
            extraOptions=extraOptions,
        )

    apiKey = _ReadFirstEnvValue(
        envValues,
        [
            "EU_EXPORT_OPENAI_API_KEY",
            "OPENAI_API_KEY",
        ],
    )
    if apiKey is not None:
        extraOptions["api_key"] = apiKey

    return LlmRuntimeConfig(
        runtimeKind=LlmRuntimeKind.OPENAI,
        modelName=_ReadFirstEnvValue(
            envValues,
            [
                "EU_EXPORT_OPENAI_MODEL",
                "EU_EXPORT_LLM_MODEL",
            ],
        ),
        endpointUrl=_ReadEnvValue(envValues, "EU_EXPORT_OPENAI_ENDPOINT_URL"),
        extraOptions=extraOptions,
    )


def _BuildLocalRuntimeConfigFromEnv(
    runtimeKind: LlmRuntimeKind,
    envValues: Mapping[str, str],
    endpointEnvName: str,
) -> LlmRuntimeConfig:
    return LlmRuntimeConfig(
        runtimeKind=runtimeKind,
        modelName=_ReadEnvValue(envValues, "EU_EXPORT_LLM_MODEL"),
        endpointUrl=_ReadEnvValue(envValues, endpointEnvName),
        extraOptions=_BuildCommonExtraOptions(envValues),
    )


def _ReadMergedEnvValues(
    envFilePath: Optional[str | Path],
    environment: Optional[Mapping[str, str]],
) -> Dict[str, str]:
    envValues: Dict[str, str] = {}

    if envFilePath is not None:
        envValues.update(_ReadEnvFile(envFilePath))

    sourceEnvironment = environment if environment is not None else os.environ
    for envName, envValue in sourceEnvironment.items():
        if isinstance(envValue, str) and envValue.strip() != "":
            envValues[envName] = envValue.strip()

    return envValues


def _ReadEnvFile(envFilePath: str | Path) -> Dict[str, str]:
    resolvedPath = Path(envFilePath)
    if not resolvedPath.exists():
        return {}

    envValues: Dict[str, str] = {}
    for line in resolvedPath.read_text(encoding="utf-8").splitlines():
        strippedLine = line.strip()
        if strippedLine == "" or strippedLine.startswith("#"):
            continue

        if strippedLine.startswith("export "):
            strippedLine = strippedLine[len("export ") :].strip()

        if "=" not in strippedLine:
            continue

        envName, rawValue = strippedLine.split("=", 1)
        normalizedEnvName = envName.strip()
        normalizedEnvValue = _NormalizeEnvFileValue(rawValue)
        if normalizedEnvName != "" and normalizedEnvValue != "":
            envValues[normalizedEnvName] = normalizedEnvValue

    return envValues


def _NormalizeEnvFileValue(rawValue: str) -> str:
    value = rawValue.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()

    return value


def _ReadEnvValue(
    envValues: Mapping[str, str],
    envName: str,
) -> Optional[str]:
    envValue = envValues.get(envName)
    if envValue is None or envValue.strip() == "":
        return None

    return envValue.strip()


def _ReadFirstEnvValue(
    envValues: Mapping[str, str],
    envNames: list[str],
) -> Optional[str]:
    for envName in envNames:
        envValue = _ReadEnvValue(envValues, envName)
        if envValue is not None:
            return envValue

    return None


def _BuildCommonExtraOptions(
    envValues: Mapping[str, str],
) -> Dict[str, Any]:
    extraOptions: Dict[str, Any] = {}
    timeoutSeconds = _ReadPositiveIntEnvValue(
        envValues,
        "EU_EXPORT_LLM_TIMEOUT_SECONDS",
    )
    if timeoutSeconds is not None:
        extraOptions["timeout_seconds"] = timeoutSeconds

    return extraOptions


def _ReadPositiveIntEnvValue(
    envValues: Mapping[str, str],
    envName: str,
) -> Optional[int]:
    envValue = _ReadEnvValue(envValues, envName)
    if envValue is None:
        return None

    try:
        parsedValue = int(envValue)
    except ValueError:
        return None

    if parsedValue <= 0:
        return None

    return parsedValue
