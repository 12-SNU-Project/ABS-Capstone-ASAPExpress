import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import DataTable from "../components/DataTable";
import KeyValueRows from "../components/KeyValueRows";
import { useClassificationRun } from "../hooks/useClassificationRun";
import { importClassification } from "../lib/enterpriseApi.js";
import {
  GRADE_LABELS,
  conditionLabel,
  decisionLabel,
  detailValueText,
  extractTrace,
  gradeOf,
  isTrueVerdict,
  operationLabel,
  reasonLabel,
  stageEntryForCode,
  summarizeSummons,
  summonsForStage,
  stageLabelKo,
  trueDetails,
  verdictLabel,
} from "../lib/traceContract.js";
import {
  BuildCandidateHierarchy,
  CLASSIFICATION_STEPS,
  EVENT_STAGE_LABELS,
  RECONSTRUCTION_KEYS,
  STAGES,
  ClassificationStepForResult,
  RoutingScoreLabel,
  RoutingTermLabel,
  UnderstandingValueLabel,
} from "../lib/labels.js";
import {
  asList,
  asObject,
  candidateKey,
  clean,
  labelFor,
  sourceLabel,
  statusLabel,
} from "../lib/format.js";

const INTENDED_USE_OPTIONS = [
  ["human consumption", "최종 소비용"],
  ["further processing", "추가 가공용"],
  ["animal feed", "동물 사료용"],
  ["non-food use", "비식품용"],
];

function CreateIngredient(role = "secondary") {
  return { role, name: "", percentage: "" };
}

function ValidateStructuredInput(form) {
  const errors = { ingredientRows: {} };
  const rows = asList(form.ingredients);
  const completedRows = [];

  rows.forEach((row, index) => {
    const name = clean(row?.name);
    const percentageText = clean(row?.percentage);
    if (!name && !percentageText) {
      return;
    }
    if (!name) {
      errors.ingredientRows[index] = "재료명을 입력하세요.";
      return;
    }
    if (name.length > 100 || !/[A-Za-z가-힣]/.test(name)) {
      errors.ingredientRows[index] = "재료명은 한글 또는 영문을 포함해 100자 이내로 입력하세요.";
      return;
    }
    const percentage = Number(percentageText);
    if (!percentageText || !Number.isFinite(percentage) || percentage <= 0 || percentage > 100) {
      errors.ingredientRows[index] = "함유율은 0 초과 100 이하의 숫자로 입력하세요.";
      return;
    }
    completedRows.push({ ...row, name, percentage });
  });

  const normalizedNames = completedRows.map((row) => row.name.toLocaleLowerCase());
  if (new Set(normalizedNames).size !== normalizedNames.length) {
    errors.ingredients = "같은 재료명을 중복해서 입력할 수 없습니다.";
  } else if (completedRows.reduce((sum, row) => sum + row.percentage, 0) > 100) {
    errors.ingredients = "성분 함유율 합계는 100%를 넘을 수 없습니다.";
  } else if (
    completedRows.length > 0
    && completedRows.filter((row) => row.role === "primary").length !== 1
  ) {
    errors.ingredients = "성분을 입력한 경우 주성분을 정확히 1개 지정하세요.";
  }

  const originCountry = clean(form.originCountry).toUpperCase();
  if (originCountry && !/^[A-Z]{2}$/.test(originCountry)) {
    errors.originCountry = "원산국은 KR, VN처럼 영문 2자리 코드로 입력하세요.";
  }
  if (
    form.intendedUse
    && !INTENDED_USE_OPTIONS.some(([value]) => value === form.intendedUse)
  ) {
    errors.intendedUse = "제공된 상품 용도 중 하나를 선택하세요.";
  }

  return errors;
}

function HasFormErrors(errors) {
  return Boolean(
    errors.ingredients
    || errors.originCountry
    || errors.intendedUse
    || Object.keys(errors.ingredientRows || {}).length,
  );
}

function IngredientInputRows({ rows, errors, onChange, onAdd, onRemove }) {
  return (
    <fieldset className="cjs-ingredient-fieldset">
      <legend>주·부성분</legend>
      <div className="cjs-field-heading">
        <small>완제품 기준 재료명과 함유율(%)을 입력하세요.</small>
        <button
          type="button"
          className="cjs-add-button"
          onClick={onAdd}
          disabled={rows.length >= 20}
          aria-label="성분 입력 행 추가"
        >
          + 성분 추가
        </button>
      </div>
      <div className="cjs-ingredient-labels" aria-hidden="true">
        <span>구분</span>
        <span>재료명</span>
        <span>함유율 (%)</span>
        <span />
      </div>
      {rows.map((row, index) => {
        const errorId = `cjs-ingredient-error-${index}`;
        return (
          <div className="cjs-ingredient-row-wrap" key={index}>
            <div className="cjs-ingredient-row">
              <select
                className="cjs-input"
                aria-label={`${index + 1}번째 성분 구분`}
                value={row.role}
                onChange={(event) => onChange(index, "role", event.target.value)}
              >
                <option value="primary">주성분</option>
                <option value="secondary">부성분</option>
              </select>
              <input
                type="text"
                className="cjs-input"
                aria-label={`${index + 1}번째 재료명`}
                aria-describedby={errors[index] ? errorId : undefined}
                placeholder="예: 낙지"
                value={row.name}
                onChange={(event) => onChange(index, "name", event.target.value)}
              />
              <input
                type="number"
                className="cjs-input"
                aria-label={`${index + 1}번째 함유율`}
                aria-describedby={errors[index] ? errorId : undefined}
                min="0.01"
                max="100"
                step="0.01"
                placeholder="예: 60"
                value={row.percentage}
                onChange={(event) => onChange(index, "percentage", event.target.value)}
              />
              <button
                type="button"
                className="cjs-remove-button"
                onClick={() => onRemove(index)}
                disabled={rows.length === 1}
                aria-label={`${index + 1}번째 성분 삭제`}
              >
                ×
              </button>
            </div>
            {errors[index] ? (
              <div id={errorId} className="cjs-field-error">{errors[index]}</div>
            ) : null}
          </div>
        );
      })}
    </fieldset>
  );
}

function eventLabel(stage) {
  const key = clean(stage);
  return EVENT_STAGE_LABELS[key] || key || "대기";
}

function componentDone(result, nameFragment) {
  return asList(result?.component_results).some(
    (entry) =>
      clean(entry.component_name).toLowerCase().includes(nameFragment) && entry.success,
  );
}

