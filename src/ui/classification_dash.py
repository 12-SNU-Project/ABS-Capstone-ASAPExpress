from __future__ import annotations

import json
from typing import Any

from dash import dcc, html


CARD = {
    "background": "white",
    "border": "1px solid #e5e7eb",
    "borderRadius": "10px",
    "padding": "16px 18px",
    "boxShadow": "0 1px 3px rgba(15,23,42,0.05)",
}
LABEL = {
    "fontSize": "11px",
    "color": "#64748b",
    "fontWeight": 850,
    "textTransform": "uppercase",
    "marginBottom": "8px",
}
PLACEHOLDER = {
    "color": "#64748b",
    "fontSize": "13px",
    "fontStyle": "italic",
    "padding": "20px",
    "textAlign": "center",
    "background": "#f8fafc",
    "borderRadius": "8px",
    "border": "1px dashed #cbd5e1",
}
INPUT = {
    "width": "100%",
    "height": "42px",
    "lineHeight": "20px",
    "padding": "10px 12px",
    "fontSize": "14px",
    "fontFamily": "inherit",
    "boxSizing": "border-box",
    "border": "1px solid #cbd5e1",
    "borderRadius": "8px",
    "marginBottom": "8px",
}
TEXTAREA = {
    **INPUT,
    "height": "auto",
    "minHeight": "94px",
    "lineHeight": "1.45",
    "resize": "vertical",
}
PILL = {
    "display": "inline-block",
    "padding": "3px 8px",
    "borderRadius": "999px",
    "fontSize": "11px",
    "fontWeight": 800,
    "background": "#eff6ff",
    "color": "#2563eb",
    "marginRight": "6px",
}
MONO = {
    "fontFamily": "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
    "fontSize": "12px",
}


def _small(label: str, value: Any) -> html.Div:
    return html.Div(
        [
            html.Div(label, style={"fontSize": "11px", "color": "#64748b", "marginBottom": "4px"}),
            html.Div(str(value or "-"), style={"fontWeight": 850, "fontSize": "14px", "overflowWrap": "anywhere"}),
        ],
        style={
            "border": "1px solid #e5e7eb",
            "borderRadius": "8px",
            "padding": "10px 12px",
            "background": "#fbfcfe",
            "minWidth": "120px",
        },
    )


def json_pre(data: Any, *, max_height: int = 420) -> html.Pre:
    return html.Pre(
        json.dumps(data, ensure_ascii=False, indent=2),
        style={
            **MONO,
            "whiteSpace": "pre-wrap",
            "overflow": "auto",
            "maxHeight": f"{max_height}px",
            "background": "#0f172a",
            "color": "#e5e7eb",
            "borderRadius": "8px",
            "padding": "14px",
            "border": "1px solid #111827",
        },
    )


def detail_block(title: str, data: Any, *, max_height: int = 320, open_: bool = False) -> html.Details:
    return html.Details(
        [
            html.Summary(title, style={"cursor": "pointer", "fontSize": "12px", "fontWeight": 850, "color": "#334155"}),
            json_pre(data, max_height=max_height),
        ],
        open=open_,
        style={"marginTop": "8px"},
    )


