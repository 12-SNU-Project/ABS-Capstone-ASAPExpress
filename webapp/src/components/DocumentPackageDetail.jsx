import { useMemo, useState } from "react";
import { asList, asObject, clean, previewValue } from "../lib/format.js";

const FLOW_KEYS = {
  REQUIREMENTS: "requirements",
  DUTY: "duty",
  BASELINE: "baseline",
  PRE_ARRIVAL: "pre_arrival",
};

const FLOW_ITEMS = [
  {
    key: FLOW_KEYS.REQUIREMENTS,
    step: "01",
    title: "TARIC 관련 수입요건 확인",
    shortTitle: "수입요건",
  },
  {
    key: FLOW_KEYS.DUTY,
    step: "02",
    title: "세율 확인",
    shortTitle: "세율",
  },
  {
    key: FLOW_KEYS.BASELINE,
    step: "03",
    title: "기본 통관 준비서류",
    shortTitle: "기본서류",
  },
  {
    key: FLOW_KEYS.PRE_ARRIVAL,
    step: "04",
    title: "입항 전 서류·시스템 준비",
    shortTitle: "입항 전",
  },
];

const REQUIREMENT_VIEW_KEYS = {
  EXPORTER: "exporter",
  BROKER: "broker",
};

const CERT_DUPLICATE_DOCUMENT_IDS = new Set([
  "health_cert_support",
  "organic_coi",
  "cites_species_evidence",
]);

const EVIDENCE_LABELS_KO = {
  animal_origin: "동물성 원료 또는 제품 여부 확인",
  "approved establishment number": "EU 승인시설 번호 확인",
  "catch certificate": "어획증명서 준비",
  "CHED-D reference": "CHED-D 참조번호 또는 제출 상태 확인",
  "CHED-P reference": "CHED-P 참조번호 또는 제출 상태 확인",
  "competent authority listing evidence": "관할기관 등재 또는 승인 근거 확인",
  control_body: "유기농 관리기관 확인",
  establishment_approval_known: "EU 승인시설 여부 확인",
  "health certificate": "위생증명서 준비",
  origin_country: "원산국 확인",
  processing_country: "가공국 확인",
  "processing establishment approval": "가공시설 승인 여부 확인",
  processing_type: "가공 형태 확인",
  product_category: "제품군 확인",
  production_country: "생산국 확인",
  "vessel or factory vessel evidence": "어선 또는 가공선 관련 증빙 확인",
};

function joinList(value) {
  return asList(value)
    .map((item) => clean(item))
    .filter(Boolean)
    .join(", ");
}

function splitTokens(value) {
  return asList(value)
    .flatMap((item) => String(item ?? "").split(/[;,]/))
    .map((item) => clean(item))
    .filter(Boolean);
}

function unique(values) {
  return Array.from(new Set(asList(values).map((value) => clean(value)).filter(Boolean)));
}

function firstNonEmpty(...values) {
  return values.map((value) => clean(value)).find(Boolean) || "";
}

function formatRate(value) {
  const text = clean(value);
  if (!text) {
    return "";
  }
  if (/^-?\d+(\.\d+)?$/.test(text)) {
    return `${Number(text).toLocaleString(undefined, { maximumFractionDigits: 3 })}%`;
  }
  return text;
}

function statusLabel(value) {
  const normalized = clean(value).toLowerCase();
  if (normalized === "required" || normalized === "mandatory") {
    return "필수";
  }
  if (normalized === "conditional") {
    return "조건부";
  }
  if (normalized === "optional") {
    return "선택";
  }
  if (normalized === "pending") {
    return "확인 필요";
  }
  return clean(value) || "조건부";
}

function evidenceLabelKo(value) {
  const text = clean(value);
  if (!text) {
    return "";
  }
  return EVIDENCE_LABELS_KO[text] || text;
}

