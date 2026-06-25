"""Shared document package rendering implementation."""

from __future__ import annotations

import json
import re
from typing import Any

import dash_mantine_components as dmc
from dash import dcc, html

from frontend.ui.document_package_debug import render_debug_pipeline_log


STATUS = {
    "required": ("필요", "#b91c1c", "#fef2f2"),
    "conditional": ("조건부", "#9a3412", "#fff7ed"),
    "pending": ("판단보류", "#475569", "#f8fafc"),
    "exempted": ("면제", "#166534", "#f0fdf4"),
}

OVERVIEW_PANEL_ID = "overview"
DRAWER_PANEL_IDS = {"scenario", "bundles"}


def CleanCode(value: str) -> str:
    return re.sub(r"\D", "", value or "")


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


def _is_control_measure(req: dict[str, Any]) -> bool:
    measure_type = req.get("measure_type") or ""
    return any(
        key in measure_type
        for key in (
            "Import control",
            "Import restriction",
            "Veterinary",
            "CITES",
            "GMO",
            "Phytosanitary",
            "REACH",
        )
    ) or any(
        key in measure_type.lower()
        for key in ("fishing", "luxury", "sanction", "restriction", "surveillance", "control")
    )


def _is_preferential_measure(req: dict[str, Any]) -> bool:
    measure_type = req.get("measure_type") or ""
    return any(key in measure_type for key in ("Tariff preference", "Customs Union", "Preferential"))


def _is_duty_measure(req: dict[str, Any]) -> bool:
    measure_type = req.get("measure_type") or ""
    return any(key in measure_type for key in ("duty", "Duty", "Tariff", "Preference", "Preferential", "Customs Union", "Supplementary"))


def _is_base_duty_measure(req: dict[str, Any]) -> bool:
    if _is_preferential_measure(req):
        return False
    measure_type = req.get("measure_type") or ""
    return any(key in measure_type for key in ("Third country duty", "Additional duties", "Supplementary unit", "duty", "Duty"))


def _find_measure(measures: list[dict[str, Any]], needles: tuple[str, ...]) -> dict[str, Any] | None:
    return next((m for m in measures if any(n in (m.get("measure_type") or "") for n in needles)), None)


def package_context(pkg: dict[str, Any]) -> dict[str, Any]:
    view_context = document_view_context(pkg)
    if view_context:
        return view_context
    raw_context = raw_package_context(pkg)
    if raw_context:
        return raw_context
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
        "metrics": {},
        "missing": [],
        "product_reqs": [],
        "product_pre": [],
        "product_post": [],
        "related_declarations": {},
        "source": "unresolved",
        "_raw_package": pkg,
    }


def _documents_from_checklist(checklist: dict[str, Any]) -> list[dict[str, Any]]:
    documents = checklist.get("documents") or []
    if isinstance(documents, list):
        return [
            document
            for document in documents
            if isinstance(document, dict)
        ]
    if not isinstance(documents, dict):
        return []

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for status, names in documents.items():
        if not isinstance(names, list):
            continue
        for name in names:
            text = _compact_text(name)
            if not text or text in seen:
                continue
            seen.add(text)
            out.append({
                "document_code": re.sub(r"[^A-Z0-9]+", "_", text.upper()).strip("_") or text,
                "document_name_ko": text,
                "decision_status": str(status or "conditional"),
                "required_level": str(status or "conditional"),
                "prepared_by": "exporter / seller / logistics party",
                "submitted_to": "EU importer / customs broker",
                "fields": [],
                "pre_checks": [],
                "post_requirements": [],
                "missing_facts": [],
                "taric_certificates": [],
            })
    return out


def _document_counts(documents: list[dict[str, Any]], counts: dict[str, Any] | None = None) -> dict[str, Any]:
    out = dict(counts or {})
    out["total"] = len(documents)
    out.setdefault("required", sum(1 for doc in documents if _doc_status(doc) == "required"))
    out.setdefault("conditional", sum(1 for doc in documents if _doc_status(doc) == "conditional"))
    out.setdefault("pending", sum(1 for doc in documents if _doc_status(doc) == "pending"))
    out["with_pre_links"] = sum(1 for doc in documents if doc.get("pre_taric_links") or doc.get("pre_checks"))
    out["with_post_links"] = sum(1 for doc in documents if doc.get("post_taric_links") or doc.get("post_requirements"))
    return out


