// 분류 trace UI 계약 — /api/runs/{jobId}의 candidate_code_set → 화면 요소 매핑.
import { asList, asObject, clean } from "./format.js";

// EU EBTI 공개 DB — 판례 번호 조회 화면 (신뢰도용 외부 링크)
export const EBTI_CONSULT_URL =
  "https://ec.europa.eu/taxation_customs/dds2/ebti/ebti_consultation.jsp?Lang=en";

// bti_summons.silence 사유 → 사용자 문구
export const SILENCE_LABELS = {
  no_lexical_overlap: "관련 판례 없음",
  no_phrase_match: "공유 구문 일치 없음",
  distribution_split: "판례 의견 갈림",
  k_below_min: "합의 판례 수 부족",
  not_in_tree: "판례 코드가 현행 트리에 없음(개정)",
};

// 분류 단계 한글명 — BTI 소환은 4/6/8에서만 일어난다(라우팅 2·TARIC 10은 소환 없음).
// 자릿수 기준 사용자 모델(2/4/6/8/10)에 맞춘 표기.
export const STAGE_LABELS_KO = {
  hs2: "2자리 (HS2·챕터 라우팅)",
  hs4: "4자리 (HS4·호 좁히기)",
  hs6: "6자리 (HS6·소호 좁히기)",
  cn8: "8자리 (CN8·EU 세분류)",
  taric10: "10자리 (TARIC10·신고코드)",
};

export function stageLabelKo(level) {
  const key = clean(level).toLowerCase();
  return STAGE_LABELS_KO[key] || (key ? key.toUpperCase() : "");
}

export const GRADE_LABELS = {
  named: "코드 설명 어휘",
  precedent: "판례",
  derived: "파생 근거",
  fallback: "보조 일치",
};

const CONDITION_LABELS = {
  product_identity: "상품 정체",
  species_source: "원재료·종",
  material_composition: "재료 구성",
  physical_form: "상품 형태",
  processing_method: "가공 방식",
  processing_state: "가공 상태",
  preservation_state: "보존 상태",
  quantitative_threshold: "함유량 기준",
  intended_use_function: "상품 용도",
  exclusion_boundary: "제외 조건",
};

const OPERATION_LABELS = {
  has_token: "관련 어휘 포함",
  not_contains: "제외 어휘 없음",
  equals: "값 일치",
  in: "허용 범위 포함",
  quant_gate: "함유량 기준 확인",
};

const DECISION_LABELS = {
  confirmed: "후보 유지",
  violated: "후보 제외",
  undecided: "추가 검토",
};

const VERDICT_LABELS = {
  true: "조건 충족",
  false: "조건 불충족",
  skipped: "판정 제외",
  undecided: "추가 확인",
  unknown: "추가 확인",
};

export function conditionLabel(value) {
  const key = clean(value);
  return CONDITION_LABELS[key] || "기타 판정 조건";
}

export function operationLabel(value) {
  const key = clean(value);
  return OPERATION_LABELS[key] || "조건 확인";
}

export function decisionLabel(value) {
  return DECISION_LABELS[clean(value).toLowerCase()] || "검토 중";
}

export function verdictLabel(detail) {
  const verdict = clean(asObject(detail).verdict).toLowerCase();
  return VERDICT_LABELS[verdict] || "판정 기록";
}

export function reasonLabel(value) {
  const reason = clean(value);
  if (!reason) return "조건과 일치했습니다.";
  if (reason.startsWith("field_hit:")) return "수집된 상품 정보에서 관련 어휘를 확인했습니다.";
  if (reason.startsWith("alias_hit:")) return "상품 설명의 유사 어휘에서 관련 근거를 확인했습니다.";
  if (reason === "field_no_match") return "현재 상품 정보에서 일치 근거를 찾지 못했습니다.";
  if (reason === "qualifier_rank_excluded") return "보조 설명 어휘이므로 점수 반영에서 제외했습니다.";
  if (reason === "exclusion_present_in_pool") return "제외 조건에 해당하는 어휘가 확인됐습니다.";
  if (reason === "exclusion_absent") return "제외 조건에 해당하는 어휘가 확인되지 않았습니다.";
  if (reason === "no_percentages") return "성분 함유량 정보가 없어 기준 충족 여부를 판단하지 못했습니다.";
  return "내부 분류 규칙에 따라 기록된 사유입니다.";
}

