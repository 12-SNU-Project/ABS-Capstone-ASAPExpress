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

from dash import ALL, Dash, Input, Output, State, ctx, dcc, html, no_update

from agents.document_package import _dc_to_dict, get_document_package
from eu_export.app_config import LoadAppConfig
from ui.classification_dash import display_stage_name


APP_CONFIG = LoadAppConfig(PROJECT_ROOT)
RUNS_ROOT = APP_CONFIG.paths.ResolvePath(
    PROJECT_ROOT,
    APP_CONFIG.paths.blackboard_runs_root,
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

STATUS = {
    "required": ("필요", "#b91c1c", "#fef2f2"),
    "conditional": ("조건부", "#9a3412", "#fff7ed"),
    "pending": ("판단보류", "#475569", "#f8fafc"),
    "exempted": ("면제", "#166534", "#f0fdf4"),
}

CERT_LABELS = {
    "mandatory_certificate": "필수 서류",
    "national_document": "국가/국제 문서",
    "exemption_declaration": "신고 선언문",
    "preferential_origin": "우대 원산지 증빙",
    "import_license": "수입 라이선스",
    "other": "기타 코드",
    "unknown": "분류 미상",
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


def clean_code(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def is_taric_like(value: str) -> bool:
    text = (value or "").strip()
    if re.match(r"^(https?://|www\.)", text, flags=re.IGNORECASE):
        return False
    return bool(re.fullmatch(r"[\d\s.\-]+", text)) and len(clean_code(text)) >= 8


def fmt_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def parse_facts_json(facts_text: str) -> dict[str, Any]:
    text = facts_text or "{}"
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("facts JSON must be an object")
    return parsed


def status_badge(status: str) -> html.Span:
    label, color, bg = STATUS.get(status or "pending", ("검토", "#475569", "#f8fafc"))
    return html.Span(label, className="badge", style={"color": color, "backgroundColor": bg, "border": f"1px solid {color}33"})


def duty_rate(req: dict[str, Any] | None) -> str:
    if not req:
        return "없음"
    return (req.get("duty") or {}).get("rate") or "조건부"


def cert_color(category: str) -> str:
    if category in {"mandatory_certificate", "national_document", "import_license"}:
        return "#b91c1c"
    if category == "preferential_origin":
        return "#166534"
    if category == "exemption_declaration":
        return "#1d4ed8"
    return "#475569"


def cert_help(cert: dict[str, Any]) -> str:
    guidance = cert.get("guidance") or {}
    if guidance.get("certificate_description") or guidance.get("when_required"):
        return guidance.get("certificate_description") or guidance.get("when_required") or ""
    category = cert.get("category") or "unknown"
    role = {
        "mandatory_certificate": "C-code: TARIC 조건에서 요구되는 certificate/document 코드입니다.",
        "national_document": "N-code: 국가/국제 표준 문서 또는 관련 증빙 코드입니다.",
        "exemption_declaration": "Y-code: 통관 신고에 입력하는 declaration/waiver 코드입니다.",
        "preferential_origin": "U-code: 우대관세 또는 원산지 증빙 관련 코드입니다.",
        "import_license": "L-code: licence/authorisation 관련 코드입니다.",
    }.get(category, "TARIC certificate/declaration 코드입니다.")
    return f"{role} 코드별 세부 의미는 TARIC description 기준입니다: {cert.get('description') or 'description 없음'}"


def guidance_row(label: str, value: Any) -> html.Div | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return html.Div([html.Span(label + ": ", className="guidance-label"), html.Span(text)], className="guidance-row")


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


def _first_text(*values: Any) -> str:
    for value in values:
        text = _compact_text(value)
        if text:
            return text
    return ""


def _cert_kind_label(category: str) -> str:
    if category == "exemption_declaration":
        return "선언문"
    if category == "preferential_origin":
        return "우대 증빙"
    if category in {"mandatory_certificate", "national_document"}:
        return "증명서/서류"
    if category == "import_license":
        return "수입 라이선스"
    return "certificate/declaration 코드"


def _readable_evidence(guidance: dict[str, Any]) -> str:
    evidence = _compact_text(guidance.get("required_evidence"))
    if not evidence:
        return ""
    return ", ".join(part.strip() for part in re.split(r"[;,]", evidence) if part.strip())


def _cert_topic(cert: dict[str, Any], guidance: dict[str, Any]) -> str:
    title = _first_text(guidance.get("certificate_description"), cert.get("description"), guidance.get("guidance_title"))
    code = _compact_text(cert.get("code"))
    if title.lower().startswith((code or "").lower()):
        return title
    category = cert.get("category") or "unknown"
    topic = f"{code}는 {title}에 관한 {_cert_kind_label(category)}입니다." if title else cert_help(cert)
    evidence = _readable_evidence(guidance)
    if not evidence:
        return topic
    if category == "exemption_declaration":
        return f"{topic} {evidence} 확인 후 수입신고서의 declaration/supporting document code로 선언합니다."
    if category == "preferential_origin":
        return f"{topic} {evidence} 확인 후 우대관세 신청 시 원산지 증빙 코드와 문서번호를 신고서에 기재합니다."
    return f"{topic} {evidence} 확인 후 해당 증명서/문서번호를 수입신고 supporting document로 제출 또는 기재합니다."


def _certificate_content_label(category: str) -> str:
    return "선언문 내용" if category == "exemption_declaration" else "문서 내용"


def _certificate_content(cert: dict[str, Any], guidance: dict[str, Any]) -> str:
    category = cert.get("category") or "unknown"
    if category == "exemption_declaration":
        return _first_text(guidance.get("declaration_wording"), guidance.get("certificate_description"), cert.get("description"))
    return _first_text(guidance.get("certificate_description"), cert.get("description"), guidance.get("guidance_title"))


def _certificate_condition(cert: dict[str, Any], guidance: dict[str, Any]) -> str:
    category = cert.get("category") or "unknown"
    if category == "exemption_declaration":
        return _first_text(guidance.get("not_applicable_condition"), guidance.get("when_required"))
    return _first_text(guidance.get("when_required"), guidance.get("not_applicable_condition"))


def cert_guidance_detail(cert: dict[str, Any]) -> html.Details:
    guidance = cert.get("guidance") or {}
    rows = [
        guidance_row("설명", _cert_topic(cert, guidance)),
        guidance_row(_certificate_content_label(cert.get("category") or "unknown"), _certificate_content(cert, guidance)),
        guidance_row("해당 조건", _certificate_condition(cert, guidance)),
        guidance_row("근거", guidance.get("source_basis") or guidance.get("source_legal_bases") or cert.get("description")),
        guidance_row("CELEX", guidance.get("source_celex_ids")),
    ]
    rows = [row for row in rows if row is not None]
    if not rows:
        rows = [html.Div(cert_help(cert), className="cert-help")]
    return html.Details(
        [html.Summary("상세 설명"), html.Div(rows, className="cert-help")],
        className="cert-detail",
    )


def cert_card(cert: dict[str, Any]) -> html.Div:
    category = cert.get("category") or "unknown"
    color = cert_color(category)
    guidance = cert.get("guidance") or {}
    return html.Div(
        [
            html.Div(cert.get("code") or "", className="cert-code", style={"color": color}),
            html.Div(guidance.get("guidance_title") or cert.get("description") or "description 없음", className="cert-desc"),
            cert_guidance_detail(cert),
        ],
        className="cert",
        style={"borderLeftColor": color},
    )


def detail_card(detail: dict[str, Any], label: str, related_declarations: list[str] | None = None) -> html.Div:
    status = detail.get("decision_status") or "pending"
    _, color, _ = STATUS.get(status, ("검토", "#475569", "#f8fafc"))
    missing = ", ".join((detail.get("missing_facts") or [])[:5]) or "없음"
    facts = ", ".join((detail.get("required_facts") or [])[:5]) or "없음"
    declarations = ", ".join((related_declarations or [])[:5]) or ""
    lookups = detail.get("external_dataset_ids") or []
    lookup = None
    if lookups:
        lookup_label = "외부참조 필요" if detail.get("external_lookup_required") == "true" else "외부참조 조건부"
        lookup = html.Div(
            [
                html.B(lookup_label),
                html.Span(": " + ", ".join(lookups[:5])),
                html.Br(),
                html.Span(detail.get("external_lookup_mode") or detail.get("data_gap_status") or ""),
            ],
            className="lookup",
        )
    return html.Div(
        [
            html.Div([html.Span(f"{label} · {detail.get('required_level') or ''}", style={"color": color, "fontWeight": 950}), status_badge(status)]),
            html.Div(detail.get("required_document") or "문서명 없음", className="card-title", style={"marginTop": "5px"}),
            html.Div(f"{detail.get('domain_route') or detail.get('domain') or '-'} · {detail.get('requirement_type') or '-'}", className="card-meta"),
            html.Div([html.B("필요 facts: "), html.Span(facts)], className="card-meta", style={"color": "#334155"}),
            html.Div([html.B("관련 선언/면제: "), html.Span(declarations)], className="card-meta", style={"color": "#334155"}) if declarations else None,
            html.Div([html.B("누락: "), html.Span(missing)], className="card-meta", style={"color": "#9a3412"}),
            lookup,
        ],
        className="detail-card",
        style={"borderLeftColor": color},
    )


def metric(label: str, value: Any, color: str = "#111827", mono: bool = False) -> html.Div:
    return html.Div(
        [
            html.Div(label, className="metric-label"),
            html.Div(str(value), className="metric-value", style={"color": color, "fontFamily": "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" if mono else "inherit"}),
        ],
        className="metric",
    )


def node(kicker: str, value: Any, cls: str = "node-blue") -> html.Div:
    return html.Div([html.Div(kicker, className="node-kicker"), html.Div(str(value), className="node-main")], className=f"node {cls}")


def package_context(pkg: dict[str, Any]) -> dict[str, Any]:
    view_context = document_view_context(pkg)
    if view_context:
        return view_context
    return _unresolved_context(pkg)


def _unresolved_context(pkg: dict[str, Any]) -> dict[str, Any]:
    return {
        "kr": [],
        "non_kr": [],
        "controls": [],
        "duties": [],
        "base_duty_measures": [],
        "preferential_measures": [],
        "third_country": None,
        "fta_pref": None,
        "additional_duty": None,
        "groups": [],
        "counts": {},
        "missing": [],
        "product_reqs": [],
        "product_pre": [],
        "product_post": [],
        "related_declarations": {},
        "source": "unresolved",
        "_raw_package": pkg,
    }


def document_view_context(pkg: dict[str, Any]) -> dict[str, Any] | None:
    """Use DocumentAgent's view model when a pipeline package provides it.

    Direct TARIC lookup still falls back to raw package splitting. Pipeline
    detail pages should be display-only consumers of Document_Agent output.
    """
    view = pkg.get("_document_view") or pkg.get("document_view")
    if not isinstance(view, dict):
        return None
    sections = view.get("sections") or {}
    if not isinstance(sections, dict):
        return None

    overview = sections.get("overview") or {}
    customs = sections.get("customs_check_items") or {}
    basic = sections.get("basic_duty") or {}
    preferential = sections.get("preferential_evidence") or {}
    required_docs = sections.get("required_documents") or {}
    product = sections.get("product_regulations") or {}

    reqs = pkg.get("requirements") or []
    kr = [r for r in reqs if r.get("applies_to_korea")]
    non_kr = [r for r in reqs if not r.get("applies_to_korea")]
    controls = customs.get("render_bucket") or customs.get("agent_bucket") or []
    base_duty_measures = basic.get("render_bucket") or basic.get("agent_bucket") or []
    preferential_measures = preferential.get("render_bucket") or preferential.get("agent_bucket") or []
    groups = required_docs.get("document_groups") or []
    product_reqs = product.get("requirements") or []

    return {
        "kr": kr,
        "non_kr": non_kr,
        "controls": controls,
        "duties": list(base_duty_measures) + list(preferential_measures),
        "base_duty_measures": base_duty_measures,
        "preferential_measures": preferential_measures,
        "third_country": overview.get("third_country_duty"),
        "fta_pref": overview.get("fta_preference"),
        "additional_duty": overview.get("additional_duty"),
        "groups": groups,
        "counts": overview.get("counts") or {},
        "missing": overview.get("missing_facts") or [],
        "product_reqs": product_reqs,
        "product_pre": product.get("pre") or [],
        "product_post": product.get("post") or [],
        "related_declarations": product.get("related_declarations") or {},
        "document_view": view,
        "source": "document_view",
    }


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
                            {"label": " Blackboard log 표시", "value": "blackboard"},
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
    if not pkg:
        return "TARIC 코드를 입력하거나 좌측 예제를 선택하세요."
    if not pkg.get("has_data"):
        return html.Div("이 코드에 대한 현재 적용 measure가 없습니다.", className="empty")

    cx = package_context(pkg)
    if cx.get("source") == "unresolved":
        return render_unresolved(pkg, options or [])
    third_country = cx["third_country"]
    fta_pref = cx["fta_pref"]
    final_duty = fta_pref or third_country
    counts = cx["counts"]
    groups = cx["groups"]
    controls = cx["controls"]
    duties = cx["duties"]
    product_reqs = cx["product_reqs"]
    selected = panel or "overview"
    product_count = (
        len(cx.get("product_pre") or [])
        + len(cx.get("product_post") or [])
        or sum(len(r.get("detailed_requirements") or []) for r in product_reqs)
    )

    panel_defs = [
        ("overview", "전체 결론", "요약"),
        ("customs", "세관 확인사항", f"{len(controls)}건"),
        ("base_duty", "기본 관세", duty_rate(third_country)),
        ("preferential", "우대 증빙", duty_rate(fta_pref)),
        ("bundles", "요구서류", f"{len(groups)}묶음"),
        ("product", "제품 규제", f"{product_count}개"),
    ]

    children = [
        html.Div(
            [
                metric("TARIC10", pkg.get("taric10"), "#1d4ed8", True),
                metric("CN8", pkg.get("cn8"), "#1d4ed8", True),
                metric("최종 관세율 후보", duty_rate(final_duty), "#166534"),
                metric("KR measure", len(cx["kr"])),
                metric("필요 / 조건부", f"{counts.get('required', 0)} / {counts.get('conditional', 0)}", "#9a3412"),
                metric("판단보류", counts.get("pending", 0), "#475569"),
            ],
            className="metric-grid",
        ),
        html.Div(
            [
                html.Div(
                    [
                        node("CODE", pkg.get("taric10"), "node-blue"),
                        node("세관 확인사항", f"{len(controls)} control / {len(duties)} duty", "node-red"),
                        node("기본 관세", duty_rate(third_country), "node-amber"),
                        node("우대 증빙 시", duty_rate(fta_pref), "node-green"),
                        node("요구서류 묶음", f"{len(groups)} groups", "node-blue"),
                    ],
                    className="flow-grid",
                )
            ],
            className="flow",
        ),
        html.Div(
            [
                html.Button([html.Div(title), html.Div(sub, style={"fontSize": "11px", "fontWeight": 700, "marginTop": "3px"})], id={"type": "panel-btn", "panel": pid}, className=f"panel-btn {'active' if selected == pid else ''}")
                for pid, title, sub in panel_defs
            ],
            className="panel-buttons",
        ),
        html.Div(render_panel(pkg, selected, cx, options or []), className="panel"),
    ]
    return children


def render_unresolved(pkg: dict[str, Any], options: list[str]):
    taric10 = pkg.get("taric10") or "-"
    children = [
        html.Div(
            [
                html.Div("⚠ document_view missing", className="metric-label", style={"color": "#b91c1c"}),
                html.Div(
                    f"TARIC10 {taric10} 의 분류 결과를 받지 못했습니다.",
                    style={"fontSize": "15px", "fontWeight": 600, "marginTop": "6px"},
                ),
                html.Div(
                    "DocumentAgent 가 sections 을 채우지 못했거나, direct TARIC 조회로 pipeline 을 거치지 않았습니다. 관리자에게 pipeline 재실행을 요청하세요.",
                    style={"fontSize": "13px", "color": "#475569", "marginTop": "4px"},
                ),
            ],
            className="empty",
            style={"borderLeft": "4px solid #b91c1c", "padding": "16px"},
        ),
    ]
    if "admin" in (options or []) or "debug" in (options or []):
        children.append(
            html.Details(
                [
                    html.Summary("raw_document_package (admin debug)"),
                    html.Pre(
                        str(pkg)[:4000],
                        style={"fontSize": "11px", "color": "#334155", "whiteSpace": "pre-wrap"},
                    ),
                ],
                style={"marginTop": "16px"},
            )
        )
    return children


def render_panel(pkg: dict[str, Any], panel: str, cx: dict[str, Any], options: list[str]):
    if panel == "customs":
        return render_customs(pkg, cx["controls"])
    if panel == "base_duty":
        return render_base_duty(cx["base_duty_measures"])
    if panel == "preferential":
        return render_preferential(cx["preferential_measures"])
    if panel == "bundles":
        return render_bundles(cx["groups"])
    if panel == "product":
        return render_product_rules_from_view(
            cx.get("product_pre") or [],
            cx.get("product_post") or [],
            cx.get("related_declarations") or {},
        )
    return render_overview(cx, options, pkg)


def render_overview(cx: dict[str, Any], options: list[str], pkg: dict[str, Any]):
    missing = cx["missing"]
    items = [
        ("세관 확인사항", f"{len(cx['controls'])}개 control measure 확인"),
        ("관세 measure", f"{len(cx['duties'])}개 duty/preference measure 확인"),
        ("서류 묶음", f"{len(cx['groups'])}개 document group 검토"),
    ]
    left = html.Div(
        [
            html.Div("오늘 봐야 할 것", className="section-title"),
            *[
                html.Div([html.Div(title, className="card-title"), html.Div(body, className="card-meta")], className="card")
                for title, body in items
            ],
        ]
    )
    right = html.Div(
        [
            html.Div("남은 판단 facts", className="section-title"),
            html.Div(
                [html.Span(fact, className="chip") for fact in missing[:22]]
                if missing
                else html.Div("현재 상세 row 기준 추가 missing facts가 없습니다.", className="card-meta"),
                className="card",
            ),
        ]
    )
    raw = None
    if "raw" in options:
        raw = html.Details([html.Summary("Raw JSON"), html.Pre(json.dumps(pkg, ensure_ascii=False, indent=2), className="textarea")])
    blackboard = render_blackboard_log(pkg) if "blackboard" in options else None
    return html.Div([html.Div([left, right], className="two-col"), blackboard, raw])


def render_blackboard_log(pkg: dict[str, Any]) -> html.Div | None:
    pipeline = pkg.get("_pipeline") or {}
    if not pipeline:
        return html.Details(
            [
                html.Summary("Blackboard log"),
                html.Div("TARIC 직접조회 모드입니다. Agent pipeline log가 없습니다.", className="card-meta"),
            ]
        )

    summary = {
        "run_id": pipeline.get("run_id"),
        "run_dir": pipeline.get("run_dir"),
        "agent_results": pipeline.get("agent_results") or [],
        "decision": pipeline.get("decision") or {},
    }
    agent_runs = pipeline.get("agent_runs") or []
    candidate_set = pipeline.get("candidate_code_set") or {}
    document_package = pipeline.get("document_package") or {}
    compact_document_package = {
        key: value
        for key, value in document_package.items()
        if key != "raw_document_package"
    } if isinstance(document_package, dict) else document_package

    payload = {
        "summary": summary,
        "candidate_code_set": candidate_set,
        "document_package": compact_document_package,
        "agent_runs": agent_runs,
    }
    cards = []
    for run in agent_runs:
        cards.append(
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
        )
    return html.Details(
        [
            html.Summary("Blackboard log"),
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
                    html.Summary("Blackboard JSON"),
                    html.Pre(json.dumps(payload, ensure_ascii=False, indent=2), className="textarea"),
                ]
            ),
        ]
    )


def render_customs(pkg: dict[str, Any], controls: list[dict[str, Any]]):
    if not controls:
        return html.Div("별도 control measure가 없습니다.", className="card-meta")
    rows = []
    for req in controls:
        certs = req.get("certificates") or []
        rows.append(
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(pkg.get("taric10"), className="card-title", style={"fontFamily": "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace", "color": "#1d4ed8"}),
                            html.Div(f"CN8 {pkg.get('cn8')}", className="card-meta"),
                        ],
                        className="card",
                    ),
                    html.Div(
                        [
                            html.Div(req.get("measure_type"), className="card-title"),
                            html.Div(f"legal: {req.get('legal_base') or 'N/A'}", className="card-meta"),
                            html.Div(f"source: {', '.join((req.get('source_goods_codes') or [])[:3])}", className="card-meta"),
                        ],
                        className="card",
                        style={"borderLeft": "4px solid #b91c1c"},
                    ),
                    html.Div([cert_card(c) for c in certs] or html.Div("별도 certificate/declaration code 없음", className="card-meta")),
                ],
                className="three-col",
            )
        )
    return html.Div([html.Div("세관 확인사항: measure -> certificate/declaration", className="section-title"), *rows])


