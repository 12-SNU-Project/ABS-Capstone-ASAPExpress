from __future__ import annotations

import json
from typing import Any

import dash_mantine_components as dmc
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
PILL = {
    "display": "inline-block",
    "padding": "3px 8px",
    "borderRadius": "999px",
    "fontSize": "11px",
    "fontWeight": 800,
    "background": "#f3e8ff",
    "color": "#6d3fd6",
    "marginRight": "6px",
}
MONO = {
    "fontFamily": "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
    "fontSize": "12px",
}
STAGE_DISPLAY_NAMES = {
    "Input": "Input",
    "Pipeline": "Pipeline",
    "Input_Intake": "Input Processing",
    "Evidence_Intake_Agent": "Product Evidence Builder",
    "Classification_Agent": "Classification",
    "Document_Agent": "Document Recommendation",
    "Orchestrator_Agent": "Result Orchestration",
    "Product_Intake": "Product Evidence",
    "Classification": "Classification",
    "Document_Recommendation": "Document Recommendation",
    "Orchestration": "Result Orchestration",
}
PROGRESS_STEP_DEFINITIONS = [
    {
        "key": "collect",
        "title": "상품 정보 수집",
    },
    {
        "key": "reconstruct",
        "title": "상품 정보 가공",
    },
    {
        "key": "candidate",
        "title": "분류코드 산출",
    },
    {
        "key": "validation",
        "title": "산출 결과 검증",
    },
]
RECONSTRUCTION_GROUPS = (
    (
        "ingredients",
        "원재료명 및 함량",
        (
            "원재료",
            "원료명",
            "원제",
            "주원료",
            "배합",
            "전성분",
            "ingredients",
            "inci",
            "성분명",
            "함량",
            "함유량",
            "함유",
            "조성",
        ),
    ),
)
VLM_EVIDENCE_SOURCE_TYPES = {"vlm_table", "pp_table"}


def display_stage_name(stage: Any) -> str:
    stageText = str(stage or "").strip()
    return STAGE_DISPLAY_NAMES.get(stageText, stageText or "-")


def display_stage_message(message: Any) -> str:
    messageText = str(message or "")
    for rawStageName, displayName in STAGE_DISPLAY_NAMES.items():
        messageText = messageText.replace(rawStageName, displayName)
    return messageText


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


def _short_text(value: Any, *, max_length: int = 160) -> str:
    text = str(value or "").strip()
    if len(text) <= max_length:
        return text or "-"
    return text[: max_length - 1].rstrip() + "..."


def _expandable_text(value: Any, *, max_length: int = 180) -> Any:
    text = str(value or "").strip()
    if len(text) <= max_length:
        return text or "-"
    return html.Details(
        [
            html.Summary(_short_text(text, max_length=max_length)),
            html.Div(text, className="input-reconstruction-expanded-text"),
        ],
        className="input-reconstruction-expandable",
    )


def _display_source_type(source_type: Any) -> str:
    labels = {
        "vlm_table": "VLM table",
        "pp_table": "VLM table",
        "raw_ocr_tile": "Raw OCR tile",
        "notice_field": "Web notice",
        "notice_option": "Web option",
        "combined_ocr_text": "Combined OCR",
    }
    sourceType = str(source_type or "").strip()
    return labels.get(sourceType, sourceType or "-")


def _display_source_label(label: Any) -> str:
    return str(label or "-").replace("구조화 표", "VLM 표")


def _fact_source_text(
    fact: dict[str, Any],
    source_labels: dict[str, Any] | None = None,
) -> str:
    refs = fact.get("source_refs") or []
    if isinstance(refs, list):
        labels = source_labels or {}
        return ", ".join(
            _display_source_label(labels.get(str(ref), ref))
            for ref in refs[:3]
            if str(ref).strip()
        )
    return str(refs or "")


def _evidence_id(row: dict[str, Any]) -> str:
    return str(row.get("evidence_id") or row.get("id") or "").strip()


