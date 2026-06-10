from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dash import html

from ui.classification_dash import CARD, LABEL, PLACEHOLDER, PILL, detail_block, evidence_detail_panel, json_pre, render_progress


PROJECT_ROOT = Path(os.environ.get("ASAP_PROJECT_ROOT", Path(__file__).resolve().parents[2])).resolve()
RUNS_ROOT = PROJECT_ROOT / "data" / "runs"


def load_run(run_id: str | None) -> dict[str, Any]:
    if not run_id:
        return {}
    run_dir = RUNS_ROOT / run_id
    blackboard_path = run_dir / "blackboard.json"
    agent_runs_path = run_dir / "agent_runs.jsonl"
    data: dict[str, Any] = {"run_id": run_id, "run_dir": str(run_dir)}
    if blackboard_path.exists():
        data["blackboard"] = json.loads(blackboard_path.read_text(encoding="utf-8"))
    if agent_runs_path.exists():
        runs = []
        for line in agent_runs_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                runs.append(json.loads(line))
            except json.JSONDecodeError:
                runs.append({"raw": line})
        data["agent_runs"] = runs
    return data


def _agent_run_cards(agent_runs: list[dict[str, Any]]) -> html.Div:
    if not agent_runs:
        return html.Div("agent_runs 없음", style=PLACEHOLDER)
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(run.get("agent_name") or "-", style={"fontWeight": 900}),
                            html.Span(f" {run.get('duration_ms', 0)}ms", style={"fontSize": "11px", "color": "#64748b"}),
                        ]
                    ),
                    html.Div(run.get("reasoning_summary") or "", style={"fontSize": "12px", "color": "#334155", "marginTop": "4px"}),
                    html.Div("outputs: " + ", ".join(run.get("outputs_written") or []), style={"fontSize": "11px", "color": "#64748b", "marginTop": "4px"}),
                    html.Details(
                        [html.Summary("raw"), json_pre(run, max_height=260)],
                        style={"marginTop": "8px"},
                    ),
                ],
                style={**CARD, "marginBottom": "8px"},
            )
            for run in agent_runs
        ]
    )


def _citations(agent_runs: list[dict[str, Any]]) -> html.Div:
    citations = []
    for run in agent_runs:
        for cit in run.get("ontology_reads") or []:
            citations.append({"agent": run.get("agent_name"), **cit})
    if not citations:
        return html.Div("citation 없음", style=PLACEHOLDER)
    return html.Div(
        [
            html.Div(
                [
                    html.Span(c.get("agent") or "-", style={**PILL, "background": "#f8fafc", "color": "#334155"}),
                    html.Span(c.get("source_table") or "-", style=PILL),
                    html.Span(str(c.get("source_id") or ""), style={"fontFamily": "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace", "fontWeight": 800}),
                    html.Div(c.get("snippet") or "", style={"fontSize": "12px", "color": "#334155", "marginTop": "4px"}),
                    html.Div(c.get("reason") or "", style={"fontSize": "11px", "color": "#64748b", "marginTop": "2px"}),
                ],
                style={"padding": "8px 0", "borderBottom": "1px solid #eef2f7"},
            )
            for c in citations[:100]
        ],
        style=CARD,
    )


def render_page(run_id: str | None = None, live_result: dict[str, Any] | None = None) -> html.Div:
    data = live_result or load_run(run_id)
    blackboard = data.get("blackboard") or {}
    agent_runs = data.get("agent_runs") or []
    pes = blackboard.get("product_evidence_state") or {}
    events = data.get("events") or []
    effective_run_id = data.get("run_id") or run_id
    return html.Div(
        [
            html.Div(
                [
                    html.H1("ASAP Admin", style={"fontSize": "24px", "margin": 0}),
                    html.Div("Blackboard / AgentRun / ontology read log", style={"fontSize": "12px", "color": "#64748b", "marginTop": "4px"}),
                    html.Div(
                        [
                            html.A("Classification", href="/classification", style={"fontSize": "12px", "fontWeight": 850, "marginRight": "14px"}),
                            html.Span(f"run_id: {effective_run_id or '-'}", style={"fontSize": "12px", "color": "#64748b"}),
                        ],
                        style={"marginTop": "8px"},
                    ),
                ],
                style={"borderBottom": "2px solid #0f172a", "paddingBottom": "12px", "marginBottom": "22px"},
            ),
            html.Div("Stage events", style=LABEL),
            render_progress(data) if events else html.Div(
                "현재 브라우저 세션의 live stage event가 없습니다. 저장된 run에서는 AgentRun/Blackboard를 확인하세요.",
                style=PLACEHOLDER,
            ),
            html.Div("Product evidence", style={**LABEL, "marginTop": "22px"}),
            html.Div(
                [
                    html.Div(f"product_id: {pes.get('product_id') or '-'}", style={"fontSize": "12px", "color": "#334155"}),
                    evidence_detail_panel(pes) if pes else html.Div("ProductEvidenceState 없음", style=PLACEHOLDER),
                ],
                style=CARD,
            ),
            html.Div("Blackboard JSON", style=LABEL),
            json_pre(blackboard or data, max_height=560),
            detail_block("Blackboard JSON 크게 보기", blackboard or data, max_height=760),
            html.Div("AgentRun timeline", style={**LABEL, "marginTop": "22px"}),
            _agent_run_cards(agent_runs),
            html.Div("Ontology reads / citations", style={**LABEL, "marginTop": "22px"}),
            _citations(agent_runs),
        ]
    )
