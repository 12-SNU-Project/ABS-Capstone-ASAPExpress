"""LLM runtime별 generate callable 구현."""

import json
import os
from http.client import HTTPException
from typing import Dict, List
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel

from bussiness_logic.bridge.probe import (
    DEFAULT_OPENAI_API_KEY_ENV_NAMES,
    DEFAULT_OPENAI_ENDPOINT_URL,
    DEFAULT_OLLAMA_ENDPOINT_URL,
    DEFAULT_OMLX_ENDPOINT_URL,
    PRIMARY_LLM_API_KEY_ENV_NAME,
)
from bussiness_logic.bridge.schema import (
    LlmFinishReason,
    LlmRequest,
    LlmResponse,
    LlmResponseFormat,
    LlmRuntimeConfig,
    LlmRuntimeKind,
    LlmTokenUsage,
    RuntimeDescriptor,
)


DEFAULT_HTTP_TIMEOUT_SECONDS = 120
DEFAULT_OPENAI_CHAT_COMPLETIONS_PATH = "/v1/chat/completions"


class RuntimeGenerationError(RuntimeError):
    """LLM runtime 호출이 실패했을 때 사용한다."""


def GenerateRuntimeResponse(
    runtimeDescriptor: RuntimeDescriptor,
    runtimeConfig: LlmRuntimeConfig,
    request: LlmRequest,
) -> LlmResponse:
    """runtimeKind에 따라 실제 generate 호출을 dispatch한다."""

    generators = {
        LlmRuntimeKind.OMLX: _GenerateWithOpenAiCompatibleRuntime,
        LlmRuntimeKind.OLLAMA: _GenerateWithOllamaRuntime,
        LlmRuntimeKind.OPENAI: _GenerateWithOpenAiRuntime,
    }
    generator = generators.get(runtimeDescriptor.runtimeKind)
    if generator is not None:
        return generator(runtimeDescriptor, runtimeConfig, request)

    raise RuntimeGenerationError(
        "No generate implementation is configured for: {0}".format(
            runtimeDescriptor.runtimeKind.value,
        )
    )


def _GenerateWithOpenAiRuntime(
    runtimeDescriptor: RuntimeDescriptor,
    runtimeConfig: LlmRuntimeConfig,
    request: LlmRequest,
) -> LlmResponse:
    if _ShouldUseOpenAiSdkStructuredOutput(runtimeConfig, request):
        runtimeAttempts: List[str] = []
        try:
            return _GenerateWithOpenAiSdkStructuredOutput(
                runtimeDescriptor,
                runtimeConfig,
                request,
            )
        except RuntimeGenerationError as error:
            runtimeAttempts.append(_FormatRuntimeAttempt("openai_sdk_parse", error))
            try:
                return _GenerateWithOpenAiSdkToolChoice(
                    runtimeDescriptor,
                    runtimeConfig,
                    request,
                    runtimeAttempts,
                )
            except RuntimeGenerationError as toolError:
                runtimeAttempts.append(
                    _FormatRuntimeAttempt("openai_sdk_tool_choice", toolError)
                )
                jsonObjectRequest = request.model_copy(
                    update={"responseFormat": LlmResponseFormat.JSON_OBJECT}
                )
                return _GenerateWithOpenAiRuntimeViaHttp(
                    runtimeDescriptor,
                    runtimeConfig,
                    jsonObjectRequest,
                    runtimePath="openai_http_json_object_fallback",
                    runtimeAttempts=runtimeAttempts,
                )

    return _GenerateWithOpenAiRuntimeViaHttp(
        runtimeDescriptor,
        runtimeConfig,
        request,
    )


