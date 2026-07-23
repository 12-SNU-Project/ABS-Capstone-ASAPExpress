import { useMemo, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Carousel,
  CarouselContent,
  CarouselItem,
  CarouselNext,
  CarouselPrevious,
} from "@/components/ui/carousel";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import DocumentFlowSidebar from "@/features/documents/components/DocumentFlowSidebar";
import DocumentRecommendationCarousel from "@/features/documents/components/DocumentRecommendationCarousel";
import { asList, asObject, clean } from "@/lib/format.js";
import {
  DUTY_UNIT_LABELS,
  FLOW_KEYS,
  FLOW_ITEMS,
  REQUIREMENT_VIEW_KEYS,
  stripListMarker,
  buildEvidenceSourceGroups,
  unique,
  isRequiredLevel,
  dutyPriorityCount,
  buildDutyBranches,
  buildPreArrivalModel,
  BuildDocumentPackageViewModel,
} from "../model/documentPackageViewModel.js";

function EmptyBlock({ message }) {
  return <div className="rounded-lg border border-dashed p-6 text-center text-base leading-6 text-muted-foreground">{message}</div>;
}

function FlowPanel({ title, description, children }) {
  return (
    <section className="min-w-0 rounded-xl border bg-surface p-5 shadow-[var(--shadow-surface)] sm:p-6">
      <div className="mb-6 border-b pb-5">
        <h2 className="m-0 text-xl font-semibold tracking-[-0.01em] text-foreground">{title}</h2>
        {description ? <p className="mt-2 mb-0 max-w-4xl text-base leading-7 text-muted-foreground">{description}</p> : null}
      </div>
      {children}
    </section>
  );
}

function BranchCard({ title, value, description, tone = "default" }) {
  return (
    <article className={`ddv-branch-card ${tone}`}>
      <span>{title}</span>
      <strong>{value || "-"}</strong>
      {description ? <p>{description}</p> : null}
    </article>
  );
}

function UnitLegend({ unitCodes }) {
  const units = unique(unitCodes).filter((unit) => DUTY_UNIT_LABELS[unit]);
  if (!units.length) {
    return null;
  }
  return (
    <div className="ddv-duty-units">
      <span>단위</span>
      {units.map((unit) => (
        <em key={unit}>{unit} = {DUTY_UNIT_LABELS[unit]}</em>
      ))}
    </div>
  );
}

function DutyPriorityCard({ row, tone = "default" }) {
  const badges = [
    row.measureCode ? `Measure ${row.measureCode}` : "",
  ].filter(Boolean);
  const hasBranches = row.branches.length > 0;
  return (
    <article className={`ddv-branch-card ${tone}`}>
      <span>{row.measure || "세율"}</span>
      <strong>{hasBranches ? `조건 분기 ${row.branches.length}개` : row.rate || "-"}</strong>
      <div className="ddv-duty-badges">
        {badges.map((badge) => <em key={badge}>{badge}</em>)}
      </div>
      {hasBranches ? (
        <div className="ddv-duty-branches">
          {row.branches.map((branch, index) => (
            <div className="ddv-duty-branch-row" key={`${branch.expression}_${branch.rate}_${index}`}>
              <span>{branch.expression || branch.condition || "조건"}</span>
              <strong>{branch.rate}</strong>
            </div>
          ))}
        </div>
      ) : row.condition ? <p>{row.condition}</p> : null}
      {row.legalBase ? <small>{row.legalBase}</small> : null}
      <UnitLegend unitCodes={row.unitCodes} />
    </article>
  );
}

function DutyPrioritySection({ title, description, rows, tone }) {
  return (
    <section className="ddv-duty-priority-section">
      <div className="ddv-duty-priority-head">
        <strong>{title}</strong>
        <span>{description}</span>
      </div>
      {rows.length ? (
        <div className="ddv-duty-priority-grid">
          {rows.map((row, index) => (
            <DutyPriorityCard
              key={`${row.bucket}_${row.measureCode}_${row.sourceCode}_${row.rate}_${row.condition}_${index}`}
              row={row}
              tone={tone}
            />
          ))}
        </div>
      ) : (
        <EmptyBlock message="해당 세율 후보가 없습니다." />
      )}
    </section>
  );
}

