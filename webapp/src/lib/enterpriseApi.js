// 기업 서비스 관리용 백엔드 API 자리 — 아직 연결하지 않음 (구색용 스텁).
// 실제 연결 시 asap_app.py 쪽에 /api/enterprise/* 라우트를 열고, 아래 apiStub 내부를
// fetch 호출로 바꾸면 페이지 코드는 그대로 동작한다.
const BASE = "/api/enterprise"; // TODO: 백엔드 포트·라우트 확정 후 연결

async function apiStub(action, payload) {
  // 연결 시:
  // return fetch(`${BASE}/${action}`, {
  //   method: "POST",
  //   headers: { "Content-Type": "application/json" },
  //   body: JSON.stringify(payload),
  // }).then((r) => r.json());
  console.info(`[enterprise-api stub] ${BASE}/${action}`, payload);
  return { ok: true, stub: true };
}

// 상품(케이스) 등록
export const registerProduct = (payload) => apiStub("register-product", payload);
// 누락 서류 제출 요청 발송 (메일/SMS)
export const submitDocRequest = (payload) => apiStub("doc-request", payload);
// 기업 서류 제출 URL 발급
export const issueSubmitUrl = (payload) => apiStub("issue-url", payload);
// 관세사 신고 상태 조회 — 신고 완료 시 케이스에 "신고 완료" 표시
export const fetchBrokerFiling = (payload) => apiStub("broker-filing", payload);
// COI 정규화 — 업로드 COI를 DB/sources/coi_normalize.py로 넘겨 asap-coi-v1 폼을 만들고
// ASAP_COI_FORM_DIR에 저장하면, 파이프라인의 coi_loader가 product_map(제품명 매칭)으로
// 찾아 composition lane에 주입한다. COI가 확보된 케이스는 분류 실행 전 반드시 이 단계를 거친다.
export const normalizeCoi = (payload) => apiStub("coi-normalize", payload);