def render_base_duty(reqs: list[dict[str, Any]]):
    if not reqs:
        return html.Div("현재 조회 결과에 기본 관세 measure가 없습니다.", className="card-meta")
    return html.Div(
        [
            html.Div("기본 관세 적용 및 관련 서류", className="section-title"),
            *[
                html.Div(
                    [
                        html.Div(req.get("measure_type"), className="card-title"),
                        html.Div(duty_rate(req), style={"fontSize": "24px", "fontWeight": 950, "color": "#9a3412", "marginTop": "3px"}),
                        html.Div(f"legal: {req.get('legal_base') or 'N/A'} · origin: {', '.join((req.get('origins') or [])[:4])}", className="card-meta"),
                        html.Div(
                            [cert_card(c) for c in (req.get("certificates") or [])]
                            or html.Div("이 관세 measure에는 별도 certificate/declaration code가 없습니다.", className="card-meta"),
                            style={"marginTop": "10px"},
                        ),
                    ],
                    className="card",
                    style={"background": "#fff7ed", "borderLeft": "4px solid #9a3412"},
                )
                for req in reqs
            ],
        ]
    )


def render_preferential(reqs: list[dict[str, Any]]):
    if not reqs:
        return html.Div("현재 조회 결과에 우대 관세 measure가 없습니다.", className="card-meta")
    return html.Div(
        [
            html.Div("우대 관세와 원산지 증빙", className="section-title"),
            *[
                html.Div(
                    [
                        html.Div(req.get("measure_type"), className="card-title"),
                        html.Div(duty_rate(req), style={"fontSize": "24px", "fontWeight": 950, "color": "#166534", "marginTop": "3px"}),
                        html.Div(f"legal: {req.get('legal_base') or 'N/A'} · origin: {', '.join((req.get('origins') or [])[:4])}", className="card-meta"),
                        html.Div(
                            [cert_card(c) for c in (([c for c in (req.get("certificates") or []) if c.get("category") == "preferential_origin"] or (req.get("certificates") or [])))]
                            or html.Div("이 우대 관세 measure에는 별도 certificate/declaration code가 없습니다.", className="card-meta"),
                            style={"marginTop": "10px"},
                        ),
                    ],
                    className="card",
                    style={"background": "#f0fdf4", "borderLeft": "4px solid #166534"},
                )
                for req in reqs
            ],
        ]
    )


