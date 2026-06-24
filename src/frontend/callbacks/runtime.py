"""Runtime launch and SSE bridge callbacks."""

from __future__ import annotations

from dash import Dash, Input, Output, State

from frontend.client_scripts import RUN_CREATE_CALLBACK, RUN_EVENT_STREAM_CALLBACK


def RegisterRuntimeCallbacks(app: Dash) -> None:
    app.clientside_callback(
        RUN_CREATE_CALLBACK,
        Output("store-run-id", "data"),
        Output("url", "pathname"),
        Input("btn-run", "n_clicks"),
        Input("btn-rerun-reconstruction", "n_clicks"),
        State("ipt-product-name", "value"),
        State("ipt-description", "value"),
        State("ipt-kurly-url", "value"),
        State("store-run-id", "data"),
        State("store-result", "data"),
        State("api-base-url", "data"),
        prevent_initial_call=True,
    )

    app.clientside_callback(
        RUN_EVENT_STREAM_CALLBACK,
        Output("sse-bridge", "children"),
        Input("store-run-id", "data"),
        State("api-base-url", "data"),
    )

    @app.callback(
        Output("btn-run", "disabled"),
        Output("btn-rerun-reconstruction", "disabled"),
        Input("store-result", "data"),
    )
    def toggle_run_buttons(result_data: dict[str, object] | None) -> tuple[bool, bool]:
        disabled = bool(
            isinstance(result_data, dict)
            and result_data.get("job_status") in {"submitting", "queued", "running"}
        )
        return disabled, disabled
