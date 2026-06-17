from __future__ import annotations

from typing import Any

from dash import html

from frontend.ui.classification_dash import (
    CARD,
    LABEL,
    PLACEHOLDER,
    PILL,
    detail_block,
    display_stage_name,
    json_pre,
    render_progress,
)


def _agent_run_cards(agent_runs: list[dict[str, Any]]) -> html.Div:
    if not agent_runs:
        return html.Div("agent_runs 없음", style=PLACEHOLDER)
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(display_stage_name(run.get("agent_name")), style={"fontWeight": 900}),
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
            citations.append({"agent": display_stage_name(run.get("agent_name")), **cit})
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


def _text_list_block(title: str, values: list[Any], *, max_items: int = 20) -> html.Details | None:
    if not values:
        return None
    items = [
        html.Div(
            [
                html.Div(
                    f"{title} #{idx}",
                    style={
                        "fontSize": "11px",
                        "fontWeight": 850,
                        "color": "#64748b",
                        "marginBottom": "4px",
                    },
                ),
                html.Pre(
                    str(value),
                    style={
                        "fontFamily": "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
                        "fontSize": "12px",
                        "whiteSpace": "pre-wrap",
                        "overflow": "auto",
                        "maxHeight": "220px",
                        "background": "#f8fafc",
                        "border": "1px solid #e5e7eb",
                        "borderRadius": "8px",
                        "padding": "10px",
                        "color": "#111827",
                    },
                ),
            ],
            style={"marginTop": "8px"},
        )
        for idx, value in enumerate(values[:max_items], start=1)
    ]
    if len(values) > max_items:
        items.append(
            html.Div(
                f"+ {len(values) - max_items} more",
                style={"fontSize": "12px", "color": "#64748b"},
            )
        )
    return html.Details(
        [
            html.Summary(
                f"{title} 원문 보기 ({len(values)})",
                style={"cursor": "pointer", "fontSize": "12px", "fontWeight": 850},
            ),
            html.Div(items),
        ],
        style={"marginTop": "8px"},
    )


def _evidence_detail_panel(pes: dict[str, Any] | None) -> html.Div:
    pes = pes or {}
    facts = pes.get("observed_facts") or {}
    inferred = pes.get("inferred_facts") or []
    ocrText = facts.get("ocr_text") or []
    composition = facts.get("composition") or []
    return html.Div(
        [
            _text_list_block("OCR chunk", ocrText),
            _text_list_block("composition/fact", composition),
            detail_block("inferred_facts JSON", inferred, max_height=260) if inferred else None,
            detail_block("ProductEvidenceState JSON", pes, max_height=420),
        ],
        style={"marginTop": "8px"},
    )


def render_page(
    run_id: str | None = None,
    *,
    debug_result: dict[str, Any] | None = None,
    live_result: dict[str, Any] | None = None,
) -> html.Div:
    data = debug_result or {}
    publicResult = data.get("public_result") or live_result or {}
    blackboard = data.get("blackboard") or {}
    debugPayload = blackboard or data or publicResult
    agent_runs = data.get("agent_runs") or []
    pes = blackboard.get("product_evidence_state") or {}
    events = data.get("events") or publicResult.get("events") or []
    effective_run_id = data.get("run_id") or publicResult.get("run_id") or run_id
    return html.Div(
        [
            html.Div(
                [
                    html.H1("ASAP Admin", style={"fontSize": "24px", "margin": 0}),
                    html.Div("Stored run debug payload / AgentRun / core read log", style={"fontSize": "12px", "color": "#64748b", "marginTop": "4px"}),
                    html.Div(
                        f"run_id: {effective_run_id or '-'}",
                        style={"fontSize": "12px", "color": "#64748b", "marginTop": "8px"},
                    ),
                ],
                style={"borderBottom": "2px solid #0f172a", "paddingBottom": "12px", "marginBottom": "22px"},
            ),
            html.Div("Stage events", style=LABEL),
            render_progress(data) if events else html.Div(
                "현재 브라우저 세션의 live stage event가 없습니다. 저장된 run에서는 debug payload를 확인하세요.",
                style=PLACEHOLDER,
            ),
            html.Div("Product evidence", style={**LABEL, "marginTop": "22px"}),
            html.Div(
                [
                    html.Div(f"product_id: {pes.get('product_id') or '-'}", style={"fontSize": "12px", "color": "#334155"}),
                    _evidence_detail_panel(pes) if pes else html.Div("ProductEvidenceState 없음", style=PLACEHOLDER),
                ],
                style=CARD,
            ),
            html.Div("Debug payload JSON", style=LABEL),
            json_pre(debugPayload, max_height=560),
            detail_block("Debug payload JSON 크게 보기", debugPayload, max_height=760),
            html.Div("AgentRun timeline", style={**LABEL, "marginTop": "22px"}),
            _agent_run_cards(agent_runs),
            html.Div("Ontology reads / citations", style={**LABEL, "marginTop": "22px"}),
            _citations(agent_runs),
        ]
    )
