"""기업 서비스 관리 API — /api/enterprise/*

기업용 UI(webapp /enterprise)의 관리 데이터 포트.

설계 의도 (docs/enterpriseUI.md 참고):
- 표면 기능은 기업 이용자 편의(케이스 관리, 서류 수집, 요청 발송, 절감액 계산).
- 실질 자산은 이 포트를 지나는 **모든 흐름의 이벤트 원장**이다 — 상품 URL(판매 채널),
  판매가·예상 물량, COI(성분), 서류 상태 변화, 분류 결과 귀속, 통관(신고) 결과가
  전부 append-only 로그로 쌓인다. DB 이관 시 이 이벤트 포맷을 그대로 테이블로 옮긴다.

저장소는 파일 기반 플레이스홀더:
- 이벤트 원장: artifacts/enterprise/events.jsonl (append-only)
- 케이스 스냅샷: artifacts/enterprise/cases/{caseId}.json
DB 팀 작업이 들어오면 이 모듈의 _AppendEvent/_SaveCase만 교체하면 된다.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Mapping

from flask import Flask, jsonify, request
from werkzeug.utils import secure_filename

if TYPE_CHECKING:
    from backend.pipeline_service import RunRegistry

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_STORE_DIR = _PROJECT_ROOT / "artifacts" / "enterprise"
_EVENTS_PATH = _STORE_DIR / "events.jsonl"
_CASES_DIR = _STORE_DIR / "cases"
_UPLOADS_DIR = _STORE_DIR / "uploads"

_WRITE_LOCK = threading.RLock()

_CASE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")


def _EnsureDirs() -> None:
    _CASES_DIR.mkdir(parents=True, exist_ok=True)
    _UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def _AppendEvent(action: str, payload: dict) -> dict:
    """수집 원장의 단일 진입점 — 모든 관리 액션은 여기를 지난다."""
    event = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "action": action,
        "payload": payload,
    }
    with _WRITE_LOCK:
        _EnsureDirs()
        with _EVENTS_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def _CasePath(caseId: str) -> Path | None:
    if not _CASE_ID_RE.match(caseId or ""):
        return None
    return _CASES_DIR / f"{caseId}.json"


def _LoadCase(caseId: str) -> dict | None:
    path = _CasePath(caseId)
    if path is None or not path.exists():
        return None
    try:
        case = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return case if isinstance(case, dict) else None


def _FindCaseByRun(jobId: str, taric10: str) -> dict | None:
    if not _CASES_DIR.exists():
        return None
    for path in _CASES_DIR.glob("*.json"):
        try:
            case = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(case, dict) or not case.get("caseId"):
            continue
        if (
            str(case.get("lastJobId") or "") == jobId
            and str(case.get("taric10") or "") == taric10
        ):
            return case
    return None


def _SaveCase(case: dict) -> None:
    path = _CasePath(case.get("caseId", ""))
    if path is None:
        return
    with _WRITE_LOCK:
        _EnsureDirs()
        path.write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")


def _NewCaseId() -> str:
    stamp = time.strftime("%Y%m%d")
    return f"EXP-{stamp}-{uuid.uuid4().hex[:6].upper()}"


def _Payload() -> dict:
    payload = request.get_json(silent=True) or {}
    return payload if isinstance(payload, dict) else {}


def _DocumentKey(value: object, index: int) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
    return normalized[:56] or f"document_{index + 1}"


def _DocumentCategory(name: str) -> str:
    normalized = name.lower()
    if any(token in normalized for token in ("ingredient", "composition", "label", "health", "haccp", "specification", "coa")):
        return "product"
    if any(token in normalized for token in ("eori", "business registration", "company registration")):
        return "company"
    return "customs"


def _DocumentsFromPackage(package: Mapping[str, object]) -> list[dict]:
    """Flatten TARIC detailed requirements into the enterprise screen's document rows."""
    documents: list[dict] = []
    seen: set[str] = set()
    for requirement in package.get("requirements") or []:
        if not isinstance(requirement, Mapping):
            continue
        details = requirement.get("detailed_requirements") or []
        for detail in details:
            if not isinstance(detail, Mapping):
                continue
            if str(detail.get("decision_status") or "").lower() == "exempted":
                continue
            name = str(detail.get("required_document") or "").strip()
            if not name:
                continue
            baseKey = _DocumentKey(name, len(documents))
            key = baseKey
            suffix = 2
            while key in seen:
                key = f"{baseKey}_{suffix}"
                suffix += 1
            seen.add(key)
            category = _DocumentCategory(name)
            documents.append({
                "key": key,
                "cat": category,
                "name": name,
                "quality": "missing",
                "file": "",
                "chosen": "direct" if category == "customs" else None,
                "origin": "TARIC 서류 추천",
                "reason": str(detail.get("decision_reason") or ""),
            })
    if documents:
        return documents
    for index, requirement in enumerate(package.get("requirements") or []):
        if not isinstance(requirement, Mapping):
            continue
        name = str(requirement.get("measure_type") or "TARIC 요건 확인").strip()
        documents.append({
            "key": _DocumentKey(name, index),
            "cat": "customs",
            "name": name,
            "quality": "missing",
            "file": "",
            "chosen": "direct",
            "origin": "TARIC 서류 추천",
        })
    return documents