def _text_list_block(title: str, values: list[Any], *, max_items: int = 20) -> html.Details | None:
    if not values:
        return None
    items = []
    for idx, value in enumerate(values[:max_items], start=1):
        items.append(
            html.Div(
                [
                    html.Div(f"{title} #{idx}", style={"fontSize": "11px", "fontWeight": 850, "color": "#64748b", "marginBottom": "4px"}),
                    html.Pre(
                        str(value),
                        style={
                            **MONO,
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
        )
    if len(values) > max_items:
        items.append(html.Div(f"+ {len(values) - max_items} more", style={"fontSize": "12px", "color": "#64748b"}))
    return html.Details(
        [html.Summary(f"{title} 원문 보기 ({len(values)})", style={"cursor": "pointer", "fontSize": "12px", "fontWeight": 850}), html.Div(items)],
        style={"marginTop": "8px"},
    )


def evidence_detail_panel(pes: dict[str, Any] | None) -> html.Div:
    pes = pes or {}
    facts = pes.get("observed_facts") or {}
    inferred = pes.get("inferred_facts") or []
    ocr_text = facts.get("ocr_text") or []
    composition = facts.get("composition") or []
    return html.Div(
        [
            _text_list_block("OCR chunk", ocr_text),
            _text_list_block("composition/fact", composition),
            detail_block("inferred_facts JSON", inferred, max_height=260) if inferred else None,
            detail_block("ProductEvidenceState JSON", pes, max_height=420),
        ],
        style={"marginTop": "8px"},
    )


def render_input_form(facts: dict | None = None) -> html.Div:
    facts = facts or {}
    return html.Div(
        [
            html.Div("입력", style=LABEL),
            html.Div(
                [
                    dcc.Input(
                        id="ipt-product-name",
                        type="text",
                        placeholder="제품명",
                        value=facts.get("product_name") or "",
                        style=INPUT,
                    ),
                    dcc.Textarea(
                        id="ipt-description",
                        placeholder="제품 설명 / 원재료 / OCR text / COI text",
                        value=facts.get("description") or "",
                        style=TEXTAREA,
                    ),
                    dcc.Input(
                        id="ipt-kurly-url",
                        type="text",
                        placeholder="URL",
                        value=facts.get("url") or "",
                        style={**INPUT, "marginBottom": "12px"},
                    ),
                    html.Div(
                        [
                            html.Button(
                                "Run pipeline",
                                id="btn-run",
                                n_clicks=0,
                                style={
                                    "padding": "10px 24px",
                                    "fontSize": "14px",
                                    "background": "#2563eb",
                                    "color": "white",
                                    "border": "none",
                                    "borderRadius": "8px",
                                    "cursor": "pointer",
                                    "fontWeight": 850,
                                },
                            ),
                        ],
                        style={"display": "flex", "alignItems": "center"},
                    ),
                ],
                style=CARD,
            ),
        ],
        style={"marginBottom": "20px"},
    )


def _event_summary(event: dict[str, Any]) -> html.Div | None:
    partial = event.get("partial_result") or {}
    bb = partial.get("blackboard") or {}
    stage = event.get("stage") or ""
    status = event.get("status") or ""

    if stage == "Input_Intake":
        raw = event.get("raw_input") or {}
        if not raw:
            return None
        return html.Div(
            [
                html.Div(f"product_name: {raw.get('product_name') or '-'}"),
                html.Div(f"description: {(raw.get('description') or '-')[:180]}"),
                html.Div(f"ocr_text chunks: {len(raw.get('ocr_text') or [])} / composition: {len(raw.get('composition') or [])}"),
                _text_list_block("raw OCR chunk", raw.get("ocr_text") or []),
                _text_list_block("raw composition/fact", raw.get("composition") or []),
                detail_block("raw_input JSON", raw, max_height=360),
            ],
            style={"fontSize": "12px", "color": "#334155", "marginTop": "6px"},
        )

    if stage == "Evidence_Intake_Agent":
        if status == "running":
            return html.Div(
                "Evidence_Intake_Agent 실행 전입니다. 완료 이벤트에서 실제 OCR/composition count를 표시합니다.",
                style={"fontSize": "12px", "color": "#64748b", "marginTop": "6px"},
            )
        pes = bb.get("product_evidence_state") or {}
        facts = pes.get("observed_facts") or {}
        inferred = pes.get("inferred_facts") or []
        return html.Div(
            [
                html.Div(f"product_id: {pes.get('product_id') or '-'}"),
                html.Div(f"observed: {facts.get('product_name') or '-'} / OCR {len(facts.get('ocr_text') or [])} chunks"),
                html.Div(f"inferred: {', '.join(str(x.get('fact_key')) + '=' + str(x.get('value')) for x in inferred[:4]) or '-'}"),
                html.Div(f"unknowns: {', '.join(pes.get('unknowns') or []) or '-'}"),
                evidence_detail_panel(pes),
            ],
            style={"fontSize": "12px", "color": "#334155", "marginTop": "6px"},
        )

    if stage == "Classification_Agent":
        if status == "running":
            return html.Div(
                "classifier retriever/LLM/TARIC branch resolver 실행 중입니다. 완료 이벤트에서 후보 수를 표시합니다.",
                style={"fontSize": "12px", "color": "#64748b", "marginTop": "6px"},
            )
        ccs = partial.get("candidate_code_set") or {}
        candidates = ccs.get("candidates") or []
        return html.Div(
            [
                html.Div(f"candidate_set: {ccs.get('candidate_set_id') or '-'} / {len(candidates)} candidates"),
                html.Ul(
                    [
                        html.Li(
                            f"#{c.get('rank')} CN8 {c.get('cn8')} -> TARIC10 {c.get('taric10') or '-'} "
                            f"({c.get('candidate_source') or 'classifier'}, conf={c.get('confidence')})"
                        )
                        for c in candidates[:6]
                    ],
                    style={"margin": "4px 0 0 18px", "padding": 0},
                ),
                detail_block("CandidateCodeSet JSON", ccs, max_height=420) if ccs else None,
            ],
            style={"fontSize": "12px", "color": "#334155", "marginTop": "6px"},
        )

    if stage == "Document_Agent":
        dp = partial.get("document_package") or {}
        if not dp:
            return None
        return html.Div(
            [
                html.Div(f"document_package: {dp.get('document_package_id') or '-'} / TARIC10 {dp.get('taric10') or '-'}"),
                html.Div(
                    "counts: customs {0}, required_docs {1}, regulations {2}, missing {3}".format(
                        len(dp.get("customs_check_items") or []),
                        len(dp.get("required_documents") or []),
                        len(dp.get("product_regulations") or []),
                        len(dp.get("missing_facts") or []),
                    )
                ),
                detail_block(
                    "DocumentPackage compact JSON",
                    {k: v for k, v in dp.items() if k != "raw_document_package"},
                    max_height=360,
                ),
            ],
            style={"fontSize": "12px", "color": "#334155", "marginTop": "6px"},
        )

    if stage == "Orchestrator_Agent":
        dec = partial.get("decision") or {}
        if not dec:
            return None
        return html.Div(
            [
                html.Div(f"decision: {dec.get('decision_status') or '-'}"),
                html.Div(f"selected: {', '.join(dec.get('selected_candidate_ids') or []) or '-'}"),
                html.Div(f"user_questions: {', '.join(dec.get('user_questions') or []) or '-'}"),
                detail_block("OrchestratorDecision JSON", dec, max_height=300),
            ],
            style={"fontSize": "12px", "color": "#334155", "marginTop": "6px"},
        )

    return None


def render_progress(result: dict[str, Any]) -> html.Div:
    status = result.get("job_status") or result.get("status") or "idle"
    events = result.get("events") or []
    rows = []
    for event in events[-18:]:
        st = event.get("status") or "running"
        color = "#166534" if st == "completed" else "#b91c1c" if st == "failed" else "#2563eb"
        bg = "#f0fdf4" if st == "completed" else "#fef2f2" if st == "failed" else "#eff6ff"
        rows.append(
            html.Div(
                [
                    html.Span(event.get("ts") or "", style={**MONO, "color": "#64748b", "marginRight": "8px"}),
                    html.Span(st.upper(), style={**PILL, "background": bg, "color": color}),
                    html.Span(event.get("stage") or "-", style={"fontWeight": 850}),
                    html.Div(event.get("message") or "", style={"fontSize": "12px", "color": "#334155", "marginTop": "4px"}),
                    _event_summary(event),
                    detail_block(
                        "stage event JSON",
                        {k: v for k, v in event.items() if k != "partial_result"},
                        max_height=260,
                    ),
                ],
                style={"padding": "8px 0", "borderBottom": "1px solid #eef2f7"},
            )
        )

    return html.Div(
        [
            html.Div(
                [
                    _small("job", status),
                    _small("run_id", result.get("run_id")),
                    _small("run_dir", result.get("run_dir")),
                    _small("agents", len(result.get("agent_results") or [])),
                ],
                style={"display": "flex", "gap": "10px", "flexWrap": "wrap", "marginBottom": "10px"},
            ),
            html.Div(rows or html.Div("아직 stage event가 없습니다.", style=PLACEHOLDER), style=CARD),
        ]
    )


def render_candidate_cards(result: dict[str, Any]) -> html.Div:
    ccs = result.get("candidate_code_set") or {}
    candidates = ccs.get("candidates") or []
    run_id = result.get("run_id") or "current"
    if not candidates:
        return html.Div("분류 후보가 없습니다.", style=PLACEHOLDER)

    cards = []
    for cand in candidates:
        taric10 = cand.get("taric10") or ""
        branches = cand.get("taric10_branch_candidates") or []
        href = f"/document/{run_id}/{taric10}" if taric10 else "#"
        cards.append(
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(f"rank {cand.get('rank')}", style=PILL),
                            html.Span(cand.get("candidate_source") or "classifier", style={**PILL, "background": "#f8fafc", "color": "#334155"}),
                            html.Span(cand.get("status") or "-", style={**PILL, "background": "#f0fdf4", "color": "#166534"}),
                        ],
                        style={"marginBottom": "8px"},
                    ),
                    html.Div(
                        [
                            _small("CN8", cand.get("cn8")),
                            _small("TARIC10", cand.get("taric10")),
                            _small("HS6", cand.get("hs6")),
                            _small("confidence", cand.get("confidence")),
                            _small("branches", len(branches)),
                        ],
                        style={"display": "flex", "gap": "10px", "flexWrap": "wrap"},
                    ),
                    html.Div(cand.get("selected_taric10_reason") or "", style={"fontSize": "12px", "color": "#64748b", "marginTop": "10px"}),
                    html.A(
                        "TARIC10 서류 상세 보기",
                        href=href,
                        style={
                            "display": "inline-block",
                            "marginTop": "12px",
                            "padding": "8px 12px",
                            "borderRadius": "8px",
                            "background": "#2563eb",
                            "color": "white",
                            "fontWeight": 850,
                            "textDecoration": "none",
                            "fontSize": "12px",
                        },
                    ) if taric10 else None,
                ],
                style={**CARD, "marginBottom": "10px", "borderLeft": "4px solid #2563eb"},
            )
        )
    return html.Div(cards)