def raw_package_context(pkg: dict[str, Any]) -> dict[str, Any] | None:
    reqs = pkg.get("requirements") or []
    if not isinstance(reqs, list):
        return None
    checklist = pkg.get("checklist_summary") or {}
    if not isinstance(checklist, dict):
        checklist = {}

    kr = [r for r in reqs if isinstance(r, dict) and r.get("applies_to_korea")]
    non_kr = [r for r in reqs if isinstance(r, dict) and not r.get("applies_to_korea")]
    baseline_docs = checklist.get("document_binding_cards") or _documents_from_checklist(checklist)
    counts = _document_counts(baseline_docs, checklist.get("counts") or {})
    groups = checklist.get("document_groups") or []

    controls: list[dict[str, Any]] = []
    duties: list[dict[str, Any]] = []
    product_reqs: list[dict[str, Any]] = []
    product_pre: list[dict[str, Any]] = []
    product_post: list[dict[str, Any]] = []
    pre_taric_checks: list[dict[str, Any]] = []

    for req in kr:
        measure_type = req.get("measure_type") or ""
        details = req.get("detailed_requirements") or []
        if measure_type in {
            "Baseline document requirements",
            "Product regulatory requirements",
            "Pre-TARIC screening requirements",
        }:
            if measure_type != "Baseline document requirements":
                product_reqs.append(req)
            for detail in details:
                source_layer = detail.get("source_layer") or ""
                if source_layer in {"pre_taric_gate", "chapter_route_seed"}:
                    product_pre.append(detail)
                    if source_layer == "pre_taric_gate":
                        pre_taric_checks.append(detail)
                elif source_layer == "product_domain_seed":
                    product_post.append(detail)
            continue
        if _is_control_measure(req):
            controls.append(req)
        elif _is_duty_measure(req):
            duties.append(req)
        else:
            duties.append(req)

    base_duty_measures = [r for r in duties if _is_base_duty_measure(r)]
    preferential_measures = [r for r in duties if _is_preferential_measure(r)]
    return {
        "kr": kr,
        "non_kr": non_kr,
        "controls": controls,
        "duties": list(base_duty_measures) + list(preferential_measures),
        "base_duty_measures": base_duty_measures,
        "preferential_measures": preferential_measures,
        "third_country": _find_measure(duties, ("Third country duty",)),
        "fta_pref": _find_measure(duties, ("Tariff preference", "Customs Union")),
        "additional_duty": _find_measure(duties, ("Additional duties",)),
        "groups": groups,
        "document_checklist": checklist,
        "baseline_documents": baseline_docs,
        "pre_taric_checks": pre_taric_checks,
        "counts": counts,
        "metrics": {
            "kr_measure_count": len(kr),
            "non_kr_measure_count": len(non_kr),
            "control_count": len(controls),
            "duty_count": len(duties),
            "base_duty_count": len(base_duty_measures),
            "preferential_count": len(preferential_measures),
            "document_group_count": len(groups),
            "baseline_document_count": len(baseline_docs),
            "missing_count": len(checklist.get("missing_facts") or []),
        },
        "missing": checklist.get("missing_facts") or [],
        "product_reqs": product_reqs,
        "product_pre": product_pre,
        "product_post": product_post,
        "related_declarations": {},
        "document_view": {},
        "source": "raw_document_package",
    }


def document_view_context(pkg: dict[str, Any]) -> dict[str, Any] | None:
    """Use DocumentAgent's view model when a pipeline package provides it.

    Pipeline detail pages are display-only consumers of Document_Agent output.
    """
    view = pkg.get("_document_view") or pkg.get("document_view")
    if not isinstance(view, dict):
        return None
    sections = view.get("sections") or {}
    if not isinstance(sections, dict):
        return None
    metrics = view.get("metrics") or {}
    if not isinstance(metrics, dict):
        metrics = {}

    overview = sections.get("overview") or {}
    customs = sections.get("customs_check_items") or {}
    basic = sections.get("basic_duty") or {}
    preferential = sections.get("preferential_evidence") or {}
    required_docs = sections.get("required_documents") or {}
    product = sections.get("product_regulations") or {}
    baseline_section = sections.get("baseline_documents") or {}
    if not isinstance(baseline_section, dict):
        baseline_section = {}
    checklist = baseline_section or sections.get("document_checklist") or pkg.get("checklist_summary") or {}
    if not isinstance(checklist, dict):
        checklist = {}
    pre_taric_checks = sections.get("pre_taric_checks") or {}

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
        "document_checklist": checklist,
        "baseline_documents": (
            checklist.get("documents")
            if isinstance(checklist.get("documents"), list)
            else checklist.get("document_binding_cards") or _documents_from_checklist(checklist)
        ),
        "pre_taric_checks": pre_taric_checks.get("checks") or checklist.get("pre_taric_checks") or [],
        "counts": overview.get("counts") or {},
        "metrics": metrics,
        "missing": overview.get("missing_facts") or [],
        "product_reqs": product_reqs,
        "product_pre": product.get("pre") or [],
        "product_post": product.get("post") or [],
        "related_declarations": product.get("related_declarations") or {},
        "document_view": view,
        "source": "document_view",
    }


