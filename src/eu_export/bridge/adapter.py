"""교체 가능한 로컬 LLM 런타임 adapter."""

from typing import Callable, Generic, TypeVar

from eu_export.bridge.schema import (
    LocalLlmRequest,
    LocalLlmResponse,
    LocalLlmRuntimeConfig,
    LocalLlmRuntimeKind,
)


RuntimeDescriptorT = TypeVar("RuntimeDescriptorT")
GenerateCallable = Callable[
    [RuntimeDescriptorT, LocalLlmRuntimeConfig, LocalLlmRequest],
    LocalLlmResponse,
]


class RuntimeAdapter(Generic[RuntimeDescriptorT]):
    """런타임 설명자와 generate 함수를 주입받는 generic adapter."""

    def __init__(
        self,
        runtimeConfig: LocalLlmRuntimeConfig,
        runtimeDescriptor: RuntimeDescriptorT,
        generateCallable: GenerateCallable[RuntimeDescriptorT],
    ) -> None:
        self._runtimeConfig = runtimeConfig
        self._runtimeDescriptor = runtimeDescriptor
        self._generateCallable = generateCallable

    def RuntimeKind(self) -> LocalLlmRuntimeKind:
        """adapter가 감싸는 실제 런타임 종류를 반환한다."""
        return self._runtimeConfig.runtimeKind

    def RuntimeConfig(self) -> LocalLlmRuntimeConfig:
        """adapter 생성 시 확정된 런타임 설정을 반환한다."""
        return self._runtimeConfig

    def RuntimeDescriptor(self) -> RuntimeDescriptorT:
        """adapter에 주입된 runtime descriptor를 반환한다."""
        return self._runtimeDescriptor

    def Generate(self, request: LocalLlmRequest) -> LocalLlmResponse:
        """LLM 생성을 수행하고 런타임 독립 응답으로 변환한다."""
        return self._generateCallable(
            self._runtimeDescriptor,
            self._runtimeConfig,
            request,
        )
