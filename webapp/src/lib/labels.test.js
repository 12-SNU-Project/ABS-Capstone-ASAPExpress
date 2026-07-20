import assert from "node:assert/strict";
import test from "node:test";
import {
  BuildCandidateHierarchy,
  ClassificationStepForResult,
  DocumentReasonLabel,
  RoutingScoreLabel,
  RoutingTermLabel,
  UnderstandingValueLabel,
} from "./labels.js";
import {
  conditionLabel,
  decisionLabel,
  operationLabel,
  reasonLabel,
  verdictLabel,
} from "./traceContract.js";

test("내부 서류 필요 수준을 사용자 문구로 바꾼다", () => {
  assert.equal(DocumentReasonLabel("required_level=mandatory"), "기본 준비 서류");
  assert.equal(DocumentReasonLabel("required_level=conditional"), "조건 충족 시 준비 서류");
});

test("CN8 후보들의 공통 코드를 병합해 계층 트리를 만든다", () => {
  const Candidate = (rank, hs4, hs6, cn8, recommended = false) => ({
    rank,
    hs6,
    cn8,
    llm_recommended: recommended,
    classification_basis: [`basis ${cn8}`],
    candidate_static_tree: {
      nodes: [
        { level: "hs4", code: hs4, score: 10 },
        { level: "hs6", code: hs6, score: 5 },
        { level: "cn8", code: cn8, score: rank, description: `candidate ${rank}` },
      ],
    },
  });
  const tree = BuildCandidateHierarchy([
    Candidate(1, "1605", "160555", "16055500", true),
    Candidate(2, "1605", "160530", "16053010"),
    Candidate(3, "1605", "160530", "16053090"),
    Candidate(4, "1603", "160300", "16030080"),
  ], { hs2: "16" });

  assert.equal(tree.code, "16");
  assert.deepEqual(tree.children.map((node) => node.code), ["1605", "1603"]);
  assert.deepEqual(tree.children[0].children.map((node) => node.code), ["160555", "160530"]);
  assert.deepEqual(tree.children[0].children[1].children.map((node) => node.code), ["16053010", "16053090"]);
  assert.equal(tree.children[0].children[0].children[0].recommended, true);
});

test("분류 SSE의 최신 단계와 완료 상태를 4단계 화면에 연결한다", () => {
  assert.equal(ClassificationStepForResult(null), "understanding");
  assert.equal(ClassificationStepForResult({
    job_status: "running",
    events: [
      { stage: "Product_Understanding_Component" },
      { stage: "HS2_Routing_Component" },
    ],
  }), "routing");
  assert.equal(ClassificationStepForResult({
    job_status: "running",
    events: [{ stage: "Classification_Component" }],
  }), "hierarchy");
  assert.equal(ClassificationStepForResult({ job_status: "completed" }), "review");
});

test("HS2 라우팅 내부 용어를 근거가 남는 사용자 문구로 바꾼다", () => {
  assert.equal(RoutingTermLabel("prepared_food_redirect_bonus"), "가공식품 분류 가산");
  assert.equal(
    RoutingTermLabel("absorbed:molluscs aquatic<fish crustaceans molluscs aquatic"),
    "연관 어휘 일치: 연체동물류 · 수생",
  );
  assert.equal(
    RoutingTermLabel("universal_scope_muted:boiled,cooked"),
    "범용 가공 어휘(점수 제외): 삶음 · 조리",
  );
  assert.equal(RoutingScoreLabel("chapter_keywords"), "챕터 핵심어 일치");
  assert.equal(RoutingScoreLabel("prepared_scope"), "가공식품 범위 일치");
});

test("분류 Trace 내부 판정값을 사용자 문구로 바꾼다", () => {
  assert.equal(decisionLabel("violated"), "후보 제외");
  assert.equal(verdictLabel({ verdict: "true" }), "조건 충족");
  assert.equal(verdictLabel({ verdict: "undecided" }), "추가 확인");
  assert.equal(conditionLabel("quantitative_threshold"), "함유량 기준");
  assert.equal(operationLabel("quant_gate"), "함유량 기준 확인");
  assert.equal(
    reasonLabel("alias_hit:normalized_tariff_description;typed_gate_blocked"),
    "상품 설명의 유사 어휘에서 관련 근거를 확인했습니다.",
  );
});

test("상품 이해의 내부 영문 값을 사용자 문구로 바꾼다", () => {
  assert.equal(UnderstandingValueLabel("molluscs"), "연체동물류");
  assert.equal(UnderstandingValueLabel("prepared food"), "조리·가공 식품");
  assert.equal(UnderstandingValueLabel("frozen cooked prepared"), "냉동 · 조리 · 가공");
});
