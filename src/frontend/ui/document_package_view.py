from __future__ import annotations

from typing import Any

from dash import dcc, html

from frontend.ui.document_package_renderer import (
    CleanCode,
    RenderDocumentPackageResult,
)


def _contract_package_for_detail(
    documentPackage: dict[str, Any] | None,
    taric10: str,
) -> dict[str, Any]:
    if not isinstance(documentPackage, dict):
        return {}
    requestedCode = CleanCode(taric10)
    packageCode = CleanCode(documentPackage.get("taric10") or "")
    if requestedCode and packageCode and requestedCode != packageCode:
        return {}
    return dict(documentPackage)


def _render_missing_document_package(runId: str | None, taric10: str) -> html.Div:
    return html.Div(
        [
            html.Div("서류 패키지 조회 불가", className="error"),
            html.Div(
                (
                    "현재 public API에 요청한 document_package payload가 없습니다. "
                    "분류 결과에서 생성된 서류 상세 링크를 사용하거나 관리/디버그 화면에서 저장된 run을 확인하세요."
                ),
                className="card-meta",
                style={"marginTop": "8px"},
            ),
            html.Div(
                f"run/job {runId or '-'} · TARIC10 {CleanCode(taric10) or '-'}",
                className="caption",
                style={"marginTop": "8px"},
            ),
        ],
        className="main",
    )


def render_detail_page(
    runId: str | None,
    taric10: str,
    panel: str = "overview",
    *,
    documentPackage: dict[str, Any] | None = None,
) -> html.Div:
    package = _contract_package_for_detail(documentPackage, taric10)
    if not package:
        return _render_missing_document_package(runId, taric10)

    return html.Div(
        [
            dcc.Store(id="package-store", data=package),
            html.Div(
                [
                    html.H2("EU 수출 서류 패키지", className="title"),
                    html.Div(
                        f"run/job {runId or '-'} · TARIC10 {CleanCode(taric10) or '-'}",
                        className="caption",
                    ),
                ],
                style={"marginBottom": "14px"},
            ),
            html.Div(
                RenderDocumentPackageResult(package, panel or "overview", []),
                id="document-result-root",
            ),
        ],
        className="main",
    )