function eventStatus(result, stageNames) {
  let status = "idle";
  asList(result?.events).forEach((event) => {
    if (stageNames.includes(clean(event.stage))) {
      status = clean(event.status) || status;
    }
  });
  return status;
}

function NormalizeStageState(status) {
  const value = clean(status).toLowerCase();
  if (["completed", "complete", "done"].includes(value)) return "done";
  if (["running", "queued", "submitting", "failed", "skipped"].includes(value)) return value;
  return "idle";
}

function useWorkbenchDerived(result) {
  return useMemo(() => {
    const candidateSet = asObject(result?.candidate_code_set);
    const candidates = asList(candidateSet.candidates);
    const packages = asList(result?.document_packages).slice();
    if (result?.document_package && typeof result.document_package === "object") {
      const packageId = clean(
        result.document_package.document_package_id
        || result.document_package.taric10,
      );
      if (!packages.some((item) => clean(item.document_package_id || item.taric10) === packageId)) {
        packages.push(result.document_package);
      }
    }
    const packagesByTaric = {};
    packages.forEach((pkg) => {
      const taric = clean(pkg.taric10);
      if (taric) {
        (packagesByTaric[taric] = packagesByTaric[taric] || []).push(pkg);
      }
    });
    return { candidateSet, candidates, packagesByTaric };
  }, [result]);
}

function stageState(result, derived, key) {
  if (key === "product_collection") {
    const event = NormalizeStageState(eventStatus(result, ["Kurly_Product_Collection"]));
    if (event !== "idle") return event;
    return result?.input_processing_view || derived.candidates.length ? "done" : "idle";
  }
  if (key === "classification") {
    if (derived.candidates.length) return "done";
    const event = NormalizeStageState(eventStatus(result, [
      "Input_Intake",
      "Evidence_Intake_Component",
      "Product_Understanding_Component",
      "HS2_Routing_Component",
      "Classification",
      "Classification_Component",
    ]));
    if (event !== "idle") return event;
    return componentDone(result, "classification") ? "done" : "idle";
  }
  if (key === "document_recommendation") {
    const event = NormalizeStageState(eventStatus(result, ["Document_Component"]));
    if (event !== "idle") return event;
    return asList(result?.document_packages).length || result?.document_package ? "done" : "idle";
  }
  return "idle";
}

function currentStageInfo(result) {
  const events = asList(result?.events);
  const lastRelevant =
    events
      .slice()
      .reverse()
      .find((event) => clean(event.stage) && clean(event.stage) !== "Pipeline") ||
    events[events.length - 1] ||
    null;
  const status = clean(result?.job_status || lastRelevant?.status || "idle");
  if (result?.error) {
    return { label: "오류", status: "failed", message: result.error };
  }
  if (status === "completed" || status === "complete") {
    return {
      label: "전체 완료",
      status: "completed",
      message: "분류 결과와 서류 연결 정보를 확인할 수 있습니다.",
    };
  }
  if (!lastRelevant) {
    return {
      label: "대기",
      status: "idle",
      message: "상품명 또는 URL을 입력하고 분류를 실행하세요.",
    };
  }
  return {
    label: eventLabel(lastRelevant.stage),
    status: clean(lastRelevant.status || status || "running"),
    message: clean(lastRelevant.message) || "처리 중입니다.",
  };
}

function StageNav({ result, derived, activeStage, onSelect, busy }) {
  const info = currentStageInfo(result);
  const completed = STAGES.filter(([key]) =>
    ["done", "skipped"].includes(stageState(result, derived, key))
  ).length;
  return (
    <div id="cjs-stage-rail" className={`cjs-stage-rail ${busy ? "busy" : ""}`}>
      <div className="cjs-stage-rail-heading">
        <div className="cjs-panel-title">전체 처리 단계</div>
        <strong>{completed}/{STAGES.length} 완료</strong>
      </div>
      {busy || result?.error ? (
        <div
          className={`cjs-stage-live-status ${info.status}`}
          role={result?.error ? "alert" : "status"}
        >
          <span className="cjs-stage-live-dot" aria-hidden="true" />
          <div>
            <strong>{info.label}</strong>
            <p>{info.message}</p>
          </div>
        </div>
      ) : null}
      {busy ? (
        <div className="cjs-progressbar" aria-hidden="true">
          <span />
        </div>
      ) : null}
      <nav className="cjs-stage-nav" aria-label="전체 처리 단계">
        {STAGES.map(([key, label, pipelineName], index) => {
          const state = stageState(result, derived, key);
          const done = ["done", "skipped"].includes(state);
          const active = activeStage === key;
          return (
            <button
              key={key}
              type="button"
              className={`cjs-stage-item ${active ? "active" : ""} state-${state}`}
              aria-current={active ? "step" : undefined}
              title={pipelineName}
              onClick={() => onSelect(key)}
            >
              <span className="cjs-stage-item-marker" aria-hidden="true">
                {done ? "✓" : index + 1}
              </span>
              <span className="cjs-stage-item-label">
                <strong>{label}</strong>
                <small>{statusLabel(state)}{active ? " · 열람 중" : ""}</small>
              </span>
            </button>
          );
        })}
      </nav>
    </div>
  );
}

function ClassificationFlow({ activeStep, onSelect }) {
  const activeIndex = Math.max(
    CLASSIFICATION_STEPS.findIndex(([key]) => key === activeStep),
    0,
  );
  return (
    <div className="cjs-panel cjs-classification-flow">
      <div className="cjs-classification-flow-heading">
        <div>
          <div className="cjs-panel-title">품목 분류 결과 확인</div>
          <small>전체 처리 과정의 ‘품목 분류’ 결과를 읽는 4개 화면입니다.</small>
        </div>
        <strong>
          {activeIndex + 1}/{CLASSIFICATION_STEPS.length} · {CLASSIFICATION_STEPS[activeIndex][1]}
        </strong>
      </div>
      <nav className="cjs-classification-step-nav" aria-label="품목 분류 검토 단계">
        {CLASSIFICATION_STEPS.map(([key, label, componentName], index) => (
          <button
            type="button"
            className={key === activeStep ? "active" : ""}
            aria-current={key === activeStep ? "step" : undefined}
            onClick={() => onSelect(key)}
            key={key}
          >
            <span>{index + 1}</span>
            <strong>{label}</strong>
            <small>{componentName}</small>
          </button>
        ))}
      </nav>
      <div className="cjs-review-warning">
        이 결과는 품목분류 검토 후보이며 세관·관세 전문가의 최종 확인이 필요합니다.
      </div>
    </div>
  );
}