def _UpdateDocument(case: dict, documentKey: str, changes: Mapping[str, object]) -> None:
    documents = case.setdefault("documents", [])
    if not isinstance(documents, list):
        documents = []
        case["documents"] = documents
    for document in documents:
        if isinstance(document, dict) and document.get("key") == documentKey:
            document.update({key: value for key, value in changes.items() if value is not None})
            break
    else:
        documents.append({"key": documentKey, "name": documentKey, **changes})


def RegisterEnterpriseApi(app: Flask, *, registry: "RunRegistry | None" = None) -> None:
    @app.post("/api/enterprise/import-classification")
    def enterprise_import_classification():
        payload = _Payload()
        jobId = str(payload.get("jobId") or "").strip()
        taric10 = str(payload.get("taric10") or "").strip()
        if not jobId or not taric10:
            return jsonify({"ok": False, "error": "jobId_and_taric10_required"}), 400
        if registry is None:
            return jsonify({"ok": False, "error": "run_registry_unavailable"}), 503

        detail = registry.BuildDocumentPackageDetail(jobId, taric10)
        package = detail.get("document_package") if isinstance(detail, Mapping) else None
        snapshot = registry.BuildUiResult(jobId)
        if not isinstance(package, Mapping) or not snapshot:
            return jsonify({"ok": False, "error": "classification_result_not_found"}), 404

        packageTaric10 = str(package.get("taric10") or "").strip()
        if packageTaric10 != taric10:
            return jsonify({"ok": False, "error": "taric10_not_in_run"}), 400

        understanding = snapshot.get("product_understanding_view")
        requestView = snapshot.get("request")
        understanding = understanding if isinstance(understanding, Mapping) else {}
        requestView = requestView if isinstance(requestView, Mapping) else {}
        facts = requestView.get("facts") if isinstance(requestView.get("facts"), Mapping) else {}
        name = str(understanding.get("product_name") or facts.get("product_name") or requestView.get("query") or taric10).strip()
        url = str(facts.get("url") or "").strip()

        with _WRITE_LOCK:
            existingCase = _FindCaseByRun(jobId, taric10)
            if existingCase is not None:
                return jsonify({
                    "ok": True,
                    "caseId": existingCase["caseId"],
                    "case": existingCase,
                })

            caseId = _NewCaseId()
            case = {
                "caseId": caseId,
                "name": name,
                "url": url,
                "taric10": taric10,
                "lastJobId": jobId,
                "jobHistory": [jobId],
                "documentPackage": dict(package),
                "documents": _DocumentsFromPackage(package),
                "events": 1,
                "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            }
            _SaveCase(case)
            _AppendEvent("import-classification", {
                "caseId": caseId,
                "jobId": jobId,
                "taric10": taric10,
            })
        return jsonify({"ok": True, "caseId": caseId, "case": case})

    @app.post("/api/enterprise/register-product")
    def enterprise_register_product():
        payload = _Payload()
        caseId = str(payload.get("caseId") or "").strip() or _NewCaseId()
        case = _LoadCase(caseId) or {"caseId": caseId, "docs": {}, "events": 0}
        # 편의 기능(절감액 계산)을 명분으로 들어오는 핵심 수집 필드들:
        # url(판매 채널), price(판매가), volume(월 물량), channel(판매처)
        for key in ("name", "url", "coi", "price", "volume", "channel", "destination"):
            value = payload.get(key)
            if value not in (None, ""):
                case[key] = value
        case["events"] = int(case.get("events", 0)) + 1
        _SaveCase(case)
        _AppendEvent("register-product", {**payload, "caseId": caseId})
        return jsonify({"ok": True, "caseId": caseId, "case": case})

    @app.post("/api/enterprise/doc-status")
    def enterprise_doc_status():
        # 서류 원장 이벤트 — 업로드/원본확인/직접·대행 전환이 전부 이력으로 남는다.
        payload = _Payload()
        caseId = str(payload.get("caseId") or "").strip()
        docKey = str(payload.get("doc") or "").strip()
        if not caseId or not docKey:
            return jsonify({"ok": False, "error": "caseId_and_doc_required"}), 400
        case = _LoadCase(caseId) or {"caseId": caseId, "docs": {}, "events": 0}
        docs = case.setdefault("docs", {})
        entry = docs.setdefault(docKey, {})
        for key in ("quality", "file", "chosen", "requested"):
            value = payload.get(key)
            if value not in (None, ""):
                entry[key] = value
        _UpdateDocument(case, docKey, entry)
        case["events"] = int(case.get("events", 0)) + 1
        case["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        _SaveCase(case)
        _AppendEvent("doc-status", payload)
        return jsonify({"ok": True})

    @app.post("/api/enterprise/cases/<caseId>/documents/<documentKey>/upload")
    def enterprise_upload_document(caseId: str, documentKey: str):
        case = _LoadCase(caseId)
        upload = request.files.get("file")
        if case is None:
            return jsonify({"ok": False, "error": "case_not_found"}), 404
        if upload is None or not upload.filename:
            return jsonify({"ok": False, "error": "file_required"}), 400
        filename = secure_filename(upload.filename)
        if not filename:
            return jsonify({"ok": False, "error": "invalid_filename"}), 400
        targetDir = _UPLOADS_DIR / caseId / _DocumentKey(documentKey, 0)
        targetDir.mkdir(parents=True, exist_ok=True)
        targetPath = targetDir / filename
        upload.save(targetPath)
        relativePath = str(targetPath.relative_to(_STORE_DIR))
        _UpdateDocument(case, documentKey, {
            "quality": "unverified",
            "file": filename,
            "filePath": relativePath,
            "uploadedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "origin": "직접 업로드",
        })
        case["events"] = int(case.get("events", 0)) + 1
        case["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        _SaveCase(case)
        _AppendEvent("upload-document", {"caseId": caseId, "doc": documentKey, "file": filename})
        return jsonify({"ok": True, "file": filename, "filePath": relativePath})

    @app.post("/api/enterprise/doc-request")
    def enterprise_doc_request():
        payload = _Payload()
        caseId = str(payload.get("caseId") or "").strip()
        docKey = str(payload.get("doc") or "").strip()
        contact = str(payload.get("contact") or "").strip()
        case = _LoadCase(caseId) if caseId else None
        if case is not None and docKey and contact:
            _UpdateDocument(case, docKey, {"requested": contact})
            case["events"] = int(case.get("events", 0)) + 1
            case["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            _SaveCase(case)
        _AppendEvent("doc-request", payload)
        # TODO: 실제 메일/SMS 발송 연동 — 지금은 요청 이력만 원장에 적재.
        return jsonify({"ok": True, "sent": False, "logged": True})

    @app.post("/api/enterprise/issue-url")
    def enterprise_issue_url():
        payload = _Payload()
        caseId = str(payload.get("caseId") or "").strip() or "case"
        docKey = str(payload.get("doc") or "").strip() or "doc"
        token = uuid.uuid4().hex[:16]
        submitUrl = f"asap.export/submit/{caseId}/{docKey}?t={token}"
        _AppendEvent("issue-url", {**payload, "token": token})
        return jsonify({"ok": True, "url": submitUrl, "token": token})

    @app.post("/api/enterprise/coi-normalize")
    def enterprise_coi_normalize():
        payload = _Payload()
        _AppendEvent("coi-normalize", payload)
        # TODO(파이프라인 담당): 업로드 실물 파일 수취 → DB/sources/coi_normalize.py로
        # asap-coi-v1 폼 생성 → ASAP_COI_FORM_DIR 저장. 이후 coi_loader가 제품명
        # 매칭으로 composition lane에 주입한다. 여기서는 요청 이벤트만 적재.
        return jsonify({"ok": True, "normalized": False, "logged": True})

    @app.post("/api/enterprise/link-job")
    def enterprise_link_job():
        # 케이스 ↔ 분류 job 귀속 — 재방문 복원과 분류 이력의 근거.
        payload = _Payload()
        caseId = str(payload.get("caseId") or "").strip()
        jobId = str(payload.get("jobId") or "").strip()
        if not caseId or not jobId:
            return jsonify({"ok": False, "error": "caseId_and_jobId_required"}), 400
        case = _LoadCase(caseId) or {"caseId": caseId, "docs": {}, "events": 0}
        history = case.setdefault("jobHistory", [])
        if jobId not in history:
            history.append(jobId)
        case["lastJobId"] = jobId
        for key in ("taric10", "hs10"):
            value = payload.get(key)
            if value:
                case[key] = value
        _SaveCase(case)
        _AppendEvent("link-job", payload)
        return jsonify({"ok": True})

    @app.get("/api/enterprise/broker-filing")
    def enterprise_broker_filing():
        caseId = str(request.args.get("caseId") or "").strip()
        case = _LoadCase(caseId) if caseId else None
        return jsonify({"ok": True, "caseId": caseId, "filed": bool((case or {}).get("filed"))})

    @app.get("/api/enterprise/cases")
    def enterprise_cases():
        # 기업 서비스 화면용 목록 — 파일 스냅샷 나열.
        _EnsureDirs()
        cases = []
        for path in sorted(_CASES_DIR.glob("*.json")):
            try:
                cases.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return jsonify({"ok": True, "cases": cases})

    @app.get("/api/enterprise/cases/<caseId>")
    def enterprise_case(caseId: str):
        case = _LoadCase(caseId)
        if case is None:
            return jsonify({"ok": False, "error": "case_not_found"}), 404
        return jsonify({"ok": True, "case": case})
