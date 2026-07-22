import DataTable from "@/components/DataTable";
import KeyValueRows from "@/components/KeyValueRows";
import { RECONSTRUCTION_KEYS, UnderstandingValueLabel } from "@/lib/labels.js";
import { asList, asObject, clean, labelFor } from "@/lib/format.js";
import { EvidenceTerms, FactLabel } from "./EvidenceElements";

const INTENDED_USE_OPTIONS = [
  ["human consumption", "최종 소비용"],
  ["further processing", "추가 가공용"],
  ["animal feed", "동물 사료용"],
  ["non-food use", "비식품용"],
];

function ParseCompositionTerms(terms) {
  return asList(terms)
    .map((term) => {
      const text = clean(term);
      const splitAt = text.indexOf(":");
      return splitAt < 1
        ? { 구분: "", 내용: text }
        : { 구분: text.slice(0, splitAt).trim(), 내용: text.slice(splitAt + 1).trim() };
    })
    .filter((row) => row.내용);
}

function ReconstructionValueLabel(key, value) {
  const text = clean(value);
  if (key === "mode") {
    return {
      fallback_reconstruction: "규칙 기반 복원",
      llm_reconstruction: "LLM 구조화 복원",
    }[text] || text;
  }
  if (key === "fallback_reason") {
    return {
      llm_reconstruction_not_used: "입력 복원 LLM 미사용",
      llm_reconstruction_unavailable: "입력 복원 LLM 사용 불가",
    }[text] || text.replaceAll("_", " ");
  }
  return value;
}

function ReconstructionWarningLabel(value) {
  const warning = clean(value);
  if (warning.startsWith("llm_input_reconstruction_unavailable:")) {
    return "입력 복원 LLM을 사용할 수 없어 규칙 기반 복원을 사용했습니다.";
  }
  if (warning.includes("reason=normalized_value_not_found_in_source")) {
    return "복원 값이 수집 원문에서 확인되지 않아 해당 항목을 유보했습니다.";
  }
  if (warning.includes("reason=ingredient_fact_requires_label_or_ocr_evidence")) {
    return "성분값을 뒷받침할 라벨 또는 OCR 근거가 충분하지 않아 유보했습니다.";
  }
  return warning.replaceAll("_", " ");
}

