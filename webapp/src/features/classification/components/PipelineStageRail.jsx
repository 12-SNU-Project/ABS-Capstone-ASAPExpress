import { EVENT_STAGE_LABELS, STAGES } from "@/lib/labels.js";
import { asList, clean, statusLabel } from "@/lib/format.js";
import { GetPipelineStageState } from "@/features/classification/model/classificationViewModel.js";

function EventLabel(stage) {
  const key = clean(stage);
  return EVENT_STAGE_LABELS[key] || key || "대기";
}

function GetCurrentStageInfo(result) {
  const events = asList(result?.events);
  const lastRelevant = events
    .slice()
    .reverse()
    .find((event) => clean(event.stage) && clean(event.stage) !== "Pipeline")
    || events[events.length - 1]
    || null;
  const status = clean(result?.job_status || lastRelevant?.status || "idle");
  if (result?.error) return { label: "오류", status: "failed", message: result.error };
  if (["completed", "complete"].includes(status)) {
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
    label: EventLabel(lastRelevant.stage),
    status: clean(lastRelevant.status || status || "running"),
    message: clean(lastRelevant.message) || "처리 중입니다.",
  };
}

export default function PipelineStageRail({ result, viewModel, activeStage, onSelect, busy }) {
  const info = GetCurrentStageInfo(result);
  const completed = STAGES.filter(([key]) => (
    ["done", "skipped"].includes(GetPipelineStageState(result, viewModel, key))
  )).length;

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
        <div className="cjs-progressbar" aria-hidden="true"><span /></div>
      ) : null}
      <nav className="cjs-stage-nav" aria-label="전체 처리 단계">
        {STAGES.map(([key, label, pipelineName], index) => {
          const state = GetPipelineStageState(result, viewModel, key);
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
