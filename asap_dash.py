"""
ASAP Dash integrated shell.

Pages:
  /classification           Evidence -> Classification -> TARIC10 candidates
  /document/<run>/<taric10> Precomputed DocumentPackage detail
  /admin/<run>              Blackboard / AgentRun log

Run:
  python asap_dash.py
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dash import ALL, MATCH, Dash, Input, Output, State, dcc, html, no_update
from dash.exceptions import PreventUpdate
from flask import Response, jsonify, request as flask_request

ASAP_ROOT = Path(os.environ.get("ASAP_PROJECT_ROOT", Path(__file__).resolve().parent)).resolve()
ASAP_SRC_ROOT = ASAP_ROOT / "src"
for _path in (ASAP_ROOT, ASAP_SRC_ROOT):
    if _path.exists() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from agents.document_pipeline import run_document_pipeline
from backend import PipelineRunRequest, PipelineRunService, RunRegistry
from ui import admin_dash, classification_dash, document_package_dash


app = Dash(__name__, title="ASAP — 수출 분류·서류 추천", suppress_callback_exceptions=True)
server = app.server

# Reuse the current document package UI stylesheet so the detail page is exactly
# the same visual system as the standalone document_package_dash page.
app.index_string = document_package_dash.app.index_string


RUN_REGISTRY = RunRegistry()
PIPELINE_RUN_SERVICE = PipelineRunService(
    registry=RUN_REGISTRY,
    pipelineCallable=run_document_pipeline,
)


def _split_path(pathname: str | None) -> list[str]:
    return [p for p in (pathname or "/classification").split("/") if p]


def _build_run_facts(
    *,
    productName: str,
    description: str,
    kurlyUrl: str,
    extraFacts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    facts = dict(extraFacts or {})
    facts.update({
        "product_name": productName,
        "description": description,
        "url": kurlyUrl,
        "source_urls": [kurlyUrl] if kurlyUrl else facts.get("source_urls", []),
        "origin_country": facts.get("origin_country") or "KR",
        "intended_use": facts.get("intended_use") or "human consumption",
    })
    return facts


def _start_pipeline_run(*, query: str, facts: Mapping[str, Any]) -> str:
    jobId = f"job_{uuid.uuid4().hex[:10]}"
    runId = RUN_REGISTRY.CreateRun(
        jobId,
        status="queued",
        query=query,
        facts=facts,
        events=[
            {
                "ts": time.strftime("%H:%M:%S"),
                "stage": "Pipeline",
                "status": "queued",
                "message": "작업이 등록되었습니다.",
            }
        ],
        reuseActive=True,
    )
    if runId != jobId:
        return runId

    PIPELINE_RUN_SERVICE.StartBackgroundRun(
        jobId,
        PipelineRunRequest(query=query, facts=dict(facts)),
    )
    return jobId


@server.route("/api/runs", methods=["POST"])
def create_run():
    payload = flask_request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"error": "invalid_json_payload"}), 400

    extraFacts = payload.get("facts") if isinstance(payload.get("facts"), dict) else {}
    productName = str(
        payload.get("product_name") or extraFacts.get("product_name") or ""
    ).strip()
    description = str(
        payload.get("description") or extraFacts.get("description") or ""
    ).strip()
    kurlyUrl = str(
        payload.get("url")
        or payload.get("kurly_url")
        or extraFacts.get("url")
        or ""
    ).strip()
    query = str(
        payload.get("query") or productName or description or kurlyUrl
    ).strip()
    if not query:
        return jsonify({"error": "missing_query"}), 400

    facts = _build_run_facts(
        productName=productName,
        description=description,
        kurlyUrl=kurlyUrl,
        extraFacts=extraFacts,
    )
    jobId = _start_pipeline_run(query=query, facts=facts)
    return jsonify({
        "job_id": jobId,
        "status": "queued",
        "events_url": f"/api/runs/{jobId}/events",
        "result_url": f"/api/runs/{jobId}",
    }), 202


@server.route("/api/runs/<job_id>")
def read_run_snapshot(job_id: str):
    snapshot = RUN_REGISTRY.BuildUiResult(job_id)
    if not snapshot:
        return jsonify({"error": "run_not_found", "job_id": job_id}), 404
    return jsonify(snapshot)


@server.route("/api/runs/<job_id>/events")
def stream_run_events(job_id: str):
    lastEventId = flask_request.headers.get("Last-Event-ID")
    startIndexText = lastEventId or flask_request.args.get("start") or "0"
    try:
        startIndex = int(startIndexText)
    except ValueError:
        startIndex = 0
    if lastEventId:
        startIndex += 1

    return Response(
        RUN_REGISTRY.StreamEvents(job_id, startIndex=startIndex),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


app.layout = html.Div(
    [
        dcc.Location(id="url", refresh=False),
        dcc.Store(id="store-run-id"),
        dcc.Store(id="store-result"),
        dcc.Store(id="document-panel-store", data="overview"),
        dcc.Interval(id="poll", interval=2500, disabled=True),
        html.Div(id="page-root"),
    ],
    style={
        "maxWidth": "1200px",
        "margin": "0 auto",
        "padding": "24px",
        "fontFamily": "-apple-system, BlinkMacSystemFont, 'SF Pro', 'Apple SD Gothic Neo', sans-serif",
    },
)


@app.callback(
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
def start_run(n_clicks, product_name, description, kurly_url, current_run_id, result_data):
    if not n_clicks:
        raise PreventUpdate

    if (
        current_run_id
        and isinstance(result_data, dict)
        and result_data.get("job_id") == current_run_id
        and result_data.get("job_status") in {"queued", "running"}
    ):
        return current_run_id, "/classification"

    product_name = (product_name or "").strip()
    description = (description or "").strip()
    kurly_url = (kurly_url or "").strip()
    query = product_name or description or kurly_url
    if not query:
        job_id = f"job_{uuid.uuid4().hex[:10]}"
        RUN_REGISTRY.CreateRun(
            job_id,
            query="",
            facts={},
            status="failed",
            events=[
                {
                    "ts": time.strftime("%H:%M:%S"),
                    "stage": "Input",
                    "status": "failed",
                    "message": "제품명, 설명, URL 중 하나는 입력해야 합니다.",
                }
            ],
        )
        RUN_REGISTRY.UpdateRun(
            job_id,
            error="제품명, 설명, URL 중 하나는 입력해야 합니다.",
        )
        return job_id, "/classification"

    facts = _build_run_facts(
        productName=product_name,
        description=description,
        kurlyUrl=kurly_url,
    )
    job_id = _start_pipeline_run(query=query, facts=facts)
    return job_id, "/classification"


@app.callback(
    Output("store-result", "data"),
    Input("poll", "n_intervals"),
    State("store-run-id", "data"),
)
def poll_run(_n, job_id):
    if not job_id:
        raise PreventUpdate
    resultData = RUN_REGISTRY.BuildUiResult(job_id)
    if not resultData:
        raise PreventUpdate
    return resultData


@app.callback(
    Output("poll", "disabled"),
    Input("store-run-id", "data"),
    Input("store-result", "data"),
)
def toggle_polling(job_id, result_data):
    if not job_id:
        return True
    if not result_data:
        return False
    if result_data.get("job_id") != job_id:
        return False
    return result_data.get("job_status") in {"completed", "failed"}


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
    cx = document_package_dash.package_context(package_data)
    if cx.get("source") == "unresolved":
        return no_update
    return document_package_dash.render_scenario_decision(package_data, cx, selected_values or [])


@app.callback(
    Output("page-root", "children"),
    Input("url", "pathname"),
    Input("store-result", "data"),
    Input("document-panel-store", "data"),
)
def render_page(pathname, result_data, document_panel):
    parts = _split_path(pathname)
    if not parts:
        return classification_dash.render_page(result_data)

    page = parts[0]
    if page == "document":
        run_id = parts[1] if len(parts) > 1 else None
        taric10 = parts[2] if len(parts) > 2 else ""
        return document_package_dash.render_detail_page(run_id, taric10, document_panel or "overview")

    if page == "admin":
        run_id = parts[1] if len(parts) > 1 else None
        live = result_data if result_data and (not run_id or result_data.get("run_id") == run_id) else None
        return admin_dash.render_page(run_id=run_id, live_result=live)

    return classification_dash.render_page(result_data)


if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=8050)
