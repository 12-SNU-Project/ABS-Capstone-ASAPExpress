import { CLASSIFICATION_STEPS } from "@/lib/labels.js";

export function ClassificationStageHeader({ activeStep, onSelect }) {
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

export function ClassificationPager({ activeStep, onSelect }) {
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
