export const STAGES = [
  ["product_collection", "상품 정보 수집", "KurlyProductCollectionPipeline"],
  ["classification", "품목 분류", "HsCodeClassificationPipeline"],
  ["document_recommendation", "서류 추천", "DocumentRecommendationPipeline"],
];

export const CLASSIFICATION_STEPS = [
  ["understanding", "상품 이해", "상품 정체·성분 정리"],
  ["routing", "HS2 Routing", "HS2 후보 비교"],
  ["hierarchy", "계층 분류", "HS4 → HS6 → CN8"],
  ["review", "결과 검토", "판단 근거·판례"],
];

export function BuildCandidateHierarchy(candidates, selectedPath = {}) {
  const rows = Array.isArray(candidates) ? candidates : [];
  const firstCode = String(rows[0]?.cn8 || rows[0]?.hs6 || "");
  const root = {
    level: "HS2",
    code: String(selectedPath?.hs2 || firstCode.slice(0, 2)),
    children: [],
  };
  const GetOrAdd = (children, level, code, score) => {
    let node = children.find((item) => item.code === code);
    if (!node) {
      node = { level, code, score, children: [] };
      children.push(node);
    }
    return node;
  };

  rows.forEach((candidate, index) => {
    const nodes = Array.isArray(candidate?.candidate_static_tree?.nodes)
      ? candidate.candidate_static_tree.nodes
      : [];
    const NodeAt = (level) => nodes.find((node) => node?.level === level) || {};
    const hs4Data = NodeAt("hs4");
    const hs6Data = NodeAt("hs6");
    const cn8Data = NodeAt("cn8");
    const cn8 = String(candidate?.cn8 || cn8Data.code || "");
    const hs6 = String(candidate?.hs6 || hs6Data.code || cn8.slice(0, 6));
    const hs4 = String(hs4Data.code || hs6.slice(0, 4));
    if (!hs4 || !hs6 || !cn8) return;

    const hs4Node = GetOrAdd(root.children, "HS4", hs4, hs4Data.score);
    const hs6Node = GetOrAdd(hs4Node.children, "HS6", hs6, hs6Data.score);
    hs6Node.children.push({
      level: "CN8",
      code: cn8,
      score: cn8Data.score,
      description: String(cn8Data.description || ""),
      basis: String(candidate?.classification_basis?.[0] || ""),
      rank: candidate?.rank || index + 1,
      recommended: Boolean(candidate?.llm_recommended),
      children: [],
    });
  });
  return root;
}

const DOCUMENT_REASON_LABELS = {
  "required_level=mandatory": "기본 준비 서류",
  "required_level=required": "기본 준비 서류",
  "required_level=conditional": "조건 충족 시 준비 서류",
  "required_level=optional": "선택 준비 서류",
  "required_level=pending": "필요 여부 확인 중",
};

export function DocumentReasonLabel(value) {
  const reason = String(value ?? "").trim();
  return DOCUMENT_REASON_LABELS[reason.toLowerCase()] || reason;
}

const CLASSIFICATION_EVENT_STEPS = {
  Input_Intake: "understanding",
  Evidence_Intake_Component: "understanding",
  Product_Understanding_Component: "understanding",
  Product_Understanding: "understanding",
  ProductUnderstanding: "understanding",
  HS2_Routing_Component: "routing",
  Classification: "hierarchy",
  Classification_Component: "hierarchy",
};

export function ClassificationStepForResult(result) {
  const status = String(result?.job_status || "").toLowerCase();
  if (["completed", "complete", "done"].includes(status)) {
    return "review";
  }
  const events = Array.isArray(result?.events) ? result.events : [];
  const latest = events
    .slice()
    .reverse()
    .find((event) => CLASSIFICATION_EVENT_STEPS[event?.stage]);
  return CLASSIFICATION_EVENT_STEPS[latest?.stage] || "understanding";
}

export function RoutingTermLabel(value) {
  const term = String(value ?? "").trim();
  if (term === "prepared_food_redirect_bonus") return "가공식품 분류 가산";
  if (term === "condiment_product_form_bonus") return "조미·소스 상품 형태 일치";
  if (term.startsWith("absorbed:")) {
    return `연관 어휘 일치: ${UnderstandingValueLabel(term.slice(9).split("<", 1)[0])}`;
  }
  if (term.startsWith("universal_scope_muted:")) {
    const terms = term.slice(22).split(",").map(UnderstandingValueLabel).join(" · ");
    return `범용 가공 어휘(점수 제외): ${terms}`;
  }
  if (term.startsWith("ambiguous_only_disqualified:")) {
    return `단독 판별력이 부족한 어휘: ${UnderstandingValueLabel(term.slice(28))}`;
  }
  return UnderstandingValueLabel(term.replaceAll("_", " "));
}