export function ProductCollectionPanel({ result }) {
  const inputView = asObject(result?.input_processing_view);
  const pageProductFacts = asObject(inputView.page_product_facts);
  const evidenceLabels = asObject(inputView.evidence_source_labels);
  const MapFact = (fact) => {
    const source = asObject(fact);
    return {
      ...source,
      field_name: labelFor(clean(source.field_name)),
      source_refs: asList(source.source_refs)
        .map((ref) => clean(evidenceLabels[clean(ref)]) || "수집 근거")
        .filter((item, index, all) => item && all.indexOf(item) === index),
      validation_status: clean(source.validation_status) === "accepted"
        ? "형식 수용 · 사실 확정 아님"
        : clean(source.validation_status) === "unresolved"
          ? "근거 부족 · 확인 필요"
          : clean(source.validation_status),
    };
  };
  const reconstructedFacts = asList(inputView.reconstructed_product_facts).map(MapFact);
  const unresolvedFacts = asList(inputView.unresolved_product_facts).map(MapFact);
  const reconstructionStatus = Object.fromEntries(
    Object.entries(asObject(inputView.reconstruction_status)).map(([key, value]) => [
      key,
      ReconstructionValueLabel(key, value),
    ]),
  );
  const warnings = [
    ...asList(inputView.product_fact_conflicts),
    ...asList(inputView.warnings),
  ].map(ReconstructionWarningLabel).filter(
    (warning, index, all) => warning && all.indexOf(warning) === index,
  );
  const collectedFacts = [
    ["상품명", pageProductFacts.product_name],
    ["상품 용도", pageProductFacts.intended_use],
    ["상품 원산국", pageProductFacts.origin_country],
  ].filter(([, value]) => clean(value) !== "");

  return (
    <div className="cjs-panel">
      <div className="cjs-panel-title">KurlyProductCollectionPipeline · 수집 및 입력 복원</div>
      <div className="cjs-collection-stack">
        <section>
          <div className="cjs-subpanel-title cjs-first">수집된 상품 기본 정보</div>
          <div className="cjs-fact-tiles cjs-collection-fact-tiles">
            {collectedFacts.map(([label, value]) => (
              <div className="cjs-fact-tile" key={label}>
                <span>{label}</span>
                <strong>{clean(value)}</strong>
              </div>
            ))}
          </div>
          {clean(pageProductFacts.description) ? (
            <>
              <div className="cjs-subpanel-title">상품 설명</div>
              <p className="cjs-desc-text">{clean(pageProductFacts.description)}</p>
            </>
          ) : null}
        </section>
        <section>
          <div className="cjs-subpanel-title cjs-first">입력 복원 상태</div>
          <div className="cjs-reconstruction-status">
            <KeyValueRows data={reconstructionStatus} keys={RECONSTRUCTION_KEYS} limit={8} />
          </div>
          {warnings.length ? (
            <>
              <div className="cjs-subpanel-title">복원 경고 ({warnings.length}건)</div>
              <ul className="cjs-warning-list">
                {warnings.slice(0, 12).map((warning, index) => <li key={index}>{warning}</li>)}
              </ul>
            </>
          ) : null}
        </section>
        <section>
          <div className="cjs-subpanel-title cjs-first">복원 fact 표 ({reconstructedFacts.length}건)</div>
          <DataTable
            rows={reconstructedFacts}
            limit={30}
            className="cjs-reconstruction-table"
            emptyMessage="LLM 복원이 만든 구조화 fact가 없습니다."
            columns={[
              { key: "field_name", label: "필드", variant: "mono" },
              { key: "normalized_value", label: "값" },
              { key: "source_refs", label: "출처", variant: "mono" },
              { key: "validation_status", label: "상태", variant: "pill" },
            ]}
          />
          <div className="cjs-subpanel-title">확정하지 못한 항목 ({unresolvedFacts.length}건)</div>
          <DataTable
            rows={unresolvedFacts}
            limit={20}
            className="cjs-unresolved-table"
            emptyMessage="별도로 유보된 복원 항목이 없습니다."
            columns={[
              { key: "field_name", label: "필드", variant: "mono" },
              { key: "normalized_value", label: "값" },
              { key: "source_refs", label: "출처", variant: "mono" },
              { key: "validation_status", label: "상태", variant: "pill" },
            ]}
          />
        </section>
      </div>
    </div>
  );
}

function CoiEvidenceBlock({ coi }) {
  const evidence = asObject(coi);
  const documents = asList(evidence.matched_documents);
  const texts = asList(evidence.matched_texts);
  const scores = asList(evidence.match_scores);
  const rows = texts.map((text, index) => ({
    문서: clean(documents[index] || documents[0] || "-"),
    "매칭 텍스트": clean(text),
    점수: scores[index] !== undefined ? scores[index] : "",
  }));
  if (!rows.length && !clean(evidence.error)) return null;
  return (
    <>
      <div className="cjs-subpanel-title">추가 문서 근거 ({rows.length}건)</div>
      {rows.length ? (
        <DataTable
          rows={rows}
          limit={8}
          columns={[
            { key: "문서", label: "문서", variant: "mono" },
            { key: "매칭 텍스트", label: "매칭 텍스트" },
            { key: "점수", label: "점수", variant: "mono" },
          ]}
        />
      ) : (
        <div className="cjs-muted">추가 문서 근거를 불러오지 못했습니다.</div>
      )}
    </>
  );
}