def render_decision(result: dict[str, Any]) -> html.Div:
    dec = result.get("decision") or {}
    if not dec:
        return html.Div("최종 결정이 아직 없습니다.", style=PLACEHOLDER)

    # user-facing user questions (Orchestrator 가 만든 UserQuestion 객체에서 question 텍스트만 표시)
    bb = (result.get("blackboard") or {})
    user_questions = [
        q for q in (bb.get("user_questions") or [])
        if q.get("status") == "open" and q.get("question_id") in (dec.get("user_questions") or [])
    ]

    return html.Div(
        [
            html.Div(
                [
                    _small("decision", dec.get("decision_status")),
                    _small("selected", ", ".join(dec.get("selected_candidate_ids") or [])),
                    _small("packages", ", ".join(dec.get("document_package_ids") or [])),
                ],
                style={"display": "flex", "gap": "10px", "flexWrap": "wrap", "marginBottom": "10px"},
            ),
            html.Div(
                [
                    html.Div("추가 확인 필요", style={"fontSize": "13px", "fontWeight": 700, "marginBottom": "6px"}),
                    html.Ul(
                        [html.Li(q.get("question") or q.get("fact_key") or "") for q in user_questions],
                        style={"fontSize": "13px", "color": "#334155", "marginTop": 0},
                    ),
                ]
            ) if user_questions else html.Div("추가 확인 필요 없음", style={"fontSize": "13px", "color": "#166534"}),
        ],
        style=CARD,
    )