def render_bundles(groups: list[dict[str, Any]]):
    if not groups:
        return html.Div("요구서류 묶음이 없습니다.", className="card-meta")
    cards = []
    for group in groups[:24]:
        doc_items = (group.get("documents") or [])[:6]
        declaration_items = (group.get("declarations") or [])[:6]
        docs = ", ".join(doc_items) or "없음"
        declarations = ", ".join(declaration_items) or "없음"
        needed_names = doc_items or declaration_items or [group.get("group_name") or "필요서류"]
        missing_facts = group.get("missing_facts") or []
        missing = (
            f"해당서류 없음({', '.join(needed_names[:3])})"
            + (f" · 확인 필요 facts: {', '.join(missing_facts[:4])}" if missing_facts else "")
            if missing_facts
            else "없음"
        )
        lookups = ", ".join((group.get("external_dataset_ids") or [])[:6]) or "없음"
        cards.append(
            html.Div(
                [
                    html.Div([html.Span(group.get("group_name") or "문서 묶음", className="card-title"), status_badge(group.get("status") or "pending")]),
                    html.Div([html.B("준비 서류: "), docs], className="card-meta", style={"color": "#334155"}),
                    html.Div([html.B("선언/면제: "), declarations], className="card-meta", style={"color": "#334155"}),
                    html.Div([html.B("missing: "), missing], className="card-meta", style={"color": "#9a3412"}),
                    html.Div([html.B("외부참조: "), lookups], className="card-meta", style={"color": "#7c2d12"}),
                ],
                className="card",
            )
        )
    return html.Div([html.Div("요구서류 묶음", className="section-title"), html.Div(cards, className="two-col")])


