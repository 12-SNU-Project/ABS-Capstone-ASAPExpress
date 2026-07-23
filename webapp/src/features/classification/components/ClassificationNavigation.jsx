import { AlertCircle, ArrowLeft, ArrowRight } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { CLASSIFICATION_STEPS } from "@/lib/labels.js";

export function ClassificationStageHeader({ activeStep, onSelect }) {
  const reduceMotion = useReducedMotion();
  const stepTransition = reduceMotion
    ? { duration: 0 }
    : { duration: 0.34, ease: [0.22, 1, 0.36, 1] };

  return (
    <div className="grid min-w-0 gap-3">
      <section className="isolate overflow-hidden rounded-xl border bg-surface shadow-[var(--shadow-surface)]">
        <div className="min-w-0 overflow-hidden px-4 py-5 sm:px-5 sm:py-6">
          <div className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <h2 className="m-0 text-base font-semibold">품목 분류 결과</h2>
            <p className="m-0 text-sm leading-5 text-muted-foreground">
              단계별 근거 검토
            </p>
          </div>
          <Tabs className="mt-6 min-w-0 w-full max-w-full gap-0 p-1" value={activeStep} onValueChange={onSelect}>
            <TabsList
              variant="line"
              className="grid h-auto min-w-0 w-full grid-cols-4 gap-0 bg-transparent p-0 group-data-horizontal/tabs:h-auto"
              aria-label="품목 분류 검토 단계"
            >
              {CLASSIFICATION_STEPS.map(([key, label], index) => {
                const active = key === activeStep;
                return (
                  <TabsTrigger
                    className="h-auto min-h-16 min-w-0 w-full flex-col gap-1.5 overflow-visible bg-transparent px-1 py-3 text-center whitespace-normal after:hidden data-active:bg-transparent data-active:shadow-none sm:flex-row sm:gap-2.5"
                    value={key}
                    key={key}
                  >
                    <span className={`relative z-10 grid size-8 shrink-0 place-items-center rounded-full border text-xs font-bold sm:size-9 ${active ? "border-primary text-primary-foreground" : "border-border bg-surface text-muted-foreground"}`}>
                      {active ? (
                        <motion.span
                          className="absolute -inset-1 rounded-full"
                          layoutId="classification-review-step"
                          transition={stepTransition}
                          aria-hidden="true"
                        >
                          {!reduceMotion ? (
                            <motion.span
                              className="absolute inset-0 rounded-full opacity-55 blur-[1px] will-change-transform"
                              style={{
                                background: "conic-gradient(from 0deg, transparent 0deg, var(--primary) 78deg, transparent 150deg)",
                              }}
                              animate={{ rotate: 360 }}
                              transition={{ duration: 2.8, ease: "linear", repeat: Infinity }}
                            />
                          ) : null}
                          <span className="absolute inset-1 rounded-full bg-primary shadow-[0_0_0_1px_color-mix(in_srgb,var(--primary)_38%,transparent)]" />
                        </motion.span>
                      ) : null}
                      <span className="relative">{index + 1}</span>
                    </span>
                    <span className={`text-[11px] leading-4 font-semibold sm:text-sm ${active ? "text-foreground" : "text-muted-foreground"}`}>
                      {label}
                    </span>
                  </TabsTrigger>
                );
              })}
            </TabsList>
          </Tabs>
        </div>
      </section>
      <div className="flex items-start gap-2 px-1 text-xs leading-5 text-muted-foreground sm:text-sm" role="note">
        <AlertCircle className="mt-0.5 size-4 shrink-0 text-needs-review" aria-hidden="true" />
        <span>시스템 추천은 법적 확정이 아니며 세관 또는 관세 전문가의 최종 확인이 필요합니다.</span>
      </div>
    </div>
  );
}

export function ClassificationPager({ activeStep, onSelect }) {
  const activeIndex = Math.max(CLASSIFICATION_STEPS.findIndex(([key]) => key === activeStep), 0);
  const previous = CLASSIFICATION_STEPS[activeIndex - 1];
  const next = CLASSIFICATION_STEPS[activeIndex + 1];
  return (
    <nav className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-2" aria-label="분류 단계 이동">
      <Button type="button" variant="outline" disabled={!previous} onClick={() => previous && onSelect(previous[0])}>
        <ArrowLeft /> {previous ? previous[1] : "이전"}
      </Button>
      <span className="text-xs font-semibold text-muted-foreground">{activeIndex + 1}/{CLASSIFICATION_STEPS.length}</span>
      <Button type="button" variant="outline" disabled={!next} onClick={() => next && onSelect(next[0])}>
        {next ? next[1] : "다음"} <ArrowRight />
      </Button>
    </nav>
  );
}