def _GenerateWithOpenAiRuntimeViaHttp(
    runtimeDescriptor: RuntimeDescriptor,
    runtimeConfig: LlmRuntimeConfig,
    request: LlmRequest,
    runtimePath: str = "openai_http_chat_completions",
    runtimeAttempts: List[str] | None = None,
) -> LlmResponse:
    endpointUrl = _BuildEndpointUrl(
        runtimeDescriptor.endpointUrl or DEFAULT_OPENAI_ENDPOINT_URL,
        _ReadStringOption(
            runtimeConfig,
            "chat_completions_path",
            DEFAULT_OPENAI_CHAT_COMPLETIONS_PATH,
        ),
    )
    payload = _BuildOpenAiChatPayload(
        runtimeConfig,
        request,
        includeResponseFormat=_ShouldIncludeOpenAiRuntimeResponseFormat(
            runtimeConfig,
        ),
    )
    responseData = _PostJson(
        endpointUrl,
        payload,
        _ReadTimeoutSeconds(runtimeConfig),
        _ReadOpenAiHeaders(runtimeConfig),
    )

    generatedText = _ExtractOpenAiChatText(responseData)
    responseModelName = responseData.get("model")
    if not isinstance(responseModelName, str) or responseModelName.strip() == "":
        responseModelName = runtimeConfig.modelName

    return LlmResponse(
        generatedText=generatedText,
        runtimeKind=runtimeConfig.runtimeKind,
        modelName=responseModelName,
        responseFormat=request.responseFormat,
        finishReason=_NormalizeFinishReason(
            _ExtractOpenAiProviderFinishReason(responseData),
        ),
        providerFinishReason=_ExtractOpenAiProviderFinishReason(responseData),
        tokenUsage=_ExtractOpenAiTokenUsage(responseData),
        responseId=_ExtractResponseId(responseData),
        runtimePath=runtimePath,
        runtimeAttempts=runtimeAttempts or [],
        rawResponse=responseData,
        limitations=[
            "OpenAI API output is draft reasoning and must not be treated as official determination.",
        ],
    )


def _GenerateWithOpenAiSdkStructuredOutput(
    runtimeDescriptor: RuntimeDescriptor,
    runtimeConfig: LlmRuntimeConfig,
    request: LlmRequest,
) -> LlmResponse:
    responseModel = request.responseModel
    if responseModel is None:
        raise RuntimeGenerationError(
            "JSON_SCHEMA requests require responseModel for SDK parse."
        )

    client = _BuildOpenAiSdkClient(runtimeDescriptor, runtimeConfig)
    try:
        response = client.beta.chat.completions.parse(
            **_BuildOpenAiSdkChatArgs(runtimeConfig, request),
            response_format=responseModel,
        )
    except Exception as error:  # noqa: BLE001 - external SDK boundary
        raise RuntimeGenerationError(
            "OpenAI SDK structured output parse failed: {0}".format(error)
        ) from error

    responseData = _DumpSdkObject(response)
    return _BuildOpenAiSdkResponse(
        runtimeConfig,
        request,
        response,
        responseData,
        _ExtractOpenAiSdkParsedText(response),
        "openai_sdk_parse",
        [],
        [
            "OpenAI-compatible SDK structured output is draft reasoning and must not be treated as official determination.",
        ],
    )


def _GenerateWithOpenAiSdkToolChoice(
    runtimeDescriptor: RuntimeDescriptor,
    runtimeConfig: LlmRuntimeConfig,
    request: LlmRequest,
    runtimeAttempts: List[str] | None = None,
) -> LlmResponse:
    responseSchema = _ReadResponseSchema(request)
    toolName = _ReadResponseSchemaName(request)
    client = _BuildOpenAiSdkClient(runtimeDescriptor, runtimeConfig)
    tool = {
        "type": "function",
        "function": {
            "name": toolName,
            "description": "Return the requested structured JSON object.",
            "parameters": responseSchema,
        },
    }
    toolChoice = {
        "type": "function",
        "function": {
            "name": toolName,
        },
    }
    try:
        response = client.chat.completions.create(
            **_BuildOpenAiSdkChatArgs(runtimeConfig, request),
            tools=[tool],
            tool_choice=toolChoice,
        )
    except Exception as error:  # noqa: BLE001 - external SDK boundary
        raise RuntimeGenerationError(
            "OpenAI SDK tool_choice structured output failed: {0}".format(error)
        ) from error

    generatedText = _ExtractOpenAiSdkToolArguments(response)
    if generatedText == "":
        raise RuntimeGenerationError(
            "OpenAI SDK tool_choice response did not include tool arguments."
        )

    responseData = _DumpSdkObject(response)
    return _BuildOpenAiSdkResponse(
        runtimeConfig,
        request,
        response,
        responseData,
        generatedText,
        "openai_sdk_tool_choice",
        runtimeAttempts or [],
        [
            "OpenAI-compatible SDK tool_choice output is draft reasoning and must not be treated as official determination.",
        ],
    )


