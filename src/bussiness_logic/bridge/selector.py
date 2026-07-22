"""현재 OS에 맞는 기본 LLM 런타임 선택 로직."""

import os
import platform
from pathlib import Path
from typing import Dict, Mapping, Optional

from bussiness_logic.app_config import (
    LlmAppConfig,
    LlmProfileName,
    LoadAppConfig,
)
from bussiness_logic.bridge.probe import (
    DEFAULT_ANTHROPIC_API_KEY_ENV_NAMES,
    DEFAULT_GOOGLE_AI_STUDIO_API_KEY_ENV_NAMES,
    DEFAULT_OPENAI_API_KEY_ENV_NAMES,
    PRIMARY_LLM_API_KEY_ENV_NAME,
)
from bussiness_logic.bridge.schema import (
    LlmRuntimeConfig,
    LlmRuntimeKind,
    OperatingSystemKind,
)

DEFAULT_GOOGLE_AI_STUDIO_ENDPOINT_URL = (
    "https://generativelanguage.googleapis.com/v1beta/openai"
)
DEFAULT_GOOGLE_AI_STUDIO_CHAT_COMPLETIONS_PATH = "/chat/completions"
DEFAULT_OPENAI_ENDPOINT_URL = "https://api.openai.com"
DEFAULT_ANTHROPIC_ENDPOINT_URL = "https://api.anthropic.com"
DEFAULT_OMLX_ENDPOINT_URL = "http://127.0.0.1:8000"
DEFAULT_OLLAMA_ENDPOINT_URL = "http://localhost:11434"
DEFAULT_OPENAI_CHAT_COMPLETIONS_PATH = "/v1/chat/completions"
DEFAULT_OMLX_CHAT_COMPLETIONS_PATH = "/v1/chat/completions"
DEFAULT_ANTHROPIC_MESSAGES_PATH = "/v1/messages"


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
    appConfigPath: Optional[str | Path] = None,
    projectRootPath: Optional[str | Path] = None,
    profileName: Optional[LlmProfileName] = None,
) -> LlmRuntimeConfig:
    """.appconfig 설정과 .env 비밀값을 LlmRuntimeConfig로 분배한다."""

    resolvedProjectRootPath = _ResolveProjectRootPath(
        envFilePath,
        projectRootPath,
    )
    if envFilePath == ".env":
        configuredEnvFilePath = os.environ.get("ASAP_ENV_FILE")
        if configuredEnvFilePath:
            rawEnvFilePath = Path(configuredEnvFilePath).expanduser()
            envFilePath = (
                rawEnvFilePath
                if rawEnvFilePath.is_absolute()
                else resolvedProjectRootPath / rawEnvFilePath
            )
    appConfig = LoadAppConfig(resolvedProjectRootPath, appConfigPath)
    envValues = _ReadMergedEnvValues(envFilePath, environment)
    llmConfig = (
        appConfig.ResolveLlmProfile(profileName)
        if profileName is not None
        else appConfig.llm
    )
    configEnvValues = envValues if profileName is None else {}
    runtimeName = _ReadConfigOrEnvString(
        llmConfig.runtime,
        configEnvValues,
        ["EU_EXPORT_LLM_RUNTIME"],
    )

    if runtimeName is None:
        return BuildDefaultLlmRuntimeConfig(
            osName=osName,
            modelName=_ReadConfigOrEnvString(
                llmConfig.model,
                configEnvValues,
                ["EU_EXPORT_LLM_MODEL"],
            ),
        )

    normalizedRuntimeName = runtimeName.strip().lower()
    if normalizedRuntimeName == LlmRuntimeKind.OPENAI.value:
        return _BuildOpenAiRuntimeConfig(
            llmConfig,
            configEnvValues,
            envValues,
        )
    if normalizedRuntimeName == LlmRuntimeKind.ANTHROPIC.value:
        return _BuildAnthropicRuntimeConfig(
            llmConfig,
            configEnvValues,
            envValues,
        )
    if normalizedRuntimeName == LlmRuntimeKind.OMLX.value:
        return _BuildApiRuntimeConfig(
            LlmRuntimeKind.OMLX,
            llmConfig,
            configEnvValues,
            envValues,
            DEFAULT_OMLX_ENDPOINT_URL,
            ["EU_EXPORT_OMLX_ENDPOINT_URL"],
            DEFAULT_OMLX_CHAT_COMPLETIONS_PATH,
        )
    if normalizedRuntimeName == LlmRuntimeKind.OLLAMA.value:
        return _BuildApiRuntimeConfig(
            LlmRuntimeKind.OLLAMA,
            llmConfig,
            configEnvValues,
            envValues,
            DEFAULT_OLLAMA_ENDPOINT_URL,
            ["EU_EXPORT_OLLAMA_ENDPOINT_URL"],
            None,
        )

    raise UnsupportedLlmRuntimeError(
        "Unsupported LLM runtime from environment: {0}".format(runtimeName)
    )


