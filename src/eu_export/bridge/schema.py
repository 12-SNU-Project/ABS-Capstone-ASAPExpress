"""LLM 런타임 계층의 데이터 계약."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class OperatingSystemKind(str, Enum):
    """로컬 LLM 런타임 선택에 필요한 OS 구분."""

    MACOS = "macos"
    WINDOWS = "windows"
    LINUX = "linux"
    UNKNOWN = "unknown"


class LlmRuntimeKind(str, Enum):
    """교체 가능한 LLM 런타임 종류."""

    OMLX = "omlx"
    OLLAMA = "ollama"
    OPENAI = "openai"


class LlmResponseFormat(str, Enum):
    """LLM 응답 형식에 대한 provider 독립 요청 힌트."""

    TEXT = "text"
    JSON_OBJECT = "json_object"


@dataclass(frozen=True)
class RuntimeDependencyStatus:
    """현재 환경에서 선택 runtime을 사용할 수 있는지 나타내는 probe 결과."""

    runtimeKind: LlmRuntimeKind
    isAvailable: bool
    message: str
    moduleName: Optional[str] = None
    executablePath: Optional[str] = None
    endpointUrl: Optional[str] = None
    limitations: List[str] = field(default_factory=list)

    def ToDict(self) -> Dict[str, Any]:
        return {
            "runtime_kind": self.runtimeKind.value,
            "is_available": self.isAvailable,
            "message": self.message,
            "module_name": self.moduleName,
            "executable_path": self.executablePath,
            "endpoint_url": self.endpointUrl,
            "limitations": list(self.limitations),
        }

    @classmethod
    def FromDict(cls, data: Dict[str, Any]) -> "RuntimeDependencyStatus":
        return cls(
            runtimeKind=LlmRuntimeKind(data["runtime_kind"]),
            isAvailable=data["is_available"],
            message=data["message"],
            moduleName=data.get("module_name"),
            executablePath=data.get("executable_path"),
            endpointUrl=data.get("endpoint_url"),
            limitations=list(data.get("limitations", [])),
        )


@dataclass(frozen=True)
class LlmGenerationOptions:
    """LLM 호출 시 런타임에 전달할 생성 옵션."""

    temperature: float = 0.0
    maxTokens: Optional[int] = None
    topP: Optional[float] = None
    stopSequences: List[str] = field(default_factory=list)

    def ToDict(self) -> Dict[str, Any]:
        return {
            "temperature": self.temperature,
            "max_tokens": self.maxTokens,
            "top_p": self.topP,
            "stop_sequences": list(self.stopSequences),
        }

    @classmethod
    def FromDict(cls, data: Dict[str, Any]) -> "LlmGenerationOptions":
        return cls(
            temperature=data.get("temperature", 0.0),
            maxTokens=data.get("max_tokens"),
            topP=data.get("top_p"),
            stopSequences=list(data.get("stop_sequences", [])),
        )


@dataclass(frozen=True)
class LlmRuntimeConfig:
    """adapter에 전달할 런타임 설정."""

    runtimeKind: LlmRuntimeKind
    modelName: Optional[str] = None
    executablePath: Optional[str] = None
    endpointUrl: Optional[str] = None
    extraOptions: Dict[str, Any] = field(default_factory=dict)

    def ToDict(self) -> Dict[str, Any]:
        return {
            "runtime_kind": self.runtimeKind.value,
            "model_name": self.modelName,
            "executable_path": self.executablePath,
            "endpoint_url": self.endpointUrl,
            "extra_options": dict(self.extraOptions),
        }

    @classmethod
    def FromDict(cls, data: Dict[str, Any]) -> "LlmRuntimeConfig":
        return cls(
            runtimeKind=LlmRuntimeKind(data["runtime_kind"]),
            modelName=data.get("model_name"),
            executablePath=data.get("executable_path"),
            endpointUrl=data.get("endpoint_url"),
            extraOptions=dict(data.get("extra_options", {})),
        )


@dataclass(frozen=True)
class RuntimeDescriptor:
    """선택 runtime의 실행 방식과 dependency 상태를 설명하는 객체."""

    runtimeKind: LlmRuntimeKind
    dependencyStatus: RuntimeDependencyStatus
    moduleName: Optional[str] = None
    executablePath: Optional[str] = None
    endpointUrl: Optional[str] = None
    extraOptions: Dict[str, Any] = field(default_factory=dict)

    def ToDict(self) -> Dict[str, Any]:
        return {
            "runtime_kind": self.runtimeKind.value,
            "dependency_status": self.dependencyStatus.ToDict(),
            "module_name": self.moduleName,
            "executable_path": self.executablePath,
            "endpoint_url": self.endpointUrl,
            "extra_options": dict(self.extraOptions),
        }

    @classmethod
    def FromDict(cls, data: Dict[str, Any]) -> "RuntimeDescriptor":
        return cls(
            runtimeKind=LlmRuntimeKind(data["runtime_kind"]),
            dependencyStatus=RuntimeDependencyStatus.FromDict(
                data["dependency_status"],
            ),
            moduleName=data.get("module_name"),
            executablePath=data.get("executable_path"),
            endpointUrl=data.get("endpoint_url"),
            extraOptions=dict(data.get("extra_options", {})),
        )


@dataclass(frozen=True)
class LlmRequest:
    """RAG 또는 보고서 생성 단계가 LLM adapter에 전달하는 요청."""

    userPrompt: str
    systemPrompt: Optional[str] = None
    contextChunks: List[str] = field(default_factory=list)
    responseFormat: LlmResponseFormat = LlmResponseFormat.TEXT
    generationOptions: LlmGenerationOptions = field(
        default_factory=LlmGenerationOptions,
    )

    def ToDict(self) -> Dict[str, Any]:
        return {
            "user_prompt": self.userPrompt,
            "system_prompt": self.systemPrompt,
            "context_chunks": list(self.contextChunks),
            "response_format": self.responseFormat.value,
            "generation_options": self.generationOptions.ToDict(),
        }

    @classmethod
    def FromDict(cls, data: Dict[str, Any]) -> "LlmRequest":
        return cls(
            userPrompt=data["user_prompt"],
            systemPrompt=data.get("system_prompt"),
            contextChunks=list(data.get("context_chunks", [])),
            responseFormat=LlmResponseFormat(
                data.get("response_format", LlmResponseFormat.TEXT.value),
            ),
            generationOptions=LlmGenerationOptions.FromDict(
                data.get("generation_options", {}),
            ),
        )


@dataclass(frozen=True)
class LlmResponse:
    """LLM adapter가 반환하는 원문 응답과 추적 정보."""

    generatedText: str
    runtimeKind: LlmRuntimeKind
    modelName: Optional[str] = None
    rawResponse: Dict[str, Any] = field(default_factory=dict)
    limitations: List[str] = field(default_factory=list)

    def ToDict(self) -> Dict[str, Any]:
        return {
            "generated_text": self.generatedText,
            "runtime_kind": self.runtimeKind.value,
            "model_name": self.modelName,
            "raw_response": dict(self.rawResponse),
            "limitations": list(self.limitations),
        }

    @classmethod
    def FromDict(cls, data: Dict[str, Any]) -> "LlmResponse":
        return cls(
            generatedText=data["generated_text"],
            runtimeKind=LlmRuntimeKind(data["runtime_kind"]),
            modelName=data.get("model_name"),
            rawResponse=dict(data.get("raw_response", {})),
            limitations=list(data.get("limitations", [])),
        )


# Backward-compatible aliases. 신규 코드는 Llm* 이름을 사용한다.
LocalLlmRuntimeKind = LlmRuntimeKind
LocalLlmGenerationOptions = LlmGenerationOptions
LocalLlmRuntimeConfig = LlmRuntimeConfig
LocalLlmRequest = LlmRequest
LocalLlmResponse = LlmResponse