def _GenerateWithOpenAiCompatibleRuntime(
    runtimeDescriptor: RuntimeDescriptor,
    runtimeConfig: LlmRuntimeConfig,
    request: LlmRequest,
) -> LlmResponse:
    endpointUrl = _BuildEndpointUrl(
        runtimeDescriptor.endpointUrl or DEFAULT_OMLX_ENDPOINT_URL,
        _ReadStringOption(
            runtimeConfig,
            "chat_completions_path",
            "/v1/chat/completions",
        ),
    )
    payload = _BuildOpenAiChatPayload(
        runtimeConfig,
        request,
        includeResponseFormat=_ShouldIncludeOpenAiCompatibleResponseFormat(
            runtimeConfig,
        ),
    )
    responseData = _PostJson(
        endpointUrl,
        payload,
        _ReadTimeoutSeconds(runtimeConfig),
        _ReadHeaders(runtimeConfig),
    )

    generatedText = _ExtractOpenAiChatText(responseData)
    return LlmResponse(
        generatedText=generatedText,
        runtimeKind=runtimeConfig.runtimeKind,
        modelName=runtimeConfig.modelName,
        responseFormat=request.responseFormat,
        finishReason=_NormalizeFinishReason(
            _ExtractOpenAiProviderFinishReason(responseData),
        ),
        providerFinishReason=_ExtractOpenAiProviderFinishReason(responseData),
        tokenUsage=_ExtractOpenAiTokenUsage(responseData),
        responseId=_ExtractResponseId(responseData),
        runtimePath="openai_compatible_http_chat_completions",
        rawResponse=responseData,
        limitations=[
            "LLM output is draft reasoning and must not be treated as official determination.",
        ],
    )


def _GenerateWithOllamaRuntime(
    runtimeDescriptor: RuntimeDescriptor,
    runtimeConfig: LlmRuntimeConfig,
    request: LlmRequest,
) -> LlmResponse:
    endpointUrl = _BuildEndpointUrl(
        runtimeDescriptor.endpointUrl or DEFAULT_OLLAMA_ENDPOINT_URL,
        "/api/generate",
    )
    payload = _BuildOllamaPayload(runtimeConfig, request)
    responseData = _PostJson(
        endpointUrl,
        payload,
        _ReadTimeoutSeconds(runtimeConfig),
        _ReadHeaders(runtimeConfig),
    )

    generatedText = str(responseData.get("response", ""))
    return LlmResponse(
        generatedText=generatedText,
        runtimeKind=runtimeConfig.runtimeKind,
        modelName=runtimeConfig.modelName,
        responseFormat=request.responseFormat,
        finishReason=_NormalizeFinishReason(
            _ExtractOllamaProviderFinishReason(responseData),
        ),
        providerFinishReason=_ExtractOllamaProviderFinishReason(responseData),
        tokenUsage=_ExtractOllamaTokenUsage(responseData),
        runtimePath="ollama_http_generate",
        rawResponse=responseData,
        limitations=[
            "LLM output is draft reasoning and must not be treated as official determination.",
        ],
    )


