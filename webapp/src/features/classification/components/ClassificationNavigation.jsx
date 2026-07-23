import { AlertCircle, ArrowLeft, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { CLASSIFICATION_STEPS } from "@/lib/labels.js";

export function ClassificationStageHeader({ activeStep, onSelect }) {
  return (
    <section className="rounded-xl border bg-surface p-4 shadow-[var(--shadow-surface)]">
      <div className="mb-3">
        <h2 className="m-0 text-base font-semibold">품목 분류 결과</h2>
        <p className="mt-1 mb-0 text-sm text-muted-foreground">상품 이해부터 최종 후보 근거까지 단계별로 검토합니다.</p>
      </div>
      <Tabs value={activeStep} onValueChange={onSelect}>
        <TabsList className="grid h-auto w-full grid-cols-2 gap-1 p-1 md:grid-cols-4" aria-label="품목 분류 검토 단계">
          {CLASSIFICATION_STEPS.map(([key, label]) => (
            <TabsTrigger className="min-h-9 px-3" value={key} key={key}>{label}</TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      <div className="mt-3 flex items-start gap-2 rounded-lg border border-needs-review/30 bg-needs-review/5 px-3 py-2.5 text-sm text-foreground">
        <AlertCircle className="mt-0.5 size-4 shrink-0 text-needs-review" aria-hidden="true" />
        <span>시스템 추천은 법적 확정이 아니며 세관 또는 관세 전문가의 최종 확인이 필요합니다.</span>
      </div>
    </section>
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