def render_page(result: dict[str, Any] | None = None) -> html.Div:
    result = result or {}
    run_id = result.get("run_id")
    return html.Div(
        [
            html.Div(
                [
                    html.H1("ASAP 수출 분류", style={"fontSize": "24px", "margin": 0}),
                    html.Div("URL / text / COI evidence -> CN8/TARIC10 후보 -> 서류 상세 연결", style={"fontSize": "12px", "color": "#64748b", "marginTop": "4px"}),
                    html.Div(
                        [
                            html.A("Admin log", href=f"/admin/{run_id}" if run_id else "/admin", style={"fontSize": "12px", "fontWeight": 850}),
                        ],
                        style={"marginTop": "8px"},
                    ),
                ],
                style={"borderBottom": "2px solid #2563eb", "paddingBottom": "12px", "marginBottom": "22px"},
            ),
            render_input_form(result.get("facts")),
            html.Div("진행 상태", style=LABEL),
            html.Div(render_progress(result) if result else html.Div("[Run] 버튼을 누르면 단계별 진행 상태가 표시됩니다.", style=PLACEHOLDER), id="out-progress"),
            html.Div("분류 결과", style={**LABEL, "marginTop": "22px"}),
            html.Div(render_candidate_cards(result) if result else html.Div("분류 결과가 여기에 표시됩니다.", style=PLACEHOLDER), id="out-classification"),
            html.Div("최종 결정", style={**LABEL, "marginTop": "22px"}),
            html.Div(render_decision(result) if result else html.Div("Orchestrator 결정이 여기에 표시됩니다.", style=PLACEHOLDER), id="out-decision"),
        ]
    )
