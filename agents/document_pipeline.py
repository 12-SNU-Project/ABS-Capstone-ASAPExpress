"""End-to-end UI pipeline: product input -> classifier -> documents.

This module is intentionally thin. It does not classify or recommend documents
itself; it only runs the existing Blackboard agents in order and returns the
Document_Agent output that the Dash UI can render.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(os.environ.get("ASAP_PROJECT_ROOT", Path(__file__).resolve().parents[1])).resolve()
SRC_ROOT = PROJECT_ROOT / "src"
for _path in (PROJECT_ROOT, SRC_ROOT):
    if _path.exists() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from agents.classification_agent import ClassificationAgent
from agents.document_agent import DocumentAgent
from agents.evidence_intake_agent import EvidenceIntakeAgent
from agents.orchestrator_agent import OrchestratorAgent
from blackboard import BlackboardStore


def _read_agent_runs(store: BlackboardStore) -> list[dict[str, Any]]:
    if not store.runs_path.exists():
        return []
    out: list[dict[str, Any]] = []
    with store.runs_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                out.append({"raw": line, "parse_error": "invalid_jsonl"})
    return out


def collect_kurly_url_facts(
    url: str,
    *,
    run_ocr: bool = True,
    headless: bool = True,
    timeout_seconds: int = 60,
    scroll_count: int = 8,
    max_ocr_images: int = 8,
) -> dict[str, Any]:
    """Collect product facts from a Kurly product URL.

    This keeps URL/OCR intake outside the Dash callback and before
    Evidence_Intake_Agent, so the Blackboard still starts from normalized
    product facts.
    """
    from eu_export.product.kurly_market_collector import KurlyPageCollector
    from eu_export.product.pipeline import KurlyProductPipeline
    from eu_export.product.pipeline_schema import KurlyPipelineInput
    from eu_export.ontology import ProductClassificationInputNormalizer

    warnings: list[str] = []
    collector = KurlyPageCollector(
        headless=headless,
        timeoutMilliseconds=timeout_seconds * 1000,
        scrollCount=scroll_count,
    )
    if run_ocr:
        try:
            from eu_export.product.paddle_ocr import PaddleOcrEngine

            pipeline = KurlyProductPipeline(
                collector=collector,
                ocrEngine=PaddleOcrEngine(),
            )
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"ocr_engine_unavailable: {exc}")
            pipeline = KurlyProductPipeline(collector=collector)
            run_ocr = False
    else:
        pipeline = KurlyProductPipeline(collector=collector)

    artifact_root = PROJECT_ROOT / "tmp" / "asap_dash_url_intake"
    artifact_root.mkdir(parents=True, exist_ok=True)
    result = pipeline.Run(
        KurlyPipelineInput(
            productPageUrl=url,
            runOcrFallback=run_ocr,
            artifactRootPath=artifact_root,
            maxOcrImageCount=max_ocr_images,
        )
    )
    product_input = ProductClassificationInputNormalizer().BuildFromKurlyPipelineResult(result)
    facts = {
        "url": url,
        "source_urls": [url],
        "product_name": product_input.productName or "",
        "description": product_input.shortDescription or product_input.productNoticeText or "",
        "short_description": product_input.shortDescription or "",
        "product_domain": product_input.productDomain or "unknown",
        "ocr_text": [product_input.ocrText] if product_input.ocrText else [],
        "ingredient_list": list(product_input.normalizedOcrFactTexts or []),
        "origin_country": "KR",
        "intended_use": "human consumption",
        "warnings": warnings,
    }
    return facts


def build_raw_input_from_ui(
    *,
    query: str,
    facts: dict[str, Any],
) -> dict[str, Any]:
    """Map Dash text + Product facts JSON into EvidenceIntakeAgent input."""
    facts = _normalize_loose_product_facts(facts or {})
    url = str(facts.get("url") or "").strip()
    if url and "kurly.com/goods/" in url:
        try:
            collected = collect_kurly_url_facts(url)
            merged = dict(facts)
            for key, value in collected.items():
                if value not in ("", [], None):
                    merged[key] = value
            facts = _normalize_loose_product_facts(merged)
        except Exception as exc:  # noqa: BLE001
            facts.setdefault("warnings", [])
            facts["warnings"].append(f"kurly_url_intake_failed: {exc}")

    source_urls = facts.get("source_urls") or facts.get("source_url") or facts.get("url") or []
    if isinstance(source_urls, str):
        source_urls = [source_urls] if source_urls.strip() else []

    ocr_text = facts.get("ocr_text") or facts.get("coi_text") or facts.get("coi") or []
    if isinstance(ocr_text, str):
        ocr_text = [ocr_text] if ocr_text.strip() else []

    return {
        "product_name": facts.get("product_name") or query,
        "description": facts.get("description") or facts.get("short_description") or "",
        "composition": facts.get("composition") or facts.get("ingredient_list") or [],
        "ocr_text": ocr_text,
        "source_urls": source_urls,
        "origin_country": facts.get("origin_country") or "KR",
        "intended_use": facts.get("intended_use") or "unknown",
        "warnings": facts.get("warnings") or [],
    }


def _normalize_loose_product_facts(facts: dict[str, Any]) -> dict[str, Any]:
    """Accept common user-pasted wrappers before normalizing product facts."""
    if not isinstance(facts, dict):
        return {}
    facts = _unwrap_product_fact_wrapper(facts)

    # Some UI flows pass a JSON-ish evidence object as the query/product_name
    # string. Parse it here so Evidence_Intake_Agent sees real facts rather
    # than a large JSON blob as the product name.
    for key in ("raw_input_to_evidence_intake", "raw_input_to_evidence", "product_facts"):
        value = facts.get(key)
        if isinstance(value, dict):
            merged = dict(facts)
            merged.update(value)
            facts = merged
            break

    for text_key in ("product_name", "description", "query", "text"):
        parsed = _parse_embedded_product_fact_text(facts.get(text_key))
        if parsed:
            merged = dict(facts)
            merged.update(parsed)
            facts = merged
            break

    return _normalize_kurly_result_facts(facts)


def _unwrap_product_fact_wrapper(facts: dict[str, Any]) -> dict[str, Any]:
    for key in ("raw_input_to_evidence_intake", "raw_input_to_evidence", "product_facts"):
        value = facts.get(key)
        if isinstance(value, dict):
            return value
    return facts


def _parse_embedded_product_fact_text(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, str):
        return None
    text = value.strip().rstrip(",")
    if not text:
        return None

    candidates = [text]
    if text.startswith('"raw_input_to_evidence_intake"') or text.startswith('"raw_input_to_evidence"'):
        candidates.append("{" + text + "}")
    if text.startswith("raw_input_to_evidence_intake"):
        candidates.append('{"' + text)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return _unwrap_product_fact_wrapper(parsed)
    return None


def _normalize_kurly_result_facts(facts: dict[str, Any]) -> dict[str, Any]:
    """Flatten the Kurly collector/OCR result shape into Product facts.

    Accepts the object shape emitted by ABS-Capstone-ASAPExpress, e.g.
    parsed_product_page/product/ocr_summary/combined_ocr_text.
    """
    if not isinstance(facts, dict):
        return {}
    parsed = facts.get("parsed_product_page") or {}
    product = facts.get("product") or {}
    ocr_summary = facts.get("ocr_summary") or {}
    normalization = ocr_summary.get("normalization") or {}

    fact_texts = normalization.get("fact_texts") or []
    combined_ocr_text = facts.get("combined_ocr_text") or ""
    ocr_text: list[str] = []
    if isinstance(combined_ocr_text, str) and combined_ocr_text.strip():
        ocr_text.append(combined_ocr_text)
    if isinstance(fact_texts, list):
        ocr_text.extend(str(t) for t in fact_texts if str(t).strip())

    product_page_url = (
        facts.get("product_page_url")
        or parsed.get("product_page_url")
        or facts.get("url")
    )
    product_name = (
        product.get("product_name")
        or parsed.get("product_name")
        or facts.get("product_name")
    )
    short_description = (
        product.get("short_description")
        or parsed.get("short_description")
        or facts.get("short_description")
        or facts.get("description")
    )
    product_domain = (
        product.get("product_domain")
        or parsed.get("product_domain")
        or facts.get("product_domain")
    )

    flattened = dict(facts)
    flattened.update({
        "url": product_page_url or facts.get("url") or "",
        "product_name": product_name or "",
        "description": short_description or "",
        "short_description": short_description or "",
        "product_domain": product_domain or facts.get("product_domain") or "unknown",
        "product_category": facts.get("product_category") or product_domain or "unknown",
        "brand_name": product.get("brand_name") or parsed.get("brand_name") or facts.get("brand_name") or "",
        "package_type": product.get("package_type") or parsed.get("package_type") or facts.get("package_type") or "",
        "sale_unit": product.get("sale_unit") or parsed.get("sale_unit") or facts.get("sale_unit") or "",
        "ocr_text": ocr_text or facts.get("ocr_text") or [],
        "ingredient_list": fact_texts or facts.get("ingredient_list") or [],
    })
    return flattened


def run_document_pipeline(
    *,
    query: str,
    facts: dict[str, Any],
    include_celex_excerpt: bool = False,
    progress_callback=None,
) -> dict[str, Any]:
    """Run Evidence -> Classification -> Document -> Orchestrator.

    Return shape:
      {
        "store": BlackboardStore,
        "blackboard": dict,
        "raw_document_package": dict | None,
        "document_package": dict | None,
        "candidate_code_set": dict | None,
        "decision": dict | None,
        "agent_results": list[dict],
      }
    """
    store = BlackboardStore.create(runtime_mode="dash")

    def emit(stage: str, status: str, **payload) -> None:
        if progress_callback is None:
            return
        try:
            progress_callback({
                "stage": stage,
                "status": status,
                "run_id": store.run_id,
                **payload,
            })
        except Exception:
            pass

    emit("Input_Intake", "running", message="사용자 입력/URL/OCR evidence intake 준비")
    raw_input = build_raw_input_from_ui(query=query, facts=facts)
    emit("Input_Intake", "completed", message="raw product facts 생성", raw_input=raw_input)

    agents = [
        EvidenceIntakeAgent(raw_input),
        ClassificationAgent(),
        DocumentAgent(include_celex_excerpt=include_celex_excerpt),
        OrchestratorAgent(),
    ]

    agent_results: list[dict[str, Any]] = []
    for agent in agents:
        emit(agent.agent_name, "running", message=f"{agent.stage} 실행 중")
        result = agent.execute(store)
        agent_results.append({
            "agent_name": agent.agent_name,
            "success": result.success,
            "error": result.error,
            "outputs_written": result.outputs_written,
        })
        bb_snapshot = store.load()
        partial = {
            "blackboard": bb_snapshot,
            "candidate_code_set": (bb_snapshot.get("candidate_code_sets") or [None])[-1],
            "document_package": (bb_snapshot.get("document_packages") or [None])[-1],
            "decision": (bb_snapshot.get("orchestrator_decisions") or [None])[-1],
            "agent_results": list(agent_results),
            "agent_runs": _read_agent_runs(store),
            "run_id": store.run_id,
            "run_dir": str(Path(store.run_dir)),
        }
        emit(
            agent.agent_name,
            "completed" if result.success else "failed",
            message=f"{agent.agent_name} 완료" if result.success else f"{agent.agent_name} 실패",
            agent_result=agent_results[-1],
            partial_result=partial,
        )
        if not result.success:
            break

    bb = store.load()
    document_package = (bb.get("document_packages") or [None])[-1]
    candidate_code_set = (bb.get("candidate_code_sets") or [None])[-1]
    decision = (bb.get("orchestrator_decisions") or [None])[-1]
    raw_document_package = (
        document_package.get("raw_document_package")
        if isinstance(document_package, dict)
        else None
    )

    return {
        "store": store,
        "blackboard": bb,
        "raw_document_package": raw_document_package,
        "document_package": document_package,
        "candidate_code_set": candidate_code_set,
        "decision": decision,
        "agent_results": agent_results,
        "agent_runs": _read_agent_runs(store),
        "run_id": store.run_id,
        "run_dir": str(Path(store.run_dir)),
    }
