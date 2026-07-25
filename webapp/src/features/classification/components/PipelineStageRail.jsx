import { AlertCircle, Check, Circle, CircleHelp, Clock3, LoaderCircle, LockKeyhole, Minus } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { EVENT_STAGE_LABELS, STAGES } from "@/lib/labels.js";
import { asList, clean, statusLabel } from "@/lib/format.js";
import { GetPipelineStageState } from "@/features/classification/model/classificationViewModel.js";

function EventLabel(stage) {
  const key = clean(stage);
  return EVENT_STAGE_LABELS[key] || key || "대기";
}

function GetCurrentStageInfo(result) {
  const events = asList(result?.events);
  const lastRelevant = events.slice().reverse().find(
    (event) => clean(event.stage) && clean(event.stage) !== "Pipeline",
  ) || events[events.length - 1] || null;
  const status = clean(result?.job_status || lastRelevant?.status || "idle");
  if (result?.error) return { label: "처리 오류", status: "failed", message: result.error };
  if (["completed", "complete"].includes(status)) {
    return { label: "전체 완료", status: "done", message: "분류 결과와 서류 연결 정보를 확인할 수 있습니다." };
  }
  if (status === "awaiting_input") {
    return {
      label: "사용자 응답 대기",
      status: "awaiting-input",
      message: "분류 조건 질문에 답하면 중단 지점부터 계속 실행합니다.",
    };
  }
  if (!lastRelevant) {
    return { label: "분석 대기", status: "idle", message: "상품 정보를 입력하고 분류를 실행하세요." };
  }
  return {
    label: EventLabel(lastRelevant.stage),
    status: clean(lastRelevant.status || status || "running"),
    message: clean(lastRelevant.message) || "처리 중입니다.",
  };
}

function DisplayStageState(state) {
  return state === "submitting" ? "queued" : state;
}

function StageIcon({ state }) {
  const icons = {
    done: Check,
    skipped: Minus,
    running: LoaderCircle,
    queued: Clock3,
    failed: AlertCircle,
    "needs-review": AlertCircle,
    "awaiting-input": CircleHelp,
    idle: Circle,
  };
  const Icon = icons[state] || Circle;
  return <Icon className={state === "running" ? "motion-safe:animate-spin" : ""} />;
}

const STATE_TONES = {
  done: "border-success bg-success text-success-foreground",
  skipped: "border-muted-foreground/50 bg-muted text-muted-foreground",
  running: "border-primary bg-primary text-primary-foreground",
  queued: "border-primary/50 bg-primary/10 text-primary",
  failed: "border-destructive bg-destructive text-white",
  "needs-review": "border-needs-review bg-needs-review text-needs-review-foreground",
  "awaiting-input": "border-warning bg-warning/15 text-warning-foreground",
  idle: "border-border bg-surface text-muted-foreground",
};

export default function PipelineStageRail({
  result,
  viewModel,
  activeStage,
  onSelect,
  busy,
  restoring,
  documentReady,
}) {
  const reduceMotion = useReducedMotion();
  const info = restoring
    ? { label: "기존 작업 복원", status: "running", message: "저장된 실행 결과를 불러오는 중입니다." }
    : GetCurrentStageInfo(result);
  const completed = STAGES.filter(([key]) => (
    ["done", "skipped"].includes(GetPipelineStageState(result, viewModel, key))
  )).length;

  return (
    <section id="pipeline-stage-rail" className="rounded-xl border bg-surface p-4 shadow-[var(--shadow-surface)]">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="m-0 text-sm font-semibold text-foreground">분석 진행 단계</h2>
          <p className="mt-1 mb-0 text-xs text-muted-foreground">실제 파이프라인 이벤트와 동기화됩니다.</p>
        </div>
        <span className="text-xs font-semibold text-muted-foreground">{completed}/{STAGES.length} 완료</span>
      </div>

      {busy || info.status === "awaiting-input" || result?.error ? (
        <div className={`mt-3 flex gap-3 rounded-lg border px-3 py-2.5 ${result?.error ? "border-destructive/30 bg-destructive/5" : "bg-surface-muted"}`} role={result?.error ? "alert" : "status"}>
          <StageIcon state={DisplayStageState(info.status)} />
          <div className="min-w-0">
            <strong className="block text-sm">{info.label}</strong>
            <p className="mt-0.5 mb-0 break-words text-xs leading-5 text-muted-foreground">{info.message}</p>
          </div>
        </div>
      ) : null}

      <nav className="mt-4 grid min-w-0 gap-3 sm:grid-cols-3" aria-label="전체 처리 단계">
        {STAGES.map(([key, label], index) => {
          const state = DisplayStageState(GetPipelineStageState(result, viewModel, key));
          const active = activeStage === key;
          const locked = key === "document_recommendation" && !documentReady;
          const markerState = locked ? "idle" : state;
          const connectorDone = ["done", "skipped"].includes(state);
          return (
            <div className="relative min-w-0" key={key}>
              <button
                type="button"
                className={`flex w-full min-w-0 items-center gap-2.5 rounded-lg border px-3 py-2.5 text-left transition-colors duration-200 disabled:cursor-not-allowed disabled:opacity-60 ${active ? "border-primary bg-primary/5" : "border-transparent hover:bg-muted"}`}
                aria-current={active ? "step" : undefined}
                onClick={() => onSelect(key)}
                disabled={locked}
              >
                <motion.span
                  key={markerState}
                  initial={{ opacity: 0.55 }}
                  animate={{ opacity: 1 }}
                  transition={{ duration: reduceMotion ? 0 : 0.18 }}
                  className={`grid size-7 shrink-0 place-items-center rounded-full border [&>svg]:size-3.5 ${STATE_TONES[markerState] || STATE_TONES.idle}`}
                  aria-hidden="true"
                >
                  {locked ? <LockKeyhole /> : <StageIcon state={state} />}
                </motion.span>
                <span className="min-w-0">
                  <strong className="block truncate text-sm font-semibold text-foreground">{label}</strong>
                  <small className="block text-xs text-muted-foreground">
                    {locked ? "후보 선택 필요" : statusLabel(state)}
                  </small>
                </span>
              </button>
              {index < STAGES.length - 1 ? (
                <motion.span
                  className="absolute top-1/2 left-full hidden h-px w-3 sm:block"
                  animate={{ backgroundColor: connectorDone ? "var(--success)" : "var(--border)" }}
                  transition={{ duration: reduceMotion ? 0 : 0.18 }}
                  aria-hidden="true"
                />
              ) : null}
            </div>
          );
        })}
      </nav>
    </section>
  );
}
