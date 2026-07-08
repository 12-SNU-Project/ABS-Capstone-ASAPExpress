"""Document package panel callbacks."""

from __future__ import annotations

from dash import ALL, Dash, Input, Output, ctx, no_update


def RegisterDocumentPackageCallbacks(app: Dash) -> None:
    app.callback(
        Output("document-panel-store", "data"),
        Input({"type": "panel-btn", "panel": ALL}, "n_clicks"),
        Input({"type": "drawer-close-btn", "target": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )(_select_document_panel)


def _select_document_panel(
    _panelClicks: list[int | None],
    _closeClicks: list[int | None],
) -> object:
    triggered = ctx.triggered_id
    if isinstance(triggered, dict) and triggered.get("type") == "panel-btn":
        return triggered.get("panel") or "overview"
    if isinstance(triggered, dict) and triggered.get("type") == "drawer-close-btn":
        return "overview"
    return no_update