function CandidateBoard({ derived, selectedKey, onSelect }) {
  const { candidates } = derived;
  if (!candidates.length) {
    return (
      <div className="cjs-candidate-board">
        <div className="cjs-panel-title">CN8(8자리) 분류 후보</div>
        <div className="cjs-muted">분류 후보가 여기에 표시됩니다.</div>
      </div>
    );
  }
  const defaultIndex = Math.max(candidates.findIndex((candidate) => candidate.llm_recommended), 0);
  const activeKey = candidates.some((candidate, index) => candidateKey(candidate, index) === selectedKey)
    ? selectedKey
    : candidateKey(candidates[defaultIndex], defaultIndex);
  return (
    <div className="cjs-candidate-board">
      <div className="cjs-candidate-heading">
        <div>
          <div className="cjs-panel-title">CN8(8자리) 분류 후보</div>
          <small>후보를 선택하면 바로 아래 결정 근거가 해당 코드 기준으로 바뀝니다.</small>
        </div>
        <strong>{candidates.length}건</strong>
      </div>
      <div className="cjs-candidate-grid">
        {candidates.map((candidate, index) => {
          const key = candidateKey(candidate, index);
          return (
            <button
              type="button"
              key={key}
              className={`cjs-candidate-card ${key === activeKey ? "active" : ""}`}
              aria-pressed={key === activeKey}
              onClick={() => onSelect(key)}
            >
              <span className="cjs-rank">{candidate.rank || index + 1}순위</span>
              <span className="cjs-source">
                {sourceLabel(candidate.candidate_source || candidate.status || "candidate")}
              </span>
              <div className="cjs-code-row">
                <span>HS6</span>
                <strong>{candidate.hs6 || "-"}</strong>
              </div>
              <div className="cjs-code-row">
                <span>CN8</span>
                <strong>{candidate.cn8 || "-"}</strong>
              </div>
              <div className="cjs-card-foot">
                {candidate.llm_recommended ? "현재 1순위 후보" : "검토 후보"}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

// composition_terms는 "키: 값" 문자열 목록 — LLM reconstruction 표의 행이다.
function parseCompositionTerms(terms) {
  return asList(terms)
    .map((term) => {
      const text = clean(term);
      const splitAt = text.indexOf(":");
      if (splitAt < 1) {
        return { 구분: "", 내용: text };
      }
      return { 구분: text.slice(0, splitAt).trim(), 내용: text.slice(splitAt + 1).trim() };
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

function ProductCollectionPanel({ result }) {
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
  const reconstructedFacts = asList(inputView.reconstructed_product_facts).map((fact) => ({
    ...MapFact(fact),
  }));
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
                {warnings.slice(0, 12).map((warning, index) => (
                  <li key={index}>{warning}</li>
                ))}
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
  if (!rows.length && !clean(evidence.error)) {
    return null;
  }
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

function PrecedentList({ cases }) {
  const list = asList(cases);
  if (!list.length) {
    return <div className="cjs-muted">이 후보와 연결된 유사 판례가 없습니다.</div>;
  }
  return (
    <div className="cjs-precedent-list">
      {list.map((item, index) => (
        <div className="cjs-precedent" key={index}>
          <div className="cjs-precedent-ref">{clean(item.evidence_ref)}</div>
          <div className="cjs-precedent-sim">{clean(item.similarity_comment)}</div>
          {clean(item.difference_comment) ? (
            <div className="cjs-precedent-diff">{clean(item.difference_comment)}</div>
          ) : null}
          {clean(item.case_summary) ? (
            <details className="cjs-precedent-more">
              <summary>판결문 요약</summary>
              <div className="cjs-precedent-body">{clean(item.case_summary)}</div>
            </details>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function TermChips({ label, terms }) {
  const list = asList(terms).map((term) => clean(term)).filter(Boolean);
  if (!list.length) {
    return null;
  }
  return (
    <div className="cjs-term-group">
      <div className="cjs-subpanel-title">{label} ({list.length})</div>
      <div className="cjs-chip-row">
        {list.slice(0, 16).map((term, index) => (
          <span className="cjs-chip" key={index}>
            {term}
          </span>
        ))}
      </div>
    </div>
  );
}

function UnderstandingPanel({ result }) {
  const understandingView = asObject(result?.product_understanding_view);
  const hints = asObject(understandingView.identity_hints);
  const composition = asObject(understandingView.composition_facts);
  const compositionRows = parseCompositionTerms(composition.composition_terms);
  const percentages = asList(composition.ingredient_percentages);
  const hasValue = (value) => !["", "unknown", "other"].includes(clean(value).toLowerCase());
  const reportedMissing = [
    ...asList(understandingView.unknowns),
    ...asList(composition.missing_composition_facts),
  ].map(FactLabel);
  const reviewReasons = [
    ...reportedMissing,
    ...(!clean(composition.principal_ingredient) && !reportedMissing.includes("주원료") ? ["주원료"] : []),
    ...(!percentages.length && !reportedMissing.includes("성분별 함유율") ? ["성분별 함유율"] : []),
  ].map(clean).filter((item, index, all) => item && all.indexOf(item) === index);
  const modeLabel = { llm_json: "AI 기반 구조화", llm_fallback: "규칙 기반 보완", regex_fallback: "규칙 기반" }[
    clean(hints.understanding_mode)
  ] || "기타 방식";
  const ingredientClasses = asList(composition.ingredient_classes).length
    ? asList(composition.ingredient_classes)
    : [hints.ingredient_class];
  const ingredientClassLabel = ingredientClasses
    .filter(hasValue)
    .map(UnderstandingValueLabel)
    .filter((value, index, all) => value && all.indexOf(value) === index)
    .join(" · ");
  const intendedUse = clean(hints.intended_use);
  const intendedUseLabel = INTENDED_USE_OPTIONS.find(([value]) => value === intendedUse)?.[1]
    || (hasValue(intendedUse) ? intendedUse : "");
  const processingState = hasValue(composition.processing_state)
    ? composition.processing_state
    : hints.processing_state;
  const facts = [
    ["원재료 계열", ingredientClassLabel],
    ["상품 형태", hasValue(hints.food_form) ? UnderstandingValueLabel(hints.food_form) : ""],
    [
      "가공·보존 상태",
      UnderstandingValueLabel(processingState),
    ],
    ["상품 용도", intendedUseLabel],
  ].filter(([, value]) => hasValue(value));
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
          {showNormalizedDescription ? (
            <p>분류용 상품 설명: {normalizedDescription}</p>
          ) : null}
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
          {hasValue(hints.translated_product_name) ? (
            <>
              <span>영문 상품명</span>
              <strong>{clean(hints.translated_product_name)}</strong>
            </>
          ) : null}
        </div>
        <TermChips label="상품 정체 어휘" terms={hints.identity_terms} />
        <TermChips label="형태·가공 어휘" terms={hints.product_form_terms} />
        <CoiEvidenceBlock coi={understandingView.coi_evidence} />
      </details>
    </div>
  );
}

function DocumentStagePanel({ result, derived }) {
  const navigate = useNavigate();
  const jobId = clean(result?.job_id || result?.run_id);
  const packages = Object.entries(derived.packagesByTaric);
  const [selectedTaric, setSelectedTaric] = useState("");
  const [savingProject, setSavingProject] = useState(false);
  const [projectError, setProjectError] = useState("");

  useEffect(() => {
    setSelectedTaric("");
    setProjectError("");
  }, [jobId]);

  const AddSelectedPackageToProject = async () => {
    if (!jobId || !selectedTaric || savingProject) {
      return;
    }
    setSavingProject(true);
    setProjectError("");
    try {
      const response = await importClassification({ jobId, taric10: selectedTaric });
      if (!response?.caseId) {
        throw new Error("프로젝트 생성 결과를 확인할 수 없습니다.");
      }
      navigate(`/enterprise?caseId=${encodeURIComponent(response.caseId)}&panel=docs`);
    } catch (error) {
      setProjectError(String(error?.message || error));
    } finally {
      setSavingProject(false);
    }
  };

  return (
    <div className="cjs-panel">
      <div className="cjs-panel-title">DocumentRecommendationPipeline · 서류 검토 패키지 ({packages.length}건)</div>
      <div className="cjs-note">
        TARIC10 분기별 서류 후보입니다. 필수 여부는 목적지·원산지·제품 사실과 공식 근거를 추가 확인해야 합니다.
      </div>
      {packages.length ? (
        <div className="cjs-taric-list">
          {packages.map(([taric, group]) => {
            const groupedPackages = asList(group);
            const documentCount = groupedPackages.reduce(
              (sum, item) => sum + Number(asObject(item).required_document_count || 0),
              0,
            );
            const missingCount = groupedPackages.reduce(
              (sum, item) => sum + asList(asObject(item).missing_facts).length,
              0,
            );
            return (
              <div className={`cjs-taric-row ${selectedTaric === taric ? "selected" : ""}`} key={taric}>
                <label className="cjs-taric-choice">
                  <input
                    type="radio"
                    name="document-project-package"
                    value={taric}
                    checked={selectedTaric === taric}
                    onChange={() => setSelectedTaric(taric)}
                  />
                  <span className="cjs-taric-copy">
                    <strong>{taric}</strong>
                    <small>서류 후보 {documentCount}건 · 추가 확인 {missingCount}건</small>
                  </span>
                </label>
                <Link
                  className="cjs-taric-detail-link"
                  to={`/document/${encodeURIComponent(jobId)}/${encodeURIComponent(taric)}`}
                >
                  상세 보기
                </Link>
              </div>
            );
          })}
          <div className="cjs-project-add-row">
            <span>
              {selectedTaric
                ? `TARIC10 ${selectedTaric} 서류 패키지를 프로젝트로 등록합니다.`
                : "프로젝트로 등록할 TARIC10 후보를 하나 선택하세요."}
            </span>
            <button
              type="button"
              className="cjs-primary-button"
              disabled={!jobId || !selectedTaric || savingProject}
              onClick={AddSelectedPackageToProject}
            >
              {savingProject ? "추가 중…" : "프로젝트에 추가하기"}
            </button>
          </div>
          {projectError ? <div className="cjs-note error" role="alert">{projectError}</div> : null}
        </div>
      ) : (
        <div className="cjs-muted">생성된 서류 패키지가 없습니다.</div>
      )}
    </div>
  );
}

const FACT_LABELS = {
  primary_ingredient_ratio: "주원료 함유율",
  animal_origin_content_pct: "동물성 원료 함유율",
  composition_pct: "성분별 함유율",
  ingredient_percentages: "성분별 함유율",
  principal_ingredient: "주원료",
  origin_country: "상품 원산국",
  intended_use: "상품 용도",
};

function FactLabel(value) {
  const key = clean(value);
  return FACT_LABELS[key] || key.replaceAll("_", " ");
}

function RoutingPanel({ result }) {
  const routingView = asObject(result?.routing_view);
  const understandingView = asObject(result?.product_understanding_view);
  const hints = asObject(understandingView.identity_hints);
  const chapterDetails = asList(routingView.candidate_chapter_details).map((detail) => {
    const source = asObject(detail);
    const scoreBreakdown = Object.entries(asObject(source.score_breakdown)).flatMap(
      ([key, amount]) => {
        const score = Number(amount);
        return Number.isFinite(score) && score !== 0
          ? [`${RoutingScoreLabel(key)} ${score > 0 ? "+" : ""}${score}`]
          : [];
      },
    );
    return {
      chapter: clean(source.chapter),
      score: source.score,
      scoreBreakdown: scoreBreakdown.length ? scoreBreakdown : ["세부 점수 기록 없음"],
      rawEvidence: asList(source.matched_terms).length
        ? asList(source.matched_terms).slice(0, 4).map(RoutingTermLabel)
        : ["기록된 어휘 없음"],
    };
  });
  const missingFacts = asList(routingView.missing_facts).map(FactLabel);
  const topChapter = chapterDetails[0];
  const scoredChapters = chapterDetails.filter((detail) => Number(detail.score) > 0).slice(0, 5);
  const comparedChapters = scoredChapters.length ? scoredChapters : chapterDetails.slice(0, 5);
  return (
    <div className="cjs-panel cjs-routing-panel">
      <div className="cjs-panel-title">챕터 후보 좁히기</div>
      {chapterDetails.length ? (
        <>
          <div className="cjs-routing-summary">
            <div className="cjs-routing-primary-result">
              <span>현재 1순위 후보</span>
              <div>
                <small>HS2</small>
                <strong>{topChapter.chapter}</strong>
              </div>
            </div>
            <div className="cjs-routing-score-result">
              <span>상대 점수</span>
              <strong>{topChapter.score}</strong>
              <small>확률이나 신뢰도가 아닌 후보 비교값</small>
            </div>
          </div>

          {missingFacts.length ? (
            <div className="cjs-routing-warning">
              <strong>추가 확인</strong>
              <span>{missingFacts.join(", ")} 정보가 있으면 후보 비교를 더 정교하게 검토할 수 있습니다.</span>
            </div>
          ) : null}

          <div className="cjs-routing-section-heading">
            <strong>{scoredChapters.length ? "점수를 받은 후보" : "비교 후보"}</strong>
            <span>같은 실행 안에서 상위 5개까지 비교합니다.</span>
          </div>
          <DataTable
            rows={comparedChapters}
            limit={5}
            className="cjs-routing-table"
            columns={[
              { key: "chapter", label: "HS2 챕터", variant: "mono" },
              { key: "score", label: "상대 점수", variant: "mono" },
              { key: "scoreBreakdown", label: "점수 구성", variant: "chips" },
            ]}
          />

          <details className="cjs-secondary-evidence cjs-routing-details">
            <summary>사전 힌트와 전체 후보 근거 보기</summary>
            <div className="cjs-subpanel-title cjs-first">상품 이해에서 전달된 사전 힌트</div>
            {clean(hints.chapter_hint_basis) ? (
              <p className="cjs-desc-text">{clean(hints.chapter_hint_basis)}</p>
            ) : (
              <div className="cjs-muted">기록된 챕터 사전 힌트가 없습니다.</div>
            )}
            <TermChips label="챕터 힌트" terms={hints.chapter_hint_terms} />
            <TermChips label="챕터 기준 어휘" terms={hints.chapter_hint_source_terms} />
            <TermChips label="라우팅 어휘" terms={understandingView.routing_terms} />

            <div className="cjs-subpanel-title">후보별 원문 근거</div>
            <DataTable
              rows={chapterDetails}
              limit={chapterDetails.length}
              className="cjs-routing-detail-table"
              columns={[
                { key: "chapter", label: "HS2 챕터", variant: "mono" },
                { key: "score", label: "상대 점수", variant: "mono" },
                { key: "rawEvidence", label: "라우팅에서 확인한 어휘", variant: "chips" },
              ]}
            />

            <div className="cjs-subpanel-title">전체 라우팅 검토 범위</div>
            <TermChips label="라우팅 검토 범위" terms={routingView.allowed_hs2} />
            <TermChips label="검토 도메인" terms={routingView.domain_scopes} />
          </details>
        </>
      ) : (
        <div className="cjs-muted">기록된 HS2 후보가 없습니다.</div>
      )}
    </div>
  );
}

// 등급 뱃지 — named=법정 서술(파랑)/precedent=판례(보라)/derived=승인 파생(초록)/fallback=회색
function GradeBadge({ detail }) {
  const grade = gradeOf(detail);
  if (!grade) {
    return null;
  }
  return <span className={`cjs-grade g-${grade}`}>{GRADE_LABELS[grade] || grade}</span>;
}

function StageSummonRow({ row, stageCode }) {
  const joined = row.fired && stageCode && row.code === stageCode;
  return (
    <div className={`cjs-stage-summon ${row.fired ? "fired" : ""}`}>
      <b>📚 이 지점에서 판례 조회</b>
      {row.fired ? (
        <span>
          분류 후보에 반영 — <span className="cjs-mono">{row.code}</span>
          {joined ? " (현재 후보와 일치)" : " (비교 후보로 반영)"}
          {row.refs.length ? ` · ${row.refs.slice(0, 3).join(", ")}` : ""}
        </span>
      ) : (
        <span>
          {row.reviewed || "-"}건 검토 — {row.silenceLabel || "미반영"}
          {row.notInTree ? ` (${row.notInTree})` : ""}
          {row.refs.length ? ` · 근거 판례 ${row.refs.slice(0, 3).join(", ")}` : ""}
        </span>
      )}
      {row.phrases.length ? <em>매치 구문: {row.phrases.slice(0, 3).join(" / ")}</em> : null}
      {row.distribution.length > 1 ? (
        <div className="cjs-summons-bar" title={row.distribution.map((d) => `${d.code} ${d.count}`).join(" · ")}>
          {row.distribution.map((entry) => (
            <span key={entry.code} style={{ flexGrow: Math.max(entry.count, 1) }}>
              {entry.code.slice(-6)} {entry.count}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function StageTraceBlock({ stage, cn8, summons }) {
  const entry = stageEntryForCode(stage, cn8);
  const stageName = clean(asObject(stage).stage);
  const stageSummons = summonsForStage(summons, stageName);
  if (!entry && !stageSummons.length) {
    return null;
  }
  const decision = clean(entry?.decision);
  const positives = entry ? trueDetails(entry) : [];
  const allDetails = entry ? asList(entry.decision_detail) : [];
  return (
    <div className="cjs-stage-trace">
      <div className="cjs-stage-trace-head">
        <b>{stageLabelKo(stageName)}</b>
        {entry ? <span className="cjs-mono">{clean(entry.code)}</span> : null}
        {decision ? (
          <span className={`cjs-decision d-${decision}`}>
            {decisionLabel(decision)}
          </span>
        ) : null}
        {entry?.residual ? <span className="cjs-residual">기타 항목</span> : null}
      </div>
      {stageSummons.map((row, index) => (
        <StageSummonRow row={row} stageCode={clean(entry?.code)} key={index} />
      ))}
      {entry ? (
        positives.length ? (
          positives.map((detail, index) => (
            <div className="cjs-trace-detail" key={index}>
              <GradeBadge detail={detail} />
              <span className="cjs-mono dim">{conditionLabel(detail.cond)}</span>
              <span>{detailValueText(detail) || reasonLabel(detail.why)}</span>
            </div>
          ))
        ) : (
          <div className="cjs-muted">이 후보를 뒷받침하는 조건이 확인되지 않았습니다.</div>
        )
      ) : null}
      {allDetails.length > positives.length ? (
        <details className="cjs-trace-more">
          <summary>모든 조건 확인 내역 ({allDetails.length}건)</summary>
          {allDetails.map((detail, index) => (
            <div className="cjs-trace-detail full" key={index}>
              <span className={isTrueVerdict(detail) ? "cjs-mono ok" : "cjs-mono dim"}>
                {verdictLabel(detail)}
              </span>
              <span className="cjs-mono dim">
                {conditionLabel(asObject(detail).cond)} · {operationLabel(asObject(detail).op)}
              </span>
              <span>{reasonLabel(asObject(detail).why)}</span>
            </div>
          ))}
        </details>
      ) : null}
    </div>
  );
}

// 스테이지에 앵커되지 못한(level 없는) 소환 기록만 — 나머지는 StageTraceBlock 안에 표시
function BtiSummonsBlock({ summons }) {
  const rows = summarizeSummons(summons).filter((row) => !row.level);
  if (!rows.length) {
    return null;
  }
  return (
    <>
      <div className="cjs-subpanel-title">BTI 판례 조회 이력 (단계 미지정)</div>
      {rows.map((row, index) => {
        const total = row.distribution.reduce((sum, entry) => sum + entry.count, 0);
        return (
          <div className="cjs-summons" key={index}>
            <div>
              {row.fired
                ? `분류 후보에 반영: ${row.code}${row.refs.length ? ` — ${row.refs.slice(0, 3).join(", ")}` : ""}`
                : `판례 조회: ${row.reviewed || "-"}건 검토 — ${row.silenceLabel || "미반영"}`}
            </div>
            {row.distribution.length > 1 ? (
              <div className="cjs-summons-bar" title={row.distribution.map((d) => `${d.code} ${d.count}`).join(" · ")}>
                {row.distribution.map((entry) => (
                  <span key={entry.code} style={{ flexGrow: Math.max(entry.count, 1) }}>
                    {entry.code.slice(-6)} {entry.count}
                  </span>
                ))}
              </div>
            ) : null}
            {total ? null : null}
          </div>
        );
      })}
    </>
  );
}

function ClassificationBasisLabel(value) {
  const basis = clean(value);
  if (basis.startsWith("Staged narrowing")) {
    return basis.replace(
      /^Staged narrowing hs4->hs6->cn8 selected CN8=/,
      "HS4 → HS6 → CN8 단계 축소 결과: ",
    );
  }
  return basis.replaceAll("_", " ");
}

function HierarchyTreeNode({ node }) {
  const children = asList(node.children);
  const basis = ClassificationBasisLabel(node.basis || node.description);
  return (
    <li>
      <div className={`cjs-hierarchy-node ${node.recommended ? "recommended" : ""}`}>
        <span className="cjs-hierarchy-marker">{node.level}</span>
        <div className="cjs-hierarchy-copy">
          <strong>{node.code}</strong>
          {node.level === "CN8" ? (
            <small>{basis || "후보 설명이 기록되지 않았습니다."}</small>
          ) : (
            <small>하위 분기 {children.length}개</small>
          )}
        </div>
        <div className="cjs-hierarchy-meta">
          {node.level === "CN8" ? (
            <span>{node.rank}순위{node.recommended ? " · 시스템 추천" : ""}</span>
          ) : null}
          {Number.isFinite(Number(node.score)) ? <small>단계 비교값 {node.score}</small> : null}
        </div>
      </div>
      {children.length ? (
        <ul>
          {children.map((child) => (
            <HierarchyTreeNode node={child} key={`${child.level}-${child.code}`} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

function HierarchyEvidencePanel({ candidates, selectedPath }) {
  const tree = BuildCandidateHierarchy(candidates, asObject(selectedPath));
  const hasCandidates = asList(tree.children).length > 0;
  return (
    <div className="cjs-panel cjs-hierarchy-panel">
      <div className="cjs-hierarchy-heading">
        <div>
          <div className="cjs-panel-title">후보 계층 분류 트리</div>
          <small>공통 상위 코드는 묶고, 코드가 갈라지는 지점부터 후보를 들여쓰기했습니다.</small>
        </div>
        <strong>CN8 후보 {asList(candidates).length}개</strong>
      </div>
      {hasCandidates ? (
        <ul className="cjs-hierarchy-tree" aria-label="HS 코드 후보 계층 트리">
          <HierarchyTreeNode node={tree} />
        </ul>
      ) : (
        <div className="cjs-muted">계층 분류 후보가 기록되지 않았습니다.</div>
      )}
      <div className="cjs-muted">단계 비교값은 각 단계 내부의 후보 비교 기록이며 확률 또는 법적 확신도가 아닙니다.</div>
    </div>
  );
}

function ReviewPanel({ candidate, trace }) {
  const basis = asList(candidate?.classification_basis).map(ClassificationBasisLabel);
  const validator = asObject(trace?.validator);
  const citations = asList(candidate?.classification_citations);
  const validatorCode = clean(validator.cn8 || validator.code || validator.chapter || validator.heading);
  return (
    <div className="cjs-panel">
      <div className="cjs-review-panel-heading">
        <div>
          <div className="cjs-panel-title">선택 후보 결정 근거</div>
          <small>현재 선택한 후보에 연결된 판단 메모와 단계별 근거입니다.</small>
        </div>
        <strong>CN8 {clean(candidate?.cn8) || "미선택"}</strong>
      </div>
      <div className="cjs-subpanel-title cjs-first">판단 메모</div>
      {basis.length ? (
        basis.map((line, index) => (
          <div className="cjs-pill" key={index}>
            {line}
          </div>
        ))
      ) : (
        <div className="cjs-muted">표시할 판단 메모가 없습니다.</div>
      )}
      {trace?.hasTrace ? (
        <>
          <div className="cjs-subpanel-title">단계별 분류 근거 · EU 품목분류 판례(BTI) 조회 포함</div>
          {asList(trace.stages).map((stage, index) => (
            <StageTraceBlock stage={stage} cn8={candidate?.cn8} summons={trace.summons} key={index} />
          ))}
          {Object.keys(validator).length ? (
            <div className={`cjs-validator ${validator.applied ? "applied" : ""}`}>
              <b>모델 검증 권고</b>
              <span className="cjs-mono">{validatorCode || "코드 미지정"}</span>
              <span>{clean(validator.reason) || "별도 권고 사유가 기록되지 않았습니다."}</span>
              {validator.applied && clean(validator.original_top_cn8) ? (
                <em>적용됨 — 원 1순위 {clean(validator.original_top_cn8)} 교체</em>
              ) : null}
            </div>
          ) : null}
          <BtiSummonsBlock summons={trace.summons} />
        </>
      ) : (
        <div className="cjs-muted">이 실행에는 단계별 분류 근거가 기록되지 않았습니다.</div>
      )}
      <div className="cjs-subpanel-title">분류에 반영된 BTI 판례 조회</div>
      <div className="cjs-muted">
        {asList(trace?.summons).length
          ? `${asList(trace.summons).length}건의 판례 조회 기록이 있습니다.`
          : "이 실행에는 분류에 반영된 BTI 판례 조회 결과가 없습니다."}
      </div>
      {citations.length ? (
        <div className="cjs-note">
          연결된 인용 {citations.length}건은 TARIC 분기 조회 출처입니다. CN8 법적 확정 근거로 해석하지 않습니다.
        </div>
      ) : null}
      <details className="cjs-secondary-evidence">
        <summary>
          유사 EU 분류 판례 {asList(candidate?.similar_ebti_cases).length}건
          (참고 전용 · 후보 선택에 무관여)
        </summary>
        <PrecedentList cases={candidate?.similar_ebti_cases} />
      </details>
    </div>
  );
}

function ClassificationPager({ activeStep, onSelect }) {
  const activeIndex = Math.max(
    CLASSIFICATION_STEPS.findIndex(([key]) => key === activeStep),
    0,
  );
  const previous = CLASSIFICATION_STEPS[activeIndex - 1];
  const next = CLASSIFICATION_STEPS[activeIndex + 1];
  return (
    <nav className="cjs-classification-pager" aria-label="분류 단계 이동">
      <button type="button" disabled={!previous} onClick={() => previous && onSelect(previous[0])}>
        ← {previous ? previous[1] : "이전"}
      </button>
      <span>{activeIndex + 1} / {CLASSIFICATION_STEPS.length}</span>
      <button type="button" disabled={!next} onClick={() => next && onSelect(next[0])}>
        {next ? next[1] : "다음"} →
      </button>
    </nav>
  );
}

export default function WorkbenchPage() {
  const [searchParams] = useSearchParams();
  const { result, busy, runPipeline, loadRun } = useClassificationRun(searchParams.get("job"));
  const [form, setForm] = useState({
    productName: "",
    url: "",
    ingredients: [CreateIngredient("primary")],
    intendedUse: "",
    originCountry: "",
  });
  const [formErrors, setFormErrors] = useState({ ingredientRows: {} });
  const [jobIdInput, setJobIdInput] = useState("");
  const [loadError, setLoadError] = useState("");
  const [selectedKey, setSelectedKey] = useState("");
  const [inputExpanded, setInputExpanded] = useState(true);
  const derived = useWorkbenchDerived(result);
  const trace = useMemo(
    () => extractTrace(derived.candidateSet),
    [derived.candidateSet],
  );
  const [activeStage, setActiveStage] = useState("classification");
  const [classificationStep, setClassificationStep] = useState("understanding");
  const followStageRef = useRef(true);
  const followClassificationRef = useRef(true);

  useEffect(() => {
    if (clean(result?.job_id)) {
      setJobIdInput(clean(result.job_id));
    }
  }, [result?.job_id]);

  // 실행 중에는 진행 단계를 자동 추적, 완료되면 분류 결과로 착지.
  // 사용자가 레일을 직접 클릭하면 그 run이 끝날 때까지 수동 모드 유지.
  useEffect(() => {
    if (busy) {
      followStageRef.current = true;
      followClassificationRef.current = true;
    }
  }, [busy]);

  useEffect(() => {
    if (!followStageRef.current) {
      return;
    }
    const status = clean(result?.job_status).toLowerCase();
    if (["completed", "complete", "done"].includes(status)) {
      setActiveStage("classification");
      return;
    }
    let latest = "product_collection";
    STAGES.forEach(([key]) => {
      const state = stageState(result, derived, key);
      if (state === "done" || state === "running" || state === "completed") {
        latest = key;
      }
    });
    setActiveStage(latest);
  }, [result, derived, busy]);

  useEffect(() => {
    if (followClassificationRef.current) {
      setClassificationStep(ClassificationStepForResult(result));
    }
  }, [result]);

  const pickStage = (key) => {
    followStageRef.current = false;
    setActiveStage(key);
  };

  const pickClassificationStep = (key) => {
    followClassificationRef.current = false;
    setClassificationStep(key);
  };

  const defaultCandidate =
    derived.candidates.find((candidate) => candidate.llm_recommended) || derived.candidates[0] || null;
  const selectedCandidate =
    derived.candidates.find(
      (candidate, index) => candidateKey(candidate, index) === selectedKey,
    ) || defaultCandidate;

  const setField = (key) => (event) => {
    setFormErrors({ ingredientRows: {} });
    setForm((prev) => ({ ...prev, [key]: event.target.value }));
  };

  const setIngredient = (index, key, value) => {
    setFormErrors({ ingredientRows: {} });
    setForm((prev) => ({
      ...prev,
      ingredients: prev.ingredients.map((item, itemIndex) => (
        itemIndex === index ? { ...item, [key]: value } : item
      )),
    }));
  };

  const addIngredient = () => {
    setFormErrors({ ingredientRows: {} });
    setForm((prev) => ({
      ...prev,
      ingredients: [...prev.ingredients, CreateIngredient()],
    }));
  };

  const removeIngredient = (index) => {
    setFormErrors({ ingredientRows: {} });
    setForm((prev) => ({
      ...prev,
      ingredients: prev.ingredients.filter((_, itemIndex) => itemIndex !== index),
    }));
  };

  const handleRun = (mode) => {
    if (mode !== "reconstruct") {
      const nextErrors = ValidateStructuredInput(form);
      setFormErrors(nextErrors);
      if (HasFormErrors(nextErrors)) {
        return;
      }
    }
    setInputExpanded(false);
    runPipeline(mode, form);
  };

  const restoreRun = async () => {
    setLoadError("");
    try {
      await loadRun(jobIdInput);
      setInputExpanded(false);
      followStageRef.current = true;
    } catch (error) {
      setLoadError(String(error?.message || error));
    }
  };

  const requestFacts = asObject(result?.request?.facts);
  const inputSummaryName = clean(form.productName)
    || clean(requestFacts.product_name)
    || clean(requestFacts.product_id)
    || "상품 정보";
  const inputSummaryUrl = clean(form.url) || clean(requestFacts.url);

  return (
    <div className="classification-js-shell">
      <div className="cjs-hero">
        <div className="cjs-heading">
          <div className="cjs-eyebrow">ASAP Classification</div>
          <h1 className="cjs-title">EU 수출 품목분류</h1>
          <div className="cjs-subtitle">
            상품 정보를 읽고 HS6/CN8 후보와 TARIC10 서류 연결 지점을 확인합니다.
          </div>
        </div>
      </div>

      <section className={`cjs-run-card ${inputExpanded ? "" : "collapsed"}`}>
        <div className="cjs-run-card-heading">
          <div>
            <strong>상품 입력</strong>
            <span>{inputExpanded ? "분류에 사용할 상품 정보와 확인된 보정값을 입력합니다." : "입력값이 요약되어 있습니다."}</span>
          </div>
          <button
            type="button"
            className="cjs-input-toggle"
            aria-expanded={inputExpanded}
            aria-controls="cjs-run-form"
            onClick={() => setInputExpanded((expanded) => !expanded)}
          >
            {inputExpanded ? "입력 접기" : "입력 정보 수정"}
          </button>
        </div>
        {inputExpanded ? (
          <div id="cjs-run-form" className="cjs-run-form">
            <div className="cjs-input-section-heading">
              <strong>기본 상품 정보</strong>
              <span>상품명 또는 URL 중 하나를 입력하세요.</span>
            </div>
            <div className="cjs-field">
              <label htmlFor="cjs-product-name">상품명</label>
              <input
                id="cjs-product-name"
                type="text"
                className="cjs-input"
                placeholder="예: 신라면, 낙지 볶음, 데오도란트"
                value={form.productName}
                onChange={setField("productName")}
              />
            </div>
            <div className="cjs-field">
              <label htmlFor="cjs-product-url">상품 URL</label>
              <input
                id="cjs-product-url"
                type="text"
                className="cjs-input"
                placeholder="Kurly 또는 상품 상세 URL"
                value={form.url}
                onChange={setField("url")}
              />
            </div>
            <div className="cjs-input-section-heading cjs-input-section-heading-secondary">
              <strong>분류 보정 정보</strong>
              <span>선택 입력 · 확인된 정보만 분류 근거에 반영됩니다.</span>
            </div>
            <div className="cjs-field cjs-field-full">
              <IngredientInputRows
                rows={form.ingredients}
                errors={formErrors.ingredientRows || {}}
                onChange={setIngredient}
                onAdd={addIngredient}
                onRemove={removeIngredient}
              />
              {formErrors.ingredients ? (
                <div className="cjs-field-error">{formErrors.ingredients}</div>
              ) : null}
            </div>
            <div className="cjs-field">
              <label htmlFor="cjs-intended-use">상품 용도</label>
              <select
                id="cjs-intended-use"
                className="cjs-input"
                value={form.intendedUse}
                onChange={setField("intendedUse")}
                aria-describedby={formErrors.intendedUse ? "cjs-intended-use-error" : "cjs-use-help"}
              >
                <option value="">선택하지 않음</option>
                {INTENDED_USE_OPTIONS.map(([value, label]) => (
                  <option value={value} key={value}>{label}</option>
                ))}
              </select>
              <small id="cjs-use-help">실제 사용 목적을 아는 경우에만 선택하세요.</small>
              {formErrors.intendedUse ? (
                <div id="cjs-intended-use-error" className="cjs-field-error">
                  {formErrors.intendedUse}
                </div>
              ) : null}
            </div>
            <div className="cjs-field cjs-origin-field">
              <label htmlFor="cjs-origin-country">상품 원산국</label>
              <input
                id="cjs-origin-country"
                type="text"
                className="cjs-input cjs-uppercase-input"
                maxLength="2"
                placeholder="예: KR, VN, CN, US"
                value={form.originCountry}
                onChange={setField("originCountry")}
                aria-describedby={formErrors.originCountry ? "cjs-origin-error" : "cjs-origin-help"}
              />
              <small id="cjs-origin-help">원재료 산지가 아닌 완제품의 원산국입니다.</small>
              {formErrors.originCountry ? (
                <div id="cjs-origin-error" className="cjs-field-error">
                  {formErrors.originCountry}
                </div>
              ) : null}
            </div>
            <div className="cjs-run-actions">
              <button
                type="button"
                className="cjs-secondary-button"
                disabled={busy}
                onClick={() => handleRun("cached")}
              >
                최근 입력으로 실행
              </button>
              <button
                type="button"
                className="cjs-secondary-button"
                disabled={busy}
                onClick={() => handleRun("reconstruct")}
              >
                상품 정보만 복원
              </button>
              <button
                type="button"
                className="cjs-primary-button"
                disabled={busy}
                onClick={() => handleRun("full")}
              >
                분류 실행
              </button>
            </div>
          </div>
        ) : (
          <div id="cjs-run-form" className="cjs-input-summary">
            <div>
              <span>분석 대상</span>
              <strong>{inputSummaryName}</strong>
              {inputSummaryUrl ? <small>{inputSummaryUrl}</small> : null}
            </div>
            <span>진행 상황과 결과를 아래에서 확인하세요.</span>
          </div>
        )}
      </section>

      <details className="cjs-run-restore" open>
        <summary>기존 작업 불러오기</summary>
        <div className="cjs-run-restore-body">
          <label htmlFor="cjs-job-id">작업 번호</label>
          <div className="cjs-run-restore-controls">
            <input
              id="cjs-job-id"
              type="text"
              className="cjs-input"
              placeholder="job_..."
              value={jobIdInput}
              onChange={(event) => setJobIdInput(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && restoreRun()}
              disabled={busy}
            />
            <button type="button" className="cjs-secondary-button" disabled={busy} onClick={restoreRun}>
              불러오기
            </button>
          </div>
          <small>백엔드에 남아 있는 job_id의 분류 후보와 TARIC 서류 패키지를 다시 엽니다.</small>
          {loadError ? <div className="cjs-run-restore-error">{loadError}</div> : null}
        </div>
      </details>

      <section className="cjs-workspace cjs-workspace-nav">
        <StageNav
          result={result}
          derived={derived}
          activeStage={activeStage}
          onSelect={pickStage}
          busy={busy}
        />
        <main className="cjs-stage-content">
          {activeStage === "product_collection" ? (
            <ProductCollectionPanel result={result} />
          ) : null}
          {activeStage === "classification" ? (
            <>
              <ClassificationFlow
                activeStep={classificationStep}
                onSelect={pickClassificationStep}
              />
              <div className="cjs-classification-step-content">
                {classificationStep === "understanding" ? (
                  <UnderstandingPanel result={result} />
                ) : null}
                {classificationStep === "routing" ? (
                  <RoutingPanel result={result} />
                ) : null}
                {classificationStep === "hierarchy" ? (
                  <HierarchyEvidencePanel
                    candidates={derived.candidates}
                    selectedPath={derived.candidateSet.selected_path}
                  />
                ) : null}
                {classificationStep === "review" ? (
                  <>
                    <CandidateBoard
                      derived={derived}
                      selectedKey={selectedKey}
                      onSelect={setSelectedKey}
                    />
                    <ReviewPanel
                      candidate={selectedCandidate}
                      trace={trace}
                    />
                  </>
                ) : null}
              </div>
              <ClassificationPager
                activeStep={classificationStep}
                onSelect={pickClassificationStep}
              />
            </>
          ) : null}
          {activeStage === "document_recommendation" ? (
            <DocumentStagePanel result={result} derived={derived} />
          ) : null}
        </main>
      </section>
    </div>
  );
}
