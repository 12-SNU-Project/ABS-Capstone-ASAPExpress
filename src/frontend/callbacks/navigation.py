"""Navigation and sidebar callbacks for the Dash shell."""

from __future__ import annotations

from typing import Any

from dash import Dash, Input, Output, dcc, html


def RegisterNavigationCallbacks(app: Dash) -> None:
    @app.callback(
        Output("app-sidebar", "children"),
        Input("url", "pathname"),
        Input("store-run-id", "data"),
        Input("store-result", "data"),
    )
    def render_sidebar(
        pathname: str | None,
        job_id: str | None,
        result_data: dict[str, Any] | None,
    ) -> list[Any]:
        return RenderSidebar(pathname, job_id, result_data)


def SplitPath(pathname: str | None) -> list[str]:
    return [part for part in (pathname or "/classification").split("/") if part]


def RenderSidebar(
    pathname: str | None,
    jobId: str | None,
    resultData: dict[str, Any] | None,
) -> list[Any]:
    parts = SplitPath(pathname)
    page = parts[0] if parts else "classification"
    result = resultData if isinstance(resultData, dict) else {}
    runId = result.get("run_id") or ""
    adminHref = f"/admin/{runId}" if runId else "/admin"
    documentLinks = (
        [_NavLink("서류 상세", f"/{'/'.join(parts)}", True, "TARIC 문서 패키지")]
        if page == "document"
        else []
    )

    return [
        html.Div("ASAP", style={"fontSize": "22px", "fontWeight": 950, "color": "#0f172a"}),
        html.Div(
            "EU export workspace",
            style={"fontSize": "11px", "fontWeight": 750, "color": "#64748b", "marginTop": "4px"},
        ),
        html.Div("Workspace", style=_SIDEBAR_SECTION_STYLE),
        _NavLink("분류", "/classification", page in {"classification", ""}, "입력·후보·서류 연결"),
        *documentLinks,
        _NavLink("관리/디버그", adminHref, page == "admin", "Debug payload·Agent log"),
        html.Div("Run", style=_SIDEBAR_SECTION_STYLE),
        html.Div(
            [
                html.Div("job_id", style=_SIDEBAR_META_LABEL_STYLE),
                html.Div(jobId or "-", style=_SIDEBAR_META_VALUE_STYLE),
                html.Div("run_id", style={**_SIDEBAR_META_LABEL_STYLE, "marginTop": "10px"}),
                html.Div(runId or "-", style=_SIDEBAR_META_VALUE_STYLE),
            ],
            style=_SIDEBAR_META_BOX_STYLE,
        ),
    ]


def _NavLink(label: str, href: str, active: bool, detail: str) -> dcc.Link:
    return dcc.Link(
        [
            html.Div(label, style={"fontSize": "13px", "fontWeight": 900}),
            html.Div(detail, style={"fontSize": "11px", "marginTop": "2px", "opacity": 0.78}),
        ],
        href=href,
        style={
            "display": "block",
            "padding": "10px 11px",
            "marginBottom": "6px",
            "borderRadius": "8px",
            "background": "#eff6ff" if active else "transparent",
            "border": "1px solid #bfdbfe" if active else "1px solid transparent",
            "color": "#1d4ed8" if active else "#334155",
            "textDecoration": "none",
        },
    )


_SIDEBAR_SECTION_STYLE = {
    "marginTop": "24px",
    "marginBottom": "8px",
    "fontSize": "10px",
    "fontWeight": 950,
    "letterSpacing": "0.08em",
    "textTransform": "uppercase",
    "color": "#94a3b8",
}

_SIDEBAR_META_BOX_STYLE = {
    "padding": "10px",
    "border": "1px solid #e5e7eb",
    "borderRadius": "8px",
    "background": "#f8fafc",
}

_SIDEBAR_META_LABEL_STYLE = {
    "fontSize": "10px",
    "fontWeight": 900,
    "color": "#64748b",
}

_SIDEBAR_META_VALUE_STYLE = {
    "marginTop": "3px",
    "fontSize": "11px",
    "fontWeight": 750,
    "color": "#0f172a",
    "fontFamily": "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
    "overflowWrap": "anywhere",
}