def _BuildOpenAiChatPayload(
    runtimeConfig: LlmRuntimeConfig,
    request: LlmRequest,
    includeResponseFormat: bool,
) -> Dict[str, object]:
    payload: Dict[str, object] = {
        "model": _ReadModelName(runtimeConfig),
        "messages": _BuildChatMessages(request),
        "stream": False,
        "temperature": request.generationOptions.temperature,
    }

    if request.generationOptions.maxTokens is not None:
        payload["max_tokens"] = request.generationOptions.maxTokens
    if request.generationOptions.topP is not None:
        payload["top_p"] = request.generationOptions.topP
    if request.generationOptions.stopSequences:
        payload["stop"] = list(request.generationOptions.stopSequences)
    if (
        includeResponseFormat
        and request.responseFormat == LlmResponseFormat.JSON_OBJECT
    ):
        payload["response_format"] = {"type": "json_object"}
    if (
        includeResponseFormat
        and request.responseFormat == LlmResponseFormat.JSON_SCHEMA
    ):
        payload["response_format"] = _BuildJsonSchemaResponseFormat(request)
    reasoningEffort = _ReadReasoningEffort(runtimeConfig)
    if reasoningEffort is not None:
        payload["reasoning_effort"] = reasoningEffort

    return payload


def _BuildJsonSchemaResponseFormat(request: LlmRequest) -> Dict[str, object]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": _ReadResponseSchemaName(request),
            "strict": True,
            "schema": _ReadResponseSchema(request),
        },
    }


def _ReadResponseSchemaName(request: LlmRequest) -> str:
    if (
        request.responseSchemaName is not None
        and request.responseSchemaName.strip() != ""
    ):
        return request.responseSchemaName.strip()
    if request.responseModel is not None:
        return request.responseModel.__name__
    return "structured_response"


def _ReadResponseSchema(request: LlmRequest) -> Dict[str, object]:
    if isinstance(request.responseSchema, dict) and request.responseSchema:
        return request.responseSchema
    if request.responseModel is not None:
        schema = request.responseModel.model_json_schema(by_alias=True)
        if isinstance(schema, dict):
            return schema
    raise RuntimeGenerationError("JSON_SCHEMA requests require responseSchema.")


def _BuildOllamaPayload(
    runtimeConfig: LlmRuntimeConfig,
    request: LlmRequest,
) -> Dict[str, object]:
    options: Dict[str, object] = {
        "temperature": request.generationOptions.temperature,
    }

    if request.generationOptions.maxTokens is not None:
        options["num_predict"] = request.generationOptions.maxTokens
    if request.generationOptions.topP is not None:
        options["top_p"] = request.generationOptions.topP
    if request.generationOptions.stopSequences:
        options["stop"] = list(request.generationOptions.stopSequences)

    payload: Dict[str, object] = {
        "model": _ReadModelName(runtimeConfig),
        "prompt": _BuildPlainPrompt(request),
        "stream": False,
        "options": options,
    }

    if request.responseFormat == LlmResponseFormat.JSON_OBJECT:
        payload["format"] = "json"
    if request.responseFormat == LlmResponseFormat.JSON_SCHEMA:
        payload["format"] = _ReadResponseSchema(request)

    return payload


def _BuildChatMessages(request: LlmRequest) -> List[Dict[str, str]]:
    messages: List[Dict[str, str]] = []
    systemContent = _BuildSystemContent(request)
    if systemContent != "":
        messages.append({"role": "system", "content": systemContent})

    messages.append({"role": "user", "content": request.userPrompt})
    return messages


def _BuildSystemContent(request: LlmRequest) -> str:
    parts: List[str] = []
    if request.systemPrompt is not None and request.systemPrompt.strip() != "":
        parts.append(request.systemPrompt.strip())

    if request.contextChunks:
        parts.append(
            "Use the following source-grounded context as reference material only."
        )
        parts.extend(request.contextChunks)

    return "\n\n".join(parts)


