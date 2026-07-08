"""Split TARIC duty_text expressions into table-friendly rows."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

NUMBER_RE = r"\d[\d.,]*"
PERCENT_TOKEN_RE = re.compile(rf"(?<![\w.])({NUMBER_RE})\s*%")
MONEY_RATE_RE = re.compile(
    rf"(?<![\w.])({NUMBER_RE})\s+([A-Z]{{3}})\s*/?\s*([A-Z]{{2,6}}(?:\s+[A-Z])?)\b"
)
QUANTITY_THRESHOLD_RE = re.compile(
    rf"(?<![\w.])({NUMBER_RE})\s*/\s*([A-Z]{{2,6}}(?:\s+[A-Z])?)\b"
)
MIN_MAX_RE = re.compile(
    rf"\b(MIN|MAX)\s+({NUMBER_RE})\s+([A-Z]{{3}})\s*/?\s*([A-Z]{{2,6}}(?:\s+[A-Z])?)\b"
)
AGRICULTURAL_COMPONENT_RE = re.compile(r"\+\s*([A-Z]{2,6})\b")
UNIT_ONLY_RE = re.compile(r"^[A-Z]{2,6}(?:\s+[A-Z])?$")
COND_CERT_RE = re.compile(
    r"^(?P<condition>[A-Z][A-Z0-9]*)\s+cert:\s*(?P<certificate>[A-Z]-?\d+)\s*"
    r"\((?P<action>\d{2})\):\s*(?P<outcome>.*)$"
)
COND_ACTION_RE = re.compile(
    r"^(?P<condition>[A-Z][A-Z0-9]*)(?:\s+(?P<expression>.*?))?\s*"
    r"\((?P<action>\d{2})\):\s*(?P<outcome>.*)$"
)

RATE_OPTION_KINDS = {
    "simple_percent",
    "specific_rate",
    "compound_rate",
    "min_max_rate",
    "agricultural_component",
    "nihil",
}


@dataclass(frozen=True)
class DutyRateComponent:
    kind: str
    display: str
    amount: Decimal | None = None
    currency: str | None = None
    unit_code: str | None = None
    percent_rate: Decimal | None = None
    boundary: str | None = None


@dataclass(frozen=True)
class DutyTextRateRow:
    rate_row_id: str
    master_id: str
    row_seq: int
    source_segment: str
    segment_type: str
    rate_kind: str
    is_rate_option: bool
    is_conditional: bool
    is_fallback: bool
    condition_group: str | None = None
    certificate_code: str | None = None
    action_code: str | None = None
    condition_expression: str | None = None
    condition_outcome: str | None = None
    rate_text: str | None = None
    percent_rate: Decimal | None = None
    specific_amount: Decimal | None = None
    threshold_amount: Decimal | None = None
    currency: str | None = None
    unit_code: str | None = None
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    components_json: list[dict[str, Any]] = field(default_factory=list)
    parse_status: str = "parsed"
    parse_notes: list[str] = field(default_factory=list)

    def to_record(self) -> dict[str, Any]:
        out = asdict(self)
        return out


def split_duty_text_to_rate_rows(master_id: str, duty_text: str | None) -> list[DutyTextRateRow]:
    text = (duty_text or "").strip()
    if not text:
        return []

    if "Cond:" not in text:
        return [
            _row_from_rate_expression(
                master_id=master_id,
                row_seq=1,
                source_segment=text,
                rate_text=text,
                segment_type="unconditional_rate",
                is_conditional=False,
            )
        ]

    rows: list[DutyTextRateRow] = []
    prefix, condition_text = text.split("Cond:", 1)
    prefix = prefix.strip().rstrip(";")
    if prefix:
        rows.append(
            _row_from_rate_expression(
                master_id=master_id,
                row_seq=len(rows) + 1,
                source_segment=prefix,
                rate_text=prefix,
                segment_type="unconditional_rate_prefix",
                is_conditional=False,
            )
        )

    for segment in condition_text.split(";"):
        raw_segment = segment.strip()
        if not raw_segment:
            continue
        rows.append(_row_from_condition_segment(master_id, len(rows) + 1, raw_segment))
    return rows


def _row_from_condition_segment(master_id: str, row_seq: int, segment: str) -> DutyTextRateRow:
    cert_match = COND_CERT_RE.match(segment)
    if cert_match:
        condition_group = cert_match.group("condition")
        certificate_code = _normalize_certificate_code(cert_match.group("certificate"))
        action_code = cert_match.group("action")
        outcome = cert_match.group("outcome").strip()
        if outcome:
            return _row_from_rate_expression(
                master_id=master_id,
                row_seq=row_seq,
                source_segment=segment,
                rate_text=outcome,
                segment_type="condition_certificate_rate_outcome",
                is_conditional=True,
                condition_group=condition_group,
                certificate_code=certificate_code,
                action_code=action_code,
                condition_outcome=outcome,
            )
        return DutyTextRateRow(
            rate_row_id=_rate_row_id(master_id, row_seq, segment),
            master_id=master_id,
            row_seq=row_seq,
            source_segment=segment,
            segment_type="condition_certificate",
            rate_kind="none",
            is_rate_option=False,
            is_conditional=True,
            is_fallback=False,
            condition_group=condition_group,
            certificate_code=certificate_code,
            action_code=action_code,
        )

    action_match = COND_ACTION_RE.match(segment)
    if not action_match:
        return DutyTextRateRow(
            rate_row_id=_rate_row_id(master_id, row_seq, segment),
            master_id=master_id,
            row_seq=row_seq,
            source_segment=segment,
            segment_type="condition_unparsed",
            rate_kind="unknown",
            is_rate_option=False,
            is_conditional=True,
            is_fallback=False,
            parse_status="unparsed",
            parse_notes=["condition segment did not match supported grammar"],
        )

    condition_group = action_match.group("condition")
    expression = (action_match.group("expression") or "").strip() or None
    action_code = action_match.group("action")
    outcome = (action_match.group("outcome") or "").strip() or None
    if outcome:
        return _row_from_rate_expression(
            master_id=master_id,
            row_seq=row_seq,
            source_segment=segment,
            rate_text=outcome,
            segment_type="condition_rate_outcome",
            is_conditional=True,
            is_fallback=not bool(expression),
            condition_group=condition_group,
            action_code=action_code,
            condition_expression=expression,
            condition_outcome=outcome,
        )

    components = _parse_rate_components(expression or "")
    rate_kind = _classify_components(expression or "", components)
    primary = _primary_component_values(components)
    return DutyTextRateRow(
        rate_row_id=_rate_row_id(master_id, row_seq, segment),
        master_id=master_id,
        row_seq=row_seq,
        source_segment=segment,
        segment_type="condition_expression" if expression else "condition_fallback",
        rate_kind=rate_kind if expression else "none",
        is_rate_option=False,
        is_conditional=True,
        is_fallback=not bool(expression),
        condition_group=condition_group,
        action_code=action_code,
        condition_expression=expression,
        threshold_amount=primary.get("threshold_amount"),
        unit_code=primary.get("unit_code"),
        components_json=[_component_record(component) for component in components],
        parse_status="parsed" if expression else "no_rate",
    )


def _row_from_rate_expression(
    *,
    master_id: str,
    row_seq: int,
    source_segment: str,
    rate_text: str,
    segment_type: str,
    is_conditional: bool,
    is_fallback: bool = False,
    condition_group: str | None = None,
    certificate_code: str | None = None,
    action_code: str | None = None,
    condition_expression: str | None = None,
    condition_outcome: str | None = None,
) -> DutyTextRateRow:
    components = _parse_rate_components(rate_text)
    rate_kind = _classify_components(rate_text, components)
    primary = _primary_component_values(components)
    is_rate_option = rate_kind in RATE_OPTION_KINDS
    parse_notes = []
    if rate_kind == "unknown":
        parse_notes.append("rate expression did not match supported rate grammar")
    if rate_kind == "supplementary_unit":
        parse_notes.append("supplementary unit is not a tariff rate option")
    if rate_kind == "quantity_threshold":
        parse_notes.append("quantity threshold is a condition value, not a rate option")
    return DutyTextRateRow(
        rate_row_id=_rate_row_id(master_id, row_seq, source_segment),
        master_id=master_id,
        row_seq=row_seq,
        source_segment=source_segment,
        segment_type=segment_type,
        rate_kind=rate_kind,
        is_rate_option=is_rate_option,
        is_conditional=is_conditional,
        is_fallback=is_fallback,
        condition_group=condition_group,
        certificate_code=certificate_code,
        action_code=action_code,
        condition_expression=condition_expression,
        condition_outcome=condition_outcome,
        rate_text=rate_text,
        percent_rate=primary.get("percent_rate"),
        specific_amount=primary.get("specific_amount"),
        threshold_amount=primary.get("threshold_amount"),
        currency=primary.get("currency"),
        unit_code=primary.get("unit_code"),
        min_amount=primary.get("min_amount"),
        max_amount=primary.get("max_amount"),
        components_json=[_component_record(component) for component in components],
        parse_status="parsed" if rate_kind != "unknown" else "unknown",
        parse_notes=parse_notes,
    )


def _parse_rate_components(text: str) -> list[DutyRateComponent]:
    text = (text or "").strip()
    if not text:
        return []
    upper = text.upper()
    if upper == "NIHIL":
        return [DutyRateComponent(kind="nihil", display="NIHIL")]

    components: list[DutyRateComponent] = []
    seen: set[tuple[str, str]] = set()

    def add(component: DutyRateComponent) -> None:
        key = (component.kind, component.display)
        if key not in seen:
            seen.add(key)
            components.append(component)

    if UNIT_ONLY_RE.match(upper):
        add(DutyRateComponent(kind="supplementary_unit", display=upper, unit_code=upper))

    for match in MIN_MAX_RE.finditer(upper):
        boundary, amount, currency, unit = match.groups()
        add(DutyRateComponent(
            kind="min_max",
            display=match.group(0),
            amount=_decimal(amount),
            currency=currency,
            unit_code=_normalize_unit_code(unit),
            boundary=boundary.lower(),
        ))

    for match in PERCENT_TOKEN_RE.finditer(text):
        add(DutyRateComponent(
            kind="percentage",
            display=match.group(0),
            percent_rate=_decimal(match.group(1)),
            unit_code="%",
        ))

    for match in MONEY_RATE_RE.finditer(upper):
        amount, currency, unit = match.groups()
        add(DutyRateComponent(
            kind="specific_rate",
            display=match.group(0),
            amount=_decimal(amount),
            currency=currency,
            unit_code=_normalize_unit_code(unit),
        ))

    for match in QUANTITY_THRESHOLD_RE.finditer(upper):
        amount, unit = match.groups()
        add(DutyRateComponent(
            kind="quantity_threshold",
            display=match.group(0),
            amount=_decimal(amount),
            unit_code=_normalize_unit_code(unit),
        ))

    for match in AGRICULTURAL_COMPONENT_RE.finditer(upper):
        add(DutyRateComponent(
            kind="agricultural_component",
            display=match.group(0).replace(" ", ""),
            unit_code=_normalize_unit_code(match.group(1)),
        ))

    return components


def _classify_components(text: str, components: list[DutyRateComponent]) -> str:
    stripped = (text or "").strip()
    if not stripped:
        return "none"
    if stripped.upper() == "NIHIL":
        return "nihil"
    kinds = {component.kind for component in components}
    if not components:
        return "unknown"
    if kinds == {"supplementary_unit"}:
        return "supplementary_unit"
    if kinds == {"quantity_threshold"}:
        return "quantity_threshold"
    if "agricultural_component" in kinds:
        return "agricultural_component"
    if "min_max" in kinds:
        return "min_max_rate"
    if "percentage" in kinds and "specific_rate" in kinds:
        return "compound_rate"
    if "specific_rate" in kinds:
        return "specific_rate"
    if "percentage" in kinds:
        return "simple_percent"
    return "unknown"


def _primary_component_values(components: list[DutyRateComponent]) -> dict[str, Decimal | str | None]:
    out: dict[str, Decimal | str | None] = {
        "percent_rate": None,
        "specific_amount": None,
        "threshold_amount": None,
        "currency": None,
        "unit_code": None,
        "min_amount": None,
        "max_amount": None,
    }
    for component in components:
        if component.kind == "percentage" and out["percent_rate"] is None:
            out["percent_rate"] = component.percent_rate
        elif component.kind == "specific_rate" and out["specific_amount"] is None:
            out["specific_amount"] = component.amount
            out["currency"] = component.currency
            out["unit_code"] = component.unit_code
        elif component.kind == "min_max":
            if component.boundary == "min" and out["min_amount"] is None:
                out["min_amount"] = component.amount
            elif component.boundary == "max" and out["max_amount"] is None:
                out["max_amount"] = component.amount
            if out["currency"] is None:
                out["currency"] = component.currency
            if out["unit_code"] is None:
                out["unit_code"] = component.unit_code
        elif component.kind == "quantity_threshold" and out["threshold_amount"] is None:
            out["threshold_amount"] = component.amount
            if out["unit_code"] is None:
                out["unit_code"] = component.unit_code
        elif component.unit_code and out["unit_code"] is None:
            out["unit_code"] = component.unit_code
    return out


def _component_record(component: DutyRateComponent) -> dict[str, Any]:
    record = asdict(component)
    return {key: _json_value(value) for key, value in record.items() if value is not None}


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    return value


def _decimal(value: str | None) -> Decimal | None:
    if not value:
        return None
    normalized = value.replace(",", ".")
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None


def _normalize_certificate_code(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").strip().upper())


def _normalize_unit_code(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().upper())


def _rate_row_id(master_id: str, row_seq: int, segment: str) -> str:
    digest = hashlib.sha1(f"{master_id}|{row_seq}|{segment}".encode("utf-8")).hexdigest()[:16]
    return f"{master_id}:{row_seq}:{digest}"