def render_result(pkg, panel, options):
    if not pkg:
        return "TARIC 코드를 입력하거나 좌측 예제를 선택하세요."
    hasDocumentView = isinstance(pkg.get("document_view") or pkg.get("_document_view"), dict)
    if not hasDocumentView and not pkg.get("has_data"):
        return html.Div("이 코드에 대한 현재 적용 measure가 없습니다.", className="empty")

    cx = package_context(pkg)
    if cx.get("source") == "unresolved":
        return render_unresolved(pkg, options or [])
    third_country = cx["third_country"]
    fta_pref = cx["fta_pref"]
    final_duty = fta_pref or third_country
    counts = cx["counts"]
    metricsData = cx.get("metrics") or {}
    groups = cx["groups"]
    baseline_documents = cx.get("baseline_documents") or []
    additional_documents = _additional_detail_documents(baseline_documents)
    controls = cx["controls"]
    duties = cx["duties"]
    product_reqs = cx["product_reqs"]
    selected = panel or OVERVIEW_PANEL_ID
    product_count = (
        len(cx.get("product_pre") or [])
        + len(cx.get("product_post") or [])
        or sum(len(r.get("detailed_requirements") or []) for r in product_reqs)
    )

    panel_defs = _document_panel_defs(len(baseline_documents) or len(additional_documents) or len(groups))

    documentCount = len(baseline_documents) or len(additional_documents) or len(groups)
    summaryItems = [
        ("관세율 후보", duty_rate(final_duty)),
        ("KR measure", metricsData.get("kr_measure_count", len(cx["kr"]))),
        ("필요 / 조건부", f"{counts.get('required', 0)} / {counts.get('conditional', 0)}"),
        ("판단보류", counts.get("pending", 0)),
    ]
    routeItems = [
        ("CODE", pkg.get("taric10") or "-"),
        ("통관조건", f"{len(controls)} control"),
        ("관세", f"{len(duties)} measure"),
        ("서류", f"{documentCount} documents"),
    ]

    children = [
        html.Div(
            [
                html.Div(
                    [
                        html.Div("EU IMPORT CLASSIFICATION", className="document-result-eyebrow"),
                        html.Div(pkg.get("taric10") or "-", className="document-result-code"),
                        html.Div(f"CN8 {pkg.get('cn8') or '-'}", className="document-result-cn"),
                    ],
                    className="document-result-identity",
                ),
                html.Div(
                    [
                        html.Div(
                            [
                                html.Div(label, className="document-summary-label"),
                                html.Div(str(value), className="document-summary-value"),
                            ],
                            className="document-summary-item",
                        )
                        for label, value in summaryItems
                    ],
                    className="document-summary-rail",
                ),
            ],
            className="document-result-masthead",
        ),
        html.Ol(
            [
                html.Li(
                    [
                        html.Span(label, className="document-route-label"),
                        html.Strong(str(value), className="document-route-value"),
                    ]
                )
                for label, value in routeItems
            ],
            className="document-result-route",
        ),
        _render_drawer_toolbar(panel_defs, selected),
        html.Div(render_panel(pkg, OVERVIEW_PANEL_ID, cx, options or []), className="panel"),
        _render_detail_drawer(pkg, selected, cx, options or [], panel_defs),
    ]
    return children


def _document_panel_defs(additionalDocumentCount: int) -> list[tuple[str, str, str]]:
    return [
        (OVERVIEW_PANEL_ID, "전체 결론", "기본 화면"),
        ("scenario", "시나리오", "원산지 · Control · FTA"),
        ("bundles", "서류 추천", f"{additionalDocumentCount}개"),
    ]


def _render_drawer_toolbar(
    panelDefs: list[tuple[str, str, str]],
    selected: str,
) -> dmc.Group:
    return dmc.Group(
        [
            dmc.Button(
                [html.Div(title), html.Div(sub, style={"fontSize": "11px", "fontWeight": 750})],
                id={"type": "panel-btn", "panel": panelId},
                variant="filled" if selected == panelId else "light",
                color="blue" if panelId in DRAWER_PANEL_IDS else "gray",
                radius="sm",
                size="sm",
                className="drawer-action-btn",
                style={"height": "auto", "minHeight": "54px", "lineHeight": 1.2},
            )
            for panelId, title, sub in panelDefs
        ],
        gap="xs",
        wrap="wrap",
        className="drawer-toolbar",
    )


def _render_detail_drawer(
    pkg: dict[str, Any],
    selected: str,
    cx: dict[str, Any],
    options: list[str],
    panelDefs: list[tuple[str, str, str]],
) -> dmc.Drawer:
    panelInfo = {panelId: (title, sub) for panelId, title, sub in panelDefs}
    drawerPanel = selected if selected in DRAWER_PANEL_IDS else ""
    title, sub = panelInfo.get(drawerPanel, ("상세 보기", ""))
    return dmc.Drawer(
        id="document-detail-drawer",
        opened=bool(drawerPanel),
        position="right",
        size="min(1040px, 92vw)",
        padding="lg",
        title=_render_drawer_title(title, sub),
        withCloseButton=False,
        closeOnClickOutside=False,
        closeOnEscape=False,
        lockScroll=True,
        keepMounted=False,
        overlayProps={"backgroundOpacity": 0.42, "blur": 2},
        zIndex=3000,
        children=html.Div(
            render_panel(pkg, drawerPanel, cx, options) if drawerPanel else [],
            className="drawer-panel-body document-drawer-body",
        ),
    )


