"""로컬 LLM bridge 컴포넌트 smoke test."""

import json
import os
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv

from eu_export import (
    BuildRuntimeAdapter,
    LocalLlmGenerationOptions,
    LocalLlmRequest,
    LocalLlmRuntimeConfig,
    LocalLlmRuntimeKind,
    RuntimeAdapter,
    RuntimeDependencyStatus,
)


PROJECT_ROOT_PATH = Path(__file__).resolve().parent.parent
DEFAULT_DOTENV_PATH = PROJECT_ROOT_PATH / ".env"
DEFAULT_RUNTIME_KIND = "omlx"
DEFAULT_OMLX_ENDPOINT_URL = "http://127.0.0.1:8000"
DEFAULT_OLLAMA_ENDPOINT_URL = "http://localhost:11434"
DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_TEST_PROMPT = "Return exactly this JSON object: {\"status\":\"ok\"}"


def LoadEnvironment() -> None:
    load_dotenv(dotenv_path=DEFAULT_DOTENV_PATH)


def ReadEnvironmentValue(envName: str) -> str | None:
    envValue = os.environ.get(envName)
    if envValue is None or envValue.strip() == "":
        return None
    return envValue.strip()


def ReadRequiredEnvironmentValue(envName: str) -> str:
    envValue = ReadEnvironmentValue(envName)
    if envValue is None:
        raise ValueError("Set {0} before running bridge_test.py.".format(envName))
    return envValue


def ReadPositiveInteger(envName: str, defaultValue: int) -> int:
    envValue = ReadEnvironmentValue(envName)
    if envValue is None:
        return defaultValue

    try:
        parsedValue = int(envValue)
    except ValueError as error:
        raise ValueError("{0} must be an integer.".format(envName)) from error

    if parsedValue <= 0:
        raise ValueError("{0} must be greater than 0.".format(envName))

    return parsedValue


def ReadRuntimeKind() -> LocalLlmRuntimeKind:
    runtimeKind = ReadEnvironmentValue("EU_EXPORT_RUNTIME") or DEFAULT_RUNTIME_KIND
    if runtimeKind.lower() == "ollama":
        return LocalLlmRuntimeKind.OLLAMA
    return LocalLlmRuntimeKind.OMLX


def ReadEndpointUrl(runtimeKind: LocalLlmRuntimeKind) -> str:
    endpointUrl = ReadEnvironmentValue("EU_EXPORT_ENDPOINT")
    if endpointUrl is not None:
        return endpointUrl

    if runtimeKind == LocalLlmRuntimeKind.OLLAMA:
        return DEFAULT_OLLAMA_ENDPOINT_URL
    return DEFAULT_OMLX_ENDPOINT_URL


def BuildRuntimeAdapterForSmokeTest() -> RuntimeAdapter[Any]:
    runtimeKind = ReadRuntimeKind()
    endpointUrl = ReadEndpointUrl(runtimeKind)
    extraOptions: Dict[str, Any] = {
        "timeout_seconds": ReadPositiveInteger(
            "EU_EXPORT_TIMEOUT_SECONDS",
            DEFAULT_TIMEOUT_SECONDS,
        ),
    }
    apiKey = ReadEnvironmentValue("EU_EXPORT_API_KEY")
    if apiKey is not None:
        extraOptions["api_key"] = apiKey

    runtimeConfig = LocalLlmRuntimeConfig(
        runtimeKind=runtimeKind,
        modelName=ReadRequiredEnvironmentValue("EU_EXPORT_MODEL"),
        endpointUrl=endpointUrl,
        extraOptions=extraOptions,
    )
    dependencyStatus = RuntimeDependencyStatus(
        runtimeKind=runtimeKind,
        isAvailable=True,
        message="manual bridge smoke test",
        endpointUrl=endpointUrl,
    )

    return BuildRuntimeAdapter(runtimeConfig, dependencyStatus=dependencyStatus)


def BuildRequest() -> LocalLlmRequest:
    return LocalLlmRequest(
        systemPrompt=(
            "You are testing a local LLM bridge. "
            "Return only the requested JSON object."
        ),
        userPrompt=ReadEnvironmentValue("EU_EXPORT_BRIDGE_TEST_PROMPT")
        or DEFAULT_TEST_PROMPT,
        generationOptions=LocalLlmGenerationOptions(
            temperature=0.0,
            maxTokens=80,
        ),
    )


def PrintJson(title: str, data: Dict[str, Any]) -> None:
    print(title)
    print(json.dumps(data, ensure_ascii=False, indent=2))


def RunBridgeSmokeTest() -> None:
    LoadEnvironment()

    adapter = BuildRuntimeAdapterForSmokeTest()
    response = adapter.Generate(BuildRequest())

    PrintJson(
        "Bridge Runtime Response",
        {
            "runtime_kind": response.runtimeKind.value,
            "model_name": response.modelName,
            "generated_text": response.generatedText,
            "limitations": response.limitations,
        },
    )


if __name__ == "__main__":
    RunBridgeSmokeTest()