def _table_source_refs(table: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for sourceRef in table.get("source_refs") or []:
        sourceRefText = str(sourceRef).strip()
        if sourceRefText:
            refs.append(sourceRefText)
    for row in table.get("rows") or []:
        if not isinstance(row, dict):
            continue
        for sourceRef in row.get("source_refs") or []:
            sourceRefText = str(sourceRef).strip()
            if sourceRefText:
                refs.append(sourceRefText)
    return list(dict.fromkeys(refs))


def _table_product_context_text(
    table: dict[str, Any],
    evidence_rows: list[Any],
) -> str:
    evidenceById = {
        evidenceId: row
        for row in evidence_rows
        if isinstance(row, dict) and (evidenceId := _evidence_id(row))
    }
    optionLabels = {
        str(row.get("option_key") or "").strip(): _short_text(
            row.get("text") or row.get("source_label") or row.get("option_key"),
            max_length=120,
        )
        for row in evidence_rows
        if (
            isinstance(row, dict)
            and str(row.get("source_type") or "") == "notice_option"
            and str(row.get("option_key") or "").strip()
        )
    }
    optionKeys = []
    for sourceRef in _table_source_refs(table):
        row = evidenceById.get(sourceRef)
        if row is None:
            continue
        optionKey = str(row.get("option_key") or "").strip()
        if optionKey:
            optionKeys.append(optionKey)
    labels = [
        optionLabels.get(optionKey, optionKey)
        for optionKey in dict.fromkeys(optionKeys)
    ]
    if not labels:
        return ""
    return "상품/옵션: " + ", ".join(labels[:2])


def _is_ingredient_text(value: Any) -> bool:
    compactText = str(value or "").replace(" ", "").lower()
    return any(
        marker.replace(" ", "").lower() in compactText
        for _, _, markers in RECONSTRUCTION_GROUPS
        for marker in markers
    )


def _filter_ingredient_facts(facts: list[Any]) -> list[dict[str, Any]]:
    return [
        fact
        for fact in facts
        if isinstance(fact, dict) and _is_ingredient_text(fact.get("field_name"))
    ]


def _ingredient_fact_compare_sections(facts: list[Any]) -> list[dict[str, Any]]:
    beforeRows: list[dict[str, str]] = []
    afterRows: list[dict[str, str]] = []
    for fact in _filter_ingredient_facts(facts):
        fieldName = str(fact.get("field_name") or "원재료명 및 함량").strip()
        rawValue = str(fact.get("raw_value") or "").strip()
        normalizedValue = str(fact.get("normalized_value") or rawValue).strip()
        if rawValue:
            beforeRows.append({"field_name": fieldName, "value": rawValue})
        if normalizedValue:
            afterRows.append({"field_name": fieldName, "value": normalizedValue})
    if not beforeRows and not afterRows:
        return []
    return [
        {
            "table_name": "원재료명 및 함량 교정 비교",
            "before_rows": beforeRows,
            "after_rows": afterRows,
        }
    ]


def _vlm_evidence_tables(evidence_rows: list[Any]) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    for record in evidence_rows:
        if (
            not isinstance(record, dict)
            or record.get("source_type") not in VLM_EVIDENCE_SOURCE_TYPES
        ):
            continue
        rows: list[dict[str, str]] = []
        for line in str(record.get("text") or "").splitlines():
            cells = [cell.strip() for cell in line.split("|") if cell.strip()]
            for cellIndex in range(0, len(cells) - 1, 2):
                fieldName = cells[cellIndex]
                rawValue = cells[cellIndex + 1]
                if _is_ingredient_text("{0} {1}".format(fieldName, rawValue)):
                    rows.append({"field_name": fieldName, "value": rawValue})
        if rows:
            tables.append(
                {
                    "table_name": record.get("source_label")
                    or record.get("evidence_id")
                    or "VLM 표 원문",
                    "rows": rows,
                }
            )
    return tables


def _llm_reconstruction_tables(tables: list[Any]) -> list[dict[str, Any]]:
    cleanedTables: list[dict[str, Any]] = []
    for table in tables:
        if not isinstance(table, dict):
            continue
        tableName = str(table.get("table_name") or "LLM reconstruction")
        rows: list[dict[str, str]] = []
        for row in table.get("rows") or []:
            if not isinstance(row, dict):
                continue
            fieldName = str(row.get("field_name") or "").strip()
            rawValue = str(row.get("raw_value") or "").strip()
            normalizedValue = str(row.get("normalized_value") or "").strip()
            if normalizedValue and _is_ingredient_text(
                "{0} {1} {2} {3}".format(
                    tableName,
                    fieldName,
                    rawValue,
                    normalizedValue,
                )
            ):
                rows.append({"field_name": fieldName, "value": normalizedValue})
        if rows:
            cleanedTables.append({"table_name": tableName, "rows": rows})
    return cleanedTables


def _vlm_rows_for_source_refs(
    source_refs: list[Any],
    evidence_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seenKeys: set[tuple[str, str]] = set()
    for sourceRef in source_refs:
        record = evidence_by_id.get(str(sourceRef))
        if (
            not isinstance(record, dict)
            or record.get("source_type") not in VLM_EVIDENCE_SOURCE_TYPES
        ):
            continue
        for line in str(record.get("text") or "").splitlines():
            cells = [cell.strip() for cell in line.split("|") if cell.strip()]
            for cellIndex in range(0, len(cells) - 1, 2):
                fieldName = cells[cellIndex]
                rawValue = cells[cellIndex + 1]
                if not _is_ingredient_text("{0} {1}".format(fieldName, rawValue)):
                    continue
                key = (fieldName, rawValue)
                if key in seenKeys:
                    continue
                seenKeys.add(key)
                rows.append({"field_name": fieldName, "value": rawValue})
    return rows


def _reconstruction_option_sections(
    tables: list[Any],
    evidence_rows: list[Any],
) -> list[dict[str, Any]]:
    evidenceById = {
        str(record.get("evidence_id")): record
        for record in evidence_rows
        if isinstance(record, dict) and str(record.get("evidence_id") or "").strip()
    }
    sections: list[dict[str, Any]] = []
    for table in tables:
        if not isinstance(table, dict):
            continue
        tableName = str(table.get("table_name") or "LLM reconstruction").strip()
        tableSourceRefs = [
            str(sourceRef)
            for sourceRef in table.get("source_refs") or []
            if str(sourceRef).strip()
        ]
        beforeRows: list[dict[str, str]] = []
        afterRows: list[dict[str, str]] = []
        for row in table.get("rows") or []:
            if not isinstance(row, dict):
                continue
            fieldName = str(row.get("field_name") or "").strip()
            rawValue = str(row.get("raw_value") or "").strip()
            normalizedValue = str(row.get("normalized_value") or "").strip()
            if not _is_ingredient_text(
                "{0} {1} {2} {3}".format(
                    tableName,
                    fieldName,
                    rawValue,
                    normalizedValue,
                )
            ):
                continue
            rowSourceRefs = [
                str(sourceRef)
                for sourceRef in row.get("source_refs") or []
                if str(sourceRef).strip()
            ]
            rowVlmRows = _vlm_rows_for_source_refs(
                [*rowSourceRefs, *tableSourceRefs],
                evidenceById,
            )
            if rowVlmRows:
                beforeRows.extend(rowVlmRows)
            elif rawValue:
                beforeRows.append({"field_name": fieldName, "value": rawValue})
            if normalizedValue:
                afterRows.append({"field_name": fieldName, "value": normalizedValue})
        if beforeRows or afterRows:
            sections.append(
                {
                    "table_name": tableName,
                    "before_rows": beforeRows,
                    "after_rows": afterRows,
                }
            )
    return sections


def _reconstruction_fact_table(
    title: str,
    facts: list[dict[str, Any]],
    *,
    source_labels: dict[str, Any] | None = None,
    max_rows: int = 10,
) -> html.Div | None:
    if not facts:
        return None

    rows: list[Any] = []
    for fact in facts[:max_rows]:
        validationStatus = str(fact.get("validation_status") or "-").strip()
        correctionType = str(fact.get("correction_type") or "").strip()
        rawValue = str(fact.get("raw_value") or "").strip()
        normalizedValue = str(fact.get("normalized_value") or "").strip()
        rows.append(
            html.Tr(
                [
                    html.Td(
                        _short_text(fact.get("field_name"), max_length=90),
                        className="input-reconstruction-primary",
                    ),
                    html.Td(
                        _short_text(fact.get("raw_value"), max_length=220),
                    ),
                    html.Td(
                        _short_text(
                            fact.get("normalized_value") or fact.get("raw_value"),
                            max_length=220,
                        ),
                    ),
                    html.Td(
                        [
                            html.Div(
                                validationStatus,
                                className="input-reconstruction-status",
                            ),
                            html.Div(
                                correctionType,
                                className="input-reconstruction-secondary",
                            )
                            if correctionType
                            else None,
                        ],
                    ),
                    html.Td(
                        _short_text(
                            _fact_source_text(fact, source_labels),
                            max_length=160,
                        ),
                    ),
                ],
            )
        )

    more = None
    if len(facts) > max_rows:
        more = html.Div(
            f"+ {len(facts) - max_rows} more reconstructed facts",
            className="input-reconstruction-more",
        )

    return html.Div(
        [
            html.Div(
                [
                    html.Div(title, className="input-card-title"),
                    html.Div(f"{len(facts)} rows", className="input-card-count"),
                ],
                className="input-reconstruction-section-head",
            ),
            html.Div(
                html.Table(
                    [
                        html.Thead(
                            html.Tr(
                                [
                                    html.Th("필드"),
                                    html.Th("원문 값"),
                                    html.Th("정규화 값"),
                                    html.Th("검증 / 교정"),
                                    html.Th("출처"),
                                ]
                            )
                        ),
                        html.Tbody(rows),
                    ],
                    className="input-reconstruction-table",
                ),
                className="input-reconstruction-table-wrap",
            ),
            more,
        ],
        className="input-reconstruction-section",
    )


def _classification_fact_text_table(
    fact_texts: list[Any],
    *,
    title: str = "Classification input text lines",
    max_rows: int = 12,
) -> html.Div | None:
    cleaned = [str(text).strip() for text in fact_texts if str(text).strip()]
    if not cleaned:
        return None

    rows: list[Any] = []
    for index, text in enumerate(cleaned[:max_rows], start=1):
        rows.append(
            html.Tr(
                [
                    html.Td(str(index), className="input-reconstruction-index"),
                    html.Td(_short_text(text, max_length=360)),
                ]
            )
        )

    return html.Div(
        [
            html.Div(title, className="input-card-title") if title else None,
            html.Div(
                html.Table(
                    [
                        html.Thead(
                            html.Tr([html.Th("No."), html.Th("분류 입력 텍스트")])
                        ),
                        html.Tbody(rows),
                    ],
                    className=(
                        "input-reconstruction-table "
                        "input-reconstruction-text-table"
                    ),
                ),
                className="input-reconstruction-table-wrap",
            ),
            html.Div(
                f"+ {len(cleaned) - max_rows} more classification fact lines",
                className="input-reconstruction-more",
            )
            if len(cleaned) > max_rows
            else None,
        ],
        className="input-reconstruction-section",
    )


def _product_page_basic_card(raw: dict[str, Any]) -> html.Div | None:
    productName = raw.get("product_name") or ""
    description = raw.get("description") or ""
    sourceUrls = raw.get("source_urls") or []
    if isinstance(sourceUrls, str):
        sourceUrls = [sourceUrls] if sourceUrls.strip() else []
    url = sourceUrls[0] if isinstance(sourceUrls, list) and sourceUrls else raw.get("url") or ""
    if not any(str(value).strip() for value in [productName, description, url]):
        return None

    rows = [
        ("상품명", productName),
        ("설명", _short_text(description, max_length=260)),
        ("URL", url),
    ]
    return html.Div(
        [
            html.Div("Product Facts", className="drawer-section-kicker"),
            html.Div(
                "웹페이지 상단 영역에서 수집한 상품 기본 정보",
                className="drawer-section-description",
            ),
            html.Dl(
                [
                    html.Div(
                        [
                            html.Dt(label),
                            html.Dd(str(value or "-")),
                        ],
                        className="drawer-definition-row",
                    )
                    for label, value in rows
                ],
                className="drawer-definition-list",
            ),
        ],
        className="drawer-modern-surface input-product-facts",
    )


def _source_evidence_table(
    title: str,
    records: list[Any],
    *,
    max_rows: int = 6,
) -> html.Div | None:
    cleaned = [record for record in records if isinstance(record, dict)]
    if not cleaned:
        return None

    def evidence_card(record: dict[str, Any]) -> html.Div:
        sourceType = record.get("source_type") or ""
        sourceLabel = (
            record.get("source_label")
            or _display_source_type(sourceType)
            or "-"
        )
        return html.Div(
            [
                html.Div(
                    [
                        html.Span(
                            _short_text(
                                _display_source_label(sourceLabel),
                                max_length=70,
                            ),
                            className="input-source-label",
                        ),
                        html.Span(
                            _short_text(
                                _display_source_type(sourceType),
                                max_length=34,
                            ),
                            className="input-source-chip",
                        ),
                    ],
                    className="input-evidence-source",
                ),
                html.Div(
                    _short_text(record.get("text"), max_length=360),
                    className="input-evidence-text",
                ),
            ],
            className="input-evidence-card",
        )

    def evidence_panel(
        panel_title: str,
        panel_records: list[dict[str, Any]],
        class_name: str,
    ) -> html.Div | None:
        if not panel_records:
            return None
        shownRecords = panel_records[:max_rows]
        return html.Div(
            [
                html.Div(
                    [
                        html.Div(panel_title, className="input-evidence-panel-title"),
                        html.Div(
                            f"{len(panel_records)} rows",
                            className="input-card-count",
                        ),
                    ],
                    className="input-evidence-panel-head",
                ),
                html.Div(
                    [evidence_card(record) for record in shownRecords],
                    className="input-evidence-list",
                ),
                html.Div(
                    f"+ {len(panel_records) - max_rows} more rows",
                    className="input-reconstruction-more",
                )
                if len(panel_records) > max_rows
                else None,
            ],
            className=f"input-evidence-panel {class_name}",
        )

    rawRecords = [
        record
        for record in cleaned
        if record.get("source_type") in {"raw_ocr_tile", "combined_ocr_text"}
    ]
    vlmRecords = [
        record
        for record in cleaned
        if record.get("source_type") in {"vlm_table", "pp_table"}
    ]
    webRecords = [
        record
        for record in cleaned
        if record.get("source_type") in {"notice_field", "notice_option"}
    ]
    otherRecords = [
        record
        for record in cleaned
        if record.get("source_type")
        not in {
            "raw_ocr_tile",
            "combined_ocr_text",
            "vlm_table",
            "pp_table",
            "notice_field",
            "notice_option",
        }
    ]
    panels = [
        panel
        for panel in [
            evidence_panel("OCR 원문", rawRecords, "raw"),
            evidence_panel("VLM 표 원문", vlmRecords, "vlm"),
            evidence_panel("웹 수집 원문", webRecords, "web"),
            evidence_panel("기타 evidence", otherRecords, "other"),
        ]
        if panel is not None
    ]

    return html.Div(
        [
            html.Div(
                [
                    html.Div(title, className="input-card-title"),
                    html.Div(f"{len(cleaned)} rows", className="input-card-count"),
                ],
                className="input-card-head",
            ),
            html.Div(panels, className="input-evidence-grid"),
        ],
        className="input-card-section",
    )


def _reconstructed_tables_widget(
    title: str,
    tables: list[Any],
    *,
    source_labels: dict[str, Any] | None = None,
    evidence_rows: list[Any] | None = None,
    max_rows_per_table: int = 12,
) -> html.Div | None:
    cleanedTables = [table for table in tables if isinstance(table, dict)]
    if not cleanedTables:
        return None

    labels = source_labels or {}
    evidenceRows = evidence_rows or []
    tableBlocks: list[Any] = []
    for tableIndex, table in enumerate(cleanedTables, start=1):
        rows = table.get("rows") or []
        if not isinstance(rows, list) or not rows:
            continue
        tableName = table.get("table_name") or f"Table {tableIndex}"
        tableRows: list[Any] = []
        for row in [item for item in rows if isinstance(item, dict)][:max_rows_per_table]:
            sourceRefs = row.get("source_refs") or []
            if isinstance(sourceRefs, list):
                sourceText = ", ".join(
                    _display_source_label(labels.get(str(ref), ref))
                    for ref in sourceRefs[:3]
                    if str(ref).strip()
                )
            else:
                sourceText = str(sourceRefs or "")
            tableRows.append(
                html.Tr(
                    [
                        html.Td(
                            _short_text(row.get("field_name"), max_length=90),
                            className="input-reconstruction-primary",
                        ),
                        html.Td(_short_text(row.get("raw_value"), max_length=220)),
                        html.Td(
                            _short_text(
                                row.get("normalized_value") or row.get("raw_value"),
                                max_length=220,
                            ),
                        ),
                        html.Td(_short_text(row.get("unit"), max_length=50)),
                        html.Td(
                            _short_text(
                                row.get("daily_value_percent"),
                                max_length=60,
                            ),
                        ),
                        html.Td(_short_text(sourceText, max_length=160)),
                    ]
                )
            )
        more = None
        if len(rows) > max_rows_per_table:
            more = html.Div(
                f"+ {len(rows) - max_rows_per_table} more rows",
                className="input-reconstruction-more",
            )
        productContextText = _table_product_context_text(table, evidenceRows)
        tableBlocks.append(
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Div(
                                        _short_text(tableName, max_length=120),
                                        className="input-card-title",
                                    ),
                                    html.Div(
                                        productContextText,
                                        className="input-card-subtitle",
                                    )
                                    if productContextText
                                    else None,
                                ],
                            ),
                            html.Div(f"{len(rows)} rows", className="input-card-count"),
                        ],
                        className="input-reconstruction-section-head",
                    ),
                    html.Div(
                        html.Table(
                            [
                                html.Thead(
                                    html.Tr(
                                        [
                                            html.Th("항목"),
                                            html.Th("원문 값"),
                                            html.Th("정규화 값"),
                                            html.Th("단위"),
                                            html.Th("일일 기준"),
                                            html.Th("출처"),
                                        ]
                                    )
                                ),
                                html.Tbody(tableRows),
                            ],
                            className="input-reconstruction-table",
                        ),
                        className="input-reconstruction-table-wrap",
                    ),
                    more,
                ],
                className="input-reconstruction-table-block",
            )
        )

    if not tableBlocks:
        return None
    return html.Div(
        [
            html.Div(
                [
                    html.Div(title, className="input-card-title"),
                    html.Div(f"{len(cleanedTables)} tables", className="input-card-count"),
                ],
                className="input-reconstruction-section-head",
            ),
            *tableBlocks,
        ],
        className="input-reconstruction-section",
    )


