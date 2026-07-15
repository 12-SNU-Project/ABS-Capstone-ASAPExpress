import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useClassificationRun } from "../hooks/useClassificationRun";
import { asList, asObject, clean } from "../lib/format.js";
import {
  registerProduct,
  reportDocStatus,
  submitDocRequest,
  issueSubmitUrl,
  normalizeCoi,
  linkJob,
} from "../lib/enterpriseApi.js";
import logo from "../assets/asap_black.png";

// 페르소나: 수출업자(제조사 아님) — 예: 식당이 밀키트를 제작해 수출.
// 서류는 제조사에서 받아오되 품질은 미보증 → 서류 수집·검증이 메인 플로우.
const DEMO_CASE = {
  company: "연안식당 (밀키트 수출)",
  plan: "스탠다드 플랜",
  manager: "ASAP 전담 매니저 · 김수출",
  destination: "독일 (함부르크항)",
  caseId: "EXP-2026-0715-003",
};

// 서류 인벤토리 — 3구분:
//  product: 물품 서류(COI 등) — 우리가 대신 받을 수 없음 → 반드시 직접 제출
//  customs: 통관 서류(CI/PL 등) — 직접 제출 vs 대행 위임 선택
//  company: 기업 서류 — 제출 URL만 발급, 수취·검토는 ASAP 관리자 페이지에서
const INITIAL_DOCS = [
  { key: "coi", cat: "product", name: "성분명세서 (COI)", quality: "unverified", file: "coi_jaecheop_manufacturer.pdf", origin: "제조사 수취" },
  { key: "haccp", cat: "product", name: "HACCP 인증 · 시설 등록증 (HACCP)", quality: "unverified", file: "haccp_cert_scan.jpg", origin: "제조사 수취" },
  { key: "label", cat: "product", name: "라벨 원안 (LABEL)", quality: "missing", file: "", origin: "제조사 요청 중" },
  { key: "spec", cat: "product", name: "제품 사양서 (SPEC)", quality: "missing", file: "", origin: "미확보" },
  { key: "coo", cat: "product", name: "원산지 증명서 (C/O)", quality: "missing", file: "", origin: "미확보" },
  { key: "invoice", cat: "customs", name: "상업송장 (CI)", quality: "verified", file: "invoice_0703.pdf", chosen: "direct" },
  { key: "packing", cat: "customs", name: "포장명세서 (PL)", quality: "verified", file: "packing_0703.pdf", chosen: "direct" },
  { key: "origin", cat: "customs", name: "원산지 신고 문안 (OD · 한-EU FTA)", quality: "agency", file: "", chosen: "agency" },
  { key: "bl", cat: "customs", name: "선하증권 (B/L)", quality: "agency", file: "", chosen: "agency" },
  { key: "bizreg", cat: "company", name: "사업자등록증 (BR)", quality: "missing", file: "", url: "" },
  { key: "exporter", cat: "company", name: "수출자 신고 정보 (EORI)", quality: "missing", file: "", url: "" },
];

// 새로 추가한 상품의 초기 서류 세트 — COI만 사용자가 첨부, 나머지 미확보
const newProductDocs = (coiFile) => [
  { key: "coi", cat: "product", name: "성분명세서 (COI)", quality: coiFile ? "unverified" : "missing", file: coiFile || "", origin: coiFile ? "직접 업로드" : "미확보" },
  { key: "haccp", cat: "product", name: "HACCP 인증 · 시설 등록증 (HACCP)", quality: "missing", file: "", origin: "미확보" },
  { key: "label", cat: "product", name: "라벨 원안 (LABEL)", quality: "missing", file: "", origin: "미확보" },
  { key: "spec", cat: "product", name: "제품 사양서 (SPEC)", quality: "missing", file: "", origin: "미확보" },
  { key: "coo", cat: "product", name: "원산지 증명서 (C/O)", quality: "missing", file: "", origin: "미확보" },
  { key: "invoice", cat: "customs", name: "상업송장 (CI)", quality: "missing", file: "", chosen: "direct" },
  { key: "packing", cat: "customs", name: "포장명세서 (PL)", quality: "missing", file: "", chosen: "direct" },
  { key: "origin", cat: "customs", name: "원산지 신고 문안 (OD · 한-EU FTA)", quality: "missing", file: "", chosen: "direct" },
  { key: "bl", cat: "customs", name: "선하증권 (B/L)", quality: "missing", file: "", chosen: "direct" },
  { key: "bizreg", cat: "company", name: "사업자등록증 (BR)", quality: "missing", file: "", url: "" },
  { key: "exporter", cat: "company", name: "수출자 신고 정보 (EORI)", quality: "missing", file: "", url: "" },
];

const CAT_LABEL = {
  product: ["물품 서류", "직접 제출 필수 — ASAP이 대리 수취 불가"],
  customs: ["통관 서류", "직접 제출 또는 대행 위임 선택"],
  company: ["기업 서류", "제출 URL 발급 — 수취·검토는 ASAP 관리자"],
};

const QUALITY = {
  verified: ["원본 확인", "ok"],
  unverified: ["미검증 사본", "warn"],
  missing: ["누락", "miss"],
  agency: ["대행 진행", "violet"],
  url_sent: ["URL 발급 · 수취 대기", "info"],
};

const AGENCY_TIERS = [
  { key: "docs", title: "서류 준비까지", desc: "요건 서류 작성·검증 대행 (위생증명 신청 지원 포함)", eta: "3~5일" },
  { key: "customs", title: "통관 신고까지", desc: "서류 대행 + EU 수입 통관 신고·CHED 제출 대행", eta: "7~10일" },
  { key: "logistics", title: "운송·납품까지", desc: "통관 대행 + 냉동 물류 예약·현지 배송 추적", eta: "14~21일" },
];

const TRACK_STEPS = ["서류 수집", "분류·요건 분석", "관세사 검토", "수출 신고", "EU 통관", "현지 운송"];

// 관리 그리드의 나머지 상품들 (정적 데모 — 파이프라인 미연동)
const STATIC_ITEMS = [
  {
    id: "EXP-2026-0709-001",
    name: "매생이국 밀키트 400g",
    docs: [10, 10],
    url: "smartstore.naver.com/yeonan/5521",
    hs10: "2104100000",
    acc: "92%",
    origin: "KR",
    duty: ["0% (FTA)", "20%"],
    reqs: [["HC", "ok"], ["CHED-P", "ok"], ["Y155", "ok"], ["LABEL", "ok"]],
    customs: "제출 4 · 완료",
    filed: true,
    reviewed: true,
  },
  {
    id: "EXP-2026-0712-008",
    name: "부추전 밀키트 600g",
    docs: [7, 9],
    url: "smartstore.naver.com/yeonan/5544",
    hs10: "1901909985",
    acc: "78%",
    origin: "KR",
    duty: ["0% (FTA)", "12.8%"],
    reqs: [["HC", "unverified"], ["CHED-P", "ok"], ["Y155", "ok"], ["LABEL", "missing"]],
    customs: "제출 2 · 대행 2",
    filed: false,
  },
];

