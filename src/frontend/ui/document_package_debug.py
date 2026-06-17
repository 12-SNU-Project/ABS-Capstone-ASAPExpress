from __future__ import annotations

import json
from typing import Any

from dash import html

from frontend.ui.classification_dash import display_stage_name


def render_debug_pipeline_log(pkg: dict[str, Any]) -> html.Div | None:
    pipeline = pkg.get("_pipeline") or {}
    if not pipeline:
        return html.Details(
            [
                html.Summary("Debug pipeline log"),
                html.Div("TARIC 직접조회 모드입니다. Pipeline debug payload가 없습니다.", className="card-meta"),
            ]
        )

    summary = {
        "run_id": pipeline.get("run_id"),
        "run_dir": pipeline.get("run_dir"),
        "agent_results": pipeline.get("agent_results") or [],
        "decision": pipeline.get("decision") or {},
    }
    agentRuns = pipeline.get("agent_runs") or []
    payload = {
        "summary": summary,
        "candidate_code_set": pipeline.get("candidate_code_set") or {},
        "document_package": pipeline.get("document_package") or {},
        "agent_runs": agentRuns,
    }
    cards = [
        html.Div(
            [
                html.Div(
                    (
                        f"{display_stage_name(run.get('agent_name'))} · "
                        f"{display_stage_name(run.get('stage'))}"
                    ),
                    className="card-title",
                ),
                html.Div(
                    f"outputs: {', '.join(run.get('outputs_written') or []) or '-'}",
                    className="card-meta",
                ),
                html.Div(
                    run.get("reasoning_summary") or "reasoning 없음",
                    className="card-meta",
                ),
            ],
            className="card",
        )
        for run in agentRuns
    ]
    return html.Details(
        [
            html.Summary("Debug pipeline log"),
            html.Div(
                [
                    html.Div(f"run_id: {pipeline.get('run_id')}", className="card-meta"),
                    html.Div(f"run_dir: {pipeline.get('run_dir')}", className="card-meta"),
                ],
                className="card",
            ),
            html.Div(cards, className="two-col") if cards else html.Div("AgentRun log 없음", className="card-meta"),
            html.Details(
                [
                    html.Summary("Debug JSON"),
                    html.Pre(json.dumps(payload, ensure_ascii=False, indent=2), className="textarea"),
                ]
            ),
        ]
    )
