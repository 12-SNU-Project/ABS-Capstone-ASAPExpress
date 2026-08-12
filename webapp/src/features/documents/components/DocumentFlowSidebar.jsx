import { motion, useReducedMotion } from "motion/react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { FLOW_ITEMS } from "../model/documentPackageViewModel.js";

export default function DocumentFlowSidebar({ activeKey, counts, onSelect }) {
  const reduceMotion = useReducedMotion();
  return (
    <>
      <div className="md:hidden">
        <Select value={activeKey} onValueChange={onSelect}>
          <SelectTrigger className="w-full" aria-label="서류 검토 단계">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {FLOW_ITEMS.map((item) => (
              <SelectItem value={item.key} key={item.key}>
                {item.step} {item.title} · {counts[item.key] || 0}건
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <nav className="relative hidden min-w-0 md:block" aria-label="서류 추천 절차">
        <span className="absolute bottom-6 left-[19px] top-6 w-px bg-border" aria-hidden="true" />
        <div className="grid gap-1">
          {FLOW_ITEMS.map((item) => {
            const active = item.key === activeKey;
            const count = counts[item.key] || 0;
            return (
              <button
                key={item.key}
                type="button"
                className={`group relative grid grid-cols-[40px_minmax(0,1fr)] gap-3 rounded-lg px-0 py-4 text-left transition-colors duration-150 ${active ? "bg-primary/5" : "hover:bg-muted"}`}
                onClick={() => onSelect(item.key)}
                aria-current={active ? "step" : undefined}
              >
                <span className={`relative z-10 grid size-10 place-items-center rounded-full border text-sm font-bold ${active ? "border-primary bg-primary text-primary-foreground" : "border-border bg-surface text-muted-foreground"}`}>
                  {item.step}
                </span>
                <span className="min-w-0 self-center pr-3">
                  <strong className="block text-base font-semibold leading-6 text-foreground">{item.shortTitle}</strong>
                  <small className="mt-1 block text-sm leading-5 text-muted-foreground">
                    {active ? "검토 중" : count ? `${count}건 확인 가능` : "자료 없음"}
                  </small>
                </span>
                {active ? (
                  <motion.span
                    layoutId="document-flow-active-line"
                    className="absolute inset-y-3 right-0 w-0.5 rounded-full bg-primary"
                    transition={{ duration: reduceMotion ? 0 : 0.18, ease: "easeOut" }}
                    aria-hidden="true"
                  />
                ) : null}
              </button>
            );
          })}
        </div>
      </nav>
    </>
  );
}