function DutyBranchView({ priority, rows }) {
  const priorityCount = dutyPriorityCount(priority);
  if (priorityCount) {
    return (
      <div className="ddv-duty-priority-flow">
        <DutyPrioritySection
          title="1. FTA / 특혜세율"
          description="한국 원산지 요건과 특혜 증빙을 충족할 때 우선 확인합니다."
          rows={priority.fta}
          tone="success"
        />
        <div className="ddv-duty-arrow">다음 확인</div>
        <DutyPrioritySection
          title="2. Suspension / Quota / End-use"
          description="쿼터, suspension, end-use처럼 별도 적용 요건이 있는 세율 후보입니다."
          rows={priority.conditional}
          tone="conditional"
        />
        <div className="ddv-duty-arrow">적용 불가 시</div>
        <DutyPrioritySection
          title="3. 기본세율"
          description="위 조건을 적용하지 못하는 경우 확인하는 MFN 또는 비특혜 세율입니다."
          rows={priority.basic}
        />
      </div>
    );
  }
  const { fta, basic, conditional } = buildDutyBranches(rows);
  if (!fta && !basic && !conditional.length) {
    return <EmptyBlock message="표시할 세율 정보가 없습니다." />;
  }
  return (
    <div className="ddv-duty-flow">
      <BranchCard
        title="FTA 특혜 적용"
        value={fta?.rate || "-"}
        description={fta?.condition || "원산지 증빙 또는 FTA 원산지 요건 충족 시"}
        tone="success"
      />
      <div className="ddv-duty-arrow">또는</div>
      <BranchCard
        title="기본세율"
        value={basic?.rate || "-"}
        description={basic?.condition || "FTA/특혜 요건을 적용하지 않는 경우"}
      />
      {conditional.length ? (
        <>
          <div className="ddv-duty-split">기타 세율</div>
          <div className="ddv-duty-conditions">
            {conditional.map((row) => (
              <BranchCard
                key={`${row.measure}_${row.rate}_${row.condition}`}
                title={row.measure || "조건부"}
                value={row.rate}
                description={row.condition || row.origin}
                tone="conditional"
              />
            ))}
          </div>
        </>
      ) : null}
    </div>
  );
}

function RequirementViewSwitch({ activeView, onChange }) {
  return (
    <Tabs value={activeView} onValueChange={onChange}>
      <TabsList className="mb-4">
        <TabsTrigger value={REQUIREMENT_VIEW_KEYS.EXPORTER}>수출자 가이드</TabsTrigger>
        <TabsTrigger value={REQUIREMENT_VIEW_KEYS.BROKER}>관세사 검토</TabsTrigger>
      </TabsList>
    </Tabs>
  );
}

function GuidanceSection({ title, items, ordered = false }) {
  const reduceMotion = useReducedMotion();
  const rows = unique(items);
  if (!rows.length) {
    return null;
  }
  if (ordered) {
    return (
      <div className="ddv-guidance-section">
        <strong>{title}</strong>
        <ol className="ddv-guidance-step-list">
          {rows.map((item, index) => (
            <motion.li
              className="ddv-guidance-step"
              initial={reduceMotion ? false : { opacity: 0, x: 14 }}
              key={item}
              transition={{
                duration: reduceMotion ? 0 : 0.24,
                delay: reduceMotion ? 0 : Math.min(index * 0.05, 0.2),
                ease: [0.22, 1, 0.36, 1],
              }}
              viewport={{ once: true, amount: 0.55 }}
              whileHover={reduceMotion ? undefined : {
                x: 4,
                transition: { duration: 0.18, delay: 0, ease: "easeOut" },
              }}
              whileInView={{ opacity: 1, x: 0 }}
            >
              <span className="ddv-guidance-step-number">{String(index + 1).padStart(2, "0")}</span>
              <span>{stripListMarker(item)}</span>
            </motion.li>
          ))}
        </ol>
      </div>
    );
  }
  return (
    <div className="ddv-guidance-section">
      <strong>{title}</strong>
      <ul>
        {rows.map((item) => <li key={item}>{item}</li>)}
      </ul>
    </div>
  );
}

