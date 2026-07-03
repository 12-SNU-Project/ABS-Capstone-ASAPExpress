"""Navigation callbacks for the Dash shell."""

from __future__ import annotations

from dash import Dash, Input, Output, dcc, html


def RegisterNavigationCallbacks(app: Dash) -> None:
    @app.callback(
        Output("app-topbar", "children"),
        Input("url", "pathname"),
    )
    def render_topbar(
        pathname: str | None,
    ) -> list[object]:
        return RenderTopbar(pathname)


def SplitPath(pathname: str | None) -> list[str]:
    return [part for part in (pathname or "/classification").split("/") if part]


def RenderTopbar(
    pathname: str | None,
) -> list[object]:
    parts = SplitPath(pathname)
    page = parts[0] if parts else "classification"
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
            ],
            className="app-topbar-brand",
        ),
        html.Div(
            [
                _NavLink("프로젝트", "/classification", page in {"classification", ""}),
                *documentLinks,
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