def render_product_rules_from_view(
    pre: list[dict[str, Any]],
    post: list[dict[str, Any]],
    related_declarations: dict[str, list[str]],
):
    pre_col = html.Div(
        [
            html.Div([html.Div("Pre / domain-router 후보", className="card-title"), html.Div(f"CN chapter 기준으로 열리는 제품 규제 후보 · {len(pre)}개", className="card-meta")], className="card", style={"borderLeft": "4px solid #475569"}),
            *[
                detail_card(d, "pre 후보", related_declarations.get(d.get("domain_route") or d.get("domain") or "", []))
                for d in pre[:16]
            ],
        ]
    )
    post_col = html.Div(
        [
            html.Div([html.Div("Post / domain 상세", className="card-title"), html.Div(f"domain route 이후 준비/누락/보류 판단 항목 · {len(post)}개", className="card-meta")], className="card", style={"borderLeft": "4px solid #166534", "background": "#f0fdf4"}),
            *[
                detail_card(d, "post 상세", related_declarations.get(d.get("domain_route") or d.get("domain") or "", []))
                for d in post[:22]
            ],
        ]
    )
    return html.Div([html.Div("제품 규제 체크리스트", className="section-title"), html.Div([pre_col, post_col], className="two-col")])


def _load_pipeline_payload(run_id: str | None) -> dict[str, Any]:
    if not run_id:
        return {}
    run_dir = RUNS_ROOT / run_id
    blackboard_path = run_dir / "blackboard.json"
    agent_runs_path = run_dir / "agent_runs.jsonl"
    payload: dict[str, Any] = {"run_id": run_id, "run_dir": str(run_dir)}
    if blackboard_path.exists():
        payload["blackboard"] = json.loads(blackboard_path.read_text(encoding="utf-8"))
    if agent_runs_path.exists():
        agent_runs = []
        for line in agent_runs_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                agent_runs.append(json.loads(line))
            except json.JSONDecodeError:
                agent_runs.append({"raw": line})
        payload["agent_runs"] = agent_runs
    return payload


