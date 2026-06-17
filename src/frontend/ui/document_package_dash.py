"""
Dash UI - EU import document package workbench.

Run:
    PYTHONPATH=src python -m ui.document_package_dash

Open:
    http://127.0.0.1:8050

Optional:
    ASAP_DASH_PORT=8051 PYTHONPATH=src python -m ui.document_package_dash
"""
from __future__ import annotations

import json
import os
import re
import socket
import sys
from errno import EADDRINUSE
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(os.environ.get("ASAP_PROJECT_ROOT", Path(__file__).resolve().parents[2])).resolve()
for _path in (PROJECT_ROOT, PROJECT_ROOT / "src"):
    if _path.exists() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from dash import ALL, MATCH, Dash, Input, Output, State, ctx, dcc, html, no_update

from agents.document_package import _dc_to_dict, get_document_package
from frontend.ui.document_package_renderer import (
    BuildDocumentPackageContext,
    CleanCode,
    RenderDocumentPackageResult,
    RenderScenarioDecision,
)


EXAMPLES: list[tuple[str, str, dict[str, Any]]] = [
    ("0101210000", "말, 순종번식용", {"product_category": "live_animal", "animal_origin": True, "species": "horse"}),
    ("1605290000", "새우 prepared", {"product_category": "fishery", "fishery_product": True, "species": "shrimp"}),
    ("1902301000", "Pasta/Noodle", {"product_category": "food", "ingredient_list": ["wheat flour"], "intended_use": "human food"}),
    ("2103909000", "Sauces", {"product_category": "food", "intended_use": "human food"}),
    ("3304990000", "스킨케어", {"product_category": "cosmetic", "intended_use": "skin care", "full_ingredient_list": ["water"]}),
    ("0202203083", "Bovine forequarter", {"product_category": "animal_origin_food", "animal_origin": True, "species": "bovine"}),
]

DEFAULT_FACTS: dict[str, Any] = {
    "origin_country": "KR",
    "destination_market": "EU",
    "product_category": "unknown",
    "organic_claim": "unknown",
    "animal_origin": "unknown",
    "species": "unknown",
    "species_scientific_name": "unknown",
    "gmo_present": "unknown",
}

EXAMPLE_FACTS = {
    code: {**DEFAULT_FACTS, **facts, "origin_country": "KR", "destination_market": "EU"}
    for code, _, facts in EXAMPLES
}

app = Dash(__name__, suppress_callback_exceptions=True)
server = app.server


def _preferred_port(default: int = 8050) -> int:
    raw = os.getenv("ASAP_DASH_PORT") or os.getenv("PORT")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"Invalid ASAP_DASH_PORT/PORT value {raw!r}; falling back to {default}.")
        return default


def _port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError as exc:
            if exc.errno != EADDRINUSE:
                raise
            return False
    return True


def _select_port(host: str, preferred: int) -> int:
    if _port_available(host, preferred):
        return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        fallback = int(sock.getsockname()[1])
    print(f"Port {preferred} is already in use; starting Dash on {host}:{fallback} instead.")
    return fallback