// 판정 4단계 — 시스템 자동 산출 (사용자 선택 불가)
const VERDICTS = {
  possible: ["수출 가능", "ok", "요건 증거가 모두 충족되었습니다. 통관 절차로 진행할 수 있습니다."],
  add_docs: ["필요서류 추가", "warn", "제출됐지만 검증되지 않은 서류가 있습니다. 원본 확인 후 진행하세요."],
  missing: ["누락서류 존재", "miss", "필수 요건에 매핑된 서류가 아직 없습니다. 수집 또는 대행이 필요합니다."],
  blocked: ["수출 불가", "block", "하드 블로커가 있습니다 — 요건 변경 전에는 진행할 수 없습니다."],
};

// 관리 그리드 수입요건 칩 축약 라벨
const REQ_ABBR = {
  "관세 (FTA 0%)": "FTA",
  "위생 인증": "HC",
  "IUU (수산)": "CATCH",
  "제재 확인": "Y155",
  "제조공정": "HACCP",
  "라벨 규정": "LABEL",
};

// 분류 실행 전 BTI 카드용 데모 판례
const DEMO_PRECEDENTS = [
  {
    evidence_ref: "DEBTI2023/11420-1",
    similarity_comment: "민물조개(재첩) 기반 즉석 수프 — 연체동물 조제품으로 1605 유지",
    case_summary: "냉동 상태의 조개 국물 조리식품. 신선/단순가공(03류)이 아닌 조제품(16류)으로 판단, 소매포장 기준 1605.55 적용.",
    difference_comment: "본 건은 소스·건더기 동봉 밀키트(복합 구성)라는 점이 다름",
  },
  {
    evidence_ref: "FRBTI2022/08771-2",
    similarity_comment: "냉동 해산물 국물요리 세트 — 어패류 성분 기준 분류 유지",
    case_summary: "야채·양념이 포함되어도 본질적 특성(essential character)은 수산물이 부여한다고 보아 16류 유지.",
    difference_comment: "완제품 즉석 조리 여부에서 차이",
  },
];

const PANEL_TITLES = {
  docs: "서류 인벤토리",
  code: "코드 분류 근거 · BTI 판례",
  duty: "적용 세율 — TARIC10 세율 선언",
  review: "관세사 검토 보드",
  customs: "통관 서류 — 제출 · 대행",
};

function formatTaric(code) {
  const digits = clean(code);
  return digits.length === 10
    ? `${digits.slice(0, 4)} ${digits.slice(4, 6)} ${digits.slice(6, 8)} ${digits.slice(8)}`
    : digits || "-";
}

// 서류 배열 → 파생값 (행별 계산에 재사용)
const countSecured = (list) => list.filter((d) => d.quality !== "missing" && d.quality !== "url_sent").length;
const summarizeCustoms = (list) => {
  const customs = list.filter((d) => d.cat === "customs");
  const agency = customs.filter((d) => d.chosen === "agency").length;
  return `제출 ${customs.length - agency} · 대행 ${agency}`;
};

// 요건 증거 매트릭스 rows — 서류 배열 기준으로 계산
function evidenceRows(list, dutyBase) {
  const docBy = (key) => list.find((d) => d.key === key);
  const rows = [
    { area: "관세 (FTA 0%)", need: "한-EU FTA 원산지 신고 문안 (인증수출자)", doc: docBy("origin"), note: `미제출 시 제3국 세율 ${dutyBase} 적용` },
    { area: "위생 인증", need: "위생증명서(FISH-CRUST-HC) + CHED-P 사전신고", doc: docBy("haccp"), note: "제조시설이 EU 승인시설 목록에 있어야 발급 가능" },
    { area: "IUU (수산)", need: "어획증명 CATCH 전자제출 (양식이면 비대상 신고 Y927)", doc: docBy("coi"), note: "재첩(패류) 기원 확인 — COI의 원료 원산 정보로 판정" },
    { area: "제재 확인", need: "러시아·벨라루스 간접수출 아님 신고 (Y155)", doc: null, selfDeclare: true, note: "세관신고서 기재로 갈음 — 별도 서류 불필요" },
    { area: "제조공정", need: "HACCP·시설 등록 증빙 (승인시설 대조용)", doc: docBy("haccp"), note: "미검증 사본은 원본 대조 후 인정" },
    { area: "라벨 규정", need: "EU 표시사항(알레르겐·영양) 검토표", doc: docBy("label"), note: "제조사 라벨 원안 기준 검토" },
  ];
  return rows.map((row) => {
    let status = "missing";
    if (row.selfDeclare) status = "ok";
    else if (row.doc?.quality === "verified") status = "ok";
    else if (row.doc?.quality === "unverified") status = "unverified";
    else if (row.doc?.quality === "agency") status = "agency";
    return { ...row, status };
  });
}

const suggestVerdict = (rows) => {
  if (rows.some((e) => e.blocked)) return "blocked";
  if (rows.some((e) => e.status === "missing")) return "missing";
  if (rows.some((e) => e.status === "unverified")) return "add_docs";
  return "possible";
};

