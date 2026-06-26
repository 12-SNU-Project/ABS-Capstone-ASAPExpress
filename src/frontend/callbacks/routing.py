"""Page routing callback for the Dash shell."""

from __future__ import annotations

from typing import Any

import requests
from dash import Dash, Input, Output, html

from frontend.callbacks.navigation import SplitPath
from frontend.pipeline_api_client import PipelineApiClient
from frontend.ui import admin_dash, classification_dash, document_package_view


def RegisterRoutingCallbacks(
    app: Dash,
    pipelineApiClient: PipelineApiClient,
) -> None:
    @app.callback(
        Output("page-root", "children"),
        Input("url", "pathname"),
        Input("store-result", "data"),
        Input("document-panel-store", "data"),
        Input("input-detail-drawer-store", "data"),
        Input("candidate-tree-drawer-store", "data"),
        Input("classification-result-drawer-store", "data"),
    )
    def render_page(
        pathname: str | None,
        result_data: dict[str, Any] | None,
        document_panel: str | None,
        input_detail_drawer_mode: str | bool | None,
        candidate_tree_drawer_open: bool | None,
        classification_result_drawer_open: bool | None,
    ) -> Any:
        parts = SplitPath(pathname)
        if not parts:
            return classification_dash.render_page(
                result_data,
                input_detail_drawer_mode=input_detail_drawer_mode,
                candidate_tree_drawer_open=bool(candidate_tree_drawer_open),
                classification_result_drawer_open=classification_result_drawer_open,
            )

        page = parts[0]
        if page == "document":
            runId = parts[1] if len(parts) > 1 else ""
            taric10 = parts[2] if len(parts) > 2 else ""
            try:
                documentPackagePayload = pipelineApiClient.ReadDocumentPackageDetail(
                    runId,
                    taric10,
                )
            except (requests.RequestException, ValueError) as exc:
                return _RenderBackendError(exc)
            return document_package_view.render_detail_page(
                runId,
                taric10,
                document_panel or "overview",
                documentPackage=documentPackagePayload.get("document_package"),
            )

        if page == "admin":
            runId = parts[1] if len(parts) > 1 else None
            try:
                debugResult = pipelineApiClient.ReadAdminRunDebug(runId or "")
            except (requests.RequestException, ValueError) as exc:
                return _RenderBackendError(exc)
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

        return classification_dash.render_page(
            result_data,
            input_detail_drawer_mode=input_detail_drawer_mode,
            candidate_tree_drawer_open=bool(candidate_tree_drawer_open),
            classification_result_drawer_open=classification_result_drawer_open,
        )


def _RenderBackendError(error: Exception) -> html.Div:
    return html.Div(
        [
            html.H2("Backend API 연결 실패"),
            html.P(str(error)),
        ],
        style={
            "padding": "24px",
            "border": "1px solid #fecaca",
            "background": "#fef2f2",
            "color": "#991b1b",
        },
    )