app.index_string = """
<!DOCTYPE html>
<html>
  <head>
    {%metas%}
    <title>ASAP EU Document Package</title>
    {%favicon%}
    {%css%}
    <style>
      :root {
        --bg: #f5f7fb;
        --panel: #ffffff;
        --line: #e5e7eb;
        --muted: #64748b;
        --text: #111827;
        --blue: #2563eb;
        --red: #b91c1c;
        --green: #166534;
        --amber: #9a3412;
      }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        background: var(--bg);
        color: var(--text);
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }
      .shell { display: flex; min-height: 100vh; }
      .sidebar {
        width: 314px;
        flex: 0 0 314px;
        background: #ffffff;
        border-right: 1px solid var(--line);
        padding: 28px 22px;
        overflow-y: auto;
      }
      .main {
        flex: 1;
        min-width: 0;
        padding: 28px 34px 42px;
        overflow-y: auto;
      }
      .brand { font-size: 22px; font-weight: 900; letter-spacing: -0.01em; margin: 0 0 6px; }
      .subtle { color: var(--muted); font-size: 12px; line-height: 1.45; }
      .divider { height: 1px; background: var(--line); margin: 22px 0; }
      .label { font-size: 11px; font-weight: 850; color: #475569; margin: 12px 0 7px; }
      .input {
        width: 100%;
        border: 1px solid #cbd5e1;
        border-radius: 9px;
        padding: 12px 13px;
        font-size: 14px;
        background: #ffffff;
        color: var(--text);
      }
      .textarea {
        width: 100%;
        min-height: 160px;
        border: 1px solid #cbd5e1;
        border-radius: 9px;
        padding: 10px 11px;
        font-size: 12px;
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        background: #ffffff;
        color: var(--text);
      }
      button {
        font-family: inherit;
      }
      .primary-btn {
        width: 100%;
        border: 1px solid var(--blue);
        border-radius: 9px;
        background: var(--blue);
        color: #ffffff;
        font-weight: 900;
        padding: 12px 13px;
        cursor: pointer;
      }
      .example-btn {
        width: 100%;
        border: 1px solid var(--line);
        border-radius: 9px;
        background: #ffffff;
        color: var(--text);
        padding: 12px 13px;
        margin-bottom: 9px;
        text-align: left;
        cursor: pointer;
      }
      .example-btn:hover { border-color: var(--blue); box-shadow: 0 0 0 2px rgba(37,99,235,0.08); }
      .example-code { font-size: 14px; font-weight: 900; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
      .example-label { font-size: 12px; color: #475569; margin-top: 3px; }
      .topbar {
        display: grid;
        grid-template-columns: minmax(280px, 1fr) 132px;
        gap: 10px;
        align-items: center;
        margin-bottom: 14px;
      }
      .title { font-size: 25px; font-weight: 950; letter-spacing: -0.02em; margin: 0; }
      .caption { color: var(--muted); font-size: 12px; margin-top: 5px; }
      .metric-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
        gap: 9px;
        margin: 12px 0 10px;
      }
      .metric {
        background: #ffffff;
        border: 1px solid var(--line);
        border-radius: 9px;
        padding: 11px 12px;
        min-height: 70px;
      }
      .metric-label { font-size: 10px; color: var(--muted); font-weight: 900; }
      .metric-value { font-size: 19px; color: var(--text); font-weight: 950; margin-top: 4px; overflow-wrap: anywhere; }
      .flow {
        background: #ffffff;
        border: 1px solid var(--line);
        border-radius: 12px;
        padding: 16px;
        margin: 10px 0 12px;
        box-shadow: 0 1px 2px rgba(15,23,42,0.04);
      }
      .flow-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
        gap: 10px;
      }
      .node {
        border: 1px solid var(--line);
        border-radius: 10px;
        padding: 11px 12px;
        background: #ffffff;
        min-height: 76px;
      }
      .node-kicker { font-size: 10px; color: var(--muted); font-weight: 900; }
      .node-main { font-size: 15px; color: var(--text); font-weight: 950; margin-top: 5px; overflow-wrap: anywhere; }
      .node-blue { border-left: 4px solid var(--blue); }
      .node-red { border-left: 4px solid var(--red); }
      .node-amber { border-left: 4px solid var(--amber); background: #fff7ed; }
      .node-green { border-left: 4px solid var(--green); background: #f0fdf4; }
      .panel-buttons {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(142px, 1fr));
        gap: 8px;
        margin: 12px 0;
      }
      .panel-btn {
        min-height: 58px;
        border: 1px solid #cbd5e1;
        background: #ffffff;
        color: var(--text);
        border-radius: 9px;
        padding: 10px 11px;
        text-align: left;
        font-weight: 900;
        line-height: 1.24;
        cursor: pointer;
      }
      .panel-btn:hover { border-color: var(--blue); color: #1d4ed8; }
      .panel-btn.active { background: var(--blue); border-color: var(--blue); color: #ffffff; }
      .panel {
        background: #ffffff;
        border: 1px solid var(--line);
        border-radius: 12px;
        padding: 16px;
        margin-top: 10px;
      }
      .section-title { font-size: 15px; color: var(--text); font-weight: 950; margin-bottom: 10px; }
      .card {
        background: #ffffff;
        border: 1px solid var(--line);
        border-radius: 9px;
        padding: 11px 12px;
        margin-bottom: 9px;
      }
      .card-title { font-size: 13px; font-weight: 950; color: var(--text); }
      .card-meta { font-size: 11px; color: var(--muted); margin-top: 4px; line-height: 1.4; }
      .two-col { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
      .three-col { display: grid; grid-template-columns: 1fr 1.25fr 1.7fr; gap: 10px; align-items: start; }
      .scenario-shell {
        border: 1px solid var(--line);
        border-radius: 12px;
        background: #ffffff;
        padding: 14px;
        margin-bottom: 14px;
      }
      .scenario-head {
        display: grid;
        grid-template-columns: minmax(150px, 0.75fr) minmax(260px, 1.25fr);
        gap: 12px;
        align-items: stretch;
      }
      .scenario-code {
        border: 1px solid var(--line);
        border-left: 4px solid var(--blue);
        border-radius: 10px;
        padding: 12px;
        background: #f8fafc;
      }
      .scenario-checks {
        border: 1px solid var(--line);
        border-radius: 10px;
        padding: 10px 12px;
        background: #ffffff;
      }
      .scenario-checks label {
        display: block;
        margin: 7px 0;
        font-size: 12px;
        font-weight: 850;
        color: #334155;
      }
      .scenario-checks input { margin-right: 8px; }
      .scenario-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 10px;
        margin-top: 12px;
      }
      .scenario-card {
        border: 1px solid var(--line);
        border-left: 4px solid #475569;
        border-radius: 10px;
        padding: 12px;
        background: #ffffff;
        min-height: 164px;
      }
      .scenario-card.green { border-left-color: var(--green); background: #f0fdf4; }
      .scenario-card.amber { border-left-color: var(--amber); background: #fff7ed; }
      .scenario-card.red { border-left-color: var(--red); background: #fef2f2; }
      .scenario-duty {
        font-size: 28px;
        line-height: 1.05;
        letter-spacing: 0;
        font-weight: 950;
        margin-top: 7px;
      }
      .scenario-actions {
        margin: 9px 0 0;
        padding-left: 18px;
        color: #374151;
        font-size: 11px;
        line-height: 1.4;
      }
      .scenario-window {
        border: 1px solid #dbe3ef;
        border-radius: 10px;
        background: rgba(255,255,255,0.78);
        margin-top: 12px;
        overflow: hidden;
      }
      .scenario-window-head {
        display: flex;
        justify-content: space-between;
        gap: 10px;
        align-items: center;
        border-bottom: 1px solid #e5e7eb;
        padding: 9px 10px;
        background: #f8fafc;
      }
      .scenario-window-title { font-size: 12px; font-weight: 950; color: #111827; }
      .scenario-window-count { font-size: 10px; font-weight: 900; color: #64748b; }
      .scenario-window-body { padding: 9px 10px 10px; }
      .scenario-doc-row {
        display: grid;
        grid-template-columns: minmax(140px, 1fr) auto;
        gap: 8px;
        align-items: start;
        padding: 7px 0;
        border-bottom: 1px solid #edf2f7;
      }
      .scenario-doc-row:last-child { border-bottom: 0; }
      .scenario-doc-name { font-size: 12px; font-weight: 900; color: #111827; }
      .scenario-doc-code {
        font-size: 10px;
        color: #64748b;
        font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        margin-top: 2px;
      }
      .scenario-doc-meta { font-size: 10px; color: #64748b; line-height: 1.35; margin-top: 2px; }
      .scenario-detail summary {
        color: #1d4ed8;
        font-size: 11px;
        font-weight: 900;
      }
      .scenario-doc-fields {
        margin-top: 7px;
        padding: 7px;
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        background: #ffffff;
      }
      .scenario-field-row {
        padding: 5px 0;
        border-bottom: 1px solid #edf2f7;
        font-size: 10px;
        color: #475569;
      }
      .scenario-field-row:last-child { border-bottom: 0; }
      .badge {
        display: inline-block;
        padding: 2px 7px;
        border-radius: 999px;
        font-size: 10px;
        font-weight: 900;
        margin-left: 6px;
      }
      .chip {
        display: inline-block;
        margin: 0 6px 6px 0;
        padding: 5px 8px;
        border-radius: 999px;
        border: 1px solid var(--line);
        background: #ffffff;
        color: #334155;
        font-size: 11px;
      }
      .cert {
        background: #ffffff;
        border: 1px solid var(--line);
        border-left: 4px solid #475569;
        border-radius: 9px;
        padding: 9px 10px;
        margin-bottom: 8px;
      }
      .cert-code { font-size: 13px; font-weight: 950; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
      .cert-desc { font-size: 11px; color: #334155; margin-top: 3px; line-height: 1.38; }
      .cert-help {
        background: #f8fafc;
        border: 1px solid var(--line);
        border-radius: 7px;
        padding: 7px;
        font-size: 10px;
        color: #334155;
        margin-top: 7px;
        line-height: 1.35;
      }
      .cert-detail summary {
        cursor: pointer;
        color: #1d4ed8;
        font-size: 11px;
        font-weight: 850;
        margin-top: 8px;
      }
      .cert-detail[open] summary { margin-bottom: 7px; }
      .guidance-row { margin-top: 6px; }
      .guidance-label { font-weight: 900; color: #111827; }
      .detail-card {
        border: 1px solid var(--line);
        border-left: 4px solid #475569;
        border-radius: 9px;
        padding: 10px 11px;
        margin-bottom: 9px;
        background: #ffffff;
      }
      .lookup {
        background: #fff7ed;
        border: 1px solid #fed7aa;
        color: #7c2d12;
        border-radius: 7px;
        padding: 7px;
        margin-top: 7px;
        font-size: 10px;
        line-height: 1.35;
      }
      details {
        margin-top: 12px;
      }
      summary {
        cursor: pointer;
        color: #334155;
        font-size: 12px;
        font-weight: 900;
      }
      .error {
        background: #fef2f2;
        border: 1px solid #fecaca;
        color: #7f1d1d;
        border-radius: 9px;
        padding: 10px 12px;
        margin-top: 10px;
        font-size: 12px;
        font-weight: 800;
      }
      .empty {
        background: #ffffff;
        border: 1px dashed #cbd5e1;
        border-radius: 12px;
        padding: 24px;
        color: #475569;
        font-size: 13px;
      }
      a { color: #1d4ed8; text-decoration: none; font-weight: 850; }
      a:hover { text-decoration: underline; }
      @media (max-width: 980px) {
        .shell { display: block; }
        .sidebar { width: auto; border-right: 0; border-bottom: 1px solid var(--line); }
        .main { padding: 22px 18px 32px; }
        .topbar { grid-template-columns: 1fr; }
        .two-col, .three-col { grid-template-columns: 1fr; }
      }
    </style>
  </head>
  <body>
    {%app_entry%}
    <footer>{%config%}{%scripts%}{%renderer%}</footer>
  </body>
</html>
"""


