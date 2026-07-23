import { useMemo, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { Checkbox } from "@/components/ui/checkbox";
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
  dutyPriorityCount,
  buildDutyBranches,
  buildPreArrivalModel,
  BuildDocumentPackageViewModel,
} from "../model/documentPackageViewModel.js";

function EmptyBlock({ message }) {
  return <div className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">{message}</div>;
}

function FlowPanel({ title, description, children }) {
  return (
    <section className="min-w-0 rounded-xl border bg-surface p-4 shadow-[var(--shadow-surface)] sm:p-6">
      <div className="mb-5 border-b pb-4">
        <h2 className="m-0 text-lg font-semibold text-foreground">{title}</h2>
        {description ? <p className="mt-1.5 mb-0 max-w-3xl text-sm leading-6 text-muted-foreground">{description}</p> : null}
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
  const rows = unique(items);
  if (!rows.length) {
    return null;
  }
  const ListTag = ordered ? "ol" : "ul";
  return (
    <div className="ddv-guidance-section">
      <strong>{title}</strong>
      <ListTag>
        {rows.map((item) => <li key={item}>{ordered ? stripListMarker(item) : item}</li>)}
      </ListTag>
    </div>
  );
}

function ExporterRequirementCard({ group }) {
  const summaryItems = group.summaries?.length ? group.summaries : group.exporterGuidance;
  const fallbackItems = !group.actionSteps?.length && !group.requiredEvidenceItems?.length
    ? group.verificationDetails
    : [];
  return (
    <article className="ddv-procedure-card exporter">
      <div className="ddv-procedure-card-head">
        <strong>{group.groupName}</strong>
        <span>{group.codes.length ? `${group.codes.length} codes` : group.a2mCode || "guideline"}</span>
      </div>
      <div className="ddv-group-guidance">
        <h3>수출자 가이드</h3>
        {summaryItems.length ? (
          summaryItems.map((item) => <p key={item}>{item}</p>)
        ) : (
          <p>이 TARIC 수입요건 묶음의 적용 여부를 먼저 확인하고, 연결된 certificate/declaration code와 footnote를 기준으로 세부 신고 경로를 검토합니다.</p>
        )}
        <GuidanceSection title="진행 순서" items={group.actionSteps} ordered />
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
      <div className="ddv-requirement-list">
        {groups.map((group) =>
          activeView === REQUIREMENT_VIEW_KEYS.EXPORTER ? (
            <ExporterRequirementCard group={group} key={group.groupName} />
          ) : (
            <BrokerRequirementCard group={group} key={group.groupName} />
          ),
        )}
      </div>
    </>
  );
}

function PreArrivalCards({ model, onToggle }) {
  const rows = asList(model.groups);
  const checkGroups = rows.filter((row) => row.checkItems.length);
  return (
    <div className="grid min-w-0 gap-6">
      <section className="rounded-xl border bg-surface-muted p-4">
        <div className="mb-4">
          <strong className="text-base font-semibold">수입요건 적용 여부</strong>
          <p className="mt-1 mb-0 text-sm text-muted-foreground">확인된 요건만 선택하면 최종 추천 서류가 즉시 갱신됩니다.</p>
        </div>
        <div className="grid gap-2">
          {rows.length ? rows.map((row, index) => {
            const summaryItems = row.summaries?.length ? row.summaries : row.exporterGuidance;
            const conditionalDocs = unique(row.documentItems
              .filter((item) => item.mode === "conditional_required_document")
              .map((item) => item.label));
            return (
              <article className={`flex items-start justify-between gap-3 rounded-lg border p-3 transition-colors ${row.applies ? "border-primary/40 bg-primary/5" : "bg-surface"}`} key={row.key}>
                <label className="flex min-w-0 flex-1 cursor-pointer items-start gap-3">
                  <Checkbox
                    className="mt-1"
                    checked={row.applies}
                    onCheckedChange={(checked) => onToggle(row.key, checked === true)}
                  />
                  <div className="min-w-0">
                    <strong className="block text-sm"><span className="mr-2 font-mono text-primary">{String(index + 1).padStart(2, "0")}</span>{row.groupName}</strong>
                    {summaryItems.slice(0, 2).map((item) => <p className="mt-1 mb-0 text-sm leading-5 text-muted-foreground" key={item}>{item}</p>)}
                    {conditionalDocs.length ? (
                      <em className="mt-2 block text-xs not-italic text-needs-review">해당 시 추가: {conditionalDocs.join(", ")}</em>
                    ) : null}
                  </div>
                </label>
                <span className={`shrink-0 text-xs font-semibold ${row.applies ? "text-primary" : "text-muted-foreground"}`}>{row.applies ? "적용" : "미확인"}</span>
              </article>
            );
          }) : <EmptyBlock message="추가로 판정할 조건부 수입요건이 없습니다. 기본 필수 서류는 아래에서 계속 확인할 수 있습니다." />}
        </div>
      </section>

      <section className="min-w-0">
        <div className="mb-4 flex items-center justify-between gap-3 pr-24">
          <strong className="text-base font-semibold">선택 결과에 따른 최종 추천 서류</strong>
          <span className="text-sm font-semibold text-muted-foreground">{model.finalDocuments.length}건</span>
        </div>
        <DocumentRecommendationCarousel
          documents={model.finalDocuments}
          emptyMessage="선택 결과에 따라 추천할 서류가 없습니다."
        />
        <section className="mt-6 border-t pt-5">
          <div className="mb-3 flex items-center justify-between gap-3">
            <strong className="text-sm font-semibold">확인·보관 사항</strong>
            <span className="text-xs text-muted-foreground">{checkGroups.length}개 요건</span>
          </div>
          {checkGroups.length ? (
            <div className="ddv-check-group-list">
              {checkGroups.map((row) => (
                <div className="ddv-check-group" key={`${row.key}_checks`}>
                  <strong>{row.groupName}</strong>
                  <ul className="ddv-check-list">
                    {row.checkItems.map((item) => (
                      <li key={`${row.key}_${item.mode}_${item.label}_${item.detail}`}>
                        <strong>{item.label}</strong>
                        {item.detail && item.detail !== item.label ? <span>{item.detail}</span> : null}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          ) : (
            <EmptyBlock message="표시할 확인/보관 사항이 없습니다." />
          )}
        </section>
      </section>
    </div>
  );
}

export default function DocumentPackageWorkspace({ packageData }) {
  const [activeFlow, setActiveFlow] = useState(FLOW_KEYS.REQUIREMENTS);
  const [requirementChecks, setRequirementChecks] = useState({});
  const pkg = asObject(packageData);
  const reduceMotion = useReducedMotion();

  const viewModel = useMemo(() => BuildDocumentPackageViewModel(pkg), [pkg]);

  const preArrivalModel = useMemo(
    () => buildPreArrivalModel(viewModel.baselineRows, viewModel.requirementGroups, requirementChecks),
    [viewModel.baselineRows, viewModel.requirementGroups, requirementChecks],
  );

  function handleRequirementToggle(key, checked) {
    setRequirementChecks((current) => ({
      ...current,
      [key]: checked,
    }));
  }

  if (!Object.keys(pkg).length) {
    return <EmptyBlock message="문서 패키지 데이터가 없습니다." />;
  }

  const counts = {
    [FLOW_KEYS.REQUIREMENTS]: viewModel.requirementGroups.length,
    [FLOW_KEYS.DUTY]: dutyPriorityCount(viewModel.dutyPriority) || viewModel.dutyRows.length,
    [FLOW_KEYS.BASELINE]: viewModel.baselineRows.length,
    [FLOW_KEYS.PRE_ARRIVAL]: preArrivalModel.finalDocuments.length,
  };
  const activeItem = FLOW_ITEMS.find((item) => item.key === activeFlow) || FLOW_ITEMS[0];

  return (
    <div className="grid min-w-0 gap-4 md:grid-cols-[220px_minmax(0,1fr)]">
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
          description="기본 통관서류를 표시하고, 앞 단계에서 다룬 조건부 증명서는 중복하지 않습니다."
        >
          <div className="pr-0 sm:pr-24">
            <DocumentRecommendationCarousel
              documents={viewModel.baselineRows}
              emptyMessage="표시할 기본 통관 서류가 없습니다."
            />
          </div>
        </FlowPanel>
      ) : null}

        {activeFlow === FLOW_KEYS.PRE_ARRIVAL ? (
        <FlowPanel
          title={activeItem.title}
          description="수입요건 해당 여부를 체크하고, 기본 필수 서류와 조건부 추가 서류를 중복 없이 정리합니다."
        >
          <PreArrivalCards model={preArrivalModel} onToggle={handleRequirementToggle} />
        </FlowPanel>
        ) : null}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}