def _BuildPlainPrompt(request: LlmRequest) -> str:
    parts: List[str] = []
    systemContent = _BuildSystemContent(request)
    if systemContent != "":
        parts.append(systemContent)

    parts.append("User request:")
    parts.append(request.userPrompt)
    return "\n\n".join(parts)


def _PostJson(
    endpointUrl: str,
    payload: Dict[str, object],
    timeoutSeconds: int,
    headers: Dict[str, str],
) -> Dict[str, object]:
    request = Request(
        endpointUrl,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            **headers,
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=timeoutSeconds) as response:
            responseBody = response.read().decode("utf-8")
    except HTTPError as error:
        errorBody = error.read().decode("utf-8", errors="replace")
        raise RuntimeGenerationError(
            "Runtime HTTP request failed: {0} {1}".format(
                error.code,
                errorBody,
            )
        ) from error
    except URLError as error:
        raise RuntimeGenerationError(
            "Runtime endpoint is not reachable: {0}".format(error.reason)
        ) from error
    except (HTTPException, TimeoutError, OSError) as error:
        raise RuntimeGenerationError(
            "Runtime HTTP response could not be read: {0}".format(error)
        ) from error

    if responseBody.strip() == "":
        return {}

    try:
        responseData = json.loads(responseBody)
    except json.JSONDecodeError as error:
        raise RuntimeGenerationError(
            "Runtime response is not valid JSON."
        ) from error

    if not isinstance(responseData, dict):
        raise RuntimeGenerationError("Runtime response JSON must be an object.")

    return responseData


def _BuildOpenAiSdkClient(
    runtimeDescriptor: RuntimeDescriptor,
    runtimeConfig: LlmRuntimeConfig,
) -> object:
    try:
        from openai import OpenAI
    except ImportError as error:  # pragma: no cover - depends on environment
        raise RuntimeGenerationError(
            "OpenAI SDK is required for structured output generation."
        ) from error

    apiKey = _ReadApiKey(runtimeConfig, DEFAULT_OPENAI_API_KEY_ENV_NAMES)
    if apiKey is None:
        raise RuntimeGenerationError(
            "Hosted LLM runtime generation requires {0} or "
            "extraOptions['api_key'].".format(PRIMARY_LLM_API_KEY_ENV_NAME)
        )

    sdkBaseUrl = _BuildOpenAiSdkBaseUrl(runtimeDescriptor, runtimeConfig)
    timeoutSeconds = _ReadTimeoutSeconds(runtimeConfig)
    if sdkBaseUrl is None:
        return OpenAI(api_key=apiKey, timeout=timeoutSeconds)
    return OpenAI(api_key=apiKey, base_url=sdkBaseUrl, timeout=timeoutSeconds)


def _BuildOpenAiSdkBaseUrl(
    runtimeDescriptor: RuntimeDescriptor,
    runtimeConfig: LlmRuntimeConfig,
) -> str | None:
    endpointUrl = runtimeDescriptor.endpointUrl or runtimeConfig.endpointUrl
    providerName = _ReadProviderName(runtimeConfig)
    if providerName == "openai":
        if endpointUrl is None or endpointUrl.rstrip("/") == DEFAULT_OPENAI_ENDPOINT_URL:
            return None
        return _BuildEndpointUrl(endpointUrl, "/v1")
    if endpointUrl is None:
        return None
    return endpointUrl.rstrip("/")


def _BuildOpenAiSdkChatArgs(
    runtimeConfig: LlmRuntimeConfig,
    request: LlmRequest,
) -> Dict[str, object]:
    args: Dict[str, object] = {
        "model": _ReadModelName(runtimeConfig),
        "messages": _BuildChatMessages(request),
        "temperature": request.generationOptions.temperature,
    }
    if request.generationOptions.maxTokens is not None:
        args["max_tokens"] = request.generationOptions.maxTokens
    if request.generationOptions.topP is not None:
        args["top_p"] = request.generationOptions.topP
    if request.generationOptions.stopSequences:
        args["stop"] = list(request.generationOptions.stopSequences)
    reasoningEffort = _ReadReasoningEffort(runtimeConfig)
    if reasoningEffort is not None:
        args["reasoning_effort"] = reasoningEffort
    return args