def is_taric_like(value: str) -> bool:
    text = (value or "").strip()
    if re.match(r"^(https?://|www\.)", text, flags=re.IGNORECASE):
        return False
    return bool(re.fullmatch(r"[\d\s.\-]+", text)) and len(CleanCode(text)) >= 8


def fmt_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def parse_facts_json(facts_text: str) -> dict[str, Any]:
    text = facts_text or "{}"
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("facts JSON must be an object")
    return parsed


def render_shell() -> html.Div:
    return html.Div(
        [
            dcc.Store(id="package-store"),
            dcc.Store(id="panel-store", data="overview"),
            html.Aside(
                [
                    html.H1("ASAP 서류 패키지", className="brand"),
                    html.Div("TARIC10 기준 EU 수입 관세/서류/제품규제 확인", className="subtle"),
                    html.Div(className="divider"),
                    html.Div("예제", className="label"),
                    html.Div(
                        [
                            html.Button(
                                [html.Div(code, className="example-code"), html.Div(label, className="example-label")],
                                id={"type": "example-btn", "code": code},
                                className="example-btn",
                            )
                            for code, label, _ in EXAMPLES
                        ]
                    ),
                    html.Div(className="divider"),
                    html.Details(
                        [
                            html.Summary("Product facts JSON"),
                            dcc.Textarea(id="facts-input", value=fmt_json(DEFAULT_FACTS), className="textarea"),
                        ]
                    ),
                    html.Div(className="divider"),
                    dcc.Checklist(
                        id="options",
                        options=[
                            {"label": " CELEX 본문 발췌 포함", "value": "celex"},
                            {"label": " 한국 무관 measure 표시", "value": "nonkr"},
                            {"label": " Raw JSON 표시", "value": "raw"},
                            {"label": " Debug pipeline log 표시", "value": "debug"},
                        ],
                        value=[],
                        className="subtle",
                    ),
                ],
                className="sidebar",
            ),
            html.Main(
                [
                    html.Div([html.H2("EU 수출 서류 패키지", className="title"), html.Div("기본 화면은 결론만, 세부 설명은 카드 클릭으로 확인합니다.", className="caption")]),
                    html.Div(
                        [
                            dcc.Input(id="code-input", value="", placeholder="TARIC 코드 입력", className="input"),
                            html.Button("조회", id="search-btn", className="primary-btn"),
                        ],
                        className="topbar",
                    ),
                    html.Div(id="error-box"),
                    html.Div(id="result-root", className="empty", children="TARIC 코드를 입력하거나 좌측 예제를 선택하세요."),
                ],
                className="main",
            ),
        ],
        className="shell",
    )


