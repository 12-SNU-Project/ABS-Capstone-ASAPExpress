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

function DetailText(value) {
  if (!value || typeof value !== "object") return clean(value);
  return clean(
    value.label_ko
    || value.label
    || value.text
    || value.title
    || value.code
    || value.href
    || value.url,
  );
}

function DetailList({ label, items }) {
  const values = asList(items).map(DetailText).filter(Boolean);
  if (!values.length) return null;
  return (
    <div className="grid gap-1">
      <dt className="text-sm font-semibold text-muted-foreground">{label}</dt>
      <dd className="m-0 text-base leading-7 text-foreground">
        <ul className="m-0 grid gap-1 pl-5">
          {values.map((value) => <li key={value}>{value}</li>)}
        </ul>
      </dd>
    </div>
  );
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
          <strong className="text-lg leading-7 text-foreground">{document.documentName}</strong>
          <p className="line-clamp-3 min-h-12 text-base leading-6 text-muted-foreground">
            {condition || "적용 조건과 준비 항목은 상세에서 확인합니다."}
          </p>
          <div className="mt-auto border-t pt-3 text-sm leading-6 text-muted-foreground">
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

function DocumentListItem({ document, index, selected, onSelect }) {
  const unresolvedCount = Number(document.unresolvedCount || 0);
  return (
    <button
      type="button"
      className={`grid w-full grid-cols-[auto_minmax(0,1fr)] gap-3 border-l-2 px-4 py-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset ${
        selected
          ? "border-l-primary bg-primary/5"
          : "border-l-transparent hover:bg-surface-muted"
      }`}
      aria-pressed={selected}
      onClick={onSelect}
    >
      <span className={`pt-0.5 text-sm font-semibold tabular-nums ${selected ? "text-primary" : "text-muted-foreground"}`}>
        {String(index + 1).padStart(2, "0")}
      </span>
      <span className="min-w-0">
        <span className="flex items-start justify-between gap-3">
          <strong className="text-base leading-6 text-foreground">{document.documentName}</strong>
          <Badge className="shrink-0" variant={document.requiredLevel === "필수" ? "default" : "secondary"}>
            {document.requiredLevel || "검토 대상"}
          </Badge>
        </span>
        <span className="mt-1 block text-sm leading-6 text-muted-foreground">
          {clean(document.preparedBy) || "준비 주체 확인 필요"}
          {unresolvedCount ? ` · 미해결 ${unresolvedCount}건` : ""}
        </span>
      </span>
    </button>
  );
}

function SelectedDocumentDetail({ document, className = "" }) {
  const reduceMotion = useReducedMotion();
  const sourceMetadata = document.sourceMetadata || {};
  const decisionRows = [
    ["적용 조건", clean(document.detail) || "별도 적용 조건 없음"],
    ["연결 수입요건", clean(document.groupName) || "기본 통관 준비서류"],
    ["추천 사유", clean(document.recommendationReason) || "기본 문서 요건에 따라 포함"],
  ];
  const preparationRows = [
    ["준비 주체", clean(document.preparedBy) || "추가 확인 필요"],
    ["제출 대상", clean(document.submittedTo) || "추가 확인 필요"],
    ["필수 기재 항목", asList(document.fields).join(", ") || "연결된 필드 정보 없음"],
  ];
  const officialLinks = asList(document.officialLinks)
    .map((item) => {
      const candidateHref = clean(item?.href || item?.url || item);
      return {
        label: DetailText(item),
        href: /^https?:\/\//i.test(candidateHref) ? candidateHref : "",
      };
    })
    .filter((item) => item.label);
  const hasEvidence = [
    document.requiredEvidence,
    document.regulations,
    document.celexReferences,
    document.verificationNotes,
  ].some((items) => asList(items).length)
    || Boolean(clean(sourceMetadata.documentCode))
    || officialLinks.length > 0;
  return (
    <motion.section
      key={DocumentKey(document, 0)}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: reduceMotion ? 0 : 0.18 }}
      className={`${className || "mt-4"} rounded-xl border bg-surface p-4 md:p-6`}
      aria-live="polite"
    >
      <div className="mb-6">
        <h3 className="m-0 text-xl font-semibold tracking-[-0.01em]">{document.documentName}</h3>
      </div>
      <div className="grid gap-5">
        <section>
          <h4 className="mb-4 border-l-2 border-primary pl-3 text-lg font-semibold">적용 판단</h4>
          <dl className="grid gap-y-4 text-base">
            {decisionRows.map(([label, value]) => (
              <div className="grid gap-1" key={label}>
                <dt className="text-sm font-semibold text-muted-foreground">{label}</dt>
                <dd className="m-0 break-words leading-7 text-foreground">{value}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section className="border-t pt-5">
          <h4 className="mb-4 border-l-2 border-primary pl-3 text-lg font-semibold">작성·제출</h4>
          <dl className="grid gap-x-6 gap-y-4 text-base sm:grid-cols-2">
            {preparationRows.map(([label, value]) => (
              <div className={`grid gap-1 ${label === "필수 기재 항목" ? "sm:col-span-2" : ""}`} key={label}>
                <dt className="text-sm font-semibold text-muted-foreground">{label}</dt>
                <dd className="m-0 break-words leading-7 text-foreground">{value}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section className="border-t pt-5">
          <h4 className="mb-4 border-l-2 border-primary pl-3 text-lg font-semibold">근거·검증</h4>
          <dl className="grid gap-y-4 text-base">
            <DetailList label="준비 근거" items={document.requiredEvidence} />
            <DetailList label="관련 규정" items={document.regulations} />
            <DetailList label="CELEX 참조" items={document.celexReferences} />
            <DetailList label="검증 메모" items={document.verificationNotes} />
            {clean(sourceMetadata.documentCode) ? (
              <div className="grid gap-1">
                <dt className="text-sm font-semibold text-muted-foreground">원본 문서 코드</dt>
                <dd className="m-0 break-words leading-7 text-foreground">{sourceMetadata.documentCode}</dd>
              </div>
            ) : null}
            {officialLinks.length ? (
              <div className="grid gap-1">
                <dt className="text-sm font-semibold text-muted-foreground">공식 출처</dt>
                <dd className="m-0 grid gap-1">
                  {officialLinks.map((link) => link.href ? (
                    <a
                      className="break-all text-primary underline-offset-4 hover:underline"
                      href={link.href}
                      key={`${link.href}_${link.label}`}
                      rel="noreferrer"
                      target="_blank"
                    >
                      {link.label}
                    </a>
                  ) : <span key={link.label}>{link.label}</span>)}
                </dd>
              </div>
            ) : null}
            {!hasEvidence ? (
              <div className="grid gap-1">
                <dt className="text-sm font-semibold text-muted-foreground">연결 상태</dt>
                <dd className="m-0 leading-7 text-muted-foreground">연결된 근거·검증 정보가 없습니다.</dd>
              </div>
            ) : null}
          </dl>
        </section>
      </div>
    </motion.section>
  );
}

export default function DocumentRecommendationCarousel({ documents, emptyMessage, layout = "carousel" }) {
  const reduceMotion = useReducedMotion();
  const rows = asList(documents);
  const keys = useMemo(() => rows.map(DocumentKey), [rows]);
  const [selectedKey, setSelectedKey] = useState(keys[0] || "");

  if (!rows.length) {
    return <div className="rounded-lg border border-dashed p-6 text-center text-base leading-6 text-muted-foreground">{emptyMessage}</div>;
  }

  const activeKey = keys.includes(selectedKey) ? selectedKey : keys[0];
  const selectedIndex = Math.max(keys.indexOf(activeKey), 0);
  const selected = rows[selectedIndex];
  if (layout === "navigator") {
    return (
      <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(260px,0.72fr)_minmax(0,1.28fr)]">
        <section className="min-w-0 overflow-hidden rounded-xl border bg-surface" aria-label="문서 목록">
          <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
            <strong className="text-base font-semibold">문서 목록</strong>
            <span className="text-sm font-semibold text-muted-foreground">{rows.length}건</span>
          </div>
          <div className="max-h-80 divide-y overflow-y-auto lg:max-h-[36rem]">
            {rows.map((document, index) => (
              <DocumentListItem
                document={document}
                index={index}
                key={keys[index]}
                selected={keys[index] === activeKey}
                onSelect={() => setSelectedKey(keys[index])}
              />
            ))}
          </div>
        </section>
        <SelectedDocumentDetail document={selected} className="mt-0" />
      </div>
    );
  }
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
