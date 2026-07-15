// 기업 서비스 관리 API 클라이언트 — /api/enterprise/* (src/backend/enterprise_api.py)
//
// 실호출 우선, 실패(백엔드 미기동·구버전) 시 콘솔 스텁으로 조용히 폴백한다.
// 이 레이어를 지나는 모든 액션은 서버의 append-only 이벤트 원장(events.jsonl)에
// 쌓인다 — 관리 데이터 수집의 단일 진입점.
const BASE = "/api/enterprise";

async function call(action, payload, { method = "POST" } = {}) {
  try {
    const url =
      method === "GET"
        ? `${BASE}/${action}?${new URLSearchParams(payload || {})}`
        : `${BASE}/${action}`;
    const response = await fetch(url, {
      method,
      headers: method === "GET" ? undefined : { "Content-Type": "application/json" },
      body: method === "GET" ? undefined : JSON.stringify(payload || {}),
    });
    if (!response.ok) {
      throw new Error(`http_${response.status}`);
    }
    return await response.json();
  } catch (error) {
    // 백엔드가 아직 이 라우트를 모르는 경우 — UI는 계속 동작해야 한다.
    console.info(`[enterprise-api fallback] ${action}`, payload, String(error));
    return { ok: true, stub: true };
  }
}

// 상품(케이스) 등록 — url/판매가/물량/채널이 절감액 계산 명분으로 함께 들어온다
export const registerProduct = (payload) => call("register-product", payload);
// 서류 상태 변화 보고 (업로드/원본확인/직접·대행 전환) — 서류 원장 이벤트
export const reportDocStatus = (payload) => call("doc-status", payload);
// 누락 서류 제출 요청 발송 (메일/SMS)
export const submitDocRequest = (payload) => call("doc-request", payload);
// 기업 서류 제출 URL 발급
export const issueSubmitUrl = (payload) => call("issue-url", payload);
// COI 정규화 — 업로드 COI → coi_normalize(asap-coi-v1) → coi_loader 주입 경로
export const normalizeCoi = (payload) => call("coi-normalize", payload);
// 케이스 ↔ 분류 job 귀속 (재방문 복원·분류 이력의 근거)
export const linkJob = (payload) => call("link-job", payload);
// 관세사 신고 상태 조회
export const fetchBrokerFiling = (caseId) => call("broker-filing", { caseId }, { method: "GET" });
// 내부 관제용 케이스 목록
export const fetchCases = () => call("cases", {}, { method: "GET" });