app.layout = render_shell


@app.callback(
    Output("package-store", "data"),
    Output("error-box", "children"),
    Output("code-input", "value"),
    Output("facts-input", "value"),
    Output("panel-store", "data"),
    Input("search-btn", "n_clicks"),
    Input({"type": "example-btn", "code": ALL}, "n_clicks"),
    State("code-input", "value"),
    State("facts-input", "value"),
    State("options", "value"),
    prevent_initial_call=True,
)
def load_package(_search_clicks, _example_clicks, code_value, facts_text, options):
    triggered = ctx.triggered_id
    if isinstance(triggered, dict) and triggered.get("type") == "example-btn":
        code = triggered["code"]
        facts = EXAMPLE_FACTS.get(code, DEFAULT_FACTS)
        facts_text = fmt_json(facts)
    else:
        code = code_value or ""
        try:
            facts = parse_facts_json(facts_text or "{}")
        except Exception as exc:
            return no_update, html.Div(f"Product facts JSON 오류: {exc}", className="error"), no_update, no_update, no_update

    try:
        if not is_taric_like(code):
            return no_update, html.Div("TARIC 코드를 입력하세요.", className="error"), code, facts_text, no_update
        package = get_document_package(
            code,
            include_celex_excerpt="celex" in (options or []),
            product_facts=facts,
        )
        package_data = _dc_to_dict(package)
        display_code = package.taric10
    except Exception as exc:
        return no_update, html.Div(f"조회 오류: {exc}", className="error"), code, facts_text, no_update

    return package_data, None, display_code, facts_text, "overview"