def _simple_reconstruction_table_widget(
    title: str,
    tables: list[dict[str, Any]],
    value_header: str,
) -> html.Div | None:
    if not tables:
        return None
    blocks: list[Any] = []
    for table in tables:
        rows = table.get("rows") or []
        if not rows:
            continue
        blocks.append(
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(
                                _short_text(table.get("table_name"), max_length=120),
                                className="input-card-title",
                            ),
                            html.Div(f"{len(rows)} rows", className="input-card-count"),
                        ],
                        className="input-reconstruction-section-head",
                    ),
                    html.Div(
                        html.Table(
                            [
                                html.Thead(
                                    html.Tr(
                                        [
                                            html.Th("항목"),
                                            html.Th(value_header),
                                        ]
                                    )
                                ),
                                html.Tbody(
                                    [
                                        html.Tr(
                                            [
                                                html.Td(
                                                    _short_text(
                                                        row.get("field_name"),
                                                        max_length=90,
                                                    ),
                                                    className="input-reconstruction-primary",
                                                ),
                                                html.Td(
                                                    _expandable_text(
                                                        row.get("value"),
                                                        max_length=360,
                                                    ),
                                                    className="input-reconstruction-raw-value",
                                                ),
                                            ]
                                        )
                                        for row in rows
                                        if isinstance(row, dict)
                                    ]
                                ),
                            ],
                            className="input-reconstruction-table simple",
                        ),
                        className="input-reconstruction-table-wrap",
                    ),
                ],
                className="input-reconstruction-table-block",
            )
        )
    if not blocks:
        return None
    return html.Div(
        [
            html.Div(title, className="input-reconstruction-pane-title"),
            *blocks,
        ],
        className="input-reconstruction-pane",
    )


def _simple_reconstruction_rows_widget(
    rows: list[dict[str, Any]],
    value_header: str,
) -> html.Div | None:
    cleanedRows = [row for row in rows if isinstance(row, dict)]
    if not cleanedRows:
        return html.Div("표시할 값이 없습니다.", className="drawer-empty-state compact")
    return html.Div(
        html.Table(
            [
                html.Thead(
                    html.Tr(
                        [
                            html.Th("항목"),
                            html.Th(value_header),
                        ]
                    )
                ),
                html.Tbody(
                    [
                        html.Tr(
                            [
                                html.Td(
                                    _short_text(row.get("field_name"), max_length=90),
                                    className="input-reconstruction-primary",
                                ),
                                html.Td(
                                    _expandable_text(
                                        row.get("value"),
                                        max_length=420,
                                    ),
                                    className="input-reconstruction-raw-value",
                                ),
                            ]
                        )
                        for row in cleanedRows
                    ]
                ),
            ],
            className="input-reconstruction-table simple",
        ),
        className="input-reconstruction-table-wrap",
    )


def _reconstruction_option_compare_widget(
    sections: list[dict[str, Any]],
) -> html.Div | None:
    if not sections:
        return None
    blocks: list[Any] = []
    for section in sections:
        beforeRows = section.get("before_rows") or []
        afterRows = section.get("after_rows") or []
        rowCount = max(len(beforeRows), len(afterRows))
        blocks.append(
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(
                                _short_text(section.get("table_name"), max_length=120),
                                className="input-card-title",
                            ),
                            html.Div(f"{rowCount} rows", className="input-card-count"),
                        ],
                        className="input-reconstruction-section-head",
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Div(
                                        "교정 전 원문값",
                                        className="input-reconstruction-pane-title",
                                    ),
                                    _simple_reconstruction_rows_widget(
                                        beforeRows,
                                        "OCR/VLM 판독값",
                                    ),
                                ],
                                className="input-reconstruction-pane",
                            ),
                            html.Div(
                                [
                                    html.Div(
                                        "교정 후 LLM Reconstruction",
                                        className="input-reconstruction-pane-title",
                                    ),
                                    _simple_reconstruction_rows_widget(
                                        afterRows,
                                        "LLM 교정값",
                                    ),
                                ],
                                className="input-reconstruction-pane",
                            ),
                        ],
                        className="input-reconstruction-compare-grid",
                    ),
                ],
                className="input-reconstruction-option-section",
            )
        )
    return html.Div(blocks, className="input-reconstruction-option-list")


def _reconstruction_compare_widget(
    before_tables: list[dict[str, Any]],
    after_tables: list[dict[str, Any]],
) -> html.Div | None:
    beforePanel = _simple_reconstruction_table_widget(
        "교정 전 VLM 표 원문",
        before_tables,
        "VLM 판독값",
    )
    afterPanel = _simple_reconstruction_table_widget(
        "교정 후 LLM Reconstruction",
        after_tables,
        "LLM 교정값",
    )
    if beforePanel is None and afterPanel is None:
        return None
    return html.Div(
        [
            beforePanel
            or html.Div("VLM 표 원문이 없습니다.", className="drawer-empty-state"),
            afterPanel
            or html.Div("LLM 교정 결과가 없습니다.", className="drawer-empty-state"),
        ],
        className="input-reconstruction-compare-grid",
    )


def input_processing_detail_card(
    input_processing_view: dict[str, Any],
    drawerMode: str,
) -> html.Div | None:
    if not input_processing_view:
        return None

    sourceEvidencePreview = input_processing_view.get("detail_evidence_rows") or []
    if not isinstance(sourceEvidencePreview, list):
        sourceEvidencePreview = []
    if drawerMode == "raw":
        basicInfo = input_processing_view.get("page_product_facts") or {}
        if not isinstance(basicInfo, dict):
            basicInfo = {}
        rawPanels = [
            panel
            for panel in [
                _product_page_basic_card(basicInfo),
                _source_evidence_table(
                    "가공 전 OCR/VLM Evidence 원문",
                    sourceEvidencePreview,
                    max_rows=12,
                ),
            ]
            if panel is not None
        ]
        if not rawPanels:
            return None
        return html.Div(
            rawPanels,
            className="input-detail-result drawer-content-stack",
        )

    status = input_processing_view.get("reconstruction_status") or {}
    if not isinstance(status, dict):
        status = {}
    productFacts = input_processing_view.get("classification_input_facts") or []
    unresolvedFacts = input_processing_view.get("unresolved_input_facts") or []
    conflicts = input_processing_view.get("input_fact_conflicts") or []
    factTexts = input_processing_view.get("classification_input_text_lines") or []
    if not isinstance(productFacts, list):
        productFacts = []
    if not isinstance(unresolvedFacts, list):
        unresolvedFacts = []
    if not isinstance(conflicts, list):
        conflicts = [str(conflicts)] if str(conflicts).strip() else []
    if not isinstance(factTexts, list):
        factTexts = []
    reconstructedTables = input_processing_view.get("reconstructed_detail_tables") or []
    if not isinstance(reconstructedTables, list):
        reconstructedTables = []
    sourceLabels = input_processing_view.get("evidence_source_labels") or {}
    if not isinstance(sourceLabels, dict):
        sourceLabels = {}
    reconstructionMode = status.get("mode") or "unknown"
    reconstructionError = status.get("error")
    fallbackReason = status.get("fallback_reason")
    ingredientComparePanel = _reconstruction_option_compare_widget(
        _ingredient_fact_compare_sections([*productFacts, *unresolvedFacts]),
    )
    genericProductFacts = productFacts
    genericUnresolvedFacts = unresolvedFacts
    if ingredientComparePanel is not None:
        genericProductFacts = [
            fact
            for fact in productFacts
            if not (isinstance(fact, dict) and _is_ingredient_text(fact.get("field_name")))
        ]
        genericUnresolvedFacts = [
            fact
            for fact in unresolvedFacts
            if not (isinstance(fact, dict) and _is_ingredient_text(fact.get("field_name")))
        ]
    afterPanel = (
        _reconstructed_tables_widget(
            "LLM 복원 후 구조화된 상세 표",
            reconstructedTables,
            source_labels=sourceLabels,
            evidence_rows=sourceEvidencePreview,
        )
        or _reconstruction_fact_table(
            "LLM 복원 후 구조화된 상세 facts",
            productFacts,
            source_labels=sourceLabels,
        )
    )

    return html.Div(
        [
            html.Div(
                html.Table(
                    [
                        html.Thead(
                            html.Tr(
                                [
                                    html.Th("LLM"),
                                    html.Th("Mode"),
                                    html.Th("상세 표"),
                                    html.Th("분류 facts"),
                                    html.Th("텍스트 라인"),
                                ]
                            )
                        ),
                        html.Tbody(
                            html.Tr(
                                [
                                    html.Td(
                                        "on"
                                        if status.get("used_llm_reconstruction")
                                        else "off"
                                    ),
                                    html.Td(reconstructionMode),
                                    html.Td(
                                        status.get("detail_table_count")
                                        or len(reconstructedTables)
                                    ),
                                    html.Td(
                                        status.get("classification_fact_count")
                                        or len(productFacts)
                                    ),
                                    html.Td(
                                        status.get("classification_text_line_count")
                                        or len(factTexts)
                                    ),
                                ]
                            )
                        ),
                    ],
                    className=(
                        "input-reconstruction-table "
                        "input-reconstruction-status-table"
                    ),
                ),
                className="input-reconstruction-table-wrap",
            ),
            html.Div(
                [
                    html.Div("Input reconstruction issue", className="drawer-notice-title"),
                    html.Div(
                        reconstructionError or fallbackReason or "fallback reconstruction is being used",
                        className="drawer-notice-text",
                    ),
                ],
                className="drawer-notice warning",
            ) if reconstructionError or (
                fallbackReason
                and not status.get("used_llm_reconstruction")
            ) else None,
            ingredientComparePanel,
            afterPanel,
            _reconstruction_fact_table(
                "최종 분류 입력 facts",
                genericProductFacts,
                source_labels=sourceLabels,
                max_rows=16,
            ) if genericProductFacts else None,
            html.Details(
                [
                    html.Summary(
                        "Classification input text lines",
                        style={
                            "cursor": "pointer",
                            "fontSize": "12px",
                            "fontWeight": 850,
                            "color": "#334155",
                        },
                    ),
                    _classification_fact_text_table(factTexts, title=""),
                ],
                open=False,
                style={"marginTop": "10px"},
            ) if factTexts else None,
            _reconstruction_fact_table(
                "미해결 facts",
                genericUnresolvedFacts,
                source_labels=sourceLabels,
                max_rows=6,
            ),
            html.Div(
                [
                    html.Div("Conflicts", className="drawer-notice-title"),
                    html.Ul(
                        [html.Li(_short_text(conflict, max_length=220)) for conflict in conflicts[:6]],
                        className="drawer-notice-list",
                    ),
                ],
                className="drawer-notice danger",
            ) if conflicts else None,
        ],
        className="input-reconstruction-result drawer-content-stack",
    )


