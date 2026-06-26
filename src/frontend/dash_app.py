"""Dash frontend composition for the ASAP UI."""

from __future__ import annotations

from pathlib import Path

import dash_mantine_components as dmc
from dash import Dash, dcc, html

from frontend.callbacks import RegisterFrontendCallbacks
from frontend.pipeline_api_client import PipelineApiClient


def CreateDashApp(
    *,
    apiBaseUrl: str,
    apiRequestTimeoutSeconds: float = 15.0,
) -> Dash:
    pipelineApiClient = PipelineApiClient(
        apiBaseUrl,
        timeoutSeconds=apiRequestTimeoutSeconds,
    )

    app = Dash(
        __name__,
        title="ASAP - 수출 분류·서류 추천",
        suppress_callback_exceptions=True,
        assets_folder=str(Path(__file__).resolve().parent / "ui" / "assets"),
    )

    app.layout = dmc.MantineProvider(
        children=html.Div(
            [
                dcc.Location(id="url", refresh=False),
                dcc.Store(id="api-base-url", data=apiBaseUrl),
                dcc.Store(id="store-run-id", storage_type="session"),
                dcc.Store(id="store-result"),
                dcc.Store(id="document-panel-store", data="overview"),
                dcc.Store(id="input-detail-drawer-store", data=False),
                dcc.Store(id="candidate-tree-drawer-store", data=False),
                dcc.Store(id="classification-result-drawer-store", data=False),
                html.Div(id="sse-bridge", style={"display": "none"}),
                html.Div(
                    [
                        html.Header(id="app-topbar", style=_TOPBAR_STYLE),
                        html.Main(html.Div(id="page-root"), style=_MAIN_STYLE),
                    ],
                    style=_APP_SHELL_STYLE,
                ),
            ],
            style={
                "minHeight": "100vh",
                "background": "#f8fafc",
                "fontFamily": "-apple-system, BlinkMacSystemFont, 'SF Pro', 'Apple SD Gothic Neo', sans-serif",
            },
        ),
        defaultColorScheme="light",
    )

    RegisterFrontendCallbacks(app, pipelineApiClient)
    return app


_APP_SHELL_STYLE = {
    "display": "flex",
    "flexDirection": "column",
    "minHeight": "100vh",
}

_TOPBAR_STYLE = {
    "position": "sticky",
    "top": 0,
    "zIndex": 80,
    "display": "flex",
    "alignItems": "center",
    "flexWrap": "wrap",
    "gap": "16px 24px",
    "boxSizing": "border-box",
    "padding": "18px 28px",
    "borderBottom": "1px solid #e5e7eb",
    "background": "#ffffff",
}

_MAIN_STYLE = {
    "boxSizing": "border-box",
    "minWidth": 0,
    "width": "100%",
    "maxWidth": "1280px",
    "margin": "0 auto",
    "padding": "24px 28px",
}