def _BuildOpenAiSdkResponse(
    runtimeConfig: LlmRuntimeConfig,
    request: LlmRequest,
    response: object,
    responseData: Dict[str, object],
    generatedText: str,
    runtimePath: str,
    runtimeAttempts: List[str],
    limitations: List[str],
) -> LlmResponse:
    return LlmResponse(
        generatedText=generatedText,
        runtimeKind=runtimeConfig.runtimeKind,
        modelName=_ReadSdkStringAttribute(response, "model") or runtimeConfig.modelName,
        responseFormat=request.responseFormat,
        finishReason=_NormalizeFinishReason(
            _ExtractOpenAiProviderFinishReason(responseData),
        ),
        providerFinishReason=_ExtractOpenAiProviderFinishReason(responseData),
        tokenUsage=_ExtractOpenAiTokenUsage(responseData),
        responseId=_ReadSdkStringAttribute(response, "id"),
        runtimePath=runtimePath,
        runtimeAttempts=runtimeAttempts,
        rawResponse=responseData,
        limitations=limitations,
    )


def _ExtractOpenAiSdkParsedText(response: object) -> str:
    message = _ReadOpenAiSdkFirstMessage(response)
    if message is None:
        return ""

    parsed = getattr(message, "parsed", None)
    if isinstance(parsed, BaseModel):
        return parsed.model_dump_json(by_alias=True)
    if isinstance(parsed, dict):
        return json.dumps(parsed, ensure_ascii=False)
    if parsed is not None:
        return str(parsed)

    content = getattr(message, "content", None)
    return str(content) if content is not None else ""


def _ExtractOpenAiSdkToolArguments(response: object) -> str:
    message = _ReadOpenAiSdkFirstMessage(response)
    if message is None:
        return ""

    toolCalls = getattr(message, "tool_calls", None)
    if not isinstance(toolCalls, list) or not toolCalls:
        return ""

    functionCall = getattr(toolCalls[0], "function", None)
    arguments = getattr(functionCall, "arguments", None)
    return str(arguments) if arguments is not None else ""


def _ReadOpenAiSdkFirstMessage(response: object) -> object | None:
    choices = getattr(response, "choices", None)
    if not isinstance(choices, list) or not choices:
        return None
    return getattr(choices[0], "message", None)


def _DumpSdkObject(value: object) -> Dict[str, object]:
    modelDump = getattr(value, "model_dump", None)
    if callable(modelDump):
        dumped = modelDump(mode="json")
        if isinstance(dumped, dict):
            return dumped
    return {
        "sdk_response_type": type(value).__name__,
    }


def _ReadSdkStringAttribute(value: object, attributeName: str) -> str | None:
    attributeValue = getattr(value, attributeName, None)
    if isinstance(attributeValue, str) and attributeValue.strip() != "":
        return attributeValue
    return None


def _ExtractOpenAiChatText(responseData: Dict[str, object]) -> str:
    firstChoice = _ReadFirstOpenAiChoice(responseData)
    if firstChoice is None:
        return ""

    message = firstChoice.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if content is not None:
            return str(content)

    text = firstChoice.get("text")
    if text is not None:
        return str(text)

    return ""


def _ReadFirstOpenAiChoice(responseData: Dict[str, object]) -> Dict[str, object] | None:
    choices = responseData.get("choices")
    if not isinstance(choices, list) or not choices:
        return None

    firstChoice = choices[0]
    if not isinstance(firstChoice, dict):
        return None

    return firstChoice


def _ExtractOpenAiProviderFinishReason(
    responseData: Dict[str, object],
) -> str | None:
    firstChoice = _ReadFirstOpenAiChoice(responseData)
    if firstChoice is None:
        return None

    finishReason = firstChoice.get("finish_reason")
    if finishReason is None:
        return None

    return str(finishReason)