def input_processing_view_card(
    input_processing_view: dict[str, Any] | None,
    *,
    drawerMode: str | bool | None = None,
) -> html.Div | None:
    if not isinstance(input_processing_view, dict) or not input_processing_view:
        return None

    basicInfo = input_processing_view.get("page_product_facts") or {}
    if not isinstance(basicInfo, dict):
        basicInfo = {}
    basicPanel = _product_page_basic_card(basicInfo)
    detailDrawer = input_processing_detail_drawer(input_processing_view, drawerMode)
    panels = [panel for panel in [basicPanel, detailDrawer] if panel is not None]
    if not panels:
        return None
    return html.Div(
        panels,
        style={
            "marginBottom": "20px",
        },
    )


def input_processing_detail_drawer(
    input_processing_view: dict[str, Any],
    drawerMode: str | bool | None,
) -> html.Div | None:
    activeMode = drawerMode if drawerMode in {"raw", "reconstructed"} else ""
    detailCard = (
        input_processing_detail_card(input_processing_view, activeMode)
        if activeMode
        else None
    )
    if detailCard is None:
        return None
    isRaw = activeMode == "raw"
    return _popup_card(
        popupId="input-detail-drawer",
        cardClassName="input-detail-popup-card",
        title=html.Div(
            [
                html.Div(
                    [
                        html.Div(
                            "웹스크롤링 & OCR 원문" if isRaw else "LLM Reconstruction 결과",
                            className="drawer-title-main",
                        ),
                        html.Div(
                            (
                                "가공 전 수집 데이터"
                                if isRaw
                                else "LLM이 evidence에서 선택/정규화한 데이터"
                            ),
                            className="drawer-title-sub",
                        ),
                    ]
                ),
                dmc.Button(
                    "닫기",
                    id={
                        "type": "input-detail-drawer-close",
                        "target": "input-processing",
                    },
                    variant="subtle",
                    color="gray",
                    size="xs",
                    radius="sm",
                ),
            ],
            className="drawer-title",
        ),
        body=detailCard,
    )


def _popup_card(
    *,
    popupId: str,
    title: html.Div,
    body: Any,
    cardClassName: str = "",
) -> html.Div:
    return html.Div(
        html.Div(
            [
                title,
                html.Div(body, className="drawer-panel-body popup-card-body"),
            ],
            className=f"popup-card {cardClassName}".strip(),
            role="dialog",
        ),
        id=popupId,
        className="popup-card-overlay",
    )


def render_input_form(
    facts: dict[str, Any] | None = None,
    *,
    runDisabled: bool = False,
) -> html.Div:
    facts = facts or {}
    return html.Div(
        [
            dcc.Input(
                id="ipt-product-name",
                type="text",
                value=facts.get("product_name") or "",
                style={"display": "none"},
            ),
            dcc.Textarea(
                id="ipt-description",
                value=facts.get("description") or "",
                style={"display": "none"},
            ),
            html.Div("새 분석 생성", className="input-launch-title"),
            html.Div(
                [
                    html.Div(
                        [
                            html.Label("상품 링크", className="input-launch-label"),
                            html.Div(
                                [
                                    html.Img(
                                        src="/assets/logo_purple.png",
                                        className="input-launch-market-logo",
                                    ),
                                    dcc.Input(
                                        id="ipt-kurly-url",
                                        type="text",
                                        placeholder="Kurly 상품 URL을 입력하세요",
                                        value=facts.get("url") or "",
                                        className="input-launch-url",
                                    ),
                                ],
                                className="input-launch-url-wrap",
                            ),
                        ],
                        className="input-launch-field",
                    ),
                    html.Div(
                        [
                            html.Button(
                                [html.Span("+", className="input-launch-plus"), "생성"],
                                id="btn-run",
                                n_clicks=0,
                                disabled=runDisabled,
                                className="run-pipeline-button input-launch-button",
                            ),
                            html.Button(
                                "재복원",
                                id="btn-rerun-reconstruction",
                                n_clicks=0,
                                disabled=runDisabled,
                                className="run-pipeline-button",
                                style={"display": "none"},
                            ),
                        ],
                        className="input-launch-actions",
                    ),
                ],
                className="input-launch-grid",
            ),
        ],
        className="input-launch-card",
    )


def _event_summary(event: dict[str, Any]) -> html.Div | None:
    partial = event.get("partial_result") or {}
    stage = event.get("stage") or ""
    status = event.get("status") or ""

    if stage == "Input_Intake":
        raw = event.get("collected_input_summary") or {}
        if not raw:
            return None
        url_intake = raw.get("url_intake") or {}
        ocr_summary = url_intake.get("ocr") or {}
        return html.Div(
            [
                _product_page_basic_card(raw),
                html.Div(
                    "ocr_text chunks: {0} / composition: {1}".format(
                        raw.get("ocr_text_count")
                        or len(raw.get("ocr_text") or []),
                        raw.get("composition_count")
                        or len(raw.get("composition") or []),
                    )
                ),
                html.Div(
                    (
                        "URL collection: ocr_images={0}, combined_ocr_chars={1}"
                    ).format(
                        ocr_summary.get("image_result_count")
                        or url_intake.get("ocr_image_count", "-"),
                        ocr_summary.get("combined_text_length")
                        or url_intake.get("combined_ocr_text_length", "-"),
                    )
                ) if url_intake else None,
                html.Div(
                    (
                        "Input reconstruction: mode={0}, llm={1}, "
                        "classification_text_lines={2}"
                    ).format(
                        raw.get("input_reconstruction_mode") or "-",
                        "yes" if raw.get("input_reconstruction_available") else "no",
                        raw.get("classification_input_fact_texts_count"),
                    )
                ) if raw.get("input_reconstruction_available") else None,
                detail_block(
                    "URL collection pipeline steps",
                    url_intake.get("pipeline_steps") or [],
                    max_height=260,
                ) if url_intake.get("pipeline_steps") else None,
            ],
            style={"fontSize": "12px", "color": "#334155", "marginTop": "6px"},
        )

    if stage == "Evidence_Intake_Agent":
        if status == "running":
            return html.Div(
                "Product Evidence Builder 실행 전입니다. 완료 이벤트에서 실제 OCR/composition count를 표시합니다.",
                style={"fontSize": "12px", "color": "#64748b", "marginTop": "6px"},
            )
        pes = partial.get("input_processing_summary") or {}
        if not pes:
            return html.Div(
                "Product evidence 생성 완료. 상세 audit은 좌측 관리/디버그 메뉴에서 확인할 수 있습니다.",
                style={"fontSize": "12px", "color": "#64748b", "marginTop": "6px"},
            )
        return html.Div(
            [
                html.Div(f"product_id: {pes.get('product_id') or '-'}"),
                html.Div(f"observed: {pes.get('product_name') or '-'} / OCR {pes.get('ocr_text_count') or 0} chunks"),
                html.Div(f"composition facts: {pes.get('composition_count') or 0}"),
                html.Div(f"inferred facts: {pes.get('inferred_fact_count') or 0}"),
                html.Div(f"unknowns: {', '.join(pes.get('unknowns') or []) or '-'}"),
            ],
            style={"fontSize": "12px", "color": "#334155", "marginTop": "6px"},
        )

    if stage == "Classification_Agent":
        if status == "running":
            return html.Div(
                "Classification retriever/LLM/TARIC branch resolver 실행 중입니다. 완료 이벤트에서 후보 수를 표시합니다.",
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
                            f"({c.get('candidate_source') or 'classifier'})"
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
                    dp,
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


def render_stage_events(result: dict[str, Any]) -> html.Div:
    status = result.get("job_status") or result.get("status") or "idle"
    events = result.get("events") or []
    rows = []
    for event in events[-18:]:
        st = event.get("status") or "running"
        color = "#166534" if st == "completed" else "#b91c1c" if st == "failed" else "#6d3fd6"
        bg = "#f0fdf4" if st == "completed" else "#fef2f2" if st == "failed" else "#f3e8ff"
        rows.append(
            html.Div(
                [
                    html.Span(event.get("ts") or "", style={**MONO, "color": "#64748b", "marginRight": "8px"}),
                    html.Span(st.upper(), style={**PILL, "background": bg, "color": color}),
                    html.Span(display_stage_name(event.get("stage")), style={"fontWeight": 850}),
                    html.Div(display_stage_message(event.get("message")), style={"fontSize": "12px", "color": "#334155", "marginTop": "4px"}),
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


def _event_status(events: list[Any], stageNames: set[str]) -> str:
    matched = [
        event
        for event in events
        if isinstance(event, dict)
        and str(event.get("stage") or "") in stageNames
    ]
    if not matched:
        return "idle"
    return str(matched[-1].get("status") or "idle")


def _pipeline_step_statuses(result: dict[str, Any]) -> dict[str, dict[str, str]]:
    events = result.get("events") or []
    if not isinstance(events, list):
        events = []
    jobStatus = result.get("job_status") or result.get("status") or "idle"
    inputView = result.get("input_processing_view") or {}
    if not isinstance(inputView, dict):
        inputView = {}
    reconstructionStatus = inputView.get("reconstruction_status") or {}
    if not isinstance(reconstructionStatus, dict):
        reconstructionStatus = {}
    candidateSet = result.get("candidate_code_set") or {}
    if not isinstance(candidateSet, dict):
        candidateSet = {}
    candidates = candidateSet.get("candidates") or []
    if not isinstance(candidates, list):
        candidates = []

    collectStatus = _event_status(
        events,
        {"Input_Intake", "Evidence_Intake_Agent", "Product_Intake"},
    )
    if inputView and collectStatus == "idle":
        collectStatus = "completed"
    if collectStatus == "idle" and jobStatus in {"queued", "running"}:
        collectStatus = "running"

    reconstructStatus = "idle"
    if reconstructionStatus.get("error"):
        reconstructStatus = "failed"
    elif inputView:
        reconstructStatus = "completed"
    elif collectStatus == "completed" and jobStatus in {"queued", "running"}:
        reconstructStatus = "running"

    candidateEventStatus = _event_status(events, {"Classification_Agent", "Classification"})
    candidateStatus = "completed" if candidates else candidateEventStatus
    if candidateStatus == "idle" and reconstructStatus == "completed" and jobStatus in {"queued", "running"}:
        candidateStatus = "running"

    hasClassificationStatus = bool(candidateSet.get("classification_status"))
    validationStatus = "idle"
    if candidateEventStatus == "failed":
        validationStatus = "failed"
    elif candidateEventStatus == "completed" and candidates:
        validationStatus = "completed"
    elif candidateEventStatus == "completed" and hasClassificationStatus:
        validationStatus = "completed"
    elif candidateEventStatus == "running":
        validationStatus = "running"
    elif candidates:
        validationStatus = "completed"

    return {
        "collect": {
            "status": collectStatus,
            "detail": "상품 페이지, 상세 이미지, OCR evidence 수집",
            "meta": _progress_collect_meta(inputView),
        },
        "reconstruct": {
            "status": reconstructStatus,
            "detail": "PaddleOCR-VL 표/OCR 결과를 구조화하고 LLM reconstruction 반영",
            "meta": _progress_reconstruction_meta(reconstructionStatus),
        },
        "candidate": {
            "status": candidateStatus,
            "detail": "정적 후보 산출 및 TARIC branch 연결",
            "meta": f"{len(candidates)} candidates",
        },
        "validation": {
            "status": validationStatus,
            "detail": "후보와 수집 증거 간 모순/부족 정보 검증",
            "meta": _progress_validation_meta(candidates),
        },
    }


def pipeline_step_statuses(result: dict[str, Any]) -> dict[str, dict[str, str]]:
    return _pipeline_step_statuses(result)


def _progress_collect_meta(inputView: dict[str, Any]) -> str:
    rows = inputView.get("detail_evidence_rows") or []
    if isinstance(rows, list) and rows:
        return f"{len(rows)} evidence rows"
    pageFacts = inputView.get("page_product_facts") or {}
    if isinstance(pageFacts, dict) and any(str(value or "").strip() for value in pageFacts.values()):
        return "page facts collected"
    return "waiting for input"


def _progress_reconstruction_meta(reconstructionStatus: dict[str, Any]) -> str:
    if not reconstructionStatus:
        return "waiting"
    if reconstructionStatus.get("error"):
        return str(reconstructionStatus.get("error") or "failed")[:80]
    mode = reconstructionStatus.get("mode") or "unknown"
    llm = "LLM on" if reconstructionStatus.get("used_llm_reconstruction") else "LLM off"
    tableCount = reconstructionStatus.get("detail_table_count") or 0
    factCount = reconstructionStatus.get("classification_fact_count") or 0
    return f"{mode} · {llm} · tables {tableCount} · facts {factCount}"


def _progress_validation_meta(candidates: list[Any]) -> str:
    if not candidates:
        return "waiting"
    statuses = [
        str(candidate.get("status") or "").strip()
        for candidate in candidates
        if isinstance(candidate, dict) and str(candidate.get("status") or "").strip()
    ]
    if not statuses:
        return "human review required"
    return ", ".join(statuses[:3])


def render_progress(result: dict[str, Any]) -> html.Div:
    stepStates = _pipeline_step_statuses(result)
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Div(className="pipeline-step-dot-core"),
                                ],
                                className=f"pipeline-step-dot {state['status']}",
                            ),
                            html.Div(step["title"], className="pipeline-step-title"),
                            html.Div(
                                "완료됨",
                                className=f"pipeline-step-notify {state['status']}",
                            )
                            if state["status"] == "completed"
                            else None,
                        ],
                        id={"type": "pipeline-step-card", "step": step["key"]},
                        n_clicks=0,
                        className=(
                            f"pipeline-step-card {state['status']}"
                            + (
                                " clickable"
                                if step["key"] in {
                                    "collect",
                                    "reconstruct",
                                    "candidate",
                                    "validation",
                                }
                                and state["status"] == "completed"
                                else ""
                            )
                        ),
                    )
                    for step in PROGRESS_STEP_DEFINITIONS
                    for state in [stepStates[step["key"]]]
                ],
                className="pipeline-progress",
            )
        ],
        className="pipeline-progress-shell",
    )