def _render_drawer_title(title: str, sub: str) -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.Div(title, className="drawer-title-main"),
                    html.Div(sub, className="drawer-title-sub") if sub else None,
                ]
            ),
            dmc.Button(
                "닫기",
                id={"type": "drawer-close-btn", "target": "document-package"},
                variant="subtle",
                color="gray",
                size="xs",
                radius="sm",
            ),
        ],
        className="drawer-title",
    )


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
    if "debug" in (options or []) or "blackboard" in (options or []):
        children.append(
            html.Details(
                [
                    html.Summary("document_package payload (debug)"),
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
    if panel == "scenario":
        return render_trade_scenario(pkg, cx)
    if panel == "customs":
        return render_customs(pkg, cx["controls"])
    if panel == "base_duty":
        return render_base_duty(cx["base_duty_measures"])
    if panel == "preferential":
        return render_preferential(cx["preferential_measures"])
    if panel == "bundles":
        if cx.get("baseline_documents"):
            return render_document_checklist(
                cx.get("baseline_documents") or [],
                cx.get("pre_taric_checks") or [],
                cx.get("document_checklist") or {},
                cx.get("groups") or [],
            )
        return render_bundles(cx["groups"], showHeading=False)
    if panel == "product":
        return render_product_rules_from_view(
            cx.get("product_pre") or [],
            cx.get("product_post") or [],
            cx.get("related_declarations") or {},
        )
    return render_overview(cx, options, pkg)


def _scenario_cert_codes(reqs: list[dict[str, Any]], categories: set[str] | None = None) -> list[str]:
    codes: set[str] = set()
    for req in reqs:
        for cert in req.get("certificates") or []:
            category = cert.get("category") or "unknown"
            if categories is None or category in categories:
                code = cert.get("code")
                if code:
                    codes.add(str(code))
    return sorted(codes)


def _doc_name(doc: dict[str, Any]) -> str:
    return str(doc.get("document_name_ko") or doc.get("document_name") or doc.get("document_code") or "제출서류")


def _doc_code(doc: dict[str, Any]) -> str:
    return str(doc.get("document_code") or "")


def _doc_status(doc: dict[str, Any]) -> str:
    return str(doc.get("decision_status") or doc.get("required_level") or "conditional")


BASELINE_CORE_DOCUMENT_CODES = {
    "COMMERCIAL_INVOICE",
    "PACKING_LIST",
    "BL_AWB",
    "DELIVERY_NOTE",
}


def _additional_detail_documents(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    detailed = []
    for doc in documents:
        code = _doc_code(doc)
        if code in BASELINE_CORE_DOCUMENT_CODES:
            continue
        if (
            doc.get("taric_certificates")
            or doc.get("pre_checks")
            or doc.get("post_requirements")
            or code in {"ORIGIN_PROOF", "PRODUCT_SPEC", "INGREDIENT_LIST", "COA", "SDS", "LABEL_ARTWORK", "HEALTH_CERT_SUPPORT", "ORGANIC_COI", "CITES_SPECIES_EVIDENCE"}
        ):
            detailed.append(doc)
    return detailed


def _scenario_field_rows(fields: list[dict[str, Any]]) -> list[html.Div]:
    rows = []
    for field in fields[:8]:
        rows.append(
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(field.get("label") or field.get("field_key") or "작성항목", style={"fontWeight": 850, "color": "#111827"}),
                            html.Span(" · "),
                            status_badge(field.get("status") or "conditional"),
                        ]
                    ),
                    html.Div("required_by: " + (", ".join(field.get("required_by") or []) or "baseline")),
                    html.Div(
                        "추가 확인: " + (", ".join((field.get("missing_facts") or [])[:4]) or "없음"),
                        style={"color": "#9a3412"},
                    ),
                ],
                className="scenario-field-row",
            )
        )
    return rows


def _scenario_documents(cx: dict[str, Any], scenario: str) -> list[dict[str, Any]]:
    docs = cx.get("baseline_documents") or []
    required_docs = [doc for doc in docs if _doc_status(doc) == "required"]
    selected: list[dict[str, Any]] = list(required_docs)

    def include_by_code(*codes: str) -> None:
        code_set = set(codes)
        selected.extend([doc for doc in docs if _doc_code(doc) in code_set])

    if scenario == "fta":
        include_by_code("ORIGIN_PROOF", "PRODUCT_SPEC", "INGREDIENT_LIST")
    elif scenario == "basic":
        include_by_code("PRODUCT_SPEC", "INGREDIENT_LIST", "COA")
    elif scenario == "control":
        selected.extend(
            [
                doc
                for doc in docs
                if doc.get("taric_certificates")
                or doc.get("pre_checks")
                or doc.get("post_requirements")
            ]
        )

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for doc in selected:
        code = _doc_code(doc) or _doc_name(doc)
        if code in seen:
            continue
        seen.add(code)
        deduped.append(doc)
    return deduped


