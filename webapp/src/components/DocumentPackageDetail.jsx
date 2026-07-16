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
  const values = Array.isArray(value) ? value : [value];
  return values
    .flatMap((item) => String(item ?? "").split(/[;,]/))
    .map((item) => clean(item))
    .filter(Boolean);
}

function splitLines(value) {
  const values = Array.isArray(value) ? value : [value];
  return values
    .flatMap((item) => String(item ?? "").split(/\n+|\s+[−-]\s+/))
    .map((item) => clean(item).replace(/^[-•]\s*/, ""))
    .filter(Boolean);
}

function stripListMarker(value) {
  return clean(value).replace(/^(\d+|[A-Za-z])[\.)]\s+/, "").replace(/^[-•]\s*/, "");
}

function normalizedKey(value) {
  return clean(value).toLowerCase().replace(/\s+/g, " ");
}

function addEvidenceItem(target, seen, value) {
  const text = stripListMarker(value);
  if (!text) {
    return;
  }
  const key = normalizedKey(text);
  if (!key || seen.has(key)) {
    return;
  }
  seen.add(key);
  target.push(text);
}

function splitEvidenceSource(value) {
  const text = stripListMarker(value);
  if (!text) {
    return [];
  }
  const a2mMatch = text.match(/^A2M\s*원문\s*:\s*(.+?)(?:\s*섹션)?$/i);
  if (a2mMatch) {
    return a2mMatch[1].split(/\s*,\s*/).map((item) => `${item} 섹션`);
  }
  return [text];
}

function buildEvidenceSourceGroups(group, regulationItems) {
  const categories = {
    sections: [],
    regulations: [],
    systems: [],
    other: [],
  };
  const seen = {
    sections: new Set(),
    regulations: new Set(),
    systems: new Set(),
    other: new Set(),
  };

  asList(group.sourceSections).forEach((item) => addEvidenceItem(categories.sections, seen.sections, item));
  asList(regulationItems).forEach((item) => addEvidenceItem(categories.regulations, seen.regulations, item));
  asList(group.systems).forEach((item) => addEvidenceItem(categories.systems, seen.systems, item));
  asList(group.officialLinks).forEach((item) => addEvidenceItem(categories.systems, seen.systems, item));

  asList(group.verificationSources).forEach((source) => {
    splitEvidenceSource(source).forEach((item) => {
      const text = stripListMarker(item);
      const lower = text.toLowerCase();
      if (!text) {
        return;
      }
      if (lower.includes("섹션") || lower.includes("a2m 원문")) {
        addEvidenceItem(categories.sections, seen.sections, text);
        return;
      }
      if (
        lower.includes("regulation")
        || lower.includes("celex")
        || lower.includes("annex")
        || lower.includes("article")
        || lower.includes("legal")
        || lower.includes("법령")
        || lower.includes("근거")
      ) {
        addEvidenceItem(categories.regulations, seen.regulations, text);
        return;
      }
      if (
        lower.includes("traces")
        || lower.includes("imsoc")
        || lower.includes("ched")
        || lower.includes("bcp")
        || lower.includes("catch")
        || lower.includes("flis")
        || lower.includes("echa")
        || lower.includes("dg sante")
        || lower.includes("cbam")
        || lower.includes("portal")
        || lower.includes("registry")
        || lower.includes("competent authorit")
        || lower.includes("담당기관")
        || lower.includes("관할기관")
      ) {
        addEvidenceItem(categories.systems, seen.systems, text);
        return;
      }
      addEvidenceItem(categories.other, seen.other, text);
    });
  });

  return categories;
}

function unique(values) {
  return Array.from(new Set(asList(values).map((value) => clean(value)).filter(Boolean)));
}

function firstNonEmpty(...values) {
  return values.map((value) => clean(value)).find(Boolean) || "";
}

function firstParagraph(value) {
  return splitLines(value)[0] || "";
}