// candidate_code_set → trace 뷰모델 (없는 필드는 빈 값으로 유지해 구형 run도 표시)
export function extractTrace(candidateSet) {
  const set = asObject(candidateSet);
  const trace = asObject(set.classification_trace);
  return {
    stages: asList(trace.stages),
    validator: asObject(trace.validator),
    summons: asList(set.bti_summons),
    mergeGates: asList(set.merge_gate_observations),
    trustGates: asList(set.router_trust_gate),
    formHits: asList(set.form_hits || trace.form_hits),
    hasTrace: asList(trace.stages).length > 0,
  };
}

// verdict는 문자열 "true"로 기록된다 — 불리언과 함께 허용
export function isTrueVerdict(detail) {
  const value = asObject(detail).verdict;
  return value === true || clean(value).toLowerCase() === "true";
}

export function trueDetails(candidate) {
  return asList(asObject(candidate).decision_detail).filter(isTrueVerdict);
}

export function gradeOf(detail) {
  return clean(asObject(detail).grade).toLowerCase();
}

// detail.value는 JSON 문자열(["meal"])일 수 있다 — 표시용 평문으로
export function detailValueText(detail) {
  const raw = clean(asObject(detail).value);
  if (!raw) {
    return "";
  }
  try {
    const parsed = JSON.parse(raw);
    return asList(parsed).map((item) => clean(item)).filter(Boolean).join(", ") || raw;
  } catch {
    return raw;
  }
}

// 스테이지에서 선택 코드의 심사 엔트리 찾기 — hs4/hs6/cn8 자리수 프리픽스 매칭
export function stageEntryForCode(stage, cn8) {
  const digits = clean(cn8).replace(/\D/g, "");
  const considered = asList(asObject(stage).candidates_considered);
  const exact = considered.find((cand) => {
    const code = clean(asObject(cand).code).replace(/\D/g, "");
    return code && digits.startsWith(code);
  });
  return exact ? asObject(exact) : null;
}

// bti_summons 한 줄 요약 + 분포 (침묵의 투명성)
// level = 소환이 일어난 분류 단계(hs4/hs6/cn8) — 노출은 이 지점에 앵커링한다.
export function summarizeSummons(summons) {
  return asList(summons).map((item) => {
    const source = asObject(item);
    const matched = asList(source.matched);
    const refs = asList(source.refs).map(clean).filter(Boolean);
    const silence = clean(source.silence);
    const distribution = asObject(source.distribution);
    const distEntries = Object.entries(distribution)
      .map(([code, count]) => ({ code: clean(code), count: Number(count) || 0 }))
      .filter((entry) => entry.code)
      .sort((a, b) => b.count - a.count);
    const total = distEntries.reduce((sum, entry) => sum + entry.count, 0) || matched.length || refs.length;
    return {
      level: clean(source.level).toLowerCase(),
      fired: !!clean(source.code) && !silence,
      code: clean(source.code),
      summonedBy: clean(source.summoned_by),
      notInTree: clean(source.not_in_tree),
      phrases: asList(source.phrases).map(clean).filter(Boolean),
      silence,
      silenceLabel: SILENCE_LABELS[silence] || (silence ? `유보 (${silence})` : ""),
      refs,
      reviewed: total,
      distribution: distEntries,
    };
  });
}

// 특정 스테이지에 앵커된 소환 기록
export function summonsForStage(summons, stageName) {
  const name = clean(stageName).toLowerCase();
  return summarizeSummons(summons).filter((row) => row.level === name);
}
