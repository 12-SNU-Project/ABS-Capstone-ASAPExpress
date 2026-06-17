"""Document package panel callbacks."""

from __future__ import annotations

from typing import Any

from dash import ALL, MATCH, Dash, Input, Output, State, ctx, no_update

from frontend.ui import document_package_renderer


def RegisterDocumentPackageCallbacks(app: Dash) -> None:
    app.callback(
        Output("document-panel-store", "data"),
        Input({"type": "panel-btn", "panel": ALL}, "n_clicks"),
        Input({"type": "drawer-close-btn", "target": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )(_select_document_panel)

    app.callback(
        Output({"type": "scenario-result", "taric": MATCH}, "children"),
        Input({"type": "scenario-checks", "taric": MATCH}, "value"),
        State("package-store", "data"),
        prevent_initial_call=True,
    )(_update_document_scenario)


def _select_document_panel(
    _panelClicks: list[int | None],
    _closeClicks: list[int | None],
) -> str | Any:
    triggered = ctx.triggered_id
    if isinstance(triggered, dict) and triggered.get("type") == "panel-btn":
        return triggered.get("panel") or "overview"
    if isinstance(triggered, dict) and triggered.get("type") == "drawer-close-btn":
        return "overview"
    return no_update


def _update_document_scenario(
    selectedValues: list[str] | None,
    packageData: dict[str, Any] | None,
) -> Any:
    if not packageData:
        return no_update
    cx = document_package_renderer.BuildDocumentPackageContext(packageData)
    if cx.get("source") == "unresolved":
        return no_update
    return document_package_renderer.RenderScenarioDecision(
        packageData,
        cx,
        selectedValues or [],
    )