function plainConditionKo(value) {
  const text = clean(value);
  if (!text) {
    return "";
  }
  return text
    .replace(/^Certificate of inspection for organic products$/i, "유기농 제품 검사증명서가 필요한 경우")
    .replace(/^Goods not concerned by Regulation \(EU\) 2018\/848 \(organic products\)$/i, "EU 유기농 규정 대상이 아닌 경우")
    .replace(/^The declared goods are not concerned by Council Regulation \(EC\) No\. 1005\/2008$/i, "IUU 어업 규정 대상이 아닌 경우")
    .replace(/^Importer Declaration or Re-export Certificate.*$/i, "IUU 어업 규정 대상 수산물인 경우")
    .replace(/^Common Health Entry Document for Products.*$/i, "동물성 제품 공식통제 대상인 경우")
    .replace(/^Common Health Entry Document for Feed and Food of Non-Animal Origin.*$/i, "비동물성 고위험 식품·사료 공식통제 대상인 경우")
    .replace(/^Common Health Entry Document for Plants and Plant Products.*$/i, "식물·식물제품 공식통제 대상인 경우");
}

function EmptyBlock({ message }) {
  return <div className="ddv-empty">{message}</div>;
}

function FlowNav({ activeKey, counts, onSelect }) {
  return (
    <div className="ddv-flow-nav" role="tablist" aria-label="서류 추천 절차">
      {FLOW_ITEMS.map((item) => {
        const active = item.key === activeKey;
        return (
          <button
            key={item.key}
            type="button"
            className={`ddv-flow-button ${active ? "active" : ""}`}
            onClick={() => onSelect(item.key)}
            role="tab"
            aria-selected={active}
          >
            <span className="ddv-flow-step">{item.step}</span>
            <strong>{item.title}</strong>
            <em>{counts[item.key] || 0}건</em>
          </button>
        );
      })}
    </div>
  );
}

function FlowPanel({ title, description, children }) {
  return (
    <section className="ddv-flow-panel">
      <div className="ddv-flow-panel-head">
        <h2>{title}</h2>
        {description ? <p>{description}</p> : null}
      </div>
      {children}
    </section>
  );
}

