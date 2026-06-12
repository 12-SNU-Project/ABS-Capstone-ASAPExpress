"""
ASAP Dash integrated shell.

Pages:
  /classification           Evidence -> Classification -> TARIC10 candidates
  /document/<run>/<taric10> Precomputed DocumentPackage detail
  /admin/<run>              Blackboard / AgentRun log

Run:
  cd /Users/snu/ABS-Capstone-ASAPExpress
  python -m ui.asap_dash
"""
from __future__ import annotations

import os
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path

from dash import ALL, Dash, Input, Output, State, dcc, html, no_update
from dash.exceptions import PreventUpdate

ASAP_ROOT = Path(os.environ.get("ASAP_PROJECT_ROOT", Path(__file__).resolve().parent.parent)).resolve()
ASAP_SRC_ROOT = ASAP_ROOT / "src"
for _path in (ASAP_ROOT, ASAP_SRC_ROOT):
    if _path.exists() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from agents.document_pipeline import run_document_pipeline
from ui import admin_dash, classification_dash, document_package_dash


app = Dash(__name__, title="ASAP — 수출 분류·서류 추천", suppress_callback_exceptions=True)
server = app.server

# Reuse the current document package UI stylesheet so the detail page is exactly
# the same visual system as the standalone document_package_dash page.
app.index_string = document_package_dash.app.index_string


JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()


def _strip_store(result: dict) -> dict:
    return {k: v for k, v in result.items() if k != "store"}


def _job_snapshot(job_id: str) -> dict | None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is None:
            return None
        snap = dict(job)
        snap["events"] = list(job.get("events") or [])
        partial = job.get("partial_result")
        if isinstance(partial, dict):
            snap["partial_result"] = dict(partial)
        result = job.get("result")
        if isinstance(result, dict):
            snap["result"] = dict(result)
        return snap


def _update_job(job_id: str, **updates) -> None:
    with JOBS_LOCK:
        job = JOBS.setdefault(job_id, {})
        job.update(updates)


def _append_job_event(job_id: str, event: dict) -> None:
    event = dict(event)
    event.setdefault("ts", time.strftime("%H:%M:%S"))
    with JOBS_LOCK:
        job = JOBS.setdefault(job_id, {})
        job.setdefault("events", []).append(event)
        partial = event.get("partial_result")
        if isinstance(partial, dict):
            job["partial_result"] = partial


def _start_pipeline_job(job_id: str, *, query: str, facts: dict) -> None:
    _update_job(job_id, status="running", started_at=time.time(), query=query, facts=facts)
    try:
        result = run_document_pipeline(
            query=query,
            facts=facts,
            progress_callback=lambda event: _append_job_event(job_id, event),
        )
        result_data = _strip_store(result)
        _update_job(
            job_id,
            status="completed",
            finished_at=time.time(),
            result=result_data,
            partial_result=result_data,
        )
        _append_job_event(
            job_id,
            {
                "stage": "Pipeline",
                "status": "completed",
                "message": "전체 파이프라인 완료",
                "run_id": result_data.get("run_id"),
            },
        )
    except Exception as exc:  # noqa: BLE001
        _update_job(
            job_id,
            status="failed",
            finished_at=time.time(),
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        _append_job_event(job_id, {"stage": "Pipeline", "status": "failed", "message": str(exc)})


def _result_from_job(job: dict, job_id: str) -> dict:
    result_data = dict(job.get("result") or job.get("partial_result") or {})
    result_data["job_id"] = job_id
    result_data["job_status"] = job.get("status")
    result_data["events"] = job.get("events") or []
    # 사용자 입력값을 UI 가 re-render 시 input 에 복원할 수 있게 store-result 에 같이 박음.
    result_data["facts"] = job.get("facts") or {}
    if job.get("error"):
        result_data["error"] = job.get("error")
        result_data["traceback"] = job.get("traceback")
    return result_data


def _split_path(pathname: str | None) -> list[str]:
    return [p for p in (pathname or "/classification").split("/") if p]


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
    prevent_initial_call=True,
)
def start_run(n_clicks, product_name, description, kurly_url):
    if not n_clicks:
        raise PreventUpdate

    job_id = f"job_{uuid.uuid4().hex[:10]}"
    product_name = (product_name or "").strip()
    description = (description or "").strip()
    kurly_url = (kurly_url or "").strip()
    query = product_name or description or kurly_url
    if not query:
        _update_job(
            job_id,
            status="failed",
            error="제품명, 설명, URL 중 하나는 입력해야 합니다.",
            events=[
                {
                    "ts": time.strftime("%H:%M:%S"),
                    "stage": "Input",
                    "status": "failed",
                    "message": "제품명, 설명, URL 중 하나는 입력해야 합니다.",
                }
            ],
        )
        return job_id, "/classification"

    facts = {
        "product_name": product_name,
        "description": description,
        "url": kurly_url,
        "source_urls": [kurly_url] if kurly_url else [],
        "origin_country": "KR",
        "intended_use": "human consumption",
    }

    _update_job(
        job_id,
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
    )
    thread = threading.Thread(
        target=_start_pipeline_job,
        kwargs={"job_id": job_id, "query": query, "facts": facts},
        daemon=True,
    )
    thread.start()
    return job_id, "/classification"


@app.callback(
    Output("store-result", "data"),
    Input("poll", "n_intervals"),
    State("store-run-id", "data"),
)
def poll_run(_n, job_id):
    if not job_id:
        raise PreventUpdate
    job = _job_snapshot(job_id)
    if not job:
        raise PreventUpdate
    return _result_from_job(job, job_id)


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
