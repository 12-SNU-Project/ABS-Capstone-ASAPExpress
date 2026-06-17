"""Runtime launch and SSE bridge callbacks."""

from __future__ import annotations

from typing import Any

from dash import Dash, Input, Output, State

from frontend.client_scripts import RUN_CREATE_CALLBACK, RUN_EVENT_STREAM_CALLBACK


def RegisterRuntimeCallbacks(app: Dash) -> None:
    app.clientside_callback(
        RUN_CREATE_CALLBACK,
        Output("store-run-id", "data"),
        Output("url", "pathname"),
        Input("btn-run", "n_clicks"),
        State("ipt-product-name", "value"),
        State("ipt-description", "value"),
        State("ipt-kurly-url", "value"),
        State("store-run-id", "data"),
        State("store-result", "data"),
        prevent_initial_call=True,
    )

    app.clientside_callback(
        RUN_EVENT_STREAM_CALLBACK,
        Output("sse-bridge", "children"),
        Input("store-run-id", "data"),
    )

    @app.callback(
        Output("btn-run", "disabled"),
        Input("store-run-id", "data"),
        Input("store-result", "data"),
    )
    def toggle_run_button(job_id: str | None, result_data: dict[str, Any] | None) -> bool:
        if not job_id or not isinstance(result_data, dict):
            return False
        if result_data.get("job_id") != job_id:
            return False
        return result_data.get("job_status") in {"queued", "running"}