const ROUTING_SCORE_LABELS = {
  guardrail_redirect: "가공식품 챕터 전환",
  dictionary_gate: "상품 사전 일치",
  dictionary_gate_redirect: "상품 사전 기반 챕터 전환",
  product_form_bonus: "상품 형태 일치",
  chapter_keywords: "챕터 핵심어 일치",
  raw_scope: "원물 범위 일치",
  prepared_scope: "가공식품 범위 일치",
};

export function RoutingScoreLabel(value) {
  return ROUTING_SCORE_LABELS[String(value ?? "").trim()] || "기타 라우팅 근거";
}

const UNDERSTANDING_VALUE_LABELS = {
  mollusc: "연체동물류",
  molluscs: "연체동물류",
  crustacean: "갑각류",
  crustaceans: "갑각류",
  fish: "어류",
  meat: "육류",
  cereal: "곡물류",
  soy_legume: "콩·두류",
  vegetable: "채소류",
  seasoning_sauce: "양념·소스",
  "prepared food": "조리·가공 식품",
  frozen: "냉동",
  cooked: "조리",
  prepared: "가공",
  fermented: "발효",
  dried: "건조",
  chilled: "냉장",
  fresh: "신선",
  uncooked: "비가열",
  fried: "볶음·유탕 처리",
  live: "생물",
  raw: "원물",
  preparations: "조제품",
  preserved: "보존 처리",
  boiled: "삶음",
  roasted: "구이",
  homogenised: "균질화",
  sauce: "소스",
  seasoned: "양념",
  food: "식품",
  aquatic: "수생",
  invertebrates: "무척추동물",
};

export function UnderstandingValueLabel(value) {
  const text = String(value ?? "").trim().toLowerCase();
  if (!text) return "";
  return UNDERSTANDING_VALUE_LABELS[text]
    || text.split(/\s+/).map((term) => UNDERSTANDING_VALUE_LABELS[term] || term).join(" · ");
}

export const EVENT_STAGE_LABELS = {
  Pipeline: "파이프라인",
  User_Input_Preparation: "입력 정리",
  Kurly_Product_Collection: "상품 정보 수집",
  Input_Intake: "입력 수집",
  Evidence_Intake_Component: "증거 적재",
  Product_Intake: "상품 입력",
  Product_Understanding_Component: "상품 이해",
  Product_Understanding: "상품 이해",
  ProductUnderstanding: "상품 이해",
  HS2_Routing_Component: "HS2 라우팅",
  Regulatory_Domain_Routing: "규제 도메인 라우팅",
  Domain_Router: "도메인 라우팅",
  Regulatory_Domain: "도메인 라우팅",
  Classification: "분류",
  Classification_Component: "분류",
  Document_Component: "문서 패키지",
  Document_Recommendation: "문서 패키지",
};

export const RECONSTRUCTION_KEYS = [
  "mode",
  "used_llm_reconstruction",
  "fallback_reason",
  "error",
  "detail_table_count",
  "classification_fact_count",
  "classification_text_line_count",
];

export const LABELS = {
  product_name: "상품명",
  description: "설명",
  url: "URL",
  source_urls: "근거 URL",
  intended_use: "상품 용도",
  origin_country: "상품 원산국",
  mode: "복원 방식",
  used_llm_reconstruction: "LLM 복원 사용",
  fallback_reason: "대체 사유",
  error: "오류",
  detail_table_count: "복원 상세표 수",
  classification_fact_count: "구조화 fact 수",
  classification_text_line_count: "정규화 텍스트 줄 수",
  allowed_hs2: "허용 HS2",
  blocked_hs2: "차단 HS2",
  enforce_hs2_boundary: "HS2 경계 강제",
  fallback_allowed: "fallback 허용",
  domain_scopes: "도메인 scope",
  pre_gate_domains: "사전 게이트 도메인",
  missing_facts: "부족 정보",
  routing_basis: "라우팅 근거",
  candidate_chapter_details: "챕터 점수 상세",
  product_id: "Product ID",
  short_description: "짧은 설명",
  commercial_identity: "상업적 식별명",
  translated_product_name: "번역 상품명",
  normalized_tariff_description: "정규화 tariff 설명",
  ingredient_class: "원재료 분류",
  food_form: "식품 형태",
  processing_state: "가공 상태",
  identity_terms: "식별 토큰",
  product_form_terms: "형태 토큰",
  chapter_hint_terms: "챕터 힌트",
  chapter_hint_status: "챕터 힌트 상태",
  domain_hints: "도메인 힌트",
  confidence: "신뢰도",
  needs_review: "사람 검토 필요",
  understanding_mode: "상품 이해 방식",
  chapter_hint_basis: "챕터 제안 근거",
  chapter_hint_source_terms: "챕터 근거 어휘",
  retrieval_sources: "검색 출처",
  matched_keywords: "매칭 키워드",
  score_breakdown: "점수 분해",
  nodes: "코드 노드",
  run_id: "Run ID",
  run_dir: "Run 경로",
  document_package_id: "문서 패키지 ID",
  cn8: "CN8",
  taric10: "TARIC10",
};
