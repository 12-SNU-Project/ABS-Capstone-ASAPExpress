import { Badge } from "@/components/ui/badge";

export default function WorkspaceHeader({ eyebrow, title, description, badge, actions }) {
  return (
    <header className="flex flex-col gap-4 rounded-xl border bg-surface px-5 py-4 shadow-[var(--shadow-surface)] sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <span className="text-[11px] font-semibold tracking-[0.14em] text-primary uppercase">
            {eyebrow}
          </span>
          {badge ? <Badge variant="secondary">{badge}</Badge> : null}
        </div>
        <h1 className="m-0 text-2xl leading-tight font-semibold tracking-[-0.02em] text-foreground">
          {title}
        </h1>
        {description ? (
          <p className="mt-1.5 mb-0 max-w-3xl text-sm leading-6 text-muted-foreground">
            {description}
          </p>
        ) : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </header>
  );
}
