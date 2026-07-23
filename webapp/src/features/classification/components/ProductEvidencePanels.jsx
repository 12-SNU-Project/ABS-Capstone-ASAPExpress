import DataTable from "@/components/DataTable";
import { Database, ImageOff, ScanSearch, TriangleAlert } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { RECONSTRUCTION_KEYS, UnderstandingValueLabel } from "@/lib/labels.js";
import { asList, asObject, clean, labelFor } from "@/lib/format.js";
import { BuildImageEvidenceItems } from "@/features/classification/model/imageEvidenceAdapter.js";
import { NormalizeWarning } from "@/features/classification/model/warningViewModel.js";
import { EvidenceTerms, FactLabel } from "./EvidenceElements";

const INTENDED_USE_OPTIONS = [
  ["human consumption", "최종 소비용"],
  ["further processing", "추가 가공용"],
  ["animal feed", "동물 사료용"],
  ["non-food use", "비식품용"],
];

function ParseCompositionTerms(terms) {
  return asList(terms)
    .map((term) => {
      const text = clean(term);
      const splitAt = text.indexOf(":");
      return splitAt < 1
        ? { 구분: "", 내용: text }
        : { 구분: text.slice(0, splitAt).trim(), 내용: text.slice(splitAt + 1).trim() };
    })
    .filter((row) => row.내용);
}

function ReconstructionValueLabel(key, value) {
  const text = clean(value);
  if (key === "used_llm_reconstruction" && typeof value === "boolean") {
    return value ? "사용함" : "사용하지 않음";
  }
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
  const source = typeof value === "string" ? {} : asObject(value);
  const warning = clean(typeof value === "string" ? value : source.message || source.detail || source.warning || source.code);
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

function NormalizeReconstructionWarning(value, defaultSeverity) {
  const warning = NormalizeWarning(value, { defaultSeverity });
  if (!warning) return null;
  return { ...warning, message: ReconstructionWarningLabel(warning) };
}

export function ProductCollectionPanel({ result }) {
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
  const reconstructedFacts = asList(inputView.reconstructed_product_facts).map(MapFact);
  const unresolvedFacts = asList(inputView.unresolved_product_facts).map(MapFact);
  const reconstructionStatus = Object.fromEntries(
    Object.entries(asObject(inputView.reconstruction_status)).map(([key, value]) => [
      key,
      ReconstructionValueLabel(key, value),
    ]),
  );
  const conflicts = asList(inputView.product_fact_conflicts)
    .map((warning) => NormalizeReconstructionWarning(warning, "blocking"))
    .filter((warning, index, all) => (
      warning && all.findIndex((item) => item?.message === warning.message) === index
    ));
  const warnings = asList(inputView.warnings)
    .map((warning) => NormalizeReconstructionWarning(warning, "informational"))
    .filter((warning, index, all) => (
      warning && all.findIndex((item) => item?.message === warning.message) === index
    ));
  const normalizedWarnings = [...conflicts, ...warnings].filter((warning, index, all) => (
    all.findIndex((item) => item.message === warning.message) === index
  ));
  const blockingWarnings = normalizedWarnings.filter((warning) => warning.severity === "blocking");
  const reviewWarnings = normalizedWarnings.filter((warning) => warning.severity === "needs-review");
  const informationalWarnings = normalizedWarnings.filter((warning) => warning.severity === "informational");
  const collectedFacts = [
    ["상품명", pageProductFacts.product_name],
    [
      "상품 용도",
      INTENDED_USE_OPTIONS.find(([value]) => value === clean(pageProductFacts.intended_use))?.[1]
        || pageProductFacts.intended_use,
    ],
    ["상품 원산국", pageProductFacts.origin_country],
  ].filter(([, value]) => clean(value) !== "");

  const imageItems = BuildImageEvidenceItems(inputView);

  return (
    <div className="grid min-w-0 gap-4">
      <CollectionActivityPanel
        collectedFactCount={collectedFacts.length}
        reconstructedFactCount={reconstructedFacts.length}
        unresolvedFactCount={unresolvedFacts.length}
        status={reconstructionStatus.mode}
      />
      <EvidenceAcquisitionPanel items={imageItems} />
      <ExtractedFactsPanel
        collectedFacts={collectedFacts}
        description={pageProductFacts.description}
        reconstructedFacts={reconstructedFacts}
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(260px,0.75fr)_minmax(0,1.25fr)]">
        <ReconstructionStatusPanel
          status={reconstructionStatus}
          blockingWarnings={blockingWarnings}
          reviewWarnings={reviewWarnings}
          informationalWarnings={informationalWarnings}
        />
        <UnresolvedFactsPanel facts={unresolvedFacts} />
      </div>
    </div>
  );
}

