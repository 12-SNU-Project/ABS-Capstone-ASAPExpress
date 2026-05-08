"""LLM 응답에서 JSON object를 추출하는 helper."""

import json
from typing import Any, Dict, Optional


class JsonObjectExtractionError(ValueError):
    """LLM 응답에서 JSON object를 추출하지 못했을 때 사용한다."""


def ExtractJsonObject(generatedText: str) -> Dict[str, Any]:
    jsonText = _FindJsonObjectText(generatedText)
    if jsonText is None:
        raise JsonObjectExtractionError("No JSON object found in generated text.")

    try:
        jsonData = json.loads(jsonText)
    except json.JSONDecodeError as error:
        raise JsonObjectExtractionError("Extracted JSON object is invalid.") from error

    if not isinstance(jsonData, dict):
        raise JsonObjectExtractionError("Extracted JSON value must be an object.")

    return jsonData


def _FindJsonObjectText(generatedText: str) -> Optional[str]:
    strippedText = generatedText.strip()
    if strippedText.startswith("{") and strippedText.endswith("}"):
        return strippedText

    startIndex = strippedText.find("{")
    if startIndex < 0:
        return None

    depth = 0
    inString = False
    isEscaped = False
    for index in range(startIndex, len(strippedText)):
        character = strippedText[index]
        if isEscaped:
            isEscaped = False
            continue

        if character == "\\":
            isEscaped = True
            continue

        if character == '"':
            inString = not inString
            continue

        if inString:
            continue

        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return strippedText[startIndex : index + 1]

    return None