function parseJsonList(value) {
  if (Array.isArray(value)) {
    return value;
  }
  if (value && typeof value === "object") {
    return [value];
  }
  const text = clean(value);
  if (!text) {
    return [];
  }
  try {
    const parsed = JSON.parse(text);
    return Array.isArray(parsed) ? parsed : asList(parsed);
  } catch {
    return [];
  }
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
        a2mCode: clean(guidance.a2m_code),
        sourceType: "taric",
        measureTypes: new Set(),
        sourceCodes: new Set(),
        legalBases: new Set(),
        regulationReferences: new Set(),
        celexIds: new Set(),
        officialLinks: [],
        sourceSections: [],
        summaries: new Set(),
        actionSteps: new Set(),
        requiredEvidenceItems: new Set(),
        verificationSources: new Set(),
        exporterGuidance: new Set(),
        prepareItems: new Set(),
        checkItems: new Set(),
        verificationDetails: new Set(),
        brokerReview: new Set(),
        systems: new Set(),
        codes: [],
        footnoteGuidelines: new Map(),
      };
      if (!group.a2mCode && clean(guidance.a2m_code)) {
        group.a2mCode = clean(guidance.a2m_code);
      }
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
      splitLines(guidance.exporter_summary_ko).forEach((item) => group.summaries.add(item));
      splitLines(guidance.exporter_action_steps_ko).forEach((item) => group.actionSteps.add(item));
      splitLines(guidance.exporter_required_evidence_ko).forEach((item) => group.requiredEvidenceItems.add(item));
      splitLines(guidance.exporter_verification_sources_ko).forEach((item) => group.verificationSources.add(item));
      splitLines(guidance.broker_review_detail_ko).forEach((item) => {
        group.verificationDetails.add(item);
        group.brokerReview.add(item);
      });
      splitLines(guidance.a2m_exporter_summary_ko).forEach((item) => group.summaries.add(item));
      splitLines(guidance.a2m_exporter_action_steps_ko).forEach((item) => group.actionSteps.add(item));
      splitLines(guidance.a2m_exporter_required_evidence_ko).forEach((item) => group.requiredEvidenceItems.add(item));
      splitLines(guidance.a2m_exporter_verification_sources_ko).forEach((item) => group.verificationSources.add(item));
      splitLines(guidance.a2m_broker_review_detail_ko).forEach((item) => {
        group.verificationDetails.add(item);
        group.brokerReview.add(item);
      });
      if (clean(guidance.a2m_exporter_guideline_ko)) {
        splitLines(guidance.a2m_exporter_guideline_ko).forEach((item) => group.exporterGuidance.add(item));
      }
      splitLines(guidance.a2m_broker_review_ko).forEach((item) => {
        group.verificationDetails.add(item);
        group.brokerReview.add(item);
      });
      splitTokens(guidance.a2m_systems).forEach((system) => group.systems.add(system));
      splitTokens(guidance.a2m_regulation_refs).forEach((reference) => group.regulationReferences.add(reference));
      splitTokens(guidance.a2m_celex_ids).forEach((celexId) => group.celexIds.add(celexId));
      parseJsonList(guidance.a2m_official_links_json)
        .map((link) => asObject(link))
        .map((link) => firstNonEmpty(link.text, link.href))
        .filter(Boolean)
        .slice(0, 8)
        .forEach((link) => group.officialLinks.push(link));
      parseJsonList(guidance.a2m_key_sections_json)
        .map((section) => asObject(section))
        .map((section) => firstNonEmpty(section.heading_ko, section.heading_en))
        .filter(Boolean)
        .slice(0, 8)
        .forEach((section) => group.sourceSections.push(section));
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
        splitTokens(legalReference).forEach((reference) => group.regulationReferences.add(reference));
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
      regulationReferences: unique(Array.from(group.regulationReferences)),
      celexIds: unique(Array.from(group.celexIds)),
      officialLinks: unique(Array.from(group.officialLinks)),
      sourceSections: unique(Array.from(group.sourceSections)),
      summaries: unique(Array.from(group.summaries)),
      actionSteps: unique(Array.from(group.actionSteps)),
      requiredEvidenceItems: unique(Array.from(group.requiredEvidenceItems)),
      verificationSources: unique(Array.from(group.verificationSources)),
      exporterGuidance: unique(Array.from(group.exporterGuidance)),
      prepareItems: unique(Array.from(group.prepareItems)),
      checkItems: unique(Array.from(group.checkItems)),
      verificationDetails: unique(Array.from(group.verificationDetails)),
      brokerReview: unique(Array.from(group.brokerReview)),
      systems: unique(Array.from(group.systems)),
      codes: group.codes.sort((a, b) => a.code.localeCompare(b.code)),
      footnoteGuidelines: Array.from(group.footnoteGuidelines.values()).sort((a, b) =>
        a.footnoteCode.localeCompare(b.footnoteCode),
      ),
    }))
    .sort((a, b) => a.groupName.localeCompare(b.groupName));
}

