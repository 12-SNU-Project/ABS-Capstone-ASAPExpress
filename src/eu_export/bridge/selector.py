"""현재 OS에 맞는 기본 LLM 런타임 선택 로직."""

import platform
from typing import Optional

from eu_export.bridge.schema import (
    LlmRuntimeConfig,
    LlmRuntimeKind,
    OperatingSystemKind,
)


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
