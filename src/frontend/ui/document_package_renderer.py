"""Shared document package rendering entry points."""

from __future__ import annotations

import re
from typing import Any


def CleanCode(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def BuildDocumentPackageContext(package: dict[str, Any]) -> dict[str, Any]:
    from frontend.ui.document_package_dash import package_context

    return package_context(package)


def RenderDocumentPackageResult(
    package: dict[str, Any],
    panel: str,
    options: list[str] | None = None,
) -> Any:
    from frontend.ui.document_package_dash import render_result

    return render_result(package, panel, options or [])


def RenderScenarioDecision(
    package: dict[str, Any],
    context: dict[str, Any],
    selectedValues: list[str] | None,
) -> Any:
    from frontend.ui.document_package_dash import render_scenario_decision

    return render_scenario_decision(package, context, selectedValues or [])
