// 분류 trace UI 계약 — blackboard.json 경로 → 화면 요소 매핑.
//
// ⚠️ 이 필드명들은 기록 의무화(CYCLE9)에서 확정된 UI 계약이다.
//    trace 필드 변경은 메인 합의 사항 — 임의로 바꾸면 화면이 깨진다.
// 원천: /api/admin/runs/{jobId}/blackboard (런별 blackboard.json 서빙).
import { getJson } from "./api.js";
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

// 근거 등급 뱃지 — named=법정 서술 / precedent=판례 / derived=승인 파생 / fallback=대체
export const GRADE_LABELS = {
  named: "법정 서술",
  precedent: "판례",
  derived: "승인 파생",
  fallback: "대체",
};

export async function fetchBlackboard(jobId) {
  const id = clean(jobId);
  if (!id) {
    return null;
  }
  try {
    return await getJson(`/api/admin/runs/${encodeURIComponent(id)}/blackboard`);
  } catch {
    return null;
  }
}

// blackboard → trace 뷰모델 (없는 필드는 전부 빈 값으로 — 구형 run 안전)
export function extractTrace(blackboard) {
  const board = asObject(blackboard);
  const sets = asList(board.candidate_code_sets);
  const set = asObject(sets[sets.length - 1]);
  const trace = asObject(set.classification_trace);
  return {
    stages: asList(trace.stages),
    // 최종 추천: 전용 키가 없으면 trace.validator(동일 레코드)로 폴백
    validator: asObject(board.llm_validation_recommendation || trace.validator),
    summons: asList(set.bti_summons),
    routing: asObject(board.routing_context),
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

// 판례 지지 detail (grade=precedent, verdict=true) → refs 배열
export function precedentRefs(candidateEntry) {
  return trueDetails(candidateEntry)
    .filter((detail) => gradeOf(detail) === "precedent")
    .flatMap((detail) => asList(asObject(detail).refs))
    .map((ref) => clean(ref))
    .filter(Boolean);
}

// 소비자 "왜 이 코드인가" 3줄 — 정체 / 상태·형태 / 판례(있을 때만)
export function buildConsumerWhy(traceModel, cn8) {
  const stages = asList(traceModel?.stages);
  const collected = [];
  stages.forEach((stage) => {
    const entry = stageEntryForCode(stage, cn8);
    if (entry) {
      collected.push(...trueDetails(entry).map((detail) => ({ ...asObject(detail), _stage: clean(asObject(stage).stage) })));
    }
  });
  const byCond = (names) =>
    collected.find((detail) => names.includes(clean(detail.cond)));
  const identity = byCond(["product_identity"]);
  const state = byCond(["preservation_state", "physical_form", "processing_state", "material_composition"]);
  const precedent = collected.filter((detail) => gradeOf(detail) === "precedent");
  // 판례 지지의 원천은 두 층: decision_detail(grade=precedent) + bti_summons 발동 기록.
  // 소환 기록에는 "분류의 어느 지점(level)에서" 판례가 개입했는지가 실려 있다.
  const digits = clean(cn8).replace(/\D/g, "");
  const firedSummons = summarizeSummons(traceModel?.summons).filter(
    (row) => row.fired && row.code && digits.startsWith(row.code.replace(/\D/g, "")),
  );
  const refs = [
    ...precedent.flatMap((detail) => asList(detail.refs)).map(clean),
    ...firedSummons.flatMap((row) => row.refs),
  ].filter(Boolean).filter((ref, index, all) => all.indexOf(ref) === index);
  const firedLevel = clean(firedSummons[0]?.level);
  const firedLevelKo = stageLabelKo(firedLevel);
  const lines = [];
  if (identity) {
    const value = detailValueText(identity);
    lines.push({ kind: "identity", text: `상품 정체 ${value ? `'${value}'` : "판정 어휘"}가 관세 서술과 일치합니다.` });
  }
  if (state && state !== identity) {
    const value = detailValueText(state);
    lines.push({
      kind: "state",
      text: `${clean(state.cond) === "preservation_state" ? "보존 상태" : clean(state.cond) === "physical_form" ? "물리 형태" : "구성·가공 조건"}${value ? ` '${value}'` : ""}이 코드 조건을 충족합니다.`,
    });
  }
  if (refs.length) {
    lines.push({
      kind: "precedent",
      text: firedLevelKo
        ? `${firedLevelKo} 단계에서 EU 관세당국 판례 ${refs.length}건이 이 코드를 지지했습니다`
        : `EU 관세당국 판례 ${refs.length}건이 이 코드를 지지합니다`,
      refs,
    });
  }
  return { lines, refs };
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