def _scenario_document_window(
    cx: dict[str, Any],
    scenario: str,
    cert_codes: list[str] | None,
    title: str = "이 시나리오 제출 창",
) -> html.Div:
    docs = _scenario_documents(cx, scenario)
    cert_codes = cert_codes or []
    rows = []
    for doc in docs[:8]:
        pre_count = len(doc.get("pre_checks") or [])
        post_count = len(doc.get("post_requirements") or [])
        fields = doc.get("fields") or []
        field_preview = ", ".join(
            str(field.get("label") or field.get("field_key") or "")
            for field in fields[:4]
            if field.get("label") or field.get("field_key")
        ) or "정의 없음"
        missing = ", ".join((doc.get("missing_facts") or [])[:3]) or "없음"
        rows.append(
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(_doc_name(doc), className="scenario-doc-name"),
                            html.Div(_doc_code(doc), className="scenario-doc-code"),
                            html.Div(
                                f"사전 {pre_count} · 상세 {post_count} · 추가 확인: {missing}",
                                className="scenario-doc-meta",
                            ),
                            html.Div(
                                f"작성항목: {field_preview}",
                                className="scenario-doc-meta",
                                style={"color": "#334155"},
                            ),
                            html.Details(
                                [
                                    html.Summary(f"작성항목 {len(fields)}개"),
                                    html.Div(
                                        _scenario_field_rows(fields) or html.Div("작성항목 정의 없음", className="card-meta"),
                                        className="scenario-doc-fields",
                                    ),
                                ],
                                className="scenario-detail",
                            ),
                        ]
                    ),
                    status_badge(_doc_status(doc)),
                ],
                className="scenario-doc-row",
            )
        )
    cert_block = html.Details(
        [
            html.Summary(f"세부 서류/선언 코드 {len(cert_codes)}개"),
            html.Div(
                [html.Span(code, className="chip") for code in cert_codes[:12]]
                if cert_codes
                else html.Div("이 시나리오에 별도 TARIC certificate/declaration code가 없습니다.", className="card-meta"),
                style={"marginTop": "8px"},
            ),
        ],
        className="scenario-detail",
    )
    return html.Div(
        [
            html.Div(
                [
                    html.Div(title, className="scenario-window-title"),
                    html.Div(f"baseline {len(docs)} · 세부 코드 {len(cert_codes)}", className="scenario-window-count"),
                ],
                className="scenario-window-head",
            ),
            html.Div(
                [
                    html.Div(rows or html.Div("연결된 baseline 제출서류가 없습니다.", className="card-meta")),
                    cert_block,
                ],
                className="scenario-window-body",
            ),
        ],
        className="scenario-window",
    )


def _scenario_card(
    title: str,
    duty: str,
    basis: str,
    actions: list[str],
    color_class: str,
    cert_codes: list[str] | None = None,
    document_window: html.Div | None = None,
) -> html.Div:
    color = {
        "green": "#166534",
        "amber": "#9a3412",
        "red": "#b91c1c",
    }.get(color_class, "#111827")
    return html.Div(
        [
            html.Div(title, className="card-title"),
            html.Div(basis or "-", className="card-meta"),
            html.Div(duty or "-", className="scenario-duty", style={"color": color}),
            html.Ul([html.Li(action) for action in actions if action], className="scenario-actions"),
            html.Div(
                f"세부 서류/선언 코드 {len(cert_codes or [])}개",
                className="card-meta",
                style={"marginTop": "9px"},
            ),
            html.Details(
                [
                    html.Summary("서류 확인"),
                    document_window,
                ],
                className="scenario-detail",
            ) if document_window else None,
        ],
        className=f"scenario-card {color_class}",
    )


def _scenario_parts(cx: dict[str, Any]) -> dict[str, Any]:
    controls = cx.get("controls") or []
    third_country = cx.get("third_country")
    fta_pref = cx.get("fta_pref")
    mandatory_categories = {"mandatory_certificate", "national_document", "import_license"}
    control_cert_codes = _scenario_cert_codes(controls, mandatory_categories)
    all_control_codes = _scenario_cert_codes(controls)
    fta_codes = _scenario_cert_codes([fta_pref] if fta_pref else [], {"preferential_origin"}) or _scenario_cert_codes([fta_pref] if fta_pref else [])
    has_control_requirements = bool(control_cert_codes or all_control_codes or controls)
    return {
        "controls": controls,
        "third_country": third_country,
        "fta_pref": fta_pref,
        "control_cert_codes": control_cert_codes,
        "all_control_codes": all_control_codes,
        "fta_codes": fta_codes,
        "has_control_requirements": has_control_requirements,
    }


def _scenario_comparison_cards(cx: dict[str, Any]) -> list[html.Div]:
    parts = _scenario_parts(cx)
    third_country = parts["third_country"]
    fta_pref = parts["fta_pref"]
    all_control_codes = parts["all_control_codes"]
    fta_codes = parts["fta_codes"]
    has_control_requirements = parts["has_control_requirements"]

    scenarios: list[html.Div] = []
    if fta_pref:
        scenarios.append(
            _scenario_card(
                "FTA 우대세율 적용",
                duty_rate(fta_pref),
                fta_pref.get("measure_type") or "Tariff preference",
                [
                    "원산지가 한국이고 한-EU FTA 원산지 기준을 충족해야 합니다.",
                    "상업서류에 원산지 신고문안 또는 관련 원산지 증빙을 준비합니다.",
                    "Control 서류가 있으면 먼저 충족해야 합니다.",
                ],
                "green",
                fta_codes + all_control_codes,
                _scenario_document_window(cx, "fta", fta_codes + all_control_codes, "FTA 우대 시 제출 창"),
            )
        )
    else:
        scenarios.append(
            _scenario_card(
                "FTA 우대세율 미확인",
                "해당 없음",
                "현재 한국 기준 우대관세 measure를 찾지 못했습니다.",
                [
                    "우대세율이 필요하면 원산지/협정 기준을 별도로 확인합니다.",
                    "기본관세 시나리오와 서류 확인 창을 먼저 검토합니다.",
                ],
                "amber",
                all_control_codes,
                _scenario_document_window(cx, "basic", all_control_codes, "우대 미확인 시 제출 창"),
            )
        )

    scenarios.append(
        _scenario_card(
            "기본관세 적용",
            duty_rate(third_country),
            (third_country or {}).get("measure_type") or "Third country duty",
            [
                "FTA 우대세율을 쓰지 않을 때의 기본 세율 시나리오입니다.",
                "상업송장, 포장명세서, 운송서류 등 baseline 제출서류는 계속 필요합니다.",
                "Control 서류가 있으면 기본관세 납부와 별개로 준비해야 합니다.",
            ],
            "amber",
            all_control_codes,
            _scenario_document_window(cx, "basic", all_control_codes, "기본관세 시 제출 창"),
        )
    )

    scenarios.append(
        _scenario_card(
            "Control 서류 미준비",
            "통관 보류 가능",
            "필수 certificate/declaration 또는 비대상 근거가 준비되지 않은 경우",
            [
                "세율보다 control 서류 충족 여부가 먼저입니다.",
                "필수 코드가 있으면 관련 증명서 또는 비대상 선언 근거를 준비합니다.",
                "해당 없음으로 판단하려면 제품 성분/용도/원산지 근거가 필요합니다.",
            ],
            "red" if has_control_requirements else "amber",
            all_control_codes,
            _scenario_document_window(cx, "control", all_control_codes, "Control 확인용 제출 창"),
        )
    )

    return scenarios


