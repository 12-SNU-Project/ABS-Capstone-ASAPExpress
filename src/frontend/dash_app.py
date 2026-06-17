"""Dash frontend composition for the ASAP UI."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import dash_mantine_components as dmc
from dash import Dash, dcc, html

from agents.document_pipeline import run_document_pipeline
from backend import PipelineApi, PipelineRunService, RunRegistry
from bussiness_logic.app_config import LoadAppConfig
from frontend.callbacks import RegisterFrontendCallbacks

PipelineCallable = Callable[..., dict[str, Any]]


def CreateDashApp(
    *,
    pipelineCallable: PipelineCallable = run_document_pipeline,
) -> Dash:
    registry = RunRegistry()
    service = PipelineRunService(registry=registry, pipelineCallable=pipelineCallable)
    projectRoot = Path(__file__).resolve().parents[2]
    appConfig = LoadAppConfig(projectRoot)
    pipelineApi = PipelineApi(
        registry=registry,
        service=service,
        debugRunsRoot=appConfig.paths.ResolvePath(
            projectRoot,
            appConfig.paths.blackboard_runs_root,
        ),
    )

    app = Dash(
        __name__,
        title="ASAP - 수출 분류·서류 추천",
        suppress_callback_exceptions=True,
        assets_folder=str(Path(__file__).resolve().parent / "ui" / "assets"),
    )
    pipelineApi.RegisterRoutes(app.server)

    app.layout = dmc.MantineProvider(
        children=html.Div(
            [
                dcc.Location(id="url", refresh=False),
                dcc.Store(id="store-run-id", storage_type="session"),
                dcc.Store(id="store-result"),
                dcc.Store(id="document-panel-store", data="overview"),
                dcc.Store(id="input-detail-drawer-store", data=False),
                dcc.Store(id="candidate-tree-drawer-store", data=False),
                dcc.Store(id="classification-result-drawer-store", data=False),
                html.Div(id="sse-bridge", style={"display": "none"}),
                html.Div(
                    [
                        html.Aside(id="app-sidebar", style=_SIDEBAR_STYLE),
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

    RegisterFrontendCallbacks(app, pipelineApi)
    return app


_APP_SHELL_STYLE = {
    "display": "grid",
    "gridTemplateColumns": "230px minmax(0, 1fr)",
    "minHeight": "100vh",
}

_SIDEBAR_STYLE = {
    "position": "sticky",
    "top": 0,
    "height": "100vh",
    "boxSizing": "border-box",
    "padding": "22px 16px",
    "borderRight": "1px solid #e5e7eb",
    "background": "#ffffff",
    "overflowY": "auto",
}

_MAIN_STYLE = {
    "boxSizing": "border-box",
    "minWidth": 0,
    "width": "100%",
    "maxWidth": "1280px",
    "padding": "24px 28px",
}