function ExporterRequirementCard({ group }) {
  const summaryItems = group.summaries?.length ? group.summaries : group.exporterGuidance;
  const fallbackItems = !group.actionSteps?.length && !group.requiredEvidenceItems?.length
    ? group.verificationDetails
    : [];
  return (
    <article className="ddv-procedure-card exporter w-full">
      <div className="ddv-procedure-card-head">
        <strong>{group.groupName}</strong>
        <span>{group.codes.length ? `${group.codes.length} codes` : group.a2mCode || "guideline"}</span>
      </div>
      <div className="ddv-group-guidance">
        {summaryItems.length ? (
          summaryItems.map((item) => <p key={item}>{item}</p>)
        ) : (
          <p>이 TARIC 수입요건 묶음의 적용 여부를 먼저 확인하고, 연결된 certificate/declaration code와 footnote를 기준으로 세부 신고 경로를 검토합니다.</p>
        )}
        <GuidanceSection title="진행 순서" items={group.actionSteps} ordered />
        <GuidanceSection title="준비 자료" items={group.requiredEvidenceItems} />
        {fallbackItems.length ? (
          <div className="ddv-guidance-checkpoints">
            <strong>확인할 사항</strong>
            <ul>
              {fallbackItems.map((item) => <li key={item}>{item}</li>)}
            </ul>
          </div>
        ) : null}
      </div>
    </article>
  );
}

function BrokerEvidenceList({ items, emptyMessage }) {
  const rows = unique(items);
  if (!rows.length) {
    return emptyMessage ? <EmptyBlock message={emptyMessage} /> : null;
  }
  return (
    <ul className="ddv-evidence-list">
      {rows.map((item) => <li key={item}>{item}</li>)}
    </ul>
  );
}