def render_scenario_decision(pkg: dict[str, Any], cx: dict[str, Any], selected_values: list[str] | None) -> html.Div:
    parts = _scenario_parts(cx)
    third_country = parts["third_country"]
    fta_pref = parts["fta_pref"]
    all_control_codes = parts["all_control_codes"]
    fta_codes = parts["fta_codes"]
    has_control_requirements = parts["has_control_requirements"]
    selected = set(selected_values or [])
    origin_is_kr = "origin_kr" in selected
    controls_ready = "controls_ready" in selected or not has_control_requirements
    fta_requested = "fta_requested" in selected

    if not controls_ready:
        primary = _scenario_card(
            "현재 선택 결과: Control 서류 미준비",
            "통관 보류 가능",
            "필수 certificate/declaration 또는 비대상 근거가 준비되지 않은 상태입니다.",
            [
                "세율보다 control 서류 충족 여부가 먼저입니다.",
                "서류 확인을 열어 연결된 TARIC 코드와 준비 문서를 확인하세요.",
            ],
            "red",
            all_control_codes,
            _scenario_document_window(cx, "control", all_control_codes, "Control 서류 준비 창"),
        )
    elif origin_is_kr and fta_requested and fta_pref:
        primary = _scenario_card(
            "현재 선택 결과: FTA 우대세율 적용",
            duty_rate(fta_pref),
            fta_pref.get("measure_type") or "Tariff preference",
            [
                "원산지 기준 충족자료와 원산지 신고문안을 준비합니다.",
                "기본 제출서류에는 원산지/가격/수량/운송정보가 일관되게 들어가야 합니다.",
            ],
            "green",
            fta_codes + all_control_codes,
            _scenario_document_window(cx, "fta", fta_codes + all_control_codes, "FTA 우대 시 제출 창"),
        )
    elif origin_is_kr:
        primary = _scenario_card(
            "현재 선택 결과: 기본관세 적용",
            duty_rate(third_country),
            (third_country or {}).get("measure_type") or "Third country duty",
            [
                "FTA 우대세율을 쓰지 않거나 확인되지 않은 경우의 기본 시나리오입니다.",
                "기본 제출서류와 control 서류/비대상 근거는 별도로 준비합니다.",
            ],
            "amber",
            all_control_codes,
            _scenario_document_window(cx, "basic", all_control_codes, "기본관세 시 제출 창"),
        )
    else:
        primary = _scenario_card(
            "현재 선택 결과: 한국 원산지 아님",
            duty_rate(third_country),
            (third_country or {}).get("measure_type") or "원산지별 재조회 필요",
            [
                "한-EU FTA 한국 원산지 우대세율은 적용하지 않습니다.",
                "실제 원산지 국가 기준으로 TARIC/Access2Markets를 다시 확인해야 합니다.",
            ],
            "amber",
            all_control_codes,
            _scenario_document_window(cx, "basic", all_control_codes, "비한국 원산지 기본 제출 창"),
        )

    return html.Div(
        [
            primary,
            html.Details(
                [
                    html.Summary("가능 시나리오 비교"),
                    html.Div(_scenario_comparison_cards(cx), className="scenario-grid"),
                ],
                style={"marginTop": "12px"},
            ),
        ]
    )


def _default_scenario_values(cx: dict[str, Any]) -> list[str]:
    parts = _scenario_parts(cx)
    values = ["origin_kr"]
    if not parts["has_control_requirements"]:
        values.append("controls_ready")
    if parts["fta_pref"]:
        values.append("fta_requested")
    return values