function buildA2mGuidelineGroups(pkg) {
  const guidelineRows = [
    ...asList(pkg.a2m_guidelines),
    ...asList(pkg.additional_a2m_guidelines),
    ...asList(asObject(pkg.checklist_summary).a2m_guidelines),
  ];
  const seenCodes = new Set();
  return guidelineRows.map((item) => {
    const source = asObject(item);
    const a2mCode = clean(source.a2m_code);
    if (!a2mCode || seenCodes.has(a2mCode)) {
      return null;
    }
    seenCodes.add(a2mCode);
    const sections = parseJsonList(source.key_sections_json)
      .map((section) => asObject(section))
      .filter((section) => clean(section.summary_ko));
    const officialLinks = parseJsonList(source.official_links_json)
      .map((link) => asObject(link))
      .map((link) => firstNonEmpty(link.text, link.href))
      .filter(Boolean)
      .slice(0, 8);
    const sourceSections = sections
      .map((section) => firstNonEmpty(section.heading_ko, section.heading_en))
      .filter(Boolean)
      .slice(0, 8);
    return {
      groupName: firstNonEmpty(source.title_ko, source.title_en, source.a2m_code),
      a2mCode,
      sourceType: "a2m",
      measureTypes: ["Access2Markets"],
      sourceCodes: unique([source.goods_code_10]),
      legalBases: [],
      regulationReferences: splitTokens(source.regulation_refs),
      celexIds: splitTokens(source.celex_ids),
      officialLinks,
      sourceSections,
      summaries: splitLines(source.exporter_summary_ko),
      actionSteps: splitLines(source.exporter_action_steps_ko),
      requiredEvidenceItems: splitLines(source.exporter_required_evidence_ko),
      verificationSources: splitLines(source.exporter_verification_sources_ko),
      exporterGuidance: unique([
        ...splitLines(source.exporter_summary_ko),
        ...splitLines(source.exporter_guideline_ko),
      ]),
      prepareItems: splitLines(source.exporter_required_evidence_ko),
      checkItems: splitLines(source.exporter_verification_sources_ko),
      verificationDetails: unique([
        ...splitLines(source.broker_review_detail_ko),
        ...splitLines(source.broker_review_ko),
      ]),
      codes: [],
      footnoteGuidelines: [],
      systems: splitTokens(source.systems),
      brokerReview: unique([
        ...splitLines(source.broker_review_detail_ko),
        ...splitLines(source.broker_review_ko),
      ]),
    };
  }).filter((group) =>
    group &&
    group.groupName && (group.exporterGuidance.length || group.verificationDetails.length)
  );
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

function normalizeDutyPriorityItem(row, bucket) {
  const source = asObject(row);
  const scope = clean(source.source_scope) === "direct" ? "해당 TARIC 직접 적용" : "상위계층 적용";
  const branches = asList(source.branches).map((branch) => {
    const item = asObject(branch);
    return {
      rowSeq: item.row_seq,
      condition: clean(item.condition_label || item.condition_expression),
      expression: clean(item.condition_expression),
      rate: formatRate(item.rate_text),
      rateKind: clean(item.rate_kind),
      unitCode: clean(item.unit_code),
    };
  }).filter((branch) => branch.rate);
  return {
    bucket,
    measure: clean(source.measure_type_description),
    measureCode: clean(source.measure_type_code),
    sourceCode: clean(source.goods_code_10),
    sourceScope: scope,
    origin: clean(source.origin_description || source.origin_code),
    rate: formatRate(source.rate_text || source.rate || source.duty_text),
    branches,
    condition: clean(source.condition_label || source.condition_expression),
    certificateCode: clean(source.certificate_code),
    actionCode: clean(source.action_code),
    legalBase: clean(source.legal_base),
    rateKind: clean(source.rate_kind),
    unitCodes: unique([
      ...asList(source.unit_codes).map(clean),
      ...branches.map((branch) => branch.unitCode),
      ...extractUnitCodes(source.rate_text || source.duty_text),
      ...branches.flatMap((branch) => extractUnitCodes(`${branch.expression} ${branch.rate}`)),
    ].filter(Boolean)),
  };
}

function buildDutyPriority(pkg) {
  const priority = asObject(pkg.duty_priority);
  const hasRateOrBranches = (row) => row.rate || row.branches.length;
  return {
    fta: asList(priority.fta).map((row) => normalizeDutyPriorityItem(row, "fta")).filter(hasRateOrBranches),
    conditional: asList(priority.conditional).map((row) => normalizeDutyPriorityItem(row, "conditional")).filter(hasRateOrBranches),
    basic: asList(priority.basic).map((row) => normalizeDutyPriorityItem(row, "basic")).filter(hasRateOrBranches),
  };
}

function dutyPriorityCount(priority) {
  return asList(priority.fta).length + asList(priority.conditional).length + asList(priority.basic).length;
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

const DUTY_UNIT_LABELS = {
  DTN: "100kg 기준",
  "DTN R": "100kg 기준",
  TNE: "1,000kg 기준",
  KGM: "kg 기준",
  HLT: "100L 기준",
  LTR: "L 기준",
  NAR: "개수 기준",
  GRM: "g 기준",
  EA: "농산물 구성요소",
  ADFM: "밀가루 구성요소",
  ADSZ: "설탕 구성요소",
  AC: "농산물 구성요소",
};

function extractUnitCodes(value) {
  const text = clean(value).toUpperCase();
  if (!text) {
    return [];
  }
  return Object.keys(DUTY_UNIT_LABELS).filter((unit) => {
    const escaped = unit.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return new RegExp(`(^|[^A-Z])${escaped}([^A-Z]|$)`).test(text);
  });
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
        <GuidanceSection title="준비할 자료" items={group.requiredEvidenceItems} />
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
    const requirementGroups = [
      ...certificateGroups,
      ...buildA2mGuidelineGroups(pkg),
    ];
    const dutyRows = buildDutyRows(pkg);
    const dutyPriority = buildDutyPriority(pkg);
    const baselineRows = buildBaselineRows(pkg, certificateGroups);
    const preArrivalRows = buildPreArrivalRows(certificateGroups);
    return { certificateGroups, requirementGroups, dutyRows, dutyPriority, baselineRows, preArrivalRows };
  }, [pkg]);

  if (!Object.keys(pkg).length) {
    return <EmptyBlock message="문서 패키지 데이터가 없습니다." />;
  }

  const counts = {
    [FLOW_KEYS.REQUIREMENTS]: viewModel.requirementGroups.length,
    [FLOW_KEYS.DUTY]: dutyPriorityCount(viewModel.dutyPriority) || viewModel.dutyRows.length,
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
          <strong>{viewModel.requirementGroups.length}건</strong>
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
          <CertificateGroupCards groups={viewModel.requirementGroups} />
        </FlowPanel>
      ) : null}

      {activeFlow === FLOW_KEYS.DUTY ? (
        <FlowPanel
          title={activeItem.title}
          description="FTA/특혜세율, suspension·quota·end-use, 기본세율 순서로 적용 후보를 정리합니다."
        >
          <DutyBranchView priority={viewModel.dutyPriority} rows={viewModel.dutyRows} />
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