def load_package_for_detail(run_id: str | None, taric10: str, *, include_celex_excerpt: bool = False) -> dict[str, Any]:
    """Read the precomputed package from blackboard; resolve directly only as fallback."""
    code = clean_code(taric10)
    pipeline = _load_pipeline_payload(run_id)
    blackboard = pipeline.get("blackboard") or {}
    document_packages = blackboard.get("document_packages") or []
    for dp in document_packages:
        if clean_code(dp.get("taric10") or "") != code:
            continue
        raw = dp.get("raw_document_package")
        if isinstance(raw, dict):
            package = dict(raw)
            if isinstance(dp.get("document_view"), dict):
                package["_document_view"] = dp.get("document_view")
            package["_pipeline"] = {
                "run_id": pipeline.get("run_id"),
                "run_dir": pipeline.get("run_dir"),
                "agent_results": [],
                "agent_runs": pipeline.get("agent_runs") or [],
                "candidate_code_set": (blackboard.get("candidate_code_sets") or [None])[-1],
                "document_package": {k: v for k, v in dp.items() if k != "raw_document_package"},
                "decision": (blackboard.get("orchestrator_decisions") or [None])[-1],
            }
            return package

    package = get_document_package(code, include_celex_excerpt=include_celex_excerpt)
    package_data = _dc_to_dict(package)
    package_data["_pipeline"] = pipeline
    return package_data