def render_trade_scenario(pkg: dict[str, Any], cx: dict[str, Any]) -> html.Div:
    parts = _scenario_parts(cx)
    has_control_requirements = parts["has_control_requirements"]
    fta_pref = parts["fta_pref"]
    checklist_values = _default_scenario_values(cx)
    taric_key = CleanCode(str(pkg.get("taric10") or "unknown")) or "unknown"

    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Div("TARIC CODE", className="metric-label"),
                            html.Div(pkg.get("taric10") or "-", className="metric-value", style={"color": "#1d4ed8", "fontFamily": "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"}),
                            html.Div(f"CN8: {pkg.get('cn8') or '-'}", className="card-meta"),
                        ],
                        className="scenario-code",
                    ),
                    html.Div(
                        [
                            html.Div("조건 체크", className="card-title"),
                            dcc.Checklist(
                                id={"type": "scenario-checks", "taric": taric_key},
                                options=[
                                    {"label": "원산지가 한국인가요?", "value": "origin_kr"},
                                    {"label": "Control 서류 또는 비대상 근거가 준비되었나요?", "value": "controls_ready", "disabled": not has_control_requirements},
                                    {"label": "FTA 우대세율을 신청하나요?", "value": "fta_requested", "disabled": not bool(fta_pref)},
                                ],
                                value=checklist_values,
                                className="scenario-checks",
                                inputStyle={"marginRight": "8px"},
                                labelStyle={"display": "block"},
                            ),
                            html.Div(
                                "체크 상태에 따라 아래 시나리오를 비교하고, 실제 제출물은 각 시나리오의 서류 확인에서 봅니다.",
                                className="card-meta",
                            ),
                        ]
                    ),
                ],
                className="scenario-head",
            ),
            html.Div(
                render_scenario_decision(pkg, cx, checklist_values),
                id={"type": "scenario-result", "taric": taric_key},
            ),
        ],
        className="scenario-shell",
    )

def render_overview(cx: dict[str, Any], options: list[str], pkg: dict[str, Any]):
    missing = cx["missing"]
    items = [
        ("통관 조건", f"{len(cx['controls'])}개 control measure", "TARIC certificate/declaration 조건 확인"),
        ("관세 시나리오", f"{len(cx['duties'])}개 duty/preference measure", "기본관세와 적용 가능한 우대세율 비교"),
        (
            "제출 서류",
            f"{len(cx.get('baseline_documents') or []) or len(_additional_detail_documents(cx.get('baseline_documents') or []) or cx['groups'])}개 document",
            "기본 제출물과 조건부 증빙을 분리해 검토",
        ),
    ]
    reviewTable = html.Div(
        [
            html.Div("검토 요약", className="document-overview-title"),
            html.Div(
                html.Table(
                    [
                        html.Tbody(
                            [
                                html.Tr(
                                    [
                                        html.Th(title),
                                        html.Td(body, className="document-overview-count"),
                                        html.Td(description),
                                    ]
                                )
                                for title, body, description in items
                            ]
                        )
                    ],
                    className="document-overview-table",
                ),
                className="document-table-wrap",
            ),
            html.Div(
                [
                    html.Div("추가 확인 facts", className="document-overview-facts-label"),
                    html.Div(
                        [html.Span(fact, className="chip") for fact in missing[:22]]
                        if missing
                        else html.Span(
                            "현재 상세 row 기준 추가 missing facts가 없습니다.",
                            className="document-overview-clear",
                        ),
                        className="document-overview-facts",
                    ),
                ],
                className="document-overview-facts-row",
            ),
        ],
        className="document-overview-brief",
    )
    raw = None
    if "raw" in options:
        raw = html.Details([html.Summary("Public document_package JSON"), html.Pre(json.dumps(pkg, ensure_ascii=False, indent=2), className="textarea")])
    debug = render_debug_pipeline_log(pkg) if "debug" in (options or []) or "blackboard" in (options or []) else None
    return html.Div([render_trade_scenario(pkg, cx), reviewTable, debug, raw])


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


def render_bundles(
    groups: list[dict[str, Any]],
    *,
    showHeading: bool = True,
):
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
    return html.Div(
        [
            html.Div("요구서류 묶음", className="section-title")
            if showHeading
            else None,
            html.Div(cards, className="two-col"),
        ]
    )