def _ExtractOllamaProviderFinishReason(
    responseData: Dict[str, object],
) -> str | None:
    finishReason = responseData.get("done_reason")
    if finishReason is not None:
        return str(finishReason)

    if responseData.get("done") is True:
        return LlmFinishReason.STOP.value

    return None


def _NormalizeFinishReason(
    providerFinishReason: str | None,
) -> LlmFinishReason:
    if providerFinishReason is None:
        return LlmFinishReason.UNKNOWN

    normalizedReason = providerFinishReason.strip().lower()
    if normalizedReason in {"stop", "complete", "completed"}:
        return LlmFinishReason.STOP
    if normalizedReason in {"length", "max_tokens", "max_token", "token_limit"}:
        return LlmFinishReason.LENGTH
    if normalizedReason == "content_filter":
        return LlmFinishReason.CONTENT_FILTER
    if normalizedReason in {"tool_calls", "function_call"}:
        return LlmFinishReason.TOOL_CALLS

    return LlmFinishReason.UNKNOWN


def _ExtractOpenAiTokenUsage(responseData: Dict[str, object]) -> LlmTokenUsage:
    usage = responseData.get("usage")
    if not isinstance(usage, dict):
        return LlmTokenUsage()

    return LlmTokenUsage(
        inputTokens=_ReadOptionalInt(usage, "prompt_tokens"),
        outputTokens=_ReadOptionalInt(usage, "completion_tokens"),
        totalTokens=_ReadOptionalInt(usage, "total_tokens"),
    )


def _ExtractOllamaTokenUsage(responseData: Dict[str, object]) -> LlmTokenUsage:
    inputTokens = _ReadOptionalInt(responseData, "prompt_eval_count")
    outputTokens = _ReadOptionalInt(responseData, "eval_count")
    totalTokens = None
    if inputTokens is not None and outputTokens is not None:
        totalTokens = inputTokens + outputTokens

    return LlmTokenUsage(
        inputTokens=inputTokens,
        outputTokens=outputTokens,
        totalTokens=totalTokens,
    )


def _ExtractResponseId(responseData: Dict[str, object]) -> str | None:
    responseId = responseData.get("id")
    if isinstance(responseId, str) and responseId.strip() != "":
        return responseId

    return None


def _ReadOptionalInt(data: Dict[str, object], fieldName: str) -> int | None:
    value = data.get(fieldName)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value

    return None


def _BuildEndpointUrl(baseUrl: str, defaultPath: str) -> str:
    normalizedBaseUrl = baseUrl.rstrip("/")
    normalizedDefaultPath = (
        defaultPath if defaultPath.startswith("/") else "/" + defaultPath
    )

    if normalizedBaseUrl.endswith(normalizedDefaultPath):
        return normalizedBaseUrl

    defaultPathParts = normalizedDefaultPath.strip("/").split("/")
    if len(defaultPathParts) > 1:
        defaultPathPrefix = "/" + defaultPathParts[0]
        defaultPathRemainder = "/" + "/".join(defaultPathParts[1:])
        if normalizedBaseUrl.endswith(defaultPathPrefix):
            return normalizedBaseUrl + defaultPathRemainder

    return normalizedBaseUrl + normalizedDefaultPath


def _ReadModelName(runtimeConfig: LlmRuntimeConfig) -> str:
    if runtimeConfig.modelName is not None and runtimeConfig.modelName.strip() != "":
        return runtimeConfig.modelName

    modelName = runtimeConfig.extraOptions.get("model")
    if isinstance(modelName, str) and modelName.strip() != "":
        return modelName

    raise RuntimeGenerationError("Runtime generation requires a model name.")


def _ReadTimeoutSeconds(runtimeConfig: LlmRuntimeConfig) -> int:
    timeoutSeconds = runtimeConfig.extraOptions.get("timeout_seconds")
    if isinstance(timeoutSeconds, int) and timeoutSeconds > 0:
        return timeoutSeconds

    return DEFAULT_HTTP_TIMEOUT_SECONDS