@app.callback(
    Output("panel-store", "data", allow_duplicate=True),
    Input({"type": "panel-btn", "panel": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def select_panel(_clicks):
    triggered = ctx.triggered_id
    if isinstance(triggered, dict) and triggered.get("type") == "panel-btn":
        return triggered.get("panel") or "overview"
    return no_update


@app.callback(
    Output("result-root", "children"),
    Input("package-store", "data"),
    Input("panel-store", "data"),
    Input("options", "value"),
)
def render_result(pkg, panel, options):
    return RenderDocumentPackageResult(pkg, panel, options or [])


@app.callback(
    Output({"type": "scenario-result", "taric": MATCH}, "children"),
    Input({"type": "scenario-checks", "taric": MATCH}, "value"),
    State("package-store", "data"),
)
def update_scenario_decision(selected_values, pkg):
    if not pkg:
        return no_update
    cx = BuildDocumentPackageContext(pkg)
    if cx.get("source") == "unresolved":
        return no_update
    return RenderScenarioDecision(pkg, cx, selected_values or [])



if __name__ == "__main__":
    dash_host = os.getenv("ASAP_DASH_HOST", "127.0.0.1")
    dash_port = _select_port(dash_host, _preferred_port())
    app.run(host=dash_host, port=dash_port, debug=False)