def render_detail_page(run_id: str | None, taric10: str, panel: str = "overview", options: list[str] | None = None) -> html.Div:
    options = options or ["blackboard"]
    try:
        package = load_package_for_detail(run_id, taric10, include_celex_excerpt="celex" in options)
    except Exception as exc:  # noqa: BLE001
        return html.Div(
            [
                html.A("← 분류 화면", href="/classification", className="subtle"),
                html.Div(f"서류 패키지 조회 오류: {exc}", className="error"),
            ],
            className="main",
        )

    return html.Div(
        [
            html.Div(
                [
                    html.A("← 분류 화면", href="/classification", className="subtle"),
                    html.Span(" · ", className="subtle"),
                    html.A("Admin log", href=f"/admin/{run_id}" if run_id else "/admin", className="subtle"),
                ],
                style={"marginBottom": "12px"},
            ),
            html.Div(
                [
                    html.H2("EU 수출 서류 패키지", className="title"),
                    html.Div(
                        f"run_id {run_id or '-'} · TARIC10 {clean_code(taric10) or '-'}",
                        className="caption",
                    ),
                ],
                style={"marginBottom": "14px"},
            ),
            html.Div(render_result(package, panel or "overview", options), id="document-result-root"),
        ],
        className="main",
    )


if __name__ == "__main__":
    dash_host = os.getenv("ASAP_DASH_HOST", "127.0.0.1")
    dash_port = _select_port(dash_host, _preferred_port())
    app.run(host=dash_host, port=dash_port, debug=False)