function CollectionActivityPanel({ collectedFactCount, reconstructedFactCount, unresolvedFactCount, status }) {
  return (
    <Card className="gap-0 shadow-[var(--shadow-surface)]">
      <CardHeader className="border-b">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle>상품 정보 수집</CardTitle>
            <CardDescription>페이지 수집, OCR/VLM 근거 복원과 사실 검증 결과입니다.</CardDescription>
          </div>
          <Badge variant="secondary">{clean(status) ? ReconstructionValueLabel("mode", status) : "수집 상태 확인 중"}</Badge>
        </div>
      </CardHeader>
      <CardContent className="grid grid-cols-3 divide-x p-0">
        {[
          ["기본 정보", collectedFactCount],
          ["복원 Facts", reconstructedFactCount],
          ["미해결", unresolvedFactCount],
        ].map(([label, count]) => (
          <div className="px-4 py-3" key={label}>
            <span className="block text-xs text-muted-foreground">{label}</span>
            <strong className="mt-1 block text-xl tabular-nums">{count}</strong>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function EvidenceAcquisitionPanel({ items }) {
  return (
    <Card className="gap-0 shadow-[var(--shadow-surface)]">
      <CardHeader className="border-b">
        <div className="flex items-center gap-2">
          <ScanSearch className="size-4 text-primary" aria-hidden="true" />
          <CardTitle>이미지 근거 처리</CardTitle>
        </div>
        <CardDescription>수집 이미지의 OCR/VLM 처리 상태를 표시하는 영역입니다.</CardDescription>
      </CardHeader>
      <CardContent className="py-5">
        {items.length ? (
          <div className="text-sm text-muted-foreground">이미지 상태 계약이 연결되었습니다.</div>
        ) : (
          <div className="flex items-start gap-3 rounded-lg border border-dashed bg-surface-muted/50 p-4">
            <ImageOff className="mt-0.5 size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
            <div>
              <strong className="text-sm">이미지별 처리 상태가 snapshot에 제공되지 않습니다.</strong>
              <p className="mt-1 mb-0 text-xs leading-5 text-muted-foreground">집계 결과와 복원 Facts는 표시하지만, 이미지 URL과 단계별 상태가 없어 애니메이션 Stack은 생성하지 않습니다.</p>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ExtractedFactsPanel({ collectedFacts, description, reconstructedFacts }) {
  return (
    <Card className="gap-0 shadow-[var(--shadow-surface)]">
      <CardHeader className="border-b">
        <div className="flex items-center gap-2"><Database className="size-4 text-primary" /><CardTitle>수집·복원 Facts</CardTitle></div>
        <CardDescription>수집된 기본 정보와 구조화된 근거를 한 영역에서 검토합니다.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-5 py-4">
        <div className="divide-y rounded-lg border">
          {collectedFacts.length ? collectedFacts.map(([label, value]) => (
            <div className="grid grid-cols-[110px_minmax(0,1fr)] gap-4 px-3 py-2.5" key={label}>
              <span className="text-xs font-medium text-muted-foreground">{label}</span>
              <strong className="text-sm font-medium">{clean(value)}</strong>
            </div>
          )) : <p className="m-0 px-3 py-4 text-sm text-muted-foreground">수집된 기본 정보가 없습니다.</p>}
          {clean(description) ? (
            <div className="grid grid-cols-[110px_minmax(0,1fr)] gap-4 px-3 py-2.5">
              <span className="text-xs font-medium text-muted-foreground">상품 설명</span>
              <p className="m-0 text-sm leading-6">{clean(description)}</p>
            </div>
          ) : null}
        </div>
        <div>
          <div className="mb-2 flex items-center justify-between gap-2">
            <h3 className="m-0 text-sm font-semibold">복원 Facts 표</h3>
            <Badge variant="outline">{reconstructedFacts.length}건</Badge>
          </div>
          <DataTable
            rows={reconstructedFacts}
            limit={30}
            className="cjs-reconstruction-table"
            emptyMessage="복원된 구조화 fact가 없습니다."
            columns={[
              { key: "field_name", label: "필드", variant: "mono" },
              { key: "normalized_value", label: "값" },
              { key: "source_refs", label: "출처", variant: "mono" },
              { key: "validation_status", label: "상태", variant: "pill" },
            ]}
          />
        </div>
      </CardContent>
    </Card>
  );
}

function ReconstructionStatusPanel({ status, blockingWarnings, reviewWarnings, informationalWarnings }) {
  const entries = RECONSTRUCTION_KEYS
    .filter((key) => status[key] !== undefined && clean(status[key]) !== "")
    .map((key) => [labelFor(key), status[key]]);
  return (
    <Card className="gap-0 shadow-[var(--shadow-surface)]">
      <CardHeader className="border-b"><CardTitle>입력 복원 상태</CardTitle></CardHeader>
      <CardContent className="grid gap-3 py-4">
        <div className="divide-y">
          {entries.map(([label, value]) => (
            <div className="grid grid-cols-[minmax(100px,0.8fr)_minmax(0,1.2fr)] gap-3 py-2" key={label}>
              <span className="text-xs text-muted-foreground">{label}</span>
              <strong className="break-words text-xs font-medium">{clean(value)}</strong>
            </div>
          ))}
        </div>
        <WarningGroup title="처리 차단" tone="blocking" items={blockingWarnings} />
        <WarningGroup title="검토 필요" tone="review" items={reviewWarnings} />
        <WarningGroup title="참고" tone="info" items={informationalWarnings} />
      </CardContent>
    </Card>
  );
}

function WarningGroup({ title, tone, items }) {
  if (!items.length) return null;
  const className = tone === "blocking"
    ? "border-destructive/30 bg-destructive/5"
    : tone === "review"
      ? "border-needs-review/30 bg-needs-review/5"
      : "bg-surface-muted";
  return (
    <Alert className={className}>
      <TriangleAlert className="size-4" />
      <AlertTitle>{title} · {items.length}건</AlertTitle>
      <AlertDescription><ul className="m-0 grid gap-1 pl-4">{items.slice(0, 8).map((item) => <li key={`${item.code}_${item.message}`}>{item.message}</li>)}</ul></AlertDescription>
    </Alert>
  );
}

function UnresolvedFactsPanel({ facts }) {
  return (
    <Card className="gap-0 shadow-[var(--shadow-surface)]">
      <CardHeader className="border-b">
        <div className="flex items-center justify-between gap-2"><CardTitle>확정하지 못한 Facts</CardTitle><Badge variant="outline">{facts.length}건</Badge></div>
        <CardDescription>근거가 부족하거나 검증을 통과하지 못해 분류 입력으로 확정하지 않은 항목입니다.</CardDescription>
      </CardHeader>
      <CardContent className="py-4">
        <DataTable
          rows={facts}
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
      </CardContent>
    </Card>
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
  if (!rows.length && !clean(evidence.error)) return null;
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

export function ProductUnderstandingPanel({ result }) {
  const understandingView = asObject(result?.product_understanding_view);
  const hints = asObject(understandingView.identity_hints);
  const composition = asObject(understandingView.composition_facts);
  const compositionRows = ParseCompositionTerms(composition.composition_terms);
  const percentages = asList(composition.ingredient_percentages);
  const HasValue = (value) => !["", "unknown", "other"].includes(clean(value).toLowerCase());
  const reportedMissing = [
    ...asList(understandingView.unknowns),
    ...asList(composition.missing_composition_facts),
  ].map(FactLabel);
  const reviewReasons = [
    ...reportedMissing,
    ...(!clean(composition.principal_ingredient) && !reportedMissing.includes("주원료") ? ["주원료"] : []),
    ...(!percentages.length && !reportedMissing.includes("성분별 함유율") ? ["성분별 함유율"] : []),
  ].map(clean).filter((item, index, all) => item && all.indexOf(item) === index);
  const modeLabel = {
    llm_json: "AI 기반 구조화",
    llm_fallback: "규칙 기반 보완",
    regex_fallback: "규칙 기반",
  }[clean(hints.understanding_mode)] || "기타 방식";
  const ingredientClasses = asList(composition.ingredient_classes).length
    ? asList(composition.ingredient_classes)
    : [hints.ingredient_class];
  const ingredientClassLabel = ingredientClasses
    .filter(HasValue)
    .map(UnderstandingValueLabel)
    .filter((value, index, all) => value && all.indexOf(value) === index)
    .join(" · ");
  const intendedUse = clean(hints.intended_use);
  const intendedUseLabel = INTENDED_USE_OPTIONS.find(([value]) => value === intendedUse)?.[1]
    || (HasValue(intendedUse) ? intendedUse : "");
  const processingState = HasValue(composition.processing_state)
    ? composition.processing_state
    : hints.processing_state;
  const facts = [
    ["원재료 계열", ingredientClassLabel],
    ["상품 형태", HasValue(hints.food_form) ? UnderstandingValueLabel(hints.food_form) : ""],
    ["가공·보존 상태", UnderstandingValueLabel(processingState)],
    ["상품 용도", intendedUseLabel],
  ].filter(([, value]) => HasValue(value));
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
          {showNormalizedDescription ? <p>분류용 상품 설명: {normalizedDescription}</p> : null}
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
          {HasValue(hints.translated_product_name) ? (
            <><span>영문 상품명</span><strong>{clean(hints.translated_product_name)}</strong></>
          ) : null}
        </div>
        <EvidenceTerms label="상품 정체 어휘" terms={hints.identity_terms} />
        <EvidenceTerms label="형태·가공 어휘" terms={hints.product_form_terms} />
        <CoiEvidenceBlock coi={understandingView.coi_evidence} />
      </details>
    </div>
  );
}
