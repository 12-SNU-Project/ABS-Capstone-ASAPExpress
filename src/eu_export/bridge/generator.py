"""로컬 LLM runtime별 generate callable 구현."""

import json
from typing import Any, Dict, List
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from eu_export.bridge.probe import (
    DEFAULT_OLLAMA_ENDPOINT_URL,
    DEFAULT_OMLX_ENDPOINT_URL,
)
from eu_export.bridge.schema import (
    LocalLlmRequest,
    LocalLlmResponse,
    LocalLlmRuntimeConfig,
    LocalLlmRuntimeKind,
    RuntimeDescriptor,
)


DEFAULT_HTTP_TIMEOUT_SECONDS = 120


class RuntimeGenerationError(RuntimeError):
    """local LLM runtime 호출이 실패했을 때 사용한다."""


def GenerateRuntimeResponse(
    runtimeDescriptor: RuntimeDescriptor,
    runtimeConfig: LocalLlmRuntimeConfig,
    request: LocalLlmRequest,
) -> LocalLlmResponse:
    """runtimeKind에 따라 실제 generate 호출을 dispatch한다."""

    if runtimeDescriptor.runtimeKind == LocalLlmRuntimeKind.OMLX:
        return _GenerateWithOpenAiCompatibleRuntime(
            runtimeDescriptor,
            runtimeConfig,
            request,
        )

    if runtimeDescriptor.runtimeKind == LocalLlmRuntimeKind.OLLAMA:
        return _GenerateWithOllamaRuntime(
            runtimeDescriptor,
            runtimeConfig,
            request,
        )

    if runtimeDescriptor.runtimeKind == LocalLlmRuntimeKind.OPENAI:
        raise RuntimeGenerationError(
            "OpenAI runtime generation is not implemented yet; "
            "only runtime settings and dependency probe are configured."
        )

    raise RuntimeGenerationError(
        "No generate implementation is configured for: {0}".format(
            runtimeDescriptor.runtimeKind.value,
        )
    )


def _GenerateWithOpenAiCompatibleRuntime(
    runtimeDescriptor: RuntimeDescriptor,
    runtimeConfig: LocalLlmRuntimeConfig,
    request: LocalLlmRequest,
) -> LocalLlmResponse:
    endpointUrl = _BuildEndpointUrl(
        runtimeDescriptor.endpointUrl or DEFAULT_OMLX_ENDPOINT_URL,
        "/v1/chat/completions",
    )
    payload = _BuildOpenAiChatPayload(runtimeConfig, request)
    responseData = _PostJson(
        endpointUrl,
        payload,
        _ReadTimeoutSeconds(runtimeConfig),
        _ReadHeaders(runtimeConfig),
    )

    generatedText = _ExtractOpenAiChatText(responseData)
    return LocalLlmResponse(
        generatedText=generatedText,
        runtimeKind=runtimeConfig.runtimeKind,
        modelName=runtimeConfig.modelName,
        rawResponse=responseData,
        limitations=[
            "LLM output is draft reasoning and must not be treated as official determination.",
        ],
    )


def _GenerateWithOllamaRuntime(
    runtimeDescriptor: RuntimeDescriptor,
    runtimeConfig: LocalLlmRuntimeConfig,
    request: LocalLlmRequest,
) -> LocalLlmResponse:
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
    return LocalLlmResponse(
        generatedText=generatedText,
        runtimeKind=runtimeConfig.runtimeKind,
        modelName=runtimeConfig.modelName,
        rawResponse=responseData,
        limitations=[
            "LLM output is draft reasoning and must not be treated as official determination.",
        ],
    )


def _BuildOpenAiChatPayload(
    runtimeConfig: LocalLlmRuntimeConfig,
    request: LocalLlmRequest,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
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

    return payload


def _BuildOllamaPayload(
    runtimeConfig: LocalLlmRuntimeConfig,
    request: LocalLlmRequest,
) -> Dict[str, Any]:
    options: Dict[str, Any] = {
        "temperature": request.generationOptions.temperature,
    }

    if request.generationOptions.maxTokens is not None:
        options["num_predict"] = request.generationOptions.maxTokens
    if request.generationOptions.topP is not None:
        options["top_p"] = request.generationOptions.topP
    if request.generationOptions.stopSequences:
        options["stop"] = list(request.generationOptions.stopSequences)

    return {
        "model": _ReadModelName(runtimeConfig),
        "prompt": _BuildPlainPrompt(request),
        "stream": False,
        "options": options,
    }


def _BuildChatMessages(request: LocalLlmRequest) -> List[Dict[str, str]]:
    messages: List[Dict[str, str]] = []
    systemContent = _BuildSystemContent(request)
    if systemContent != "":
        messages.append({"role": "system", "content": systemContent})

    messages.append({"role": "user", "content": request.userPrompt})
    return messages


def _BuildSystemContent(request: LocalLlmRequest) -> str:
    parts: List[str] = []
    if request.systemPrompt is not None and request.systemPrompt.strip() != "":
        parts.append(request.systemPrompt.strip())

    if request.contextChunks:
        parts.append(
            "Use the following source-grounded context as reference material only."
        )
        parts.extend(request.contextChunks)

    return "\n\n".join(parts)


def _BuildPlainPrompt(request: LocalLlmRequest) -> str:
    parts: List[str] = []
    systemContent = _BuildSystemContent(request)
    if systemContent != "":
        parts.append(systemContent)

    parts.append("User request:")
    parts.append(request.userPrompt)
    return "\n\n".join(parts)


def _PostJson(
    endpointUrl: str,
    payload: Dict[str, Any],
    timeoutSeconds: int,
    headers: Dict[str, str],
) -> Dict[str, Any]:
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


def _ExtractOpenAiChatText(responseData: Dict[str, Any]) -> str:
    choices = responseData.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""

    firstChoice = choices[0]
    if not isinstance(firstChoice, dict):
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


def _ReadModelName(runtimeConfig: LocalLlmRuntimeConfig) -> str:
    if runtimeConfig.modelName is not None and runtimeConfig.modelName.strip() != "":
        return runtimeConfig.modelName

    modelName = runtimeConfig.extraOptions.get("model")
    if isinstance(modelName, str) and modelName.strip() != "":
        return modelName

    raise RuntimeGenerationError("Runtime generation requires a model name.")


def _ReadTimeoutSeconds(runtimeConfig: LocalLlmRuntimeConfig) -> int:
    timeoutSeconds = runtimeConfig.extraOptions.get("timeout_seconds")
    if isinstance(timeoutSeconds, int) and timeoutSeconds > 0:
        return timeoutSeconds

    return DEFAULT_HTTP_TIMEOUT_SECONDS


def _ReadHeaders(runtimeConfig: LocalLlmRuntimeConfig) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    apiKey = runtimeConfig.extraOptions.get("api_key")
    if isinstance(apiKey, str) and apiKey.strip() != "":
        headers["Authorization"] = "Bearer {0}".format(apiKey)
        headers["x-api-key"] = apiKey

    return headers