function BrokerRequirementCard({ group }) {
  const regulationItems = unique([
    ...asList(group.legalBases),
    ...asList(group.regulationReferences),
    ...asList(group.celexIds).map((id) => `CELEX ${id}`),
  ]);
  const evidenceSources = buildEvidenceSourceGroups(group, regulationItems);
  return (
    <article className="ddv-procedure-card broker">
      <div className="ddv-procedure-card-head">
        <strong>{group.groupName}</strong>
        <span>human review</span>
      </div>
      <div className="ddv-review-grid">
        <div>
          <span>Measure</span>
          <strong>{group.measureTypes.join(", ") || "-"}</strong>
        </div>
        <div>
          <span>Source TARIC/CN</span>
          <strong>{group.sourceCodes.join(", ") || "-"}</strong>
        </div>
        <div>
          <span>Legal base</span>
          <strong>{group.legalBases.join(", ") || "-"}</strong>
        </div>
      </div>

      {group.codes.length ? (
        <div className="ddv-broker-section">
          <h3>Certificate / declaration code</h3>
          <div className="ddv-cert-list">
            {group.codes.map((code) => (
              <div className="ddv-cert-row" key={`${group.groupName}_broker_${code.code}`}>
                <span>{code.code}</span>
                <div>
                  <strong>{code.title}</strong>
                  {code.description ? <p>{code.description}</p> : null}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {group.sourceType === "taric" || group.footnoteGuidelines.length ? (
        <div className="ddv-broker-section">
          <h3>Group footnote 확인</h3>
          {group.footnoteGuidelines.length ? (
            <div className="ddv-footnote-guidelines broker">
              {group.footnoteGuidelines.map((guideline) => (
                <div className="ddv-footnote-guide" key={`${group.groupName}_broker_${guideline.footnoteCode}`}>
                  <span>{guideline.footnoteCode}</span>
                  <div>
                    {guideline.footnoteDescription ? <p>{guideline.footnoteDescription}</p> : null}
                    {guideline.summary ? <p>{guideline.summary}</p> : null}
                    {guideline.importerCheck ? <p>{guideline.importerCheck}</p> : null}
                    {guideline.legalReference ? <em>{guideline.legalReference}</em> : null}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <EmptyBlock message="연결된 TARIC footnote가 없습니다." />
          )}
        </div>
      ) : null}

      <div className="ddv-broker-section">
        <h3>검토 포인트</h3>
        {group.brokerReview?.length ? (
          <div className="ddv-broker-review-list">
            {group.brokerReview.map((item) => <p key={item}>{item.replace(/^[-•]\s*/, "")}</p>)}
          </div>
        ) : null}
      </div>

      <div className="ddv-broker-section">
        <h3>근거 및 확인처</h3>
        <div className="ddv-source-grid">
          {evidenceSources.sections.length ? (
            <div className="ddv-source-section-list">
              <strong>원문 섹션</strong>
              <BrokerEvidenceList items={evidenceSources.sections} />
            </div>
          ) : null}
          {evidenceSources.regulations.length ? (
            <div className="ddv-source-section-list">
              <strong>규정/CELEX</strong>
              <BrokerEvidenceList items={evidenceSources.regulations} />
            </div>
          ) : null}
          {evidenceSources.systems.length ? (
            <div className="ddv-source-section-list">
              <strong>시스템/기관</strong>
              <BrokerEvidenceList items={evidenceSources.systems} />
            </div>
          ) : null}
          {evidenceSources.other.length ? (
            <div className="ddv-source-section-list">
              <strong>기타 확인자료</strong>
              <BrokerEvidenceList items={evidenceSources.other} />
            </div>
          ) : null}
        </div>
        {!evidenceSources.sections.length
          && !evidenceSources.regulations.length
          && !evidenceSources.systems.length
          && !evidenceSources.other.length ? (
            <EmptyBlock message="연결된 Regulation, CELEX 또는 확인처가 없습니다." />
          ) : null}
      </div>

    </article>
  );
}

function CertificateGroupCards({ groups }) {
  const [activeView, setActiveView] = useState(REQUIREMENT_VIEW_KEYS.EXPORTER);
  if (!groups.length) {
    return <EmptyBlock message="한국 적용 TARIC certificate/declaration 코드가 없습니다." />;
  }
  return (
    <>
      <RequirementViewSwitch activeView={activeView} onChange={setActiveView} />
      {activeView === REQUIREMENT_VIEW_KEYS.EXPORTER ? (
        groups.length === 1 ? (
          <ExporterRequirementCard group={groups[0]} />
        ) : (
          <Carousel className="pb-12" opts={{ align: "start", loop: false }} aria-label="수출자 준비자료 그룹">
            <CarouselContent className="items-stretch">
              {groups.map((group) => (
                <CarouselItem className="flex" key={group.groupName}>
                  <ExporterRequirementCard group={group} />
                </CarouselItem>
              ))}
            </CarouselContent>
            <CarouselPrevious className="top-auto right-12 bottom-0 left-auto my-0" aria-label="이전 준비자료 그룹" />
            <CarouselNext className="top-auto right-4 bottom-0 my-0" aria-label="다음 준비자료 그룹" />
          </Carousel>
        )
      ) : (
        <div className="ddv-requirement-list">
          {groups.map((group) => (
            <BrokerRequirementCard group={group} key={group.groupName} />
          ))}
        </div>
      )}
    </>
  );
}

function RequirementDocumentLabels(row, mode) {
  return unique(asList(row.preparationItemRows)
    .map((item) => asObject(item))
    .filter((item) => clean(item.item_type) === "document" && clean(item.recommendation_mode) === mode)
    .map((item) => clean(item.item_name_ko || item.baseline_document_id))
    .filter(Boolean));
}

function PreArrivalRequirementDetail({ row }) {
  const summaryItems = asList(row.summaries?.length ? row.summaries : row.exporterGuidance);
  const alwaysDocuments = RequirementDocumentLabels(row, "always_required_document");
  const conditionalDocuments = RequirementDocumentLabels(row, "conditional_required_document");
  const checkItems = asList(row.checkItems);

  return (
    <div className="grid gap-5 px-4 pb-6">
      <section>
        <h4 className="mb-2 text-sm font-semibold text-muted-foreground">적용 판단 요약</h4>
        <div className="grid gap-2">
          {summaryItems.length ? summaryItems.slice(0, 2).map((item) => (
            <p className="m-0 text-base leading-7 text-foreground" key={item}>{item}</p>
          )) : (
            <p className="m-0 text-base leading-7 text-muted-foreground">연결된 판단 요약이 없습니다.</p>
          )}
        </div>
      </section>

      {alwaysDocuments.length ? (
        <section className="border-t pt-5">
          <h4 className="mb-2 text-sm font-semibold text-muted-foreground">요건 공통 준비 서류</h4>
          <p className="m-0 text-base leading-7 text-foreground">{alwaysDocuments.join(", ")}</p>
        </section>
      ) : null}

      {conditionalDocuments.length ? (
        <section className="border-t pt-5">
          <h4 className="mb-2 text-sm font-semibold text-muted-foreground">조건 충족 시 추가 서류</h4>
          <p className="m-0 text-base leading-7 text-needs-review">{conditionalDocuments.join(", ")}</p>
        </section>
      ) : null}

      {checkItems.length ? (
        <section className="border-t pt-5">
          <h4 className="mb-3 text-sm font-semibold text-muted-foreground">확인·보관 사항</h4>
          <ul className="m-0 grid gap-3 pl-5">
            {checkItems.map((item) => (
              <li className="text-base leading-7" key={`${row.key}_${item.mode}_${item.label}_${item.detail}`}>
                <strong className="block font-semibold text-foreground">{item.label}</strong>
                {item.detail && item.detail !== item.label ? (
                  <span className="block text-muted-foreground">{item.detail}</span>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

function PreArrivalCards({ model, onToggle }) {
  const rows = asList(model.groups);
  const [selectedRequirementKey, setSelectedRequirementKey] = useState("");
  const selectedRequirement = rows.find((row) => row.key === selectedRequirementKey);
  const selectedRequirementIndex = rows.findIndex((row) => row.key === selectedRequirementKey);
  const selectedConditionalDocuments = useMemo(() => {
    const documents = new Map();
    rows.filter((row) => row.applies).forEach((row) => {
      RequirementDocumentLabels(row, "conditional_required_document").forEach((label) => {
        const current = documents.get(label) || { label, groupKeys: [], groupNames: [] };
        if (!current.groupKeys.includes(row.key)) current.groupKeys.push(row.key);
        if (!current.groupNames.includes(row.groupName)) current.groupNames.push(row.groupName);
        documents.set(label, current);
      });
    });
    return Array.from(documents.values());
  }, [rows]);
  return (
    <div className="grid min-w-0 gap-6">
      <section className="rounded-xl border bg-surface-muted p-4 md:p-5">
        <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
          <div>
            <strong className="text-lg font-semibold">조건부 요건 해당 여부</strong>
            <p className="mt-1 mb-0 text-base leading-6 text-muted-foreground">해당하는 조건만 선택하고, 요건별 공통·추가 준비 서류는 상세에서 확인합니다.</p>
          </div>
          <span className="text-base font-semibold text-muted-foreground">{rows.length}개 요건</span>
        </div>
        {rows.length ? (
          <div className="grid gap-x-6 md:grid-cols-2">
            {rows.map((row, index) => {
              const checkboxId = `pre-arrival-requirement-${index}`;
              return (
                <div className={`flex min-w-0 items-start gap-3 border-t px-1 py-3 ${row.applies ? "bg-primary/5" : ""}`} key={row.key}>
                  <Checkbox
                    className="mt-0.5"
                    id={checkboxId}
                    checked={row.applies}
                    onCheckedChange={(checked) => onToggle(row.key, checked === true)}
                  />
                  <label className="min-w-0 flex-1 cursor-pointer text-base font-semibold leading-6" htmlFor={checkboxId}>
                    {row.groupName}
                  </label>
                  <button
                    type="button"
                    className="shrink-0 text-sm font-semibold text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    onClick={() => setSelectedRequirementKey(row.key)}
                  >
                    내용 보기
                  </button>
                </div>
              );
            })}
          </div>
        ) : (
          <EmptyBlock message="추가로 판정할 조건부 수입요건이 없습니다. 기본 필수 서류는 아래에서 계속 확인할 수 있습니다." />
        )}
      </section>

      <Dialog
        open={Boolean(selectedRequirement)}
        onOpenChange={(open) => {
          if (!open) setSelectedRequirementKey("");
        }}
      >
        <DialogContent>
          {selectedRequirement ? (
            <>
              <DialogHeader className="border-b pr-14">
                <DialogTitle className="text-xl font-semibold">{selectedRequirement.groupName}</DialogTitle>
                <DialogDescription>
                  수입요건 {String(selectedRequirementIndex + 1).padStart(2, "0")} / {String(rows.length).padStart(2, "0")}
                  {" · "}
                  {selectedRequirement.applies ? "조건부 적용 선택됨" : "조건부 미선택"}
                </DialogDescription>
              </DialogHeader>
              <PreArrivalRequirementDetail row={selectedRequirement} />
            </>
          ) : null}
        </DialogContent>
      </Dialog>

      <section className="min-w-0 rounded-xl border bg-surface p-4 md:p-5">
        <div className="mb-4 flex items-center justify-between gap-3">
          <strong className="text-lg font-semibold">이번 선택으로 추가된 조건부 서류</strong>
          <span className="text-base font-semibold text-muted-foreground">{selectedConditionalDocuments.length}건</span>
        </div>
        {selectedConditionalDocuments.length ? (
          <ul className="m-0 grid gap-x-6 p-0 md:grid-cols-2">
            {selectedConditionalDocuments.map((document) => (
              <li className="grid list-none gap-1 border-t py-3" key={document.label}>
                <strong className="text-base font-semibold text-foreground">{document.label}</strong>
                <span className="text-sm leading-6 text-muted-foreground">
                  연결 요건 · {document.groupNames.join(", ")}
                </span>
                <button
                  type="button"
                  className="mt-1 w-fit text-sm font-semibold text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  onClick={() => setSelectedRequirementKey(document.groupKeys[0])}
                >
                  요건 내용 보기
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="m-0 text-base leading-7 text-muted-foreground">현재 선택으로 새로 추가된 조건부 서류가 없습니다.</p>
        )}
      </section>
    </div>
  );
}

export default function DocumentPackageWorkspace({ packageData }) {
  const [activeFlow, setActiveFlow] = useState(FLOW_KEYS.REQUIREMENTS);
  const [requirementChecksByPackage, setRequirementChecksByPackage] = useState({});
  const pkg = asObject(packageData);
  const packageKey = clean(pkg.document_package_id || pkg.taric10) || "document-package";
  const requirementChecks = requirementChecksByPackage[packageKey] || {};
  const reduceMotion = useReducedMotion();

  const viewModel = useMemo(() => BuildDocumentPackageViewModel(pkg), [pkg]);
  const requiredBaselineRows = useMemo(
    () => viewModel.baselineRows.filter((row) => isRequiredLevel(row.requiredLevelRaw)),
    [viewModel.baselineRows],
  );

  const preArrivalModel = useMemo(
    () => buildPreArrivalModel(viewModel.baselineRows, viewModel.requirementGroups, requirementChecks),
    [viewModel.baselineRows, viewModel.requirementGroups, requirementChecks],
  );

  function handleRequirementToggle(key, checked) {
    setRequirementChecksByPackage((current) => ({
      ...current,
      [packageKey]: {
        ...current[packageKey],
        [key]: checked,
      },
    }));
  }

  if (!Object.keys(pkg).length) {
    return <EmptyBlock message="문서 패키지 데이터가 없습니다." />;
  }

  const counts = {
    [FLOW_KEYS.REQUIREMENTS]: viewModel.requirementGroups.length,
    [FLOW_KEYS.DUTY]: dutyPriorityCount(viewModel.dutyPriority) || viewModel.dutyRows.length,
    [FLOW_KEYS.BASELINE]: requiredBaselineRows.length,
    [FLOW_KEYS.PRE_ARRIVAL]: preArrivalModel.groups.length,
  };
  const activeItem = FLOW_ITEMS.find((item) => item.key === activeFlow) || FLOW_ITEMS[0];

  return (
    <div className="grid min-w-0 gap-5 md:grid-cols-[232px_minmax(0,1fr)]">
      <DocumentFlowSidebar activeKey={activeFlow} counts={counts} onSelect={setActiveFlow} />
      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          className="min-w-0"
          key={activeFlow}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: reduceMotion ? 0 : 0.18, ease: "easeOut" }}
        >
        {activeFlow === FLOW_KEYS.REQUIREMENTS ? (
        <FlowPanel
          title={activeItem.title}
          description="선택한 TARIC10에 연결된 EU 수입요건과 제출·신고 조건을 묶어 확인합니다."
        >
          <CertificateGroupCards groups={viewModel.requirementGroups} />
        </FlowPanel>
      ) : null}

      {activeFlow === FLOW_KEYS.DUTY ? (
        <FlowPanel
          title={activeItem.title}
          description="FTA 특혜세율, 관세 유예·할당·특정 용도 조건, 기본세율 순서로 적용 가능성을 확인합니다."
        >
          <DutyBranchView priority={viewModel.dutyPriority} rows={viewModel.dutyRows} />
        </FlowPanel>
      ) : null}

        {activeFlow === FLOW_KEYS.BASELINE ? (
        <FlowPanel
          title={activeItem.title}
          description="기본 필수 통관서류만 표시합니다. 조건부 서류와 요건별 준비자료는 입항 전 단계에서 확인합니다."
        >
          <DocumentRecommendationCarousel
            documents={requiredBaselineRows}
            emptyMessage="표시할 기본 통관 서류가 없습니다."
            layout="navigator"
          />
        </FlowPanel>
      ) : null}

        {activeFlow === FLOW_KEYS.PRE_ARRIVAL ? (
        <FlowPanel
          title={activeItem.title}
          description="조건부 요건 해당 여부를 선택하고, 선택으로 추가되는 문서와 준비 근거를 확인합니다."
        >
          <PreArrivalCards model={preArrivalModel} onToggle={handleRequirementToggle} />
        </FlowPanel>
        ) : null}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}