def _ReadHeaders(runtimeConfig: LlmRuntimeConfig) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    apiKey = runtimeConfig.extraOptions.get("api_key")
    if isinstance(apiKey, str) and apiKey.strip() != "":
        headers["Authorization"] = "Bearer {0}".format(apiKey)
        headers["x-api-key"] = apiKey

    return headers


def _ShouldIncludeOpenAiCompatibleResponseFormat(
    runtimeConfig: LlmRuntimeConfig,
) -> bool:
    optionValue = runtimeConfig.extraOptions.get("supports_response_format")
    if isinstance(optionValue, bool):
        return optionValue

    return False


def _ShouldIncludeOpenAiRuntimeResponseFormat(
    runtimeConfig: LlmRuntimeConfig,
) -> bool:
    optionValue = runtimeConfig.extraOptions.get("supports_response_format")
    if isinstance(optionValue, bool):
        return optionValue

    providerName = runtimeConfig.extraOptions.get("provider")
    if isinstance(providerName, str) and providerName.strip().lower() == "openai":
        return True

    return False


def _ShouldUseOpenAiSdkStructuredOutput(
    runtimeConfig: LlmRuntimeConfig,
    request: LlmRequest,
) -> bool:
    if request.responseFormat != LlmResponseFormat.JSON_SCHEMA:
        return False
    if request.responseModel is None:
        return False
    return _ReadProviderName(runtimeConfig) in {
        "openai",
        "gemini",
        "google",
        "google_ai_studio",
    }


def _ReadProviderName(runtimeConfig: LlmRuntimeConfig) -> str:
    providerName = runtimeConfig.extraOptions.get("provider")
    if isinstance(providerName, str) and providerName.strip() != "":
        return providerName.strip().lower()
    if runtimeConfig.runtimeKind == LlmRuntimeKind.OPENAI:
        return "openai"
    return runtimeConfig.runtimeKind.value


def _FormatRuntimeAttempt(runtimePath: str, error: Exception) -> str:
    return "{0}:failed:{1}".format(runtimePath, type(error).__name__)


def _ReadStringOption(
    runtimeConfig: LlmRuntimeConfig,
    optionName: str,
    defaultValue: str,
) -> str:
    optionValue = runtimeConfig.extraOptions.get(optionName)
    if isinstance(optionValue, str) and optionValue.strip() != "":
        return optionValue.strip()

    return defaultValue


def _ReadReasoningEffort(runtimeConfig: LlmRuntimeConfig) -> str | None:
    optionValue = runtimeConfig.extraOptions.get("reasoning_effort")
    if not isinstance(optionValue, str):
        return None

    normalizedValue = optionValue.strip().lower()
    if normalizedValue in {"none", "minimal", "low", "medium", "high"}:
        return normalizedValue

    return None


def _ReadOpenAiHeaders(runtimeConfig: LlmRuntimeConfig) -> Dict[str, str]:
    apiKey = _ReadApiKey(runtimeConfig, DEFAULT_OPENAI_API_KEY_ENV_NAMES)
    if apiKey is None:
        raise RuntimeGenerationError(
            "Hosted LLM runtime generation requires {0} or "
            "extraOptions['api_key'].".format(PRIMARY_LLM_API_KEY_ENV_NAME)
        )

    return {
        "Authorization": "Bearer {0}".format(apiKey),
    }


def _ReadApiKey(
    runtimeConfig: LlmRuntimeConfig,
    apiKeyEnvNames: List[str],
) -> str | None:
    optionValue = runtimeConfig.extraOptions.get("api_key")
    if isinstance(optionValue, str) and optionValue.strip() != "":
        return optionValue.strip()

    for envName in apiKeyEnvNames:
        envValue = os.environ.get(envName)
        if envValue is not None and envValue.strip() != "":
            return envValue.strip()

    return None