def _BuildOpenAiRuntimeConfig(
    llmConfig: LlmAppConfig,
    configEnvValues: Mapping[str, str],
    secretEnvValues: Mapping[str, str],
) -> LlmRuntimeConfig:
    providerName = (
        _ReadConfigOrEnvString(
            llmConfig.provider,
            configEnvValues,
            ["EU_EXPORT_LLM_PROVIDER"],
        )
        or "openai"
    ).strip()
    normalizedProviderName = providerName.lower()

    extraOptions = _BuildCommonExtraOptions(llmConfig, configEnvValues)
    extraOptions["provider"] = normalizedProviderName
    if normalizedProviderName in {"google_ai_studio", "google", "gemini"}:
        extraOptions["chat_completions_path"] = _ReadConfigOrEnvString(
            llmConfig.chat_completions_path,
            configEnvValues,
            ["EU_EXPORT_LLM_CHAT_COMPLETIONS_PATH"],
        ) or DEFAULT_GOOGLE_AI_STUDIO_CHAT_COMPLETIONS_PATH

        return LlmRuntimeConfig(
            runtimeKind=LlmRuntimeKind.OPENAI,
            modelName=_ReadConfigOrEnvString(
                llmConfig.model,
                configEnvValues,
                [
                    "EU_EXPORT_LLM_MODEL",
                    "EU_EXPORT_GOOGLE_AI_STUDIO_MODEL",
                ],
            ),
            endpointUrl=(
                _ReadConfigOrEnvString(
                    llmConfig.endpoint_url,
                    configEnvValues,
                    [
                        "EU_EXPORT_LLM_ENDPOINT_URL",
                        "EU_EXPORT_GOOGLE_AI_STUDIO_ENDPOINT_URL",
                    ],
                )
                or DEFAULT_GOOGLE_AI_STUDIO_ENDPOINT_URL
            ),
            extraOptions=extraOptions,
            apiKey=_ReadConfiguredApiKey(
                extraOptions,
                llmConfig,
                secretEnvValues,
                DEFAULT_GOOGLE_AI_STUDIO_API_KEY_ENV_NAMES,
            ),
        )

    extraOptions["chat_completions_path"] = _ReadConfigOrEnvString(
        llmConfig.chat_completions_path,
        configEnvValues,
        ["EU_EXPORT_LLM_CHAT_COMPLETIONS_PATH"],
    ) or DEFAULT_OPENAI_CHAT_COMPLETIONS_PATH

    return LlmRuntimeConfig(
        runtimeKind=LlmRuntimeKind.OPENAI,
        modelName=_ReadConfigOrEnvString(
            llmConfig.model,
            configEnvValues,
            [
                "EU_EXPORT_LLM_MODEL",
                "EU_EXPORT_OPENAI_MODEL",
            ],
        ),
        endpointUrl=(
            _ReadConfigOrEnvString(
                llmConfig.endpoint_url,
                configEnvValues,
                [
                    "EU_EXPORT_LLM_ENDPOINT_URL",
                    "EU_EXPORT_OPENAI_ENDPOINT_URL",
                ],
            )
            or DEFAULT_OPENAI_ENDPOINT_URL
        ),
        extraOptions=extraOptions,
        apiKey=_ReadConfiguredApiKey(
            extraOptions,
            llmConfig,
            secretEnvValues,
            DEFAULT_OPENAI_API_KEY_ENV_NAMES,
        ),
    )


def _BuildAnthropicRuntimeConfig(
    llmConfig: LlmAppConfig,
    configEnvValues: Mapping[str, str],
    secretEnvValues: Mapping[str, str],
) -> LlmRuntimeConfig:
    extraOptions = _BuildCommonExtraOptions(llmConfig, configEnvValues)
    extraOptions["provider"] = "anthropic"
    extraOptions["messages_path"] = _ReadConfigOrEnvString(
        llmConfig.chat_completions_path,
        configEnvValues,
        ["EU_EXPORT_LLM_CHAT_COMPLETIONS_PATH"],
    ) or DEFAULT_ANTHROPIC_MESSAGES_PATH
    apiKey = _ReadConfiguredApiKey(
        extraOptions,
        llmConfig,
        secretEnvValues,
        DEFAULT_ANTHROPIC_API_KEY_ENV_NAMES,
    )
    return LlmRuntimeConfig(
        runtimeKind=LlmRuntimeKind.ANTHROPIC,
        modelName=_ReadConfigOrEnvString(
            llmConfig.model,
            configEnvValues,
            ["EU_EXPORT_LLM_MODEL", "EU_EXPORT_ANTHROPIC_MODEL"],
        ),
        endpointUrl=(
            _ReadConfigOrEnvString(
                llmConfig.endpoint_url,
                configEnvValues,
                ["EU_EXPORT_LLM_ENDPOINT_URL", "EU_EXPORT_ANTHROPIC_ENDPOINT_URL"],
            )
            or DEFAULT_ANTHROPIC_ENDPOINT_URL
        ),
        extraOptions=extraOptions,
        apiKey=apiKey,
    )