function MiniTable({ columns, rows, emptyMessage }) {
  const normalizedRows = asList(rows);
  if (!normalizedRows.length) {
    return <EmptyBlock message={emptyMessage} />;
  }
  return (
    <div className="ddv-table-wrap">
      <table className="ddv-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key}>{column.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {normalizedRows.map((row, index) => {
            const source = asObject(row);
            return (
              <tr key={`${index}_${previewValue(source[columns[0].key], 40)}`}>
                {columns.map((column) => (
                  <td key={column.key}>
                    {column.render
                      ? column.render(source)
                      : previewValue(source[column.key], column.limit || 180)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
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

function buildCertificateGroups(pkg) {
  const groups = new Map();
  asList(pkg.requirements).forEach((requirement) => {
    const req = asObject(requirement);
    if (req.applies_to_korea === false) {
      return;
    }
    const certificates = asList(req.certificates);
    certificates.forEach((certificate) => {
      const cert = asObject(certificate);
      const code = clean(cert.code);
      if (!code) {
        return;
      }
      const guidance = asObject(cert.guidance);
      const groupName = firstNonEmpty(
        guidance.control_document_group_name_ko,
        guidance.display_title_ko,
        cert.description,
        req.measure_type,
        "TARIC certificate/declaration",
      );
      const group = groups.get(groupName) || {
        groupName,
        measureTypes: new Set(),
        sourceCodes: new Set(),
        legalBases: new Set(),
        exporterGuidance: new Set(),
        verificationDetails: new Set(),
        codes: [],
        footnoteGuidelines: new Map(),
      };
      group.measureTypes.add(clean(req.measure_type));
      asList(req.source_goods_codes).forEach((sourceCode) => group.sourceCodes.add(clean(sourceCode)));
      if (clean(req.legal_base)) {
        group.legalBases.add(clean(req.legal_base));
      }
      if (clean(guidance.exporter_guidance_ko)) {
        group.exporterGuidance.add(clean(guidance.exporter_guidance_ko));
      }
      if (clean(guidance.verification_detail_ko)) {
        group.verificationDetails.add(clean(guidance.verification_detail_ko));
      }
      group.codes.push({
        code,
        category: clean(cert.category || guidance.certificate_category),
        title: firstNonEmpty(guidance.display_title_ko, cert.description, guidance.guidance_title, code),
        description: firstNonEmpty(guidance.display_description_ko, cert.description),
        whenRequired: plainConditionKo(guidance.when_required),
        requiredEvidence: splitTokens(guidance.required_evidence).map(evidenceLabelKo),
        notApplicableCondition: plainConditionKo(guidance.not_applicable_condition),
        declarationWording: plainConditionKo(guidance.declaration_wording),
      });
      asList(guidance.footnote_guidelines).forEach((item) => {
        const guideline = asObject(item);
        const footnoteCode = clean(guideline.footnote_code);
        const summary = clean(guideline.guidance_summary_ko);
        const importerCheck = clean(guideline.importer_check_ko);
        const legalReference = clean(guideline.legal_reference_en);
        const footnoteDescription = firstNonEmpty(
          guideline.footnote_description_ko,
          guideline.footnote_description_en,
        );
        const exporterGuidance = clean(guideline.exporter_guidance_ko);
        const verificationDetail = clean(guideline.verification_detail_ko);
        if (exporterGuidance) {
          group.exporterGuidance.add(exporterGuidance);
        }
        if (verificationDetail) {
          group.verificationDetails.add(verificationDetail);
        }
        if (!footnoteCode || (!summary && !importerCheck && !legalReference && !footnoteDescription)) {
          return;
        }
        group.footnoteGuidelines.set(`${groupName}_${footnoteCode}`, {
          footnoteCode,
          summary,
          importerCheck,
          footnoteDescription,
          legalReference,
        });
      });
      groups.set(groupName, group);
    });
  });

  return Array.from(groups.values())
    .map((group) => ({
      ...group,
      measureTypes: unique(Array.from(group.measureTypes)),
      sourceCodes: unique(Array.from(group.sourceCodes)),
      legalBases: unique(Array.from(group.legalBases)),
      exporterGuidance: unique(Array.from(group.exporterGuidance)),
      verificationDetails: unique(Array.from(group.verificationDetails)),
      codes: group.codes.sort((a, b) => a.code.localeCompare(b.code)),
      footnoteGuidelines: Array.from(group.footnoteGuidelines.values()).sort((a, b) =>
        a.footnoteCode.localeCompare(b.footnoteCode),
      ),
    }))
    .sort((a, b) => a.groupName.localeCompare(b.groupName));
}

function buildDutyRows(pkg) {
  const rows = [];
  const seen = new Set();

  function addRow(row) {
    const normalized = {
      type: clean(row.type),
      measure: clean(row.measure),
      origin: clean(row.origin),
      rate: formatRate(row.rate),
      condition: clean(row.condition),
      legalBase: clean(row.legalBase),
    };
    const key = JSON.stringify(normalized);
    if (!normalized.rate || seen.has(key)) {
      return;
    }
    seen.add(key);
    rows.push(normalized);
  }

  const basicDuty = asObject(pkg.basic_duty);
  addRow({
    type: "기본세율",
    measure: firstNonEmpty(basicDuty.measure_type, "Third country duty"),
    origin: joinList(basicDuty.origins) || "ERGA OMNES",
    rate: asObject(basicDuty.duty).rate || basicDuty.rate || basicDuty.duty,
    condition: "FTA/특혜 요건을 적용하지 않는 경우",
    legalBase: basicDuty.legal_base,
  });

  asList(pkg.preferential_evidence).forEach((record) => {
    const row = asObject(record);
    const duty = asObject(row.duty);
    addRow({
      type: "FTA/특혜",
      measure: row.measure_type || "Tariff preference",
      origin: joinList(row.origins),
      rate: duty.rate || duty.text || row.rate,
      condition: "원산지 증빙 또는 FTA 원산지 요건 충족 시",
      legalBase: row.legal_base,
    });
  });

  asList(pkg.requirements).forEach((requirement) => {
    const req = asObject(requirement);
    const duty = asObject(req.duty);
    const raw = clean(duty.raw || duty.text || duty.rate);
    const rate = duty.rate || duty.text || "";
    const isConditionOnly = raw.startsWith("Cond:") || clean(req.certificates);
    if (isConditionOnly && !rate) {
      return;
    }
    addRow({
      type: clean(req.measure_type).toLowerCase().includes("preference") ? "FTA/특혜" : "세율",
      measure: req.measure_type,
      origin: joinList(req.origins),
      rate,
      condition: duty.conditions ? joinList(duty.conditions) : "",
      legalBase: req.legal_base,
    });
  });

  return rows.sort((a, b) => {
    const rank = { "FTA/특혜": 0, "기본세율": 1, "세율": 2 };
    return (rank[a.type] ?? 9) - (rank[b.type] ?? 9) || a.measure.localeCompare(b.measure);
  });
}

function buildDutyBranches(rows) {
  const dutyRows = asList(rows);
  const fta = dutyRows.find((row) => row.type === "FTA/특혜");
  const basic = dutyRows.find((row) => row.type === "기본세율");
  const conditional = dutyRows.filter((row) => row.type !== "FTA/특혜" && row.type !== "기본세율");
  return { fta, basic, conditional };
}

function cardHasCertOverlap(card, certificateCodes) {
  const source = asObject(card);
  const cardCerts = new Set(splitTokens(source.taric_certificates));
  if (!cardCerts.size) {
    return false;
  }
  return Array.from(cardCerts).some((code) => certificateCodes.has(code));
}

function buildBaselineRows(pkg, certificateGroups) {
  const certificateCodes = new Set(
    certificateGroups.flatMap((group) => group.codes.map((code) => code.code)),
  );
  const cards = asList(asObject(pkg.checklist_summary).document_binding_cards);
  const baselineCards = cards.filter((card) => {
    const source = asObject(card);
    const sourceLayers = new Set(asList(source.source_bindings).map((binding) => clean(asObject(binding).source_layer)));
    const documentId = clean(source.document_id);
    if (CERT_DUPLICATE_DOCUMENT_IDS.has(documentId)) {
      return false;
    }
    if (cardHasCertOverlap(source, certificateCodes)) {
      return false;
    }
    return sourceLayers.has("baseline") || !sourceLayers.size;
  });

  if (baselineCards.length) {
    return baselineCards.map((card) => {
      const source = asObject(card);
      return {
        documentId: clean(source.document_id),
        documentName: firstNonEmpty(source.document_name_ko, source.document_name, source.document_code),
        family: clean(source.document_family),
        requiredLevel: statusLabel(source.required_level),
        preparedBy: firstNonEmpty(source.prepared_by_ko, source.prepared_by),
        submittedTo: firstNonEmpty(source.submitted_to_ko, source.submitted_to),
        fields: asList(source.fields)
          .map((field) => evidenceLabelKo(asObject(field).label_ko || asObject(field).label || asObject(field).field_key))
          .filter(Boolean),
      };
    });
  }
  return [];
}

function buildPreArrivalRows(certificateGroups) {
  return certificateGroups.map((group) => {
    const evidence = unique(group.codes.flatMap((code) => code.requiredEvidence));
    const conditions = unique(group.codes.map((code) => code.whenRequired).filter(Boolean));
    const exemptions = unique(group.codes.map((code) => code.notApplicableCondition).filter(Boolean));
    return {
      groupName: group.groupName,
      codes: group.codes.map((code) => code.code).join(", "),
      conditions,
      evidence,
      exemptions,
    };
  });
}

function DutyBranchView({ rows }) {
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
          <div className="ddv-duty-split">조건부 세율</div>
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
    <div className="ddv-role-switch" role="tablist" aria-label="수입요건 표시 방식">
      <button
        type="button"
        className={activeView === REQUIREMENT_VIEW_KEYS.EXPORTER ? "active" : ""}
        onClick={() => onChange(REQUIREMENT_VIEW_KEYS.EXPORTER)}
        role="tab"
        aria-selected={activeView === REQUIREMENT_VIEW_KEYS.EXPORTER}
      >
        수출자 가이드
      </button>
      <button
        type="button"
        className={activeView === REQUIREMENT_VIEW_KEYS.BROKER ? "active" : ""}
        onClick={() => onChange(REQUIREMENT_VIEW_KEYS.BROKER)}
        role="tab"
        aria-selected={activeView === REQUIREMENT_VIEW_KEYS.BROKER}
      >
        관세사 검토
      </button>
    </div>
  );
}

function ExporterRequirementCard({ group }) {
  return (
    <article className="ddv-procedure-card exporter">
      <div className="ddv-procedure-card-head">
        <strong>{group.groupName}</strong>
        <span>{group.codes.length} codes</span>
      </div>
      <div className="ddv-group-guidance">
        <h3>사용자 가이드라인</h3>
        {group.exporterGuidance.length ? (
          group.exporterGuidance.map((item) => <p key={item}>{item}</p>)
        ) : (
          <p>이 TARIC 수입요건 묶음의 적용 여부를 먼저 확인하고, 연결된 certificate/declaration code와 footnote를 기준으로 세부 신고 경로를 검토합니다.</p>
        )}
        {group.verificationDetails.length ? (
          <div className="ddv-guidance-checkpoints">
            <strong>확인할 사항</strong>
            <ul>
              {group.verificationDetails.map((item) => <li key={item}>{item}</li>)}
            </ul>
          </div>
        ) : null}
      </div>
    </article>
  );
}

function BrokerRequirementCard({ group }) {
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

      <div className="ddv-broker-section">
        <h3>Certificate / declaration code</h3>
        <div className="ddv-cert-list">
          {group.codes.map((code) => (
            <div className="ddv-cert-row" key={`${group.groupName}_broker_${code.code}`}>
              <span>{code.code}</span>
              <div>
                <strong>{code.title}</strong>
                {code.description ? <p>{code.description}</p> : null}
                {code.whenRequired ? <em>적용 조건: {code.whenRequired}</em> : null}
                {code.notApplicableCondition ? <em>비대상/면제: {code.notApplicableCondition}</em> : null}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="ddv-broker-section">
        <h3>Footnote / regulation 확인</h3>
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
          <EmptyBlock message="연결된 footnote 또는 legal reference가 없습니다." />
        )}
      </div>

      <div className="ddv-review-note">
        TARIC measure, certificate/declaration code, footnote 및 legal reference를 기준으로 대상/비대상 여부와 제출 경로를 최종 검토하세요.
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

function PreArrivalCards({ rows }) {
  if (!rows.length) {
    return <EmptyBlock message="입항 전 준비로 전환할 certificate/declaration 묶음이 없습니다." />;
  }
  return (
    <div className="ddv-procedure-grid">
      {rows.map((row) => (
        <article className="ddv-procedure-card" key={row.groupName}>
          <div className="ddv-procedure-card-head">
            <strong>{row.groupName}</strong>
            <span>{row.codes}</span>
          </div>
          {row.conditions.length ? (
            <div className="ddv-prep-block">
              <h3>적용 조건</h3>
              <ul>
                {row.conditions.map((item) => <li key={item}>{item}</li>)}
              </ul>
            </div>
          ) : null}
          {row.evidence.length ? (
            <div className="ddv-prep-block">
              <h3>준비·확인 정보</h3>
              <div className="ddv-pill-row">
                {row.evidence.slice(0, 12).map((item) => <span className="ddv-pill" key={item}>{item}</span>)}
              </div>
            </div>
          ) : null}
          {row.exemptions.length ? (
            <div className="ddv-prep-block">
              <h3>비대상·면제 경로</h3>
              <ul>
                {row.exemptions.map((item) => <li key={item}>{item}</li>)}
              </ul>
            </div>
          ) : null}
        </article>
      ))}
    </div>
  );
}

export default function DocumentPackageDetail({ packageData }) {
  const [activeFlow, setActiveFlow] = useState(FLOW_KEYS.REQUIREMENTS);
  const pkg = asObject(packageData);

  const viewModel = useMemo(() => {
    const certificateGroups = buildCertificateGroups(pkg);
    const dutyRows = buildDutyRows(pkg);
    const baselineRows = buildBaselineRows(pkg, certificateGroups);
    const preArrivalRows = buildPreArrivalRows(certificateGroups);
    return { certificateGroups, dutyRows, baselineRows, preArrivalRows };
  }, [pkg]);

  if (!Object.keys(pkg).length) {
    return <EmptyBlock message="문서 패키지 데이터가 없습니다." />;
  }

  const counts = {
    [FLOW_KEYS.REQUIREMENTS]: viewModel.certificateGroups.length,
    [FLOW_KEYS.DUTY]: viewModel.dutyRows.length,
    [FLOW_KEYS.BASELINE]: viewModel.baselineRows.length,
    [FLOW_KEYS.PRE_ARRIVAL]: viewModel.preArrivalRows.length,
  };
  const activeItem = FLOW_ITEMS.find((item) => item.key === activeFlow) || FLOW_ITEMS[0];

  return (
    <div className="ddv-shell">
      <section className="ddv-overview-band">
        <div>
          <span>TARIC10</span>
          <strong>{clean(pkg.taric10) || "-"}</strong>
        </div>
        <div>
          <span>CN8</span>
          <strong>{clean(pkg.cn8) || "-"}</strong>
        </div>
        <div>
          <span>수입요건 묶음</span>
          <strong>{viewModel.certificateGroups.length}건</strong>
        </div>
        <div>
          <span>기본서류</span>
          <strong>{viewModel.baselineRows.length}건</strong>
        </div>
      </section>

      <FlowNav activeKey={activeFlow} counts={counts} onSelect={setActiveFlow} />

      {activeFlow === FLOW_KEYS.REQUIREMENTS ? (
        <FlowPanel
          title={activeItem.title}
          description="taric_master_table의 한국 적용 measure에서 certificate/declaration code를 추출하고, taric_cert_table의 묶음명과 표시 설명으로 정리합니다."
        >
          <CertificateGroupCards groups={viewModel.certificateGroups} />
        </FlowPanel>
      ) : null}

      {activeFlow === FLOW_KEYS.DUTY ? (
        <FlowPanel
          title={activeItem.title}
          description="기본세율과 FTA/특혜세율을 분리하고, 통제 조건만 있는 certificate/fallback row는 세율 목록에서 제외합니다."
        >
          <DutyBranchView rows={viewModel.dutyRows} />
        </FlowPanel>
      ) : null}

      {activeFlow === FLOW_KEYS.BASELINE ? (
        <FlowPanel
          title={activeItem.title}
          description="baseline_table 성격의 기본 통관 서류만 표시하고, certificate code 묶음에서 이미 다룬 CHED/COI/IUU/CITES 성격의 중복 서류는 제외합니다."
        >
          <MiniTable
            rows={viewModel.baselineRows}
            emptyMessage="표시할 기본 통관 서류가 없습니다."
            columns={[
              { key: "documentName", label: "서류명" },
              { key: "requiredLevel", label: "구분" },
              { key: "preparedBy", label: "준비자" },
              { key: "submittedTo", label: "제출처" },
              { key: "fields", label: "준비 정보", render: (row) => joinList(row.fields) || "-" },
            ]}
          />
        </FlowPanel>
      ) : null}

      {activeFlow === FLOW_KEYS.PRE_ARRIVAL ? (
        <FlowPanel
          title={activeItem.title}
          description="TARIC 수입요건에서 확인한 certificate/declaration 묶음을 입항 전 준비 체크리스트로 다시 배치합니다."
        >
          <PreArrivalCards rows={viewModel.preArrivalRows} />
        </FlowPanel>
      ) : null}
    </div>
  );
}