def render_candidate_cards(result: dict[str, Any]) -> html.Div:
    ccs = result.get("candidate_code_set") or {}
    candidates = ccs.get("candidates") or []
    if not isinstance(candidates, list):
        candidates = []
    if not candidates:
        if isinstance(ccs, dict) and ccs.get("classification_status"):
            return _classification_unresolved_card(ccs)
        return html.Div("분류 후보가 없습니다.", style=PLACEHOLDER)

    cards: list[Any] = []
    packagesByTaric = _document_packages_by_taric(result)
    maxScore = max((_candidate_total_score(cand) for cand in candidates if isinstance(cand, dict)), default=0.0)
    candidateCount = len(candidates)

    for displayRank, cand in enumerate(candidates, start=1):
        if not isinstance(cand, dict):
            continue
        cards.append(
            _candidate_result_card(
                cand,
                displayRank=displayRank,
                candidateCount=candidateCount,
                maxScore=maxScore,
                packagesByTaric=packagesByTaric,
                interactive=True,
                jobStatus=result.get("job_status"),
            )
        )
    return html.Div(
        [
            html.Div(
                [
                    html.Div("TARIC 후보", className="candidate-result-title"),
                    html.Div(
                        f"{len(candidates)}개 후보 · 카드를 클릭하면 연결된 TARIC 문서 패키지를 확인합니다.",
                        className="candidate-result-subtitle",
                    ),
                ],
                className="candidate-result-heading",
            ),
            html.Div(
                cards,
                className="candidate-result-card-grid",
            ),
        ],
        className="candidate-result-shell",
    )


def _candidate_result_card(
    candidate: dict[str, Any],
    *,
    displayRank: int,
    candidateCount: int,
    maxScore: float,
    packagesByTaric: dict[str, list[dict[str, Any]]],
    interactive: bool,
    jobStatus: Any = None,
) -> html.Button | html.Div:
    themeClass = _candidate_theme_class(candidate)
    branchList = _candidate_branch_list(candidate)
    linkedBranchCount = sum(
        1
        for branch in branchList
        if _document_packages_for_taric(packagesByTaric, branch.get("taric10"))
    )
    scoreRatio = _candidate_score_ratio(candidate, displayRank, candidateCount, maxScore)
    isLinkingDocument = jobStatus in {"queued", "running"} and linkedBranchCount < len(branchList)
    linkedPackageCounts = [
        _document_package_counts(packages[0])
        for branch in branchList
        for packages in [_document_packages_for_taric(packagesByTaric, branch.get("taric10"))]
        if packages and isinstance(packages[0], dict)
    ]
    requiredCount = sum(counts["required"] for counts in linkedPackageCounts)
    checkCount = sum(counts["customs"] + counts["regulations"] for counts in linkedPackageCounts)
    missingCount = sum(counts["missing"] for counts in linkedPackageCounts)
    children = [
        html.Div(
            [
                html.Div(className="candidate-dashboard-folder", title="문서 패키지"),
                html.Div(f"{round(scoreRatio * 100)}%", className="candidate-dashboard-score"),
            ],
            className="candidate-dashboard-side",
        ),
        html.Div(
            [
                html.Div(
                    [
                        html.Div(candidate.get("taric10") or candidate.get("cn8") or "-", className="candidate-card-code"),
                        html.Span(_candidate_theme_label(candidate), className=f"candidate-card-badge {themeClass}"),
                    ],
                    className="candidate-card-top",
                ),
                html.Div(
                    _candidate_hierarchy_text(candidate),
                    className="candidate-card-route",
                    title=_candidate_hierarchy_text(candidate),
                ),
                html.Div(
                    _candidate_score_segments(scoreRatio),
                    className="candidate-card-score-bars",
                    title=f"score ratio {scoreRatio:.2f}",
                ),
                html.Div(
                    [
                        html.Span(f"CN8 {candidate.get('cn8') or '-'} · branch {len(branchList)} · "),
                        html.Span(className="document-icon", title="문서"),
                        html.Span(f" {linkedBranchCount}", className="candidate-card-doc-count"),
                    ],
                    className="candidate-card-meta",
                ),
                html.Div(
                    [
                        html.Span(f"연결 {linkedBranchCount}/{len(branchList) or 1}"),
                        html.Span(f"서류 {requiredCount}"),
                        html.Span(f"확인 {checkCount}"),
                        html.Span(f"미확인 {missingCount}"),
                    ],
                    className="candidate-dashboard-reveal",
                ),
            ],
            className="candidate-dashboard-main",
        ),
    ]
    className = f"candidate-result-card {themeClass}" + (" linking" if isLinkingDocument else "")
    if not interactive:
        return html.Div(children, className=f"{className} static")
    return html.Button(
        children,
        id={
            "type": "candidate-result-card",
            "candidate": _candidate_key(candidate, displayRank),
        },
        type="button",
        n_clicks=0,
        className=className,
    )


