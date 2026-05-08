"""RuntimeAdapter 조립 factory."""

from eu_export.bridge.adapter import RuntimeAdapter
from eu_export.bridge.generator import GenerateRuntimeResponse
from eu_export.bridge.probe import ProbeRuntimeDependency
from eu_export.bridge.schema import (
    LocalLlmRuntimeConfig,
    RuntimeDescriptor,
    RuntimeDependencyStatus,
)


class RuntimeAdapterBuildError(RuntimeError):
    """dependency가 준비되지 않아 adapter를 조립할 수 없을 때 사용한다."""


def BuildRuntimeDescriptor(
    runtimeConfig: LocalLlmRuntimeConfig,
    dependencyStatus: RuntimeDependencyStatus,
) -> RuntimeDescriptor:
    """probe 결과를 adapter에 주입 가능한 runtime descriptor로 변환한다."""

    return RuntimeDescriptor(
        runtimeKind=runtimeConfig.runtimeKind,
        dependencyStatus=dependencyStatus,
        moduleName=dependencyStatus.moduleName,
        executablePath=dependencyStatus.executablePath,
        endpointUrl=dependencyStatus.endpointUrl or runtimeConfig.endpointUrl,
        extraOptions=dict(runtimeConfig.extraOptions),
    )


def BuildRuntimeAdapter(
    runtimeConfig: LocalLlmRuntimeConfig,
    dependencyStatus: RuntimeDependencyStatus | None = None,
    requireAvailable: bool = True,
) -> RuntimeAdapter[RuntimeDescriptor]:
    """dependency 확인 결과를 바탕으로 RuntimeAdapter를 조립한다."""

    resolvedDependencyStatus = (
        dependencyStatus
        if dependencyStatus is not None
        else ProbeRuntimeDependency(runtimeConfig)
    )

    if requireAvailable and not resolvedDependencyStatus.isAvailable:
        raise RuntimeAdapterBuildError(resolvedDependencyStatus.message)

    runtimeDescriptor = BuildRuntimeDescriptor(
        runtimeConfig,
        resolvedDependencyStatus,
    )
    return RuntimeAdapter(
        runtimeConfig=runtimeConfig,
        runtimeDescriptor=runtimeDescriptor,
        generateCallable=GenerateRuntimeResponse,
    )
