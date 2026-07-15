"""기업 서비스 관리 API — /api/enterprise/*

기업용 UI(webapp /enterprise, /admin/companies)의 관리 데이터 포트.

설계 의도 (docs/enterpriseUI.md 참고):
- 표면 기능은 기업 이용자 편의(케이스 관리, 서류 수집, 요청 발송, 절감액 계산).
- 실질 자산은 이 포트를 지나는 **모든 흐름의 이벤트 원장**이다 — 상품 URL(판매 채널),
  판매가·예상 물량, COI(성분), 서류 상태 변화, 분류 결과 귀속, 통관(신고) 결과가
  전부 append-only 로그로 쌓인다. DB 이관 시 이 이벤트 포맷을 그대로 테이블로 옮긴다.

저장소는 파일 기반 플레이스홀더:
- 이벤트 원장: src/artifacts/enterprise/events.jsonl (append-only)
- 케이스 스냅샷: src/artifacts/enterprise/cases/{caseId}.json
DB 팀 작업이 들어오면 이 모듈의 _AppendEvent/_SaveCase만 교체하면 된다.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, jsonify, request

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_STORE_DIR = _PROJECT_ROOT / "src" / "artifacts" / "enterprise"
_EVENTS_PATH = _STORE_DIR / "events.jsonl"
_CASES_DIR = _STORE_DIR / "cases"

_WRITE_LOCK = threading.Lock()

_CASE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")


def _EnsureDirs() -> None:
    _CASES_DIR.mkdir(parents=True, exist_ok=True)


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
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
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


def RegisterEnterpriseApi(app: Flask) -> None:
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
        case["events"] = int(case.get("events", 0)) + 1
        _SaveCase(case)
        _AppendEvent("doc-status", payload)
        return jsonify({"ok": True})

    @app.post("/api/enterprise/doc-request")
    def enterprise_doc_request():
        payload = _Payload()
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
        # 내부 관제(/admin/companies)용 목록 — 파일 스냅샷 나열.
        _EnsureDirs()
        cases = []
        for path in sorted(_CASES_DIR.glob("*.json")):
            try:
                cases.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return jsonify({"ok": True, "cases": cases})
