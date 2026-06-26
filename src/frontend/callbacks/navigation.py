"""Navigation callbacks for the Dash shell."""

from __future__ import annotations

from typing import Any

from dash import Dash, Input, Output, dcc, html


def RegisterNavigationCallbacks(app: Dash) -> None:
    @app.callback(
        Output("app-topbar", "children"),
        Input("url", "pathname"),
        Input("store-result", "data"),
    )
    def render_topbar(
        pathname: str | None,
        result_data: dict[str, Any] | None,
    ) -> list[Any]:
        return RenderTopbar(pathname, result_data)


def SplitPath(pathname: str | None) -> list[str]:
    return [part for part in (pathname or "/classification").split("/") if part]


def RenderTopbar(
    pathname: str | None,
    resultData: dict[str, Any] | None,
) -> list[Any]:
    parts = SplitPath(pathname)
    page = parts[0] if parts else "classification"
    result = resultData if isinstance(resultData, dict) else {}
    runId = result.get("run_id") or ""
    adminHref = f"/admin/{runId}" if runId else "/admin"
    documentLinks = (
        [_NavLink("서류 상세", f"/{'/'.join(parts)}", True)]
        if page == "document"
        else []
    )

    return [
        html.Div(
            [
                dcc.Link(
                    html.Img(
                        src="/assets/ASAP%20C_purple.png",
                        className="app-topbar-logo",
                    ),
                    href="/classification",
                    className="app-topbar-logo-link",
                ),
                html.Span("회원 서비스", className="app-topbar-service"),
            ],
            className="app-topbar-brand",
        ),
        html.Div(
            [
                _NavLink("프로젝트", "/classification", page in {"classification", ""}),
                *documentLinks,
                _NavLink("관리", adminHref, page == "admin"),
            ],
            className="app-topbar-tabs",
        ),
    ]


def _NavLink(label: str, href: str, active: bool) -> dcc.Link:
    return dcc.Link(
        label,
        href=href,
        className=f"app-topbar-tab {'active' if active else ''}".strip(),
    )