def _candidate_branch_list(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    taric10 = candidate.get("taric10") or ""
    branches = candidate.get("taric10_branch_candidates") or []
    branchList = [
        branch
        for branch in branches
        if isinstance(branch, dict) and branch.get("taric10")
    ]
    if branchList:
        return branchList
    return [{"taric10": taric10, "branch_description": "primary TARIC10"}] if taric10 else []


def _document_packages_by_taric(result: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    packagesByTaric: dict[str, list[dict[str, Any]]] = {}
    documentPackages = list(result.get("document_packages") or [])
    primaryDocumentPackage = result.get("document_package")
    if isinstance(primaryDocumentPackage, dict):
        documentPackages.append(primaryDocumentPackage)
    for package in documentPackages:
        if not isinstance(package, dict):
            continue
        packageTaric = str(package.get("taric10") or "")
        packageKeys = {packageTaric, _clean_code(packageTaric)}
        for packageKey in packageKeys:
            if packageKey:
                packagesByTaric.setdefault(packageKey, []).append(package)
    return packagesByTaric


def _document_packages_for_taric(
    packagesByTaric: dict[str, list[dict[str, Any]]],
    taric10: Any,
) -> list[dict[str, Any]]:
    rawTaric = str(taric10 or "")
    return packagesByTaric.get(rawTaric) or packagesByTaric.get(_clean_code(rawTaric)) or []


def _clean_code(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _candidate_key(candidate: dict[str, Any], displayRank: int) -> str:
    return str(
        candidate.get("candidate_id")
        or candidate.get("taric10")
        or candidate.get("cn8")
        or displayRank
    )


def _candidate_total_score(candidate: dict[str, Any]) -> float:
    tree = candidate.get("candidate_static_tree") or {}
    if not isinstance(tree, dict):
        return 0.0
    try:
        return float(tree.get("total_score") or 0)
    except (TypeError, ValueError):
        return 0.0


def _candidate_score_ratio(
    candidate: dict[str, Any],
    displayRank: int,
    candidateCount: int,
    maxScore: float,
) -> float:
    score = _candidate_total_score(candidate)
    if maxScore > 0 and score > 0:
        return max(0.12, min(1.0, score / maxScore))
    if candidateCount <= 1:
        return 1.0
    return max(0.12, 1.0 - ((displayRank - 1) / candidateCount))


def _candidate_score_segments(scoreRatio: float, segmentCount: int = 8) -> list[html.Span]:
    filled = max(1, min(segmentCount, round(scoreRatio * segmentCount)))
    return [
        html.Span(className=f"candidate-card-score-segment {'filled' if index < filled else ''}".strip())
        for index in range(segmentCount)
    ]


def _candidate_hierarchy_text(candidate: dict[str, Any]) -> str:
    nodes = _candidate_nodes(candidate)
    parts = []
    for node in nodes:
        label = str(node.get("label") or node.get("level") or "").upper()
        code = str(node.get("code") or "").strip()
        description = _short_text(node.get("description") or "", max_length=26)
        parts.append(" ".join(part for part in (label, code, description) if part and part != "-"))
    if candidate.get("taric10"):
        parts.append(f"TARIC {candidate.get('taric10')}")
    return " → ".join(parts) or "-"


def _classification_unresolved_card(candidateSet: dict[str, Any]) -> html.Div:
    shortlisted = candidateSet.get("shortlisted_candidates") or []
    if not isinstance(shortlisted, list):
        shortlisted = []
    return html.Div(
        [
            html.Div("분류 후보 산출 보류", className="classification-unresolved-title"),
            html.Div(
                "정적 후보 또는 LLM 검증 결과를 후보로 확정하지 않았습니다. 추가 상품 정보나 검토가 필요합니다.",
                className="classification-unresolved-text",
            ),
            html.Div(
                [
                    _small("status", candidateSet.get("classification_status")),
                    _small("reason", candidateSet.get("failure_reason")),
                    _small("shortlisted", len(shortlisted)),
                ],
                style={"display": "flex", "gap": "8px", "flexWrap": "wrap", "marginTop": "10px"},
            ),
        ],
        className="classification-unresolved-surface",
    )


def _candidate_theme_class(candidate: dict[str, Any]) -> str:
    return "recommended" if candidate.get("llm_recommended") else "alternate"


def _candidate_theme_label(candidate: dict[str, Any]) -> str:
    if candidate.get("llm_recommended"):
        return "LLM 추천"
    status = str(candidate.get("status") or "").lower()
    if "insufficient" in status or "unresolved" in status:
        return "Insufficient"
    return "검토 후보"


def has_candidate_scope_tree(result: dict[str, Any] | None) -> bool:
    if not isinstance(result, dict):
        return False
    candidateSet = result.get("candidate_code_set") or {}
    return bool(_initial_candidate_scope(candidateSet))


def _classification_trace(candidateSet: dict[str, Any]) -> dict[str, Any]:
    trace = candidateSet.get("classification_trace") if isinstance(candidateSet, dict) else {}
    return trace if isinstance(trace, dict) else {}


def _trace_history(candidateSet: dict[str, Any]) -> list[dict[str, Any]]:
    history = _classification_trace(candidateSet).get("traversal_history") or []
    if not isinstance(history, list):
        return []
    return [entry for entry in history if isinstance(entry, dict)]


def _history_candidate_scope(entry: dict[str, Any]) -> list[dict[str, Any]]:
    scope = entry.get("candidate_scope") or []
    if not isinstance(scope, list):
        return []
    return [candidate for candidate in scope if isinstance(candidate, dict)]


def _initial_candidate_scope(candidateSet: dict[str, Any]) -> list[dict[str, Any]]:
    for entry in _trace_history(candidateSet):
        scope = _history_candidate_scope(entry)
        if scope:
            return scope
    candidates = candidateSet.get("candidates") if isinstance(candidateSet, dict) else []
    if not isinstance(candidates, list):
        return []
    return [candidate for candidate in candidates[:5] if isinstance(candidate, dict)]


def candidate_tree_drawer(
    result: dict[str, Any],
    drawerOpened: bool,
) -> html.Div | None:
    candidateSet = result.get("candidate_code_set") or {}
    initialCandidates = _initial_candidate_scope(candidateSet)
    if not initialCandidates:
        return None

    if not drawerOpened:
        return None

    return _popup_card(
        popupId="candidate-tree-drawer",
        cardClassName="candidate-tree-popup-card",
        title=html.Div(
            [
                html.Div(
                    [
                        html.Div("1차 후보군 통합 탐색 트리", className="drawer-title-main"),
                        html.Div("백트래킹 이전 정적 후보 산출 경로", className="drawer-title-sub"),
                    ]
                ),
                dmc.Button(
                    "닫기",
                    id={
                        "type": "candidate-tree-drawer-close",
                        "target": "candidate-tree",
                    },
                    variant="subtle",
                    color="gray",
                    size="xs",
                    radius="sm",
                ),
            ],
            className="drawer-title",
        ),
        body=html.Div(
            _candidate_merged_tree_panel(
                initialCandidates,
                title="",
            ),
        ),
    )


def _classification_unresolved_panel(candidateSet: dict[str, Any]) -> html.Div:
    return html.Div(
        [
            _classification_unresolved_card(candidateSet),
            (
                _classification_backtracking_route_panel(candidateSet, [])
                if _classification_trace(candidateSet).get("backtracking_occurred")
                else None
            ),
        ],
        className="candidate-tree-panel",
    )


def _candidate_nodes(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    tree = candidate.get("candidate_static_tree") or {}
    if not isinstance(tree, dict):
        tree = {}
    nodes = tree.get("nodes") or []
    if not isinstance(nodes, list) or not nodes:
        return [
            {
                "level": "cn8",
                "label": "CN8",
                "code": candidate.get("cn8") or "",
                "description": _candidate_reason_text(candidate),
                "score": "",
                "matched_keywords": [],
            }
        ]
    return [node for node in nodes if isinstance(node, dict)]


def _candidate_merged_tree_panel(
    candidates: list[Any],
    *,
    title: str = "통합 탐색 트리",
    nodeStates: dict[tuple[str, str], set[str]] | None = None,
    showMetrics: bool = True,
) -> html.Div:
    cleanCandidates = [candidate for candidate in candidates if isinstance(candidate, dict)]
    recommended = next(
        (candidate for candidate in cleanCandidates if candidate.get("llm_recommended")),
        cleanCandidates[0] if cleanCandidates else {},
    )
    return html.Div(
        [
            html.Div(
                [
                    _small("candidates", len(cleanCandidates)),
                    _small(
                        "recommended CN8"
                        if recommended.get("llm_recommended")
                        else "top CN8",
                        recommended.get("cn8"),
                    ),
                    _small(
                        "selected path"
                        if recommended.get("llm_recommended")
                        else "top path",
                        "LLM validation"
                        if recommended.get("llm_recommended")
                        else "static ranking",
                    ),
                ],
                className="candidate-tree-metrics",
            ) if showMetrics else None,
            html.Div(
                [
                    html.Div(title, className="candidate-tree-section-title")
                    if title
                    else None,
                    html.Ul(
                        [
                            _candidate_merged_branch(node)
                            for node in _build_merged_candidate_tree(
                                cleanCandidates,
                                nodeStates=nodeStates,
                            )
                        ],
                        className="candidate-outline-tree",
                    ),
                ],
                className="candidate-tree-section",
            ),
        ],
        className="candidate-tree-panel",
    )


def _classification_backtracking_route_panel(
    candidateSet: dict[str, Any],
    finalCandidates: list[dict[str, Any]],
) -> html.Div | None:
    trace = _classification_trace(candidateSet)
    history = _trace_history(candidateSet)
    initialCandidates = (
        _history_candidate_scope(history[0])
        if history
        else []
    )
    lastEntry = history[-1] if history else {}
    finalScope = (
        _history_candidate_scope(lastEntry)
        if "candidate_scope" in lastEntry
        else finalCandidates
    )
    backtrackingOccurred = bool(trace.get("backtracking_occurred"))

    if not backtrackingOccurred:
        return None

    sourceCandidates = _backtracking_source_candidates(
        history[0] if history else {},
    )
    targetLevel = str(trace.get("backtracking_target_level") or "").lower()
    combinedCandidates = _combine_candidate_scopes(
        initialCandidates or finalCandidates,
        [*finalScope, *finalCandidates],
    )
    nodeStates = _build_backtracking_node_states(sourceCandidates, targetLevel)
    sourceCodes = [
        str(candidate.get("cn8") or candidate.get("hs8") or "")
        for candidate in sourceCandidates
        if str(candidate.get("cn8") or candidate.get("hs8") or "").strip()
    ]
    reason = trace.get("backtracking_reason") or (
        history[0].get("backtracking_reason") if history else ""
    )
    if not reason:
        reason = next(
            (
                str(entry.get("error") or "").strip()
                for entry in reversed(history)
                if str(entry.get("error") or "").strip()
            ),
            str(candidateSet.get("failure_reason") or "").strip(),
        )
    retryCount = int(trace.get("retry_count") or max(0, len(history) - 1))
    sourceLabel = ", ".join(sourceCodes[:3]) or "초기 CN8 후보"
    targetLabel = targetLevel.upper() or "상위"
    basisText = _backtracking_basis_description(
        reason,
        sourceLabel=sourceLabel,
        targetLabel=targetLabel,
        retryCount=retryCount,
    )

    return html.Div(
        [
            html.Div(
                [
                    html.Div("백트래킹 근거", className="classification-backtracking-basis-title"),
                    html.Div(basisText, className="classification-backtracking-basis-text"),
                    html.Div(
                        [
                            html.Span(
                                f"재탐색 경계 {targetLabel}",
                                className="classification-backtracking-basis-tag",
                            ),
                            html.Span(
                                f"재검증 {retryCount}회",
                                className="classification-backtracking-basis-tag",
                            ),
                        ],
                        className="classification-backtracking-basis-tags",
                    ),
                ],
                className="classification-backtracking-basis",
            ),
            _backtracking_candidate_change_panel(
                initialCandidates or sourceCandidates,
                finalScope or finalCandidates,
            ),
            html.Div(
                [
                    html.Span("기본 탐색", className="candidate-tree-legend-item normal"),
                    html.Span("역방향 백트래킹 경로", className="candidate-tree-legend-item backtracking"),
                    html.Span("재탐색 추가 경로", className="candidate-tree-legend-item retry"),
                ],
                className="candidate-tree-legend",
            ),
            _candidate_merged_tree_panel(
                combinedCandidates,
                title="",
                nodeStates=nodeStates,
                showMetrics=False,
            ),
            html.Div(
                "재탐색 후보군이 없습니다.",
                className="classification-route-empty",
            )
            if not finalScope
            else None,
        ],
        className="classification-backtracking-route-panel",
    )


def _backtracking_basis_description(
    reason: Any,
    *,
    sourceLabel: str,
    targetLabel: str,
    retryCount: int,
) -> str:
    return (
        f"초기 후보({sourceLabel})를 검증했을 때 "
        f"{_backtracking_reason_korean(reason)} "
        f"그래서 후보를 바로 확정하지 않고 {targetLabel} 계층으로 되돌아가 "
        f"하위 후보를 다시 넓혀 탐색했습니다. 재검증은 {retryCount}회 수행됐습니다."
    )


def _backtracking_reason_korean(reason: Any) -> str:
    reasonText = str(reason or "").strip()
    lowerReason = reasonText.lower()
    if not lowerReason:
        return "현재 후보만으로 최종 선택 근거가 충분하지 않다는 신호가 있었습니다."
    if "insufficient" in lowerReason or "not enough" in lowerReason:
        return "상품 정보나 후보 근거가 부족해 현재 후보만으로는 선택하기 어렵다는 신호가 있었습니다."
    if any(token in lowerReason for token in ("mismatch", "conflict", "contradict", "unlikely")):
        return "수집된 상품 정보와 후보 설명이 맞지 않는다는 신호가 있었습니다."
    if "multiple" in lowerReason:
        return "여러 후보가 동시에 가능해 한 후보만 확정하기 어렵다는 신호가 있었습니다."
    if "invalid" in lowerReason or "retry" in lowerReason:
        return "검증 응답이 안정적으로 해석되지 않아 후보 범위를 다시 확인할 필요가 있었습니다."
    return "검증 단계에서 후보 범위를 재검토해야 한다는 사유가 기록됐습니다."


def _backtracking_candidate_change_panel(
    beforeCandidates: list[dict[str, Any]],
    afterCandidates: list[dict[str, Any]],
) -> html.Div:
    beforeCodes = _candidate_scope_code_list(beforeCandidates)
    afterCodes = _candidate_scope_code_list(afterCandidates)
    beforeSet = set(beforeCodes)
    afterSet = set(afterCodes)
    return html.Div(
        [
            html.Div("후보 변화", className="classification-backtracking-basis-title"),
            html.Div(
                [
                    _candidate_change_column("백트래킹 전", beforeCodes, afterSet),
                    html.Div("→", className="classification-backtracking-change-arrow"),
                    _candidate_change_column("백트래킹 후", afterCodes, beforeSet),
                ],
                className="classification-backtracking-change-grid",
            ),
            html.Div(
                [
                    html.Span(f"유지 {len(beforeSet & afterSet)}개", className="classification-backtracking-basis-tag"),
                    html.Span(f"제외 {len(beforeSet - afterSet)}개", className="classification-backtracking-basis-tag"),
                    html.Span(f"추가 {len(afterSet - beforeSet)}개", className="classification-backtracking-basis-tag"),
                ],
                className="classification-backtracking-basis-tags",
            ),
        ],
        className="classification-backtracking-change",
    )


def _candidate_scope_code_list(candidates: list[dict[str, Any]]) -> list[str]:
    codes: list[str] = []
    for candidate in candidates:
        code = str(candidate.get("cn8") or candidate.get("hs8") or candidate.get("taric10") or "").strip()
        if code and code not in codes:
            codes.append(code)
    return codes


def _candidate_change_column(
    title: str,
    codes: list[str],
    compareSet: set[str],
) -> html.Div:
    return html.Div(
        [
            html.Div(title, className="classification-backtracking-change-title"),
            html.Div(
                [
                    html.Span(
                        code,
                        className=(
                            "classification-backtracking-code kept"
                            if code in compareSet
                            else "classification-backtracking-code changed"
                        ),
                    )
                    for code in codes[:8]
                ]
                or [html.Span("-", className="classification-backtracking-code")],
                className="classification-backtracking-code-list",
            ),
        ],
        className="classification-backtracking-change-column",
    )


def _backtracking_source_candidates(entry: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = _history_candidate_scope(entry)
    sourceCodes = entry.get("rejected_candidate_hs8_codes") or entry.get("candidate_hs8_codes") or []
    if not isinstance(sourceCodes, list) or not sourceCodes:
        return candidates
    sourceCodeSet = {str(code)[:8] for code in sourceCodes if str(code).strip()}
    matched = [
        candidate
        for candidate in candidates
        if (str(candidate.get("cn8") or candidate.get("hs8") or "")[:8] in sourceCodeSet)
    ]
    return matched or candidates


def _combine_candidate_scopes(
    initialCandidates: list[dict[str, Any]],
    retryCandidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    combined: dict[str, dict[str, Any]] = {}
    for origin, candidates in (
        ("initial", initialCandidates),
        ("retry", retryCandidates),
    ):
        for candidate in candidates:
            code = str(candidate.get("cn8") or candidate.get("hs8") or "").strip()
            pathKey = code or "|".join(
                "{0}:{1}".format(node.get("level"), node.get("code"))
                for node in _candidate_nodes(candidate)
            )
            if pathKey not in combined:
                combined[pathKey] = {**candidate, "_tree_origins": [origin]}
                continue
            existing = combined[pathKey]
            origins = existing.setdefault("_tree_origins", [])
            if origin not in origins:
                origins.append(origin)
            if origin == "retry":
                existing.update({
                    key: value
                    for key, value in candidate.items()
                    if key != "_tree_origins"
                })
                existing["_tree_origins"] = origins
    return list(combined.values())


def _build_backtracking_node_states(
    sourceCandidates: list[dict[str, Any]],
    targetLevel: str,
) -> dict[tuple[str, str], set[str]]:
    nodeStates: dict[tuple[str, str], set[str]] = {}
    for candidate in sourceCandidates:
        nodes = _candidate_nodes(candidate)
        targetIndex = next(
            (
                index
                for index, node in enumerate(nodes)
                if str(node.get("level") or "").lower() == targetLevel
            ),
            0,
        )
        routeNodes = nodes[targetIndex:]
        for index, node in enumerate(routeNodes):
            key = (
                str(node.get("level") or "").lower(),
                str(node.get("code") or ""),
            )
            states = nodeStates.setdefault(key, set())
            states.add("backtracking")
            if index == 0:
                states.add("backtracking-target")
            if index == len(routeNodes) - 1:
                states.add("backtracking-source")
    return nodeStates


def _build_merged_candidate_tree(
    candidates: list[dict[str, Any]],
    *,
    nodeStates: dict[tuple[str, str], set[str]] | None = None,
) -> list[dict[str, Any]]:
    roots: list[dict[str, Any]] = []
    rootIndex: dict[str, dict[str, Any]] = {}
    for rank, candidate in enumerate(candidates, start=1):
        candidateRef = {
            "rank": rank,
            "cn8": candidate.get("cn8") or "",
            "recommended": bool(candidate.get("llm_recommended")),
            "origins": list(candidate.get("_tree_origins") or []),
        }
        siblings = roots
        siblingIndex = rootIndex
        lastMergedNode: dict[str, Any] | None = None
        for node in _candidate_nodes(candidate):
            level = str(node.get("level") or "").strip().lower()
            code = str(node.get("code") or "").strip()
            key = f"{level}:{code}"
            if key not in siblingIndex:
                mergedNode = {
                    "level": level,
                    "label": node.get("label") or node.get("level") or "-",
                    "code": code,
                    "description": node.get("description") or "",
                    "score": node.get("score"),
                    "matched_keywords": [],
                    "candidate_refs": [],
                    "leaf_candidates": [],
                    "route_states": set(),
                    "children": [],
                    "_children_index": {},
                }
                siblings.append(mergedNode)
                siblingIndex[key] = mergedNode
            mergedNode = siblingIndex[key]
            mergedNode["candidate_refs"].append(candidateRef)
            mergedNode["route_states"].update(
                (nodeStates or {}).get((level, code), set()),
            )
            for keyword in node.get("matched_keywords") or []:
                keywordText = str(keyword).strip()
                if keywordText and keywordText not in mergedNode["matched_keywords"]:
                    mergedNode["matched_keywords"].append(keywordText)
            siblings = mergedNode["children"]
            siblingIndex = mergedNode["_children_index"]
            lastMergedNode = mergedNode
        if lastMergedNode is not None:
            lastMergedNode["leaf_candidates"].append(candidateRef)
    return roots


def _candidate_merged_branch(node: dict[str, Any]) -> html.Li:
    children = node.get("children") or []
    candidateRefs = [
        ref
        for ref in node.get("candidate_refs") or []
        if isinstance(ref, dict)
    ]
    origins = {
        str(origin)
        for ref in candidateRefs
        for origin in ref.get("origins") or []
    }
    stateClasses = set(node.get("route_states") or [])
    if origins == {"retry"}:
        stateClasses.add("retry")
    if any(ref.get("recommended") for ref in candidateRefs):
        stateClasses.add("selected")
    return html.Li(
        [
            _candidate_merged_node(node),
            html.Ul(
                [
                    _candidate_merged_branch(child)
                    for child in children
                    if isinstance(child, dict)
                ],
            ) if children else None,
        ],
        className=" ".join(sorted(stateClasses)),
    )


def _candidate_merged_node(node: dict[str, Any]) -> html.Div:
    level = str(node.get("level") or "").strip().lower()
    candidateRefs = node.get("candidate_refs") or []
    leafCandidates = node.get("leaf_candidates") or []
    routeStates = set(node.get("route_states") or [])
    annotations: list[Any] = []
    if "backtracking-source" in routeStates:
        annotations.append(
            html.Span("역방향 시작 ↑", className="candidate-tree-route-note backtracking"),
        )
    if "backtracking-target" in routeStates:
        annotations.append(
            html.Span("재탐색 경계", className="candidate-tree-route-note backtracking"),
        )
    return html.Div(
        [
            html.Div(
                [
                    html.Span(
                        node.get("label") or level.upper() or "-",
                        className="candidate-path-level",
                    ),
                    html.Span(node.get("code") or "-", className="candidate-path-code"),
                    html.Span(
                        node.get("description") or "-",
                        className="candidate-path-description",
                    ),
                    *annotations,
                ],
                className="candidate-path-head",
            ),
            html.Div(
                [
                    html.Span(
                        f"경로 {len(candidateRefs)}",
                        className="candidate-tree-node-detail",
                    ),
                    html.Span(
                        f"점수 {node.get('score')}",
                        className="candidate-tree-node-detail",
                    )
                    if node.get("score") not in (None, "")
                    else None,
                    html.Span(
                        "키워드 " + ", ".join(
                            str(keyword)
                            for keyword in (node.get("matched_keywords") or [])[:5]
                        ),
                        className="candidate-tree-node-detail",
                    )
                    if node.get("matched_keywords")
                    else None,
                ],
                className="candidate-tree-node-meta",
            ),
            html.Div(
                [
                    html.Span(
                        "후보 #{0} · CN8 {1}{2}".format(
                            ref.get("rank"),
                            ref.get("cn8"),
                            " · 최종 선택" if ref.get("recommended") else "",
                        ),
                        className="candidate-tree-leaf-reference",
                    )
                    for ref in leafCandidates
                    if isinstance(ref, dict)
                ],
                className="candidate-tree-leaf-references",
            ) if leafCandidates else None,
        ],
        className="candidate-outline-node",
    )


def classification_result_drawer(
    result: dict[str, Any],
    drawerOpened: bool | str | None,
) -> html.Div | None:
    candidateSet = result.get("candidate_code_set") or {}
    candidates = candidateSet.get("candidates") if isinstance(candidateSet, dict) else []
    if not isinstance(candidates, list):
        candidates = []
    if not candidates and not (
        isinstance(candidateSet, dict) and candidateSet.get("classification_status")
    ):
        return None
    selectedKey = str(drawerOpened) if isinstance(drawerOpened, str) else ""
    selectedCandidate = _selected_candidate(
        [candidate for candidate in candidates if isinstance(candidate, dict)],
        selectedKey,
    )
    drawerBody = (
        _taric_candidate_detail_panel(selectedCandidate, result)
        if selectedCandidate
        else _classification_result_panel(candidateSet, candidates[:5])
        if candidates
        else _classification_unresolved_panel(candidateSet)
    )
    if not drawerOpened:
        return None
    titleMain = "TARIC 후보 상세" if selectedCandidate else "Classification 검증 결과"
    titleSub = (
        "선택한 TARIC 코드의 문서 패키지"
        if selectedCandidate
        else "백트래킹 근거와 후보 변화"
    )

    return _popup_card(
        popupId="classification-result-drawer",
        cardClassName="classification-result-popup-card",
        title=html.Div(
            [
                html.Div(
                    [
                        html.Div(titleMain, className="drawer-title-main"),
                        html.Div(titleSub, className="drawer-title-sub"),
                    ]
                ),
                dmc.Button(
                    "닫기",
                    id={
                        "type": "classification-result-drawer-close",
                        "target": "classification-result",
                    },
                    variant="subtle",
                    color="gray",
                    size="xs",
                    radius="sm",
                ),
            ],
            className="drawer-title",
        ),
        body=drawerBody,
    )


def _classification_result_panel(
    candidateSet: dict[str, Any],
    candidates: list[Any],
) -> html.Div:
    cleanCandidates = [candidate for candidate in candidates if isinstance(candidate, dict)]
    backtrackingPanel = _classification_backtracking_route_panel(candidateSet, cleanCandidates)
    return html.Div(
        [
            backtrackingPanel
            if backtrackingPanel
            else html.Div(
                "백트래킹은 발생하지 않았습니다. 최종 후보는 TARIC 후보 카드를 클릭해 문서 상세 페이지와 후보 요약을 확인하세요.",
                className="classification-result-flat-note",
            ),
        ],
        className="classification-result-panel",
    )


def _selected_candidate(
    candidates: list[dict[str, Any]],
    selectedKey: str,
) -> dict[str, Any] | None:
    if not selectedKey:
        return None
    for displayRank, candidate in enumerate(candidates, start=1):
        if _candidate_key(candidate, displayRank) == selectedKey:
            return candidate
    return None


def _taric_candidate_detail_panel(
    candidate: dict[str, Any],
    result: dict[str, Any],
) -> html.Div:
    taric10, package = _selected_document_package(candidate, result)
    jobStatus = result.get("job_status")
    isConnecting = not package and jobStatus in {"queued", "running"}
    return html.Div(
        _embedded_document_package_panel(taric10, package, isConnecting),
        className="taric-candidate-detail",
    )


def _selected_document_package(
    candidate: dict[str, Any],
    result: dict[str, Any],
) -> tuple[str, dict[str, Any] | None]:
    branchList = _candidate_branch_list(candidate)
    packagesByTaric = _document_packages_by_taric(result)
    for branch in branchList:
        taric10 = _clean_code(branch.get("taric10"))
        packages = _document_packages_for_taric(packagesByTaric, branch.get("taric10"))
        if packages and isinstance(packages[0], dict):
            return taric10, packages[0]
    fallbackTaric = _clean_code(candidate.get("taric10"))
    return fallbackTaric, None


def _embedded_document_package_panel(
    taric10: str,
    package: dict[str, Any] | None,
    isConnecting: bool,
) -> html.Div:
    if package:
        from frontend.ui.document_package_renderer import RenderDocumentPackageResult

        return html.Div(
            [
                html.Div(
                    [
                        html.Div("문서 패키지", className="candidate-tree-section-title"),
                        html.Div(
                            f"TARIC10 {_clean_code(package.get('taric10') or taric10) or '-'}",
                            className="taric-document-embed-caption",
                        ),
                    ],
                    className="taric-document-embed-heading",
                ),
                html.Div(
                    RenderDocumentPackageResult(package, "overview", []),
                    className="taric-document-embed-content",
                ),
            ],
            className="taric-document-embed",
        )
    return html.Div(
        [
            html.Div(className="document-icon large", title="문서"),
            html.Div(
                [
                    html.Div(taric10 or "-", className="taric-document-page-code"),
                    html.Div(
                        "연결하는 중" if isConnecting else "연결된 문서 없음",
                        className="taric-document-page-title",
                    ),
                    html.Div(
                        "TARIC 문서 패키지를 생성하고 있습니다."
                        if isConnecting
                        else "아직 이 후보에 연결된 문서 패키지가 없습니다.",
                        className="taric-document-page-desc",
                    ),
                ],
                className="taric-document-page-copy",
            ),
            html.Div(className="taric-document-floating-dot") if isConnecting else None,
        ],
        className=f"taric-document-empty-state {'linking' if isConnecting else 'empty'}",
    )


def _document_package_counts(package: dict[str, Any]) -> dict[str, int]:
    return {
        "required": len(package.get("required_documents") or []),
        "customs": len(package.get("customs_check_items") or []),
        "regulations": len(package.get("product_regulations") or []),
        "missing": len(package.get("missing_facts") or []),
    }


def _candidate_reason_text(candidate: dict[str, Any]) -> str:
    basis = candidate.get("classification_basis") or []
    if isinstance(basis, list):
        return " ".join(str(item).strip() for item in basis if str(item).strip())
    return str(basis or "").strip()


def render_decision(result: dict[str, Any]) -> html.Div:
    dec = result.get("decision") or {}
    if not dec:
        return html.Div("최종 결정이 아직 없습니다.", style=PLACEHOLDER)

    candidateSet = result.get("candidate_code_set") or {}
    candidates = candidateSet.get("candidates") if isinstance(candidateSet, dict) else []
    candidates = [candidate for candidate in candidates if isinstance(candidate, dict)]
    selectedIds = set(dec.get("selected_candidate_ids") or [])
    selectedCandidates = [
        candidate
        for candidate in candidates
        if candidate.get("candidate_id") in selectedIds
    ]
    primary = (
        next((candidate for candidate in selectedCandidates if candidate.get("llm_recommended")), None)
        or selectedCandidates[0]
        if selectedCandidates
        else next((candidate for candidate in candidates if candidate.get("llm_recommended")), None)
        or (candidates[0] if candidates else {})
    )
    cn8 = primary.get("cn8") or "-"
    taric10 = primary.get("taric10") or "-"
    status = str(dec.get("decision_status") or "검토 필요")
    title = "우선 검토 코드" if status != "accepted" else "최종 선택 후보"
    subtitle = (
        f"{len(selectedCandidates)}개 후보가 남아 있습니다."
        if len(selectedCandidates) > 1
        else "후속 서류 검토는 TARIC branch별 서류 패키지에서 확인합니다."
    )
    body = (
        _short_text(_candidate_reason_text(primary), max_length=360)
        if _candidate_reason_text(primary)
        else "표시된 TARIC10은 CN8 후보 하위 branch 중 UI 연결을 위한 대표값입니다. 실제 검토는 펼친 branch별 서류 패키지에서 확인합니다."
    )

    return html.Div(
        [
            html.Div(title, style={**LABEL, "marginBottom": "6px"}),
            html.Div(cn8, className="classification-result-primary-code"),
            html.Div(f"TARIC10 {taric10}", className="classification-result-secondary-code"),
            html.P(subtitle, className="classification-result-text"),
            html.P(body, className="classification-result-text"),
        ],
        style=CARD,
    )


def render_page(
    result: dict[str, Any] | None = None,
    *,
    input_detail_drawer_mode: str | bool | None = None,
    candidate_tree_drawer_open: bool = False,
    classification_result_drawer_open: bool | str | None = False,
) -> html.Div:
    result = result or {}
    inputProcessingView = input_processing_view_card(
        result.get("input_processing_view"),
        drawerMode=input_detail_drawer_mode,
    )
    candidateTreeDrawer = candidate_tree_drawer(result, candidate_tree_drawer_open)
    classificationResultDrawer = classification_result_drawer(
        result,
        classification_result_drawer_open,
    )
    requestFacts = (
        (result.get("request") or {}).get("facts")
        or {}
    )
    runDisabled = result.get("job_status") in {"submitting", "queued", "running"}
    return html.Div(
        [
            render_input_form(requestFacts, runDisabled=runDisabled),
            html.Div("입력 수집/복원 결과", style=LABEL) if inputProcessingView else None,
            inputProcessingView,
            html.Div("진행 상태", style=LABEL),
            html.Div(render_progress(result), id="out-progress"),
            html.Div("분류 결과", style={**LABEL, "marginTop": "22px"}),
            html.Div(render_candidate_cards(result) if result else html.Div("분류 결과가 여기에 표시됩니다.", style=PLACEHOLDER), id="out-classification"),
            candidateTreeDrawer,
            classificationResultDrawer,
            html.Div("최종 결정", style={**LABEL, "marginTop": "22px"}),
            html.Div(render_decision(result) if result else html.Div("Orchestrator 결정이 여기에 표시됩니다.", style=PLACEHOLDER), id="out-decision"),
        ]
    )
