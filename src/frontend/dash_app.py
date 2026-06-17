"""Dash frontend composition for the ASAP UI."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from dash import ALL, MATCH, Dash, Input, Output, State, dcc, html, no_update

from agents.document_pipeline import run_document_pipeline
from backend import PipelineApi, PipelineRunService, RunRegistry
from bussiness_logic.app_config import LoadAppConfig
from frontend.client_scripts import RUN_CREATE_CALLBACK, RUN_EVENT_STREAM_CALLBACK
from frontend.ui import (
    admin_dash,
    classification_dash,
    document_package_dash,
    document_package_renderer,
    document_package_view,
)

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
    )
    app.index_string = document_package_dash.app.index_string
    pipelineApi.RegisterRoutes(app.server)

    app.layout = html.Div(
        [
            dcc.Location(id="url", refresh=False),
            dcc.Store(id="store-run-id", storage_type="session"),
            dcc.Store(id="store-result"),
            dcc.Store(id="document-panel-store", data="overview"),
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
    )

    _RegisterClientsideCallbacks(app)
    _RegisterServerCallbacks(app)
    return app


def _RegisterClientsideCallbacks(app: Dash) -> None:
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


def _RegisterServerCallbacks(app: Dash) -> None:
    @app.callback(
        Output("app-sidebar", "children"),
        Input("url", "pathname"),
        Input("store-run-id", "data"),
        Input("store-result", "data"),
    )
    def render_sidebar(pathname, job_id, result_data):
        return _RenderSidebar(pathname, job_id, result_data)

    @app.callback(
        Output("btn-run", "disabled"),
        Input("store-run-id", "data"),
        Input("store-result", "data"),
    )
    def toggle_run_button(job_id, result_data):
        if not job_id or not isinstance(result_data, dict):
            return False
        if result_data.get("job_id") != job_id:
            return False
        return result_data.get("job_status") in {"queued", "running"}

    @app.callback(
        Output("document-panel-store", "data"),
        Input({"type": "panel-btn", "panel": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def select_document_panel(_clicks):
        from dash import ctx

        triggered = ctx.triggered_id
        if isinstance(triggered, dict) and triggered.get("type") == "panel-btn":
            return triggered.get("panel") or "overview"
        return no_update

    @app.callback(
        Output({"type": "scenario-result", "taric": MATCH}, "children"),
        Input({"type": "scenario-checks", "taric": MATCH}, "value"),
        State("package-store", "data"),
        prevent_initial_call=True,
    )
    def update_document_scenario(selected_values, package_data):
        if not package_data:
            return no_update
        cx = document_package_renderer.BuildDocumentPackageContext(package_data)
        if cx.get("source") == "unresolved":
            return no_update
        return document_package_renderer.RenderScenarioDecision(
            package_data,
            cx,
            selected_values or [],
        )

    @app.callback(
        Output("page-root", "children"),
        Input("url", "pathname"),
        Input("store-result", "data"),
        Input("document-panel-store", "data"),
    )
    def render_page(pathname, result_data, document_panel):
        parts = _SplitPath(pathname)
        if not parts:
            return classification_dash.render_page(result_data)

        page = parts[0]
        if page == "document":
            runId = parts[1] if len(parts) > 1 else ""
            taric10 = parts[2] if len(parts) > 2 else ""
            documentPackagePayload = pipelineApi.ReadDocumentPackageDetail(
                runId,
                taric10,
            )
            return document_package_view.render_detail_page(
                runId,
                taric10,
                document_panel or "overview",
                documentPackage=documentPackagePayload.get("document_package"),
            )

        if page == "admin":
            runId = parts[1] if len(parts) > 1 else None
            debugResult = pipelineApi.ReadAdminRunDebug(runId or "")
            live = (
                result_data
                if result_data and (not runId or result_data.get("run_id") == runId)
                else None
            )
            return admin_dash.render_page(
                run_id=runId,
                debug_result=debugResult,
                live_result=live,
            )

        return classification_dash.render_page(result_data)


def _SplitPath(pathname: str | None) -> list[str]:
    return [part for part in (pathname or "/classification").split("/") if part]


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


def _RenderSidebar(
    pathname: str | None,
    jobId: str | None,
    resultData: dict[str, Any] | None,
) -> list[Any]:
    parts = _SplitPath(pathname)
    page = parts[0] if parts else "classification"
    result = resultData if isinstance(resultData, dict) else {}
    runId = result.get("run_id") or ""
    adminHref = f"/admin/{runId}" if runId else "/admin"
    documentLinks = (
        [_NavLink("서류 상세", f"/{'/'.join(parts)}", True, "TARIC 문서 패키지")]
        if page == "document"
        else []
    )

    return [
        html.Div("ASAP", style={"fontSize": "22px", "fontWeight": 950, "color": "#0f172a"}),
        html.Div(
            "EU export workspace",
            style={"fontSize": "11px", "fontWeight": 750, "color": "#64748b", "marginTop": "4px"},
        ),
        html.Div("Workspace", style=_SIDEBAR_SECTION_STYLE),
        _NavLink("분류", "/classification", page in {"classification", ""}, "입력·후보·서류 연결"),
        *documentLinks,
        _NavLink("관리/디버그", adminHref, page == "admin", "Debug payload·Agent log"),
        html.Div("Run", style=_SIDEBAR_SECTION_STYLE),
        html.Div(
            [
                html.Div("job_id", style=_SIDEBAR_META_LABEL_STYLE),
                html.Div(jobId or "-", style=_SIDEBAR_META_VALUE_STYLE),
                html.Div("run_id", style={**_SIDEBAR_META_LABEL_STYLE, "marginTop": "10px"}),
                html.Div(runId or "-", style=_SIDEBAR_META_VALUE_STYLE),
            ],
            style=_SIDEBAR_META_BOX_STYLE,
        ),
    ]


def _NavLink(label: str, href: str, active: bool, detail: str) -> dcc.Link:
    return dcc.Link(
        [
            html.Div(label, style={"fontSize": "13px", "fontWeight": 900}),
            html.Div(detail, style={"fontSize": "11px", "marginTop": "2px", "opacity": 0.78}),
        ],
        href=href,
        style={
            "display": "block",
            "padding": "10px 11px",
            "marginBottom": "6px",
            "borderRadius": "8px",
            "background": "#eff6ff" if active else "transparent",
            "border": "1px solid #bfdbfe" if active else "1px solid transparent",
            "color": "#1d4ed8" if active else "#334155",
            "textDecoration": "none",
        },
    )


_SIDEBAR_SECTION_STYLE = {
    "marginTop": "24px",
    "marginBottom": "8px",
    "fontSize": "10px",
    "fontWeight": 950,
    "letterSpacing": "0.08em",
    "textTransform": "uppercase",
    "color": "#94a3b8",
}

_SIDEBAR_META_BOX_STYLE = {
    "padding": "10px",
    "border": "1px solid #e5e7eb",
    "borderRadius": "8px",
    "background": "#f8fafc",
}

_SIDEBAR_META_LABEL_STYLE = {
    "fontSize": "10px",
    "fontWeight": 900,
    "color": "#64748b",
}

_SIDEBAR_META_VALUE_STYLE = {
    "marginTop": "3px",
    "fontSize": "11px",
    "fontWeight": 750,
    "color": "#0f172a",
    "fontFamily": "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
    "overflowWrap": "anywhere",
}
