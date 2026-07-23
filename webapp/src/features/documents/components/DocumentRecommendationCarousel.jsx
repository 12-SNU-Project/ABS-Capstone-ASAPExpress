import { useMemo, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { FileCheck2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import {
  Carousel,
  CarouselContent,
  CarouselItem,
  CarouselNext,
  CarouselPrevious,
} from "@/components/ui/carousel";
import { asList, clean } from "@/lib/format.js";

function DocumentKey(document, index) {
  return clean(document.documentId || document.baselineDocumentId || document.documentName) || `document-${index}`;
}

function DocumentCard({ document, selected, onSelect }) {
  const condition = clean(document.detail) || asList(document.fields).join(", ");
  const unresolvedCount = Number(document.unresolvedCount || 0);
  return (
    <button type="button" className="h-full w-full text-left" aria-pressed={selected} onClick={onSelect}>
      <Card className={`h-full gap-0 py-0 transition-colors duration-150 ${selected ? "bg-primary/5 ring-primary" : "hover:ring-primary/40"}`}>
        <CardContent className="grid h-full content-start gap-3 p-4">
          <div className="flex items-start justify-between gap-3">
            <FileCheck2 className="mt-0.5 size-5 shrink-0 text-primary" aria-hidden="true" />
            <Badge variant={document.requiredLevel === "필수" ? "default" : "secondary"}>
              {document.requiredLevel || document.source || "검토 대상"}
            </Badge>
          </div>
          <strong className="text-base leading-6 text-foreground">{document.documentName}</strong>
          <p className="line-clamp-3 min-h-10 text-sm leading-5 text-muted-foreground">
            {condition || "적용 조건과 준비 항목은 상세에서 확인합니다."}
          </p>
          <div className="mt-auto border-t pt-3 text-xs text-muted-foreground">
            <span className="block">준비 주체 · {clean(document.preparedBy) || "확인 필요"}</span>
            <span className={unresolvedCount ? "text-needs-review" : "text-success"}>
              미해결 조건 {unresolvedCount}건
            </span>
          </div>
        </CardContent>
      </Card>
    </button>
  );
}

function SelectedDocumentDetail({ document }) {
  const reduceMotion = useReducedMotion();
  const rows = [
    ["적용 조건", clean(document.detail) || "별도 적용 조건 없음"],
    ["준비 주체", clean(document.preparedBy) || "추가 확인 필요"],
    ["제출 대상", clean(document.submittedTo) || "추가 확인 필요"],
    ["필수 기재 항목", asList(document.fields).join(", ") || "연결된 필드 정보 없음"],
    ["연결 수입요건", clean(document.groupName) || "기본 통관 준비서류"],
  ];
  return (
    <motion.section
      key={DocumentKey(document, 0)}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: reduceMotion ? 0 : 0.18 }}
      className="mt-4 rounded-xl border bg-surface-muted p-4"
      aria-live="polite"
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="m-0 text-base font-semibold">{document.documentName}</h3>
        <Badge variant="outline">상세 준비 정보</Badge>
      </div>
      <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
        {rows.map(([label, value]) => (
          <div className="grid gap-1" key={label}>
            <dt className="text-xs font-semibold text-muted-foreground">{label}</dt>
            <dd className="m-0 break-words leading-6 text-foreground">{value}</dd>
          </div>
        ))}
      </dl>
    </motion.section>
  );
}

export default function DocumentRecommendationCarousel({ documents, emptyMessage }) {
  const reduceMotion = useReducedMotion();
  const rows = asList(documents);
  const keys = useMemo(() => rows.map(DocumentKey), [rows]);
  const [selectedKey, setSelectedKey] = useState(keys[0] || "");

  if (!rows.length) {
    return <div className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">{emptyMessage}</div>;
  }

  const activeKey = keys.includes(selectedKey) ? selectedKey : keys[0];
  const selectedIndex = Math.max(keys.indexOf(activeKey), 0);
  const selected = rows[selectedIndex];
  const card = (document, index) => (
    <DocumentCard
      document={document}
      selected={keys[index] === activeKey}
      onSelect={() => setSelectedKey(keys[index])}
    />
  );

  return (
    <div className="min-w-0">
      {rows.length === 1 ? card(rows[0], 0) : (
        <Carousel opts={{ align: "start", loop: false, duration: reduceMotion ? 0 : 25 }} className="px-1">
          <CarouselContent>
            {rows.map((document, index) => (
              <CarouselItem className="md:basis-1/2 xl:basis-1/3" key={keys[index]}>
                {card(document, index)}
              </CarouselItem>
            ))}
          </CarouselContent>
          <CarouselPrevious className="-top-11 right-10 bottom-auto left-auto" />
          <CarouselNext className="-top-11 right-0 bottom-auto left-auto" />
        </Carousel>
      )}
      <SelectedDocumentDetail document={selected} />
    </div>
  );
}
