"""Shared JSON payload type aliases."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TypeAlias

try:
    from typing import TypeAliasType
except ImportError:  # pragma: no cover - Python 3.11 compatibility
    from typing_extensions import TypeAliasType


JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue = TypeAliasType(
    "JsonValue",
    JsonScalar | list["JsonValue"] | dict[str, "JsonValue"],
)
JsonObject = TypeAliasType("JsonObject", dict[str, JsonValue])
JsonMapping = TypeAliasType("JsonMapping", Mapping[str, JsonValue])