export default function EnterprisePage() {
  const { result, busy, runPipeline } = useClassificationRun();
  // panel: 어느 행(id)의 어느 카드(key)가 열려 있는지 — 행 바로 아래로 확장
  const [panel, setPanel] = useState({ id: DEMO_CASE.caseId, key: "docs" });
  // 행별 서류 상태 — 상품 추가 시 새 엔트리가 생긴다
  const [docsById, setDocsById] = useState({ [DEMO_CASE.caseId]: INITIAL_DOCS });
  const [extraRows, setExtraRows] = useState([]); // {id, name}
  const [urlById, setUrlById] = useState({ [DEMO_CASE.caseId]: "" });
  // 파이프라인 결과의 주인 행 — 마지막으로 분류 실행을 누른 행
  const [runOwner, setRunOwner] = useState(DEMO_CASE.caseId);
  const [openCat, setOpenCat] = useState("product");
  const [tier, setTier] = useState("customs");
  const [agencyConfirmed, setAgencyConfirmed] = useState(false);
  // 누락 서류 요청 발송 (메일/휴대폰)
  const [reqOpen, setReqOpen] = useState(null);
  const [reqContact, setReqContact] = useState("");
  // 상품 추가 폼 — 판매가·물량·채널은 "예상 관세 절감액" 계산 명분의 수집 필드
  const [addOpen, setAddOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [newUrl, setNewUrl] = useState("");
  const [newCoi, setNewCoi] = useState("");
  const [newPrice, setNewPrice] = useState("");
  const [newVolume, setNewVolume] = useState("");
  const [newChannel, setNewChannel] = useState("");
  // 행별 판매 정보 (절감액 계산용) — 메인 데모 케이스는 기본값 제공
  const [metaById, setMetaById] = useState({
    [DEMO_CASE.caseId]: { price: 12900, volume: 400, channel: "스마트스토어" },
  });
  // 관세사의 해당/비해당 오버라이드 (기본값 = 시스템 판정)
  const [regChoice, setRegChoice] = useState({});
  const fileTargetRef = useRef(null);
  const fileInputRef = useRef(null);
  const coiInputRef = useRef(null);

  // 사용자용 테마 — 기본은 화이트(가독성 피드백), 네온은 토글로. 소비자 화면과 키 공유.
  const [uiTheme, setUiTheme] = useState(
    () => window.localStorage.getItem("asap-user-theme") || "light",
  );
  useEffect(() => {
    window.localStorage.setItem("asap-user-theme", uiTheme);
    document.body.classList.remove("asap-cjs-neon", "consumer-body", "asap-user-light");
    if (uiTheme === "neon") {
      document.body.classList.add("asap-cjs-neon", "consumer-body");
    } else {
      document.body.classList.add("asap-user-light");
    }
    return () => document.body.classList.remove("asap-cjs-neon", "consumer-body", "asap-user-light");
  }, [uiTheme]);

  const candidates = asList(asObject(result?.candidate_code_set).candidates);
  const primary = candidates.find((c) => c.llm_recommended) || candidates[0] || null;
  const packages = asList(result?.document_packages);
  const firstPackage = asObject(packages[0]);
  const understanding = asObject(result?.product_understanding_view);
  const isLive = !!primary;
  const liveTaric10 = isLive
    ? clean(primary.taric10) || clean(asList(primary.taric10_branch_candidates)[0]?.taric10)
    : "";
  const mainName = clean(understanding.product_name) && runOwner === DEMO_CASE.caseId
    ? clean(understanding.product_name)
    : "재첩국 밀키트 500g (냉동)";
  const basis = clean(asList(primary?.classification_basis)[0]);
  const livePrecedents = asList(primary?.similar_ebti_cases);
  const precedents = livePrecedents.length ? livePrecedents : DEMO_PRECEDENTS;
  const dutyBase = clean(firstPackage.basic_duty) || "20%";
  const jobId = clean(result?.job_id);

  // 분류 완료 시 케이스 ↔ job 귀속을 원장에 기록 (job당 1회)
  const linkedJobRef = useRef("");
  useEffect(() => {
    if (isLive && jobId && linkedJobRef.current !== jobId) {
      linkedJobRef.current = jobId;
      linkJob({ caseId: runOwner, jobId, taric10: liveTaric10 });
    }
  }, [isLive, jobId, runOwner, liveTaric10]);

  // 활성 행 = 카드가 열려 있는 행 (없으면 메인 케이스)
  const activeId = panel?.id && docsById[panel.id] ? panel.id : DEMO_CASE.caseId;
  const docs = docsById[activeId];
  const setDocs = (updater) =>
    setDocsById((prev) => ({ ...prev, [activeId]: typeof updater === "function" ? updater(prev[activeId]) : updater }));
  const docBy = (key) => docs.find((d) => d.key === key);

  const activeIsRunOwner = activeId === runOwner;
  const taric10 = activeIsRunOwner && liveTaric10 ? liveTaric10 : "1605550000";
  const activeLive = activeIsRunOwner && isLive;
  const docDetailPath = activeLive && jobId && clean(taric10) ? `/document/${jobId}/${clean(taric10)}` : null;

  const evidence = useMemo(() => evidenceRows(docs, dutyBase), [docs, dutyBase]);
  const suggested = useMemo(() => suggestVerdict(evidence), [evidence]);

  // 수입요건 카드용 — 이 코드에 걸리는 제재·인증·사전신고 (관세사가 해당/비해당을 직접 선택)
  const regulations = useMemo(
    () => [
      { key: "hc", name: "위생증명서 FISH-CRUST-HC", applies: true, docKey: "haccp", note: "이매패류 조제품 — 수의공중보건 인증 대상" },
      { key: "ched", name: "CHED-P 사전신고 (TRACES)", applies: true, agency: true, note: "통관 시 전자 제출 — 대행 범위에 포함" },
      { key: "catch", name: "IUU 어획증명 CATCH", applies: true, docKey: "coi", note: "COI의 원료 원산 정보로 대상 판정" },
      { key: "y155", name: "제재 Y155 (러·벨 간접수출)", applies: true, selfDeclare: true, note: "신고서 기재로 갈음" },
      { key: "gmo", name: "GMO 승인 (32003R1829)", applies: false, docKey: "coi", note: "GM 원료 미포함" },
      { key: "eudr", name: "EUDR 산림전용 (1115/23)", applies: false, docKey: "spec", note: "대상 원자재 아님" },
      { key: "dualuse", name: "이중용도 통제 (0821/21)", applies: false, docKey: "spec", note: "식품 — 비대상" },
    ],
    [],
  );
  const regApplies = (reg) => regChoice[reg.key] ?? reg.applies;

  // 적용세율 카드용 — TARIC10에 붙는 세율 관련 선언만 (제재·인증은 수입요건에서)
  const dutyDeclarations = [
    { name: "FTA 협정 물품", value: "해당 — 한-EU FTA", tone: "ok", note: "원산지 기준 충족 시 특혜세율 0%" },
    { name: "특혜 관세 조건", value: "원산지 신고 문안 (OD)", tone: "warn", note: "인증수출자 문안 제출 시 특혜 적용" },
    { name: "추가 관세 (Additional duty)", value: "없음", tone: "off", note: "이 코드에 부가 관세 조치 없음" },
    { name: "관세 쿼터 (TRQ)", value: "비대상", tone: "off", note: "쿼터 물량 제한 없음" },
    { name: "반덤핑 · 상계관세", value: "비대상", tone: "off", note: "AD/CVD 조치 없음" },
  ];

  // 관세사 신고 상태 — 백엔드 연동 전 (fetchBrokerFiling 스텁). 연동 시 케이스별 조회로 대체.
  const filedById = { [DEMO_CASE.caseId]: false };

  const trackIndex = suggested === "possible" ? 3 : activeLive ? 2 : 1;

  const pickFile = (key) => {
    fileTargetRef.current = key;
    fileInputRef.current?.click();
  };

  const onFileChosen = (event) => {
    const file = event.target.files?.[0];
    const target = fileTargetRef.current;
    if (file && target) {
      setDocs((prev) =>
        prev.map((d) => (d.key === target ? { ...d, quality: "unverified", file: file.name, origin: d.origin ? d.origin : "직접 업로드" } : d)),
      );
      reportDocStatus({ caseId: activeId, doc: target, quality: "unverified", file: file.name });
    }
    event.target.value = "";
  };

  const markVerified = (key) => {
    setDocs((prev) => prev.map((d) => (d.key === key ? { ...d, quality: "verified" } : d)));
    reportDocStatus({ caseId: activeId, doc: key, quality: "verified" });
  };

  // 통관 서류: 직접 제출 ↔ 대행 위임 전환 (직접 복귀 시 이전 검증 상태 복원)
  const setMethod = (key, method) => {
    setDocs((prev) =>
      prev.map((d) => {
        if (d.key !== key) return d;
        if (method === "agency") return { ...d, chosen: "agency", prevQuality: d.quality !== "agency" ? d.quality : d.prevQuality, quality: "agency" };
        return { ...d, chosen: "direct", quality: d.file ? (d.prevQuality || "unverified") : "missing" };
      }),
    );
    reportDocStatus({ caseId: activeId, doc: key, chosen: method });
  };

  // 누락 서류 요청 — 입력한 메일/휴대폰으로 제출 요청 발송
  const sendRequest = (key) => {
    const contact = clean(reqContact);
    if (!contact) return;
    submitDocRequest({ caseId: activeId, doc: key, contact });
    setDocs((prev) => prev.map((d) => (d.key === key ? { ...d, requested: contact } : d)));
    setReqOpen(null);
    setReqContact("");
  };

  // 기업 서류: 제출 URL 발급 — 실제 수취·검토는 관리자 페이지에서.
  // 백엔드가 살아 있으면 토큰 포함 URL을 받아서 쓰고, 아니면 로컬 표기로 폴백.
  const issueUrl = async (key) => {
    const response = await issueSubmitUrl({ caseId: activeId, doc: key });
    const submitUrl = clean(response?.url) || `asap.export/submit/${activeId}/${key}`;
    setDocs((prev) =>
      prev.map((d) => (d.key === key ? { ...d, quality: "url_sent", url: submitUrl } : d)),
    );
  };

  // 분류 실행 — 제품명(또는 URL)만 있으면 실행.
  // 단, COI 서류가 확보된 행은 반드시 COI 정규화 경로를 먼저 거친다:
  // 업로드 COI → coi_normalize(정규화·번역) → asap-coi-v1 폼 → coi_loader가
  // 제품명 매칭으로 composition lane에 주입 → 그 상태로 파이프라인 실행.
  const runClassify = async (rowId, rowName) => {
    if (busy || (!clean(rowName) && !clean(urlById[rowId]))) return;
    const coiDoc = (docsById[rowId] || []).find((d) => d.key === "coi");
    if (coiDoc && coiDoc.quality !== "missing") {
      await normalizeCoi({ caseId: rowId, productName: rowName, file: coiDoc.file });
    }
    setRunOwner(rowId);
    runPipeline("full", { productName: rowName, url: clean(urlById[rowId]), description: "" });
  };

  // 상품 추가 — COI와 URL은 사용자가 제공, 등록 즉시 서류 인벤토리가 열린다.
  // 판매가·물량·채널은 절감액 계산에 쓰이며 케이스와 함께 원장에 적재된다.
  const addProduct = () => {
    const name = clean(newName);
    if (!name) return;
    const id = `EXP-2026-0715-${String(4 + extraRows.length).padStart(3, "0")}`;
    const price = Number(clean(newPrice).replace(/[^\d.]/g, "")) || 0;
    const volume = Number(clean(newVolume).replace(/[^\d.]/g, "")) || 0;
    registerProduct({
      caseId: id,
      name,
      url: clean(newUrl),
      coi: newCoi,
      price,
      volume,
      channel: clean(newChannel),
      destination: DEMO_CASE.destination,
    });
    setDocsById((prev) => ({ ...prev, [id]: newProductDocs(newCoi) }));
    setUrlById((prev) => ({ ...prev, [id]: clean(newUrl) }));
    if (price || volume || clean(newChannel)) {
      setMetaById((prev) => ({ ...prev, [id]: { price, volume, channel: clean(newChannel) } }));
    }
    setExtraRows((prev) => [...prev, { id, name }]);
    setPanel({ id, key: "docs" });
    setOpenCat("product");
    setAddOpen(false);
    setNewName("");
    setNewUrl("");
    setNewCoi("");
    setNewPrice("");
    setNewVolume("");
    setNewChannel("");
  };

  const togglePanel = (id, key) =>
    setPanel((prev) => (prev && prev.id === id && prev.key === key ? null : { id, key }));

  const cellCls = (base, id, key) =>
    `${base} ent-cell ${panel && panel.id === id && panel.key === key ? "sel" : ""}`;

  const cellClick = (id, key) => (e) => {
    e.stopPropagation();
    togglePanel(id, key);
  };

  /* ---------- 행 아래 확장 카드들 (활성 행 기준) ---------- */

  const docsPanel = (
    <>
      <div className="ent-cat-grid">
        {["product", "customs", "company"].map((cat) => {
          const list = docs.filter((d) => d.cat === cat);
          const secured = list.filter((d) => d.quality !== "missing" && d.quality !== "url_sent").length;
          const unverified = list.filter((d) => d.quality === "unverified").length;
          const missing = list.filter((d) => d.quality === "missing").length;
          return (
            <button
              key={cat}
              type="button"
              className={`ent-cat-card cat-${cat} ${openCat === cat ? "open" : ""}`}
              onClick={() => setOpenCat(openCat === cat ? null : cat)}
            >
              <div className="ent-cat-top">
                <b>{CAT_LABEL[cat][0]}</b>
                <span className="ent-cat-count">{secured}/{list.length}</span>
              </div>
              <div className="ent-cat-desc">{CAT_LABEL[cat][1]}</div>
              <div className="ent-cat-bar">
                <span style={{ width: `${list.length ? (secured / list.length) * 100 : 0}%` }} />
              </div>
              <div className="ent-cat-flags">
                {unverified ? <span className="ent-chip warn">미검증 {unverified}</span> : null}
                {missing ? <span className="ent-chip miss">누락 {missing}</span> : null}
                {!unverified && !missing ? <span className="ent-chip ok">이상 없음</span> : null}
              </div>
              <div className="ent-cat-toggle">{openCat === cat ? "접기 ▴" : "펼쳐서 확인 ▾"}</div>
            </button>
          );
        })}
      </div>
      {openCat ? (
        <div className={`ent-cat-panel cat-${openCat}`}>
          <div className="ent-bigtable-head">
            <span>서류</span><span>제출 방식</span><span>상태</span><span>파일 · 액션</span>
          </div>
          {docs.filter((d) => d.cat === openCat).map((doc) => {
            const cat = openCat;
            const [label, tone] = QUALITY[doc.quality];
            return (
              <div className={`ent-bigtable-row cat-${cat}`} key={doc.key}>
                <div className="ent-bigtable-name">
                  {doc.name}
                  {doc.origin ? <em>{doc.origin}</em> : null}
                  {doc.url ? <em className="url">📮 {doc.url}</em> : null}
                  {doc.requested ? <em className="url">📨 요청 발송 — {doc.requested}</em> : null}
                </div>
                <div className="ent-bigtable-method">
                  {cat === "product" ? <span className="ent-method-fixed">직접 제출 <b>(필수)</b></span> : null}
                  {cat === "customs" ? (
                    <span className="ent-method-toggle" role="group" aria-label="제출 방식">
                      <button type="button" className={doc.chosen === "direct" ? "on" : ""} onClick={() => setMethod(doc.key, "direct")}>직접 제출</button>
                      <button type="button" className={doc.chosen === "agency" ? "on agency" : ""} onClick={() => setMethod(doc.key, "agency")}>대행 위임</button>
                    </span>
                  ) : null}
                  {cat === "company" ? <span className="ent-method-fixed dim">제출 URL 발급</span> : null}
                </div>
                <div><span className={`ent-chip ${tone}`}>{label}</span></div>
                <div className="ent-doc-actions">
                  {doc.file ? <span className="ent-doc-file">📎 {doc.file}</span> : null}
                  {cat !== "company" && doc.quality === "missing" ? (
                    <>
                      <button type="button" className="ent-mini-btn solid" onClick={() => pickFile(doc.key)}>업로드</button>
                      {reqOpen === doc.key ? (
                        <span className="ent-req-inline">
                          <input
                            className="ent-mgmt-url-input"
                            placeholder="메일 또는 휴대폰 번호"
                            value={reqContact}
                            autoFocus
                            onChange={(e) => setReqContact(e.target.value)}
                            onKeyDown={(e) => e.key === "Enter" && sendRequest(doc.key)}
                          />
                          <button type="button" className="ent-mini-btn solid" onClick={() => sendRequest(doc.key)}>발송</button>
                          <button type="button" className="ent-mini-btn" onClick={() => setReqOpen(null)}>취소</button>
                        </span>
                      ) : (
                        <button type="button" className="ent-mini-btn" onClick={() => { setReqOpen(doc.key); setReqContact(""); }}>
                          {doc.requested ? "재요청" : "서류 요청"}
                        </button>
                      )}
                    </>
                  ) : null}
                  {doc.quality === "unverified" ? (
                    <>
                      <button type="button" className="ent-mini-btn solid" onClick={() => markVerified(doc.key)}>원본 확인</button>
                      <button type="button" className="ent-mini-btn" onClick={() => pickFile(doc.key)}>재업로드</button>
                    </>
                  ) : null}
                  {cat === "company" && doc.quality === "missing" ? (
                    <button type="button" className="ent-mini-btn solid" onClick={() => issueUrl(doc.key)}>URL 발급</button>
                  ) : null}
                  {cat === "company" && doc.quality === "url_sent" ? (
                    <span className="ent-doc-file dim">관리자 페이지에서 수취 확인</span>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      ) : null}
      <p className="ent-hint">
        <b>물품 서류</b>는 ASAP이 대리 수취할 수 없어 반드시 직접 제출해야 합니다. 제조사 수취 서류는 <b>품질 미보증</b>이라 "미검증 사본"으로
        등록되며 원본 대조 후 확정됩니다.
        {docDetailPath ? <> 요건 서류 패키지 전체는 <Link to={docDetailPath} className="ent-link">서류 상세 페이지 ›</Link></> : null}
      </p>
    </>
  );

  const codePanel = (
    <>
      <div className="ent-review-code-row">
        <div>
          <div className="ent-review-label">파이프라인 추천 TARIC10</div>
          <div className="ent-taric">{formatTaric(taric10)}</div>
          <div className="ent-review-meta">
            {activeLive && basis ? <span>{basis.slice(0, 160)}</span> : <span>연체동물(재첩) 조제품 — 소스·건더기 동봉 밀키트, 본질적 특성은 수산물이 부여</span>}
            <Link to="/classification" className="ent-link">분류 근거 전체 ›</Link>
          </div>
        </div>
        <div className="ent-duty compact">
          <div className="ent-duty-row"><span>정확도</span><strong>{activeLive ? "87%" : "—"}</strong></div>
          <div className="ent-duty-row highlight"><span>판례 근거</span><strong>{precedents.length}건</strong><em>{activeLive && livePrecedents.length ? "실데이터" : "데모"}</em></div>
        </div>
      </div>
      <div className="ent-review-label" style={{ marginTop: 16 }}>유사 BTI 판례</div>
      <div className="ent-bti-list">
        {precedents.slice(0, 3).map((p, i) => (
          <div className="ent-bti-item" key={clean(p.evidence_ref) || i}>
            <div className="ent-bti-ref">{clean(p.evidence_ref) || `BTI ${i + 1}`}</div>
            <div className="ent-bti-body">
              {clean(p.similarity_comment) ? <p><b>유사점</b> {clean(p.similarity_comment)}</p> : null}
              {clean(p.case_summary) ? <p className="dim">{clean(p.case_summary).slice(0, 220)}</p> : null}
              {clean(p.difference_comment) ? <p><b>차이점</b> {clean(p.difference_comment)}</p> : null}
            </div>
          </div>
        ))}
      </div>
    </>
  );

  // 연 예상 관세 절감액 = 판매가 × 월 물량 × 12 × 제3국 세율 (FTA 0% 적용 가정)
  const activeMeta = metaById[activeId] || {};
  const dutyRate = parseFloat(dutyBase) || 0;
  const annualSaving =
    activeMeta.price && activeMeta.volume
      ? Math.round((activeMeta.price * activeMeta.volume * 12 * dutyRate) / 100)
      : 0;

  const dutyPanel = (
    <>
      <div className="ent-duty compact wide">
        <div className="ent-duty-row"><span>제3국 세율</span><strong className="strike">{dutyBase}</strong></div>
        <div className="ent-duty-row highlight"><span>한-EU FTA</span><strong>0%</strong><em>원산지 문안 제출 시</em></div>
        {annualSaving ? (
          <div className="ent-duty-row highlight">
            <span>연 예상 절감액</span>
            <strong>{annualSaving.toLocaleString()}원</strong>
            <em>판매가 {Number(activeMeta.price).toLocaleString()}원 × 월 {Number(activeMeta.volume).toLocaleString()}개 기준</em>
          </div>
        ) : (
          <div className="ent-duty-row">
            <span>연 예상 절감액</span>
            <strong>—</strong>
            <em>상품 추가 시 판매가·물량을 입력하면 계산됩니다</em>
          </div>
        )}
      </div>
      <div className="ent-review-label" style={{ marginTop: 16 }}>TARIC10 세율 관련 선언</div>
      <div className="ent-reg-list">
        {dutyDeclarations.map((d) => (
          <div className={`ent-reg-row ${d.tone === "off" ? "na" : "applies"}`} key={d.name}>
            <div className="ent-reg-name">{d.name}<em>{d.note}</em></div>
            <span className={`ent-chip ${d.tone}`}>{d.value}</span>
            <span className="ent-reg-blank" />
          </div>
        ))}
      </div>
      <p className="ent-hint">제재·인증·사전신고 대상 여부는 <b>수입요건</b> 셀에서 확인·판정합니다.</p>
    </>
  );

  const reviewPanel = (
    <>
      <div className="ent-review-label">제재 · 인증 · 사전신고 — 해당 여부 판정</div>
      <div className="ent-reg-list">
        {regulations.map((reg) => {
          const applies = regApplies(reg);
          const doc = reg.docKey ? docBy(reg.docKey) : null;
          let docState = null;
          if (applies) {
            if (reg.selfDeclare) docState = ["신고 갈음", "ok"];
            else if (reg.agency) docState = ["대행 처리", "violet"];
            else if (doc?.quality === "verified") docState = ["서류 확보", "ok"];
            else if (doc?.quality === "unverified") docState = ["서류 있음 · 미검증", "warn"];
            else docState = ["서류 없음", "miss"];
          }
          return (
            <div className={`ent-reg-row wide4 ${applies ? "applies" : "na"}`} key={reg.key}>
              <div className="ent-reg-name">
                {reg.name}
                <em>{reg.note}{regChoice[reg.key] != null && regChoice[reg.key] !== reg.applies ? " · 관세사 수정" : ""}</em>
              </div>
              <span className="ent-method-toggle" role="group" aria-label="해당 여부">
                <button type="button" className={applies ? "on" : ""} onClick={() => setRegChoice((p) => ({ ...p, [reg.key]: true }))}>해당</button>
                <button type="button" className={!applies ? "on agency" : ""} onClick={() => setRegChoice((p) => ({ ...p, [reg.key]: false }))}>비해당</button>
              </span>
              {docState ? <span className={`ent-chip ${docState[1]}`}>{docState[0]}</span> : <span className="ent-reg-blank">—</span>}
              <span className="ent-doc-actions">
                {applies && !reg.selfDeclare && !reg.agency && doc && doc.quality === "missing" ? (
                  <button type="button" className="ent-mini-btn solid" onClick={() => pickFile(doc.key)}>서류 제출</button>
                ) : null}
                {applies && doc && doc.quality === "unverified" ? (
                  <button type="button" className="ent-mini-btn" onClick={() => markVerified(doc.key)}>원본 확인</button>
                ) : null}
              </span>
            </div>
          );
        })}
      </div>

      <div className="ent-review-label" style={{ marginTop: 18 }}>요건 증거 매트릭스</div>
      <div className="ent-matrix">
        {evidence.map((row) => (
          <div className={`ent-matrix-row st-${row.status}`} key={row.area}>
            <div className="ent-matrix-area">{row.area}</div>
            <div className="ent-matrix-need">
              {row.need}
              <div className="ent-matrix-note">{row.note}</div>
            </div>
            <div className="ent-matrix-doc">
              {row.selfDeclare ? "신고 기재" : row.doc ? row.doc.name.split(" (")[0] : "매핑 서류 없음"}
            </div>
            <div className={`ent-matrix-status st-${row.status}`}>
              {row.status === "ok" ? "충족" : row.status === "unverified" ? "미검증" : row.status === "agency" ? "대행 중" : "누락"}
            </div>
          </div>
        ))}
      </div>

      <div className="ent-review-label" style={{ marginTop: 18 }}>시스템 판정 (자동 산출)</div>
      <div className="ent-verdict-grid readonly">
        {Object.entries(VERDICTS).map(([key, [label, tone]]) => (
          <div key={key} className={`ent-verdict v-${tone} ${suggested === key ? "chosen" : "dim"}`}>
            {label}
            {suggested === key ? <em>현재</em> : null}
          </div>
        ))}
      </div>
      <p className="ent-hint">
        판정은 서류 상태와 해당/비해당 판정에서 자동 산출됩니다 — 최종 확정은 ASAP 관세사 검토를 거칩니다.
        {filedById[activeId] ? null : <> 관세사 <b>신고 완료</b> 시 이 케이스에 신고 완료 표시가 붙습니다.</>}
      </p>
    </>
  );

  const customsPanel = (
    <>
      {docDetailPath ? (
        <p className="ent-hint" style={{ marginTop: 0 }}>
          이 코드의 요건 서류 패키지(베이스라인·인증서·celex 근거)는 <Link to={docDetailPath} className="ent-link">서류 상세 페이지 ›</Link>
        </p>
      ) : null}
      <div className="ent-cat-panel cat-customs flat">
        <div className="ent-bigtable-head">
          <span>서류 (baseline)</span><span>제출 방식</span><span>상태</span><span>파일 · 액션</span>
        </div>
        {docs.filter((d) => d.cat === "customs").map((doc) => {
          const [label, tone] = QUALITY[doc.quality];
          return (
            <div className="ent-bigtable-row cat-customs" key={doc.key}>
              <div className="ent-bigtable-name">{doc.name}</div>
              <div className="ent-bigtable-method">
                <span className="ent-method-toggle" role="group" aria-label="제출 방식">
                  <button type="button" className={doc.chosen === "direct" ? "on" : ""} onClick={() => setMethod(doc.key, "direct")}>직접 제출</button>
                  <button type="button" className={doc.chosen === "agency" ? "on agency" : ""} onClick={() => setMethod(doc.key, "agency")}>대행 위임</button>
                </span>
              </div>
              <div><span className={`ent-chip ${tone}`}>{doc.chosen === "agency" ? "대행 진행" : doc.file ? label : "없음"}</span></div>
              <div className="ent-doc-actions">
                {doc.file ? <span className="ent-doc-file">📎 {doc.file}</span> : null}
                {doc.chosen === "direct" && doc.quality === "missing" ? (
                  <button type="button" className="ent-mini-btn solid" onClick={() => pickFile(doc.key)}>업로드</button>
                ) : null}
                {doc.quality === "unverified" ? (
                  <button type="button" className="ent-mini-btn solid" onClick={() => markVerified(doc.key)}>원본 확인</button>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
      <div className="ent-review-label" style={{ marginTop: 16 }}>대행 범위</div>
      <div className="ent-tiers">
        {AGENCY_TIERS.map((t) => (
          <button key={t.key} type="button" className={`ent-tier ${tier === t.key ? "active" : ""}`} onClick={() => setTier(t.key)}>
            <div className="ent-tier-title">{t.title}</div>
            <div className="ent-tier-desc">{t.desc}</div>
            <div className="ent-tier-eta">예상 소요 {t.eta}</div>
          </button>
        ))}
      </div>
      <div className="ent-cta-row">
        <button type="button" className="ent-cta" disabled={agencyConfirmed} onClick={() => setAgencyConfirmed(true)}>
          {agencyConfirmed ? "대행 요청 접수됨 — 매니저가 연락드립니다" : `"${AGENCY_TIERS.find((t) => t.key === tier)?.title}" 범위로 대행 요청`}
        </button>
      </div>
    </>
  );

  const MAIN_PANELS = { docs: docsPanel, code: codePanel, duty: dutyPanel, review: reviewPanel, customs: customsPanel };

  const renderDetailRow = (id) => {
    if (!panel || panel.id !== id) return null;
    const dynamic = !!docsById[id];
    return (
      <tr className="ent-mgmt-detail">
        <td colSpan={10}>
          <div className={`ent-detail-card p-${panel.key}`}>
            <div className="ent-detail-head">
              <b>{PANEL_TITLES[panel.key]}</b>
              <button type="button" className="ent-detail-close" onClick={() => setPanel(null)}>닫기 ✕</button>
            </div>
            {dynamic ? (
              MAIN_PANELS[panel.key]
            ) : (
              <p className="ent-hint">
                {STATIC_ITEMS.find((i) => i.id === id)?.name} — 정적 데모 항목입니다. 전체 동선은 실연동 행에서 확인하세요.
              </p>
            )}
          </div>
        </td>
      </tr>
    );
  };

  // 동적 행 (메인 케이스 + 추가된 상품) 렌더
  const renderDynamicRow = (rowId, rowName) => {
    const rowDocs = docsById[rowId];
    const secured = countSecured(rowDocs);
    const ready = !!clean(rowName) || !!clean(urlById[rowId]);
    const hasCoi = rowDocs.find((d) => d.key === "coi")?.quality !== "missing";
    const rowLive = runOwner === rowId && isLive;
    const rowEvidence = evidenceRows(rowDocs, dutyBase);
    const filed = filedById[rowId] || false;
    // 관세사 검토 완료 = 요건 증거가 전부 충족되어 판정이 "수출 가능"에 도달한 상태
    const reviewed = suggestVerdict(rowEvidence) === "possible";
    return (
      <tr className={`ent-mgmt-row ${panel?.id === rowId ? "open" : ""}`} key={rowId}>
        <td className="ent-mgmt-id">
          {rowId}
          {filed ? <span className="ent-chip ok filed">신고 완료</span> : null}
        </td>
        <td className="ent-mgmt-name">{rowName}</td>
        <td className={cellCls("", rowId, "docs")} onClick={cellClick(rowId, "docs")}>
          <div className="ent-mgmt-docs">
            <b>{secured}/{rowDocs.length}</b>
            <span className="ent-mgmt-bar"><span style={{ width: `${(secured / rowDocs.length) * 100}%` }} /></span>
          </div>
        </td>
        <td className="ent-mgmt-url" onClick={(e) => e.stopPropagation()}>
          <input
            className="ent-mgmt-url-input"
            placeholder="상품 URL 입력"
            value={urlById[rowId] || ""}
            onChange={(e) => setUrlById((prev) => ({ ...prev, [rowId]: e.target.value }))}
            disabled={busy}
          />
        </td>
        <td className={cellCls("ent-mgmt-hs", rowId, "code")} onClick={cellClick(rowId, "code")}>
          <b>{rowLive ? formatTaric(liveTaric10) : "—"}</b>
          <button
            type="button"
            className="ent-mini-btn solid"
            disabled={busy || !ready}
            title={
              !ready
                ? "제품명 또는 상품 URL이 필요합니다"
                : hasCoi
                  ? "COI 정규화(asap-coi-v1) 연동 후 파이프라인 실행"
                  : "제품명 + 상품 URL로 파이프라인 실행 (COI 업로드 시 성분 근거가 함께 들어갑니다)"
            }
            onClick={(e) => {
              e.stopPropagation();
              runClassify(rowId, rowName);
            }}
          >
            {busy && runOwner === rowId ? "분류 중…" : rowLive ? "재분류" : "분류 실행"}
          </button>
        </td>
        <td className={cellCls("ent-mgmt-acc", rowId, "code")} onClick={cellClick(rowId, "code")}>
          {rowLive ? "87%" : "—"}
        </td>
        <td>KR</td>
        <td className={cellCls("ent-mgmt-duty", rowId, "duty")} onClick={cellClick(rowId, "duty")}>
          <b>0%</b> <s>{dutyBase}</s>
        </td>
        <td className={cellCls("", rowId, "review")} onClick={cellClick(rowId, "review")}>
          <div className="ent-mgmt-reqs">
            {rowEvidence.map((row) => (
              <span key={row.area} className={`ent-req-chip st-${row.status}`} title={`${row.area} — ${row.need}`}>
                {REQ_ABBR[row.area] || row.area}
              </span>
            ))}
          </div>
        </td>
        <td className={cellCls("ent-mgmt-customs", rowId, "customs")} onClick={cellClick(rowId, "customs")}>
          {summarizeCustoms(rowDocs)}
          {reviewed ? <span className="ent-review-dot" title="관세사 검토 완료" /> : null}
        </td>
      </tr>
    );
  };

  return (
    <div className={`ent theme-${uiTheme}`}>
      <header className="ent-hero">
        <div>
          <span
            className="ent-logo"
            role="img"
            aria-label="ASAP"
            style={{ WebkitMaskImage: `url(${logo})`, maskImage: `url(${logo})` }}
          />
          <div className="ent-sub">{DEMO_CASE.plan} · {DEMO_CASE.manager}</div>
        </div>
        <div className="ent-hero-side">
          <div className="ent-case-chip">
            <span>수출 케이스</span>
            <strong>{activeId}</strong>
            <em>{activeId === DEMO_CASE.caseId ? mainName : extraRows.find((r) => r.id === activeId)?.name} → {DEMO_CASE.destination}</em>
          </div>
          <div className="user-theme-toggle small" role="group" aria-label="테마 선택">
            <button type="button" className={uiTheme === "light" ? "on" : ""} onClick={() => setUiTheme("light")}>화이트</button>
            <button type="button" className={uiTheme === "neon" ? "on" : ""} onClick={() => setUiTheme("neon")}>네온</button>
          </div>
        </div>
      </header>

      <nav className="ent-track" aria-label="수출 진행 단계">
        {TRACK_STEPS.map((label, index) => (
          <div key={label} className={`ent-track-step ${index < trackIndex ? "done" : index === trackIndex ? "now" : ""}`}>
            <span className="ent-track-dot" />
            {label}
          </div>
        ))}
      </nav>

      <div className={`ent-decision-banner v-${VERDICTS[suggested][1]}`}>
        시스템 판정: <b>{VERDICTS[suggested][0]}</b> — {VERDICTS[suggested][2]} <em className="ent-banner-note">최종 확정은 관세사 검토 후</em>
      </div>

      <input ref={fileInputRef} type="file" style={{ display: "none" }} onChange={onFileChosen} />
      <input
        ref={coiInputRef}
        type="file"
        style={{ display: "none" }}
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) setNewCoi(f.name);
          e.target.value = "";
        }}
      />

      {/* 수출 상품 관리 그리드 — 행 = 상품, 셀 클릭 = 해당 카드가 행 바로 아래로 */}
      <section className="ent-card">
        <div className="ent-card-title">수출 상품 관리
          <span className={`ent-badge ${isLive ? "live" : ""}`}>{busy ? "분류 중…" : isLive ? "파이프라인 연동" : `${STATIC_ITEMS.length + 1 + extraRows.length}건`}</span>
          <button type="button" className="ent-mini-btn solid ent-add-btn" onClick={() => setAddOpen((v) => !v)}>
            {addOpen ? "접기 ▴" : "+ 상품 추가"}
          </button>
        </div>

        {addOpen ? (
          <div className="ent-add-form">
            <input
              className="ent-mgmt-url-input grow"
              placeholder="제품명 (예: 갈비탕 밀키트 700g)"
              value={newName}
              autoFocus
              onChange={(e) => setNewName(e.target.value)}
            />
            <input
              className="ent-mgmt-url-input grow"
              placeholder="상품 URL (선택)"
              value={newUrl}
              onChange={(e) => setNewUrl(e.target.value)}
            />
            <input
              className="ent-mgmt-url-input"
              style={{ width: 120 }}
              placeholder="판매가 (원)"
              value={newPrice}
              onChange={(e) => setNewPrice(e.target.value)}
            />
            <input
              className="ent-mgmt-url-input"
              style={{ width: 120 }}
              placeholder="월 물량 (개)"
              value={newVolume}
              onChange={(e) => setNewVolume(e.target.value)}
            />
            <input
              className="ent-mgmt-url-input"
              style={{ width: 130 }}
              placeholder="판매 채널 (선택)"
              value={newChannel}
              onChange={(e) => setNewChannel(e.target.value)}
            />
            <button type="button" className="ent-mini-btn" onClick={() => coiInputRef.current?.click()}>
              {newCoi ? `📎 ${newCoi}` : "COI 첨부"}
            </button>
            <button type="button" className="ent-mini-btn solid" disabled={!clean(newName)} onClick={addProduct}>등록</button>
            <span className="ent-add-note">판매가·물량을 입력하면 FTA 적용 시 <b>연 예상 관세 절감액</b>을 계산해 드립니다.</span>
          </div>
        ) : null}

        <div className="ent-mgmt-scroll">
          <table className="ent-mgmt">
            <thead>
              <tr>
                <th>관리 ID</th><th>제품명</th><th>서류 등록</th><th>상품 URL</th><th>추천 HS10</th>
                <th>정확도</th><th>원산지</th><th>적용세율</th><th>수입요건</th><th>통관 서류</th>
              </tr>
            </thead>
            <tbody>
              {renderDynamicRow(DEMO_CASE.caseId, mainName)}
              {renderDetailRow(DEMO_CASE.caseId)}
              {extraRows.map((row) => (
                <FragmentDyn key={row.id} row={renderDynamicRow(row.id, row.name)} detail={renderDetailRow(row.id)} />
              ))}
              {STATIC_ITEMS.map((item) => (
                <FragmentRow
                  key={item.id}
                  item={item}
                  open={panel?.id === item.id}
                  onCell={(key) => togglePanel(item.id, key)}
                  detail={renderDetailRow(item.id)}
                />
              ))}
            </tbody>
          </table>
        </div>
        <p className="ent-hint">
          셀을 클릭하면 해당 항목의 카드가 <b>행 바로 아래</b>로 열립니다 — 서류 등록=인벤토리, HS10·정확도=분류 근거·BTI 판례,
          적용세율=세율 선언, 수입요건=관세사 검토 보드, 통관 서류=제출·대행 관리. <b>분류 실행</b>은 제품명 또는 상품 URL만 있으면
          바로 실행되고, <b>COI가 확보된 행은 실행 시 반드시 COI 정규화(coi_normalize → asap-coi-v1)를 거쳐 성분 레인에 주입</b>됩니다.
          통관 서류 옆{" "}
          <span className="ent-review-dot inline" aria-hidden="true" /> 보라 점은 <b>관세사 검토 완료</b> 표시입니다.
        </p>
      </section>

      <footer className="ent-foot">
        비회원 체험은 <Link to="/consumer">간편 분류</Link>, 분류 상세 근거는 <Link to="/classification">워크벤치</Link>에서.
      </footer>
    </div>
  );
}

function FragmentDyn({ row, detail }) {
  return (
    <>
      {row}
      {detail}
    </>
  );
}

// 정적 데모 행 — 셀 클릭 시에도 같은 위치 확장(내용은 데모 안내)
function FragmentRow({ item, open, onCell, detail }) {
  return (
    <>
      <tr className={`ent-mgmt-row ${open ? "open" : ""}`} onClick={() => onCell("docs")}>
        <td className="ent-mgmt-id">
          {item.id}
          {item.filed ? <span className="ent-chip ok filed">신고 완료</span> : null}
        </td>
        <td className="ent-mgmt-name">{item.name}</td>
        <td>
          <div className="ent-mgmt-docs">
            <b>{item.docs[0]}/{item.docs[1]}</b>
            <span className="ent-mgmt-bar"><span style={{ width: `${(item.docs[0] / item.docs[1]) * 100}%` }} /></span>
          </div>
        </td>
        <td className="ent-mgmt-url"><span className="ent-mgmt-url-text">{item.url}</span></td>
        <td className="ent-mgmt-hs"><b>{formatTaric(item.hs10)}</b></td>
        <td className="ent-mgmt-acc">{item.acc}</td>
        <td>{item.origin}</td>
        <td className="ent-mgmt-duty"><b>{item.duty[0]}</b> <s>{item.duty[1]}</s></td>
        <td>
          <div className="ent-mgmt-reqs">
            {item.reqs.map(([label, tone]) => (
              <span key={label} className={`ent-req-chip st-${tone}`}>{label}</span>
            ))}
          </div>
        </td>
        <td className="ent-mgmt-customs">
          {item.customs}
          {item.reviewed ? <span className="ent-review-dot" title="관세사 검토 완료" /> : null}
        </td>
      </tr>
      {detail}
    </>
  );
}