def _BuildApiRuntimeConfig(
    runtimeKind: LlmRuntimeKind,
    llmConfig: LlmAppConfig,
    configEnvValues: Mapping[str, str],
    secretEnvValues: Mapping[str, str],
    defaultEndpointUrl: str,
    endpointEnvNames: list[str],
    defaultChatCompletionsPath: Optional[str],
) -> LlmRuntimeConfig:
    extraOptions = _BuildCommonExtraOptions(llmConfig, configEnvValues)
    extraOptions["provider"] = runtimeKind.value

    apiKey = _ReadConfiguredApiKey(
        extraOptions,
        llmConfig,
        secretEnvValues,
        [PRIMARY_LLM_API_KEY_ENV_NAME],
    )

    chatCompletionsPath = _ReadConfigOrEnvString(
        llmConfig.chat_completions_path,
        configEnvValues,
        ["EU_EXPORT_LLM_CHAT_COMPLETIONS_PATH"],
    )
    if chatCompletionsPath is not None:
        extraOptions["chat_completions_path"] = chatCompletionsPath
    elif defaultChatCompletionsPath is not None:
        extraOptions["chat_completions_path"] = defaultChatCompletionsPath

    endpointUrl = _ReadFirstEnvValue(
        configEnvValues,
        [
            "EU_EXPORT_LLM_ENDPOINT_URL",
            *endpointEnvNames,
        ],
    )
    if endpointUrl is None:
        endpointUrl = _ReadConfigString(llmConfig.endpoint_url)

    return LlmRuntimeConfig(
        runtimeKind=runtimeKind,
        modelName=_ReadConfigOrEnvString(
            llmConfig.model,
            configEnvValues,
            ["EU_EXPORT_LLM_MODEL"],
        ),
        endpointUrl=endpointUrl or defaultEndpointUrl,
        extraOptions=extraOptions,
        apiKey=apiKey,
    )


def _ReadConfiguredApiKey(
    extraOptions: Dict[str, object],
    llmConfig: LlmAppConfig,
    envValues: Mapping[str, str],
    fallbackEnvNames: list[str],
) -> Optional[str]:
    configuredEnvName = _ReadConfigString(llmConfig.api_key_env)
    apiKeyEnvNames = (
        [configuredEnvName]
        if configuredEnvName is not None
        else fallbackEnvNames
    )
    apiKey = _ReadFirstEnvValue(envValues, apiKeyEnvNames)
    if configuredEnvName is not None:
        extraOptions["api_key_env_name"] = configuredEnvName
    return apiKey


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


def _ResolveProjectRootPath(
    envFilePath: Optional[str | Path],
    projectRootPath: Optional[str | Path],
) -> Path:
    if projectRootPath is not None:
        return Path(projectRootPath)
    if envFilePath is not None:
        resolvedEnvFilePath = Path(envFilePath)
        if resolvedEnvFilePath.name != "":
            return resolvedEnvFilePath.parent
    return Path.cwd()


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


def _ReadConfigString(value: Optional[str]) -> Optional[str]:
    if isinstance(value, str) and value.strip() != "":
        return value.strip()
    return None


def _ReadConfigOrEnvString(
    configValue: Optional[str],
    envValues: Mapping[str, str],
    envNames: list[str],
) -> Optional[str]:
    envValue = _ReadFirstEnvValue(envValues, envNames)
    if envValue is not None:
        return envValue
    return _ReadConfigString(configValue)


def _BuildCommonExtraOptions(
    llmConfig: LlmAppConfig,
    envValues: Mapping[str, str],
) -> Dict[str, object]:
    extraOptions: Dict[str, object] = {}
    timeoutSeconds = _ReadPositiveIntEnvValue(
        envValues,
        "EU_EXPORT_LLM_TIMEOUT_SECONDS",
    )
    if timeoutSeconds is None:
        timeoutSeconds = llmConfig.timeout_seconds
    if timeoutSeconds is not None:
        extraOptions["timeout_seconds"] = timeoutSeconds

    supportsResponseFormat = _ReadBooleanEnvValue(
        envValues,
        "EU_EXPORT_LLM_SUPPORTS_RESPONSE_FORMAT",
    )
    if supportsResponseFormat is None:
        supportsResponseFormat = llmConfig.supports_response_format
    if supportsResponseFormat is not None:
        extraOptions["supports_response_format"] = supportsResponseFormat

    reasoningEffort = _ReadConfigOrEnvString(
        llmConfig.reasoning_effort,
        envValues,
        ["EU_EXPORT_LLM_REASONING_EFFORT"],
    )
    if reasoningEffort is not None:
        extraOptions["reasoning_effort"] = reasoningEffort

    return extraOptions


def _ReadBooleanEnvValue(
    envValues: Mapping[str, str],
    envName: str,
) -> Optional[bool]:
    envValue = _ReadEnvValue(envValues, envName)
    if envValue is None:
        return None

    return envValue.strip().lower() in {"1", "true", "yes", "on"}


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