def render_document_checklist(
    documents: list[dict[str, Any]],
    pre_checks: list[dict[str, Any]],
    checklist: dict[str, Any],
    legacy_groups: list[dict[str, Any]],
):
    counts = checklist.get("counts") or {}
    intro = html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(label, className="document-checklist-count-label"),
                            html.Strong(str(value), className=f"document-checklist-count-value {tone}"),
                        ],
                        className="document-checklist-count",
                    )
                    for label, value, tone in [
                        ("전체", counts.get("total", len(documents)), "neutral"),
                        ("필수", counts.get("required", 0), "required"),
                        ("조건부", counts.get("conditional", 0), "conditional"),
                        ("판단보류", counts.get("pending", 0), "pending"),
                        ("사전 연결", counts.get("with_pre_links", 0), "linked"),
                        ("상세 연결", counts.get("with_post_links", 0), "linked"),
                    ]
                ],
                className="document-checklist-summary",
            ),
            html.Div(
                "상업송장, 포장명세서, 운송서류 같은 기본 제출서류를 먼저 보여주고, 각 문서에 연결된 사전 확인사항과 TARIC 상세 규제를 붙였습니다.",
                className="document-checklist-description",
            ),
        ],
        className="document-checklist-intro",
    )

    preRows: list[Any] = []
    for check in pre_checks[:8]:
        preRows.append(
            html.Tr(
                [
                    html.Td(
                        status_badge(check.get("decision_status") or check.get("required_level") or "conditional"),
                    ),
                    html.Td(
                        [
                            html.Div(check.get("pre_gate_family") or "pre gate", className="document-cell-title"),
                            html.Div(
                                f"{check.get('domain') or '-'} · {check.get('requirement_type') or '-'}",
                                className="document-cell-meta",
                            ),
                        ],
                    ),
                    html.Td(check.get("required_action") or "-"),
                    html.Td(
                        ", ".join((check.get("missing_facts") or [])[:6]) or "없음",
                        className="document-cell-missing",
                    ),
                ],
            )
        )
    pre_block = html.Details(
        [
            html.Summary(f"사전 확인사항 {len(pre_checks)}개"),
            html.Div(
                html.Table(
                    [
                        html.Thead(html.Tr([html.Th("상태"), html.Th("확인사항"), html.Th("조치"), html.Th("추가 확인")])),
                        html.Tbody(preRows),
                    ],
                    className="document-checklist-table document-precheck-table",
                )
                if preRows
                else html.Div("사전 확인사항 없음", className="card-meta"),
                className="document-table-wrap",
            ),
        ],
        className="document-checklist-details",
    )

    documentRows: list[Any] = []
    for doc in documents:
        fields = doc.get("fields") or []
        pre_count = len(doc.get("pre_checks") or [])
        post_count = len(doc.get("post_requirements") or [])
        certs = ", ".join((doc.get("taric_certificates") or [])[:8]) or "-"
        documentRows.append(
            html.Tr(
                [
                    html.Td(
                        status_badge(doc.get("decision_status") or doc.get("required_level") or "conditional"),
                    ),
                    html.Td(
                        [
                            html.Div(
                                doc.get("document_name_ko") or doc.get("document_name") or doc.get("document_code"),
                                className="document-cell-title",
                            ),
                            html.Div(doc.get("document_code") or "", className="document-cell-code"),
                        ],
                    ),
                    html.Td(
                        [
                            html.Div(doc.get("prepared_by") or "-", className="document-party"),
                            html.Div("→", className="document-party-arrow"),
                            html.Div(doc.get("submitted_to") or "-", className="document-party"),
                        ],
                        className="document-party-route",
                    ),
                    html.Td(
                        [
                            html.Div(f"사전 {pre_count} · 상세 {post_count}", className="document-cell-meta"),
                            html.Div(f"TARIC {certs}", className="document-cell-link"),
                        ]
                    ),
                    html.Td(
                        ", ".join((doc.get("missing_facts") or [])[:6]) or "없음",
                        className="document-cell-missing",
                    ),
                    html.Td(
                        html.Details(
                            [
                                html.Summary(f"{len(fields)}개 항목"),
                                html.Div(
                                    _scenario_field_rows(fields)
                                    or html.Div("필드 정의 없음", className="card-meta"),
                                    className="document-field-list",
                                ),
                            ],
                            className="document-row-details",
                        )
                    ),
                ],
            )
        )

    legacy = None
    if legacy_groups:
        legacy = html.Details(
            [
                html.Summary(f"기존 TARIC document group {len(legacy_groups)}개"),
                render_bundles(legacy_groups),
            ],
            style={"marginTop": "16px"},
        )
    documentTable = html.Div(
        html.Table(
            [
                html.Thead(
                    html.Tr(
                        [
                            html.Th("상태"),
                            html.Th("문서"),
                            html.Th("작성 → 제출"),
                            html.Th("연결 근거"),
                            html.Th("추가 확인"),
                            html.Th("작성 항목"),
                        ]
                    )
                ),
                html.Tbody(documentRows),
            ],
            className="document-checklist-table",
        ),
        className="document-table-wrap",
    )
    return html.Div(
        [intro, pre_block, documentTable, legacy],
        className="document-checklist-layout",
    )


def render_product_rules_from_view(
    pre: list[dict[str, Any]],
    post: list[dict[str, Any]],
    related_declarations: dict[str, list[str]],
):
    pre_col = html.Div(
        [
            html.Div([html.Div("사전 규제 후보", className="card-title"), html.Div(f"CN chapter 기준으로 먼저 확인할 규제 후보 · {len(pre)}개", className="card-meta")], className="card", style={"borderLeft": "4px solid #475569"}),
            *[
                detail_card(d, "pre 후보", related_declarations.get(d.get("domain_route") or d.get("domain") or "", []))
                for d in pre[:16]
            ],
        ]
    )
    post_col = html.Div(
        [
            html.Div([html.Div("TARIC 상세 규제", className="card-title"), html.Div(f"선택된 TARIC 코드에서 실제 준비/누락/보류 판단 항목 · {len(post)}개", className="card-meta")], className="card", style={"borderLeft": "4px solid #166534", "background": "#f0fdf4"}),
            *[
                detail_card(d, "post 상세", related_declarations.get(d.get("domain_route") or d.get("domain") or "", []))
                for d in post[:22]
            ],
        ]
    )
    return html.Div([html.Div("상세 규제/선언 체크리스트", className="section-title"), html.Div([pre_col, post_col], className="two-col")])



def BuildDocumentPackageContext(package: dict[str, Any]) -> dict[str, Any]:
    return package_context(package)


def RenderDocumentPackageResult(
    package: dict[str, Any],
    panel: str,
    options: list[str] | None = None,
) -> Any:
    return render_result(package, panel, options or [])


def RenderScenarioDecision(
    package: dict[str, Any],
    context: dict[str, Any],
    selectedValues: list[str] | None,
) -> html.Div:
    return render_scenario_decision(package, context, selectedValues or [])