export function ProductUnderstandingPanel({ result }) {
  const understandingView = asObject(result?.product_understanding_view);
  const hints = asObject(understandingView.identity_hints);
  const composition = asObject(understandingView.composition_facts);
  const compositionRows = ParseCompositionTerms(composition.composition_terms);
  const percentages = asList(composition.ingredient_percentages);
  const HasValue = (value) => !["", "unknown", "other"].includes(clean(value).toLowerCase());
  const reportedMissing = [
    ...asList(understandingView.unknowns),
    ...asList(composition.missing_composition_facts),
  ].map(FactLabel);
  const reviewReasons = [
    ...reportedMissing,
    ...(!clean(composition.principal_ingredient) && !reportedMissing.includes("주원료") ? ["주원료"] : []),
    ...(!percentages.length && !reportedMissing.includes("성분별 함유율") ? ["성분별 함유율"] : []),
  ].map(clean).filter((item, index, all) => item && all.indexOf(item) === index);
  const modeLabel = {
    llm_json: "AI 기반 구조화",
    llm_fallback: "규칙 기반 보완",
    regex_fallback: "규칙 기반",
  }[clean(hints.understanding_mode)] || "기타 방식";
  const ingredientClasses = asList(composition.ingredient_classes).length
    ? asList(composition.ingredient_classes)
    : [hints.ingredient_class];
  const ingredientClassLabel = ingredientClasses
    .filter(HasValue)
    .map(UnderstandingValueLabel)
    .filter((value, index, all) => value && all.indexOf(value) === index)
    .join(" · ");
  const intendedUse = clean(hints.intended_use);
  const intendedUseLabel = INTENDED_USE_OPTIONS.find(([value]) => value === intendedUse)?.[1]
    || (HasValue(intendedUse) ? intendedUse : "");
  const processingState = HasValue(composition.processing_state)
    ? composition.processing_state
    : hints.processing_state;
  const facts = [
    ["원재료 계열", ingredientClassLabel],
    ["상품 형태", HasValue(hints.food_form) ? UnderstandingValueLabel(hints.food_form) : ""],
    ["가공·보존 상태", UnderstandingValueLabel(processingState)],
    ["상품 용도", intendedUseLabel],
  ].filter(([, value]) => HasValue(value));
  const inputProductName = clean(understandingView.product_name);
  const summaryIdentity = clean(hints.commercial_identity)
    || clean(hints.normalized_tariff_description)
    || inputProductName;
  const normalizedDescription = clean(hints.normalized_tariff_description);
  const showNormalizedDescription = normalizedDescription
    && normalizedDescription.toLowerCase() !== summaryIdentity.toLowerCase();

  return (
    <div className="cjs-panel">
      <div className="cjs-panel-title">상품 이해 결과</div>
      {summaryIdentity ? (
        <div className="cjs-understanding-summary">
          <span>시스템이 이해한 상품</span>
          <strong>{summaryIdentity}</strong>
          {inputProductName && inputProductName !== summaryIdentity ? (
            <small>입력 상품: {inputProductName}</small>
          ) : null}
          {showNormalizedDescription ? <p>분류용 상품 설명: {normalizedDescription}</p> : null}
        </div>
      ) : (
        <div className="cjs-muted">상품 이해 결과가 아직 없습니다.</div>
      )}
      {facts.length ? (
        <div className="cjs-fact-tiles cjs-understanding-facts">
          {facts.map(([label, value]) => (
            <div className="cjs-fact-tile" key={label}>
              <span>{label}</span>
              <strong>{value}</strong>
            </div>
          ))}
        </div>
      ) : null}
      {reviewReasons.length ? (
        <div className="cjs-understanding-review">
          <strong>추가 확인</strong>
          <span>{reviewReasons.slice(0, 8).join(" · ")}</span>
        </div>
      ) : null}
      <section className="cjs-understanding-composition">
        <div className="cjs-subpanel-title cjs-first">확인된 성분 정보</div>
        <div className="cjs-chip-row">
          {clean(composition.principal_ingredient) ? (
            <span className="cjs-chip">주원료: {composition.principal_ingredient}</span>
          ) : null}
          {percentages.length ? <span className="cjs-chip">함유량 확인 {percentages.length}건</span> : null}
          {composition.contains_wrapper_or_dough ? <span className="cjs-chip">피·반죽 포함</span> : null}
          {composition.contains_sauce_or_broth ? <span className="cjs-chip">소스·육수 포함</span> : null}
        </div>
        <DataTable
          rows={compositionRows}
          limit={20}
          className="cjs-composition-table"
          emptyMessage="성분표에서 확인된 재료 정보가 없습니다."
          columns={[
            { key: "구분", label: "구분" },
            { key: "내용", label: "내용" },
          ]}
        />
      </section>
      <details className="cjs-secondary-evidence cjs-understanding-details">
        <summary>상품 해석 상세 근거</summary>
        <div className="cjs-understanding-meta">
          <span>해석 방식</span>
          <strong>{modeLabel}</strong>
          {HasValue(hints.translated_product_name) ? (
            <><span>영문 상품명</span><strong>{clean(hints.translated_product_name)}</strong></>
          ) : null}
        </div>
        <EvidenceTerms label="상품 정체 어휘" terms={hints.identity_terms} />
        <EvidenceTerms label="형태·가공 어휘" terms={hints.product_form_terms} />
        <CoiEvidenceBlock coi={understandingView.coi_evidence} />
      </details>
    </div>
  );
}
