import { asList, asObject, clean } from "../../../lib/format.js";

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

function isRequiredLevel(value) {
  const normalized = clean(value).toLowerCase();
  return normalized === "required" || normalized === "mandatory";
}

function preparationItemKey(item) {
  const source = asObject(item);
  return firstNonEmpty(source.baseline_document_id, source.item_name_ko);
}

function preparationItemLabel(item, baselineById = new Map()) {
  const source = asObject(item);
  const baselineId = clean(source.baseline_document_id);
  if (baselineId && baselineById.has(baselineId)) {
    return baselineById.get(baselineId).documentName;
  }
  return clean(source.item_name_ko);
}

function groupKey(group) {
  return `${firstNonEmpty(group.sourceType, "group")}::${firstNonEmpty(group.groupId, group.a2mCode, group.groupName)}`;
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
      const controlGroupId = clean(guidance.control_document_group_id);
      const groupName = firstNonEmpty(
        guidance.control_document_group_name_ko,
        guidance.display_title_ko,
        cert.description,
        req.measure_type,
        "TARIC certificate/declaration",
      );
      const group = groups.get(groupName) || {
        groupName,
        groupId: controlGroupId,
        a2mCode: clean(guidance.a2m_code),
        sourceType: "taric",
        measureTypes: new Set(),
        sourceCodes: new Set(),
        legalBases: new Set(),
        regulationReferences: new Set(),
        celexIds: new Set(),
        officialLinks: [],
        officialLinkDetails: [],
        sourceSections: [],
        summaries: new Set(),
        actionSteps: new Set(),
        requiredEvidenceItems: new Set(),
        preparationItems: new Set(),
        preparationItemRows: new Map(),
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
      if (!group.groupId && controlGroupId) {
        group.groupId = controlGroupId;
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
      const preparationItems = [
        ...asList(guidance.preparation_items),
        ...asList(guidance.a2m_preparation_items),
      ].map((item) => asObject(item)).filter((item) => clean(item.item_name_ko));
      preparationItems.forEach((item) => {
        const label = preparationItemLabel(item);
        const itemKey = preparationItemKey(item);
        if (label) {
          group.preparationItems.add(label);
        }
        if (itemKey && !group.preparationItemRows.has(itemKey)) {
          group.preparationItemRows.set(itemKey, item);
        }
      });
      if (!preparationItems.length) {
        splitLines(guidance.exporter_required_evidence_ko).forEach((item) => group.requiredEvidenceItems.add(item));
      }
      splitLines(guidance.exporter_verification_sources_ko).forEach((item) => group.verificationSources.add(item));
      splitLines(guidance.broker_review_detail_ko).forEach((item) => {
        group.verificationDetails.add(item);
        group.brokerReview.add(item);
      });
      splitLines(guidance.a2m_exporter_summary_ko).forEach((item) => group.summaries.add(item));
      splitLines(guidance.a2m_exporter_action_steps_ko).forEach((item) => group.actionSteps.add(item));
      if (!preparationItems.length) {
        splitLines(guidance.a2m_exporter_required_evidence_ko).forEach((item) => group.requiredEvidenceItems.add(item));
      }
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
        .filter((link) => firstNonEmpty(link.text, link.href))
        .slice(0, 8)
        .forEach((link) => {
          group.officialLinks.push(firstNonEmpty(link.text, link.href));
          group.officialLinkDetails.push({
            label: firstNonEmpty(link.text, link.href),
            href: clean(link.href),
          });
        });
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
      officialLinkDetails: cloneDetailList(group.officialLinkDetails),
      sourceSections: unique(Array.from(group.sourceSections)),
      summaries: unique(Array.from(group.summaries)),
      actionSteps: unique(Array.from(group.actionSteps)),
      requiredEvidenceItems: unique(
        group.preparationItems.size
          ? Array.from(group.preparationItems)
          : Array.from(group.requiredEvidenceItems),
      ),
      preparationItems: unique(Array.from(group.preparationItems)),
      preparationItemRows: Array.from(group.preparationItemRows.values()),
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
    const officialLinkDetails = parseJsonList(source.official_links_json)
      .map((link) => asObject(link))
      .filter((link) => firstNonEmpty(link.text, link.href))
      .slice(0, 8)
      .map((link) => ({
        label: firstNonEmpty(link.text, link.href),
        href: clean(link.href),
      }));
    const officialLinks = officialLinkDetails
      .map((link) => link.label)
      .slice(0, 8);
    const sourceSections = sections
      .map((section) => firstNonEmpty(section.heading_ko, section.heading_en))
      .filter(Boolean)
      .slice(0, 8);
    const preparationRows = asList(source.preparation_items)
      .map((item) => asObject(item))
      .filter((item) => clean(item.item_name_ko));
    const preparationLabels = unique(preparationRows.map((item) => preparationItemLabel(item)));
    return {
      groupName: firstNonEmpty(source.title_ko, source.title_en, source.a2m_code),
      groupId: a2mCode,
      a2mCode,
      sourceType: "a2m",
      measureTypes: ["Access2Markets"],
      sourceCodes: unique([source.goods_code_10]),
      legalBases: [],
      regulationReferences: splitTokens(source.regulation_refs),
      celexIds: splitTokens(source.celex_ids),
      officialLinks,
      officialLinkDetails,
      sourceSections,
      summaries: splitLines(source.exporter_summary_ko),
      actionSteps: splitLines(source.exporter_action_steps_ko),
      requiredEvidenceItems: preparationLabels.length
        ? preparationLabels
        : splitLines(source.exporter_required_evidence_ko),
      preparationItems: preparationLabels,
      preparationItemRows: preparationRows,
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

function cloneDetailList(...values) {
  const seen = new Set();
  const items = [];
  values.flatMap((value) => {
    if (Array.isArray(value)) return value;
    return value === null || value === undefined || clean(value) === "" ? [] : [value];
  }).forEach((item) => {
    const cloned = item && typeof item === "object" ? { ...item } : item;
    const key = typeof cloned === "object" ? JSON.stringify(cloned) : clean(cloned);
    if (!key || seen.has(key)) return;
    seen.add(key);
    items.push(cloned);
  });
  return items;
}

function cloneSourceMetadata(...values) {
  return values.reduce((result, value) => {
    Object.entries(asObject(value)).forEach(([key, item]) => {
      if (Array.isArray(item)) result[key] = cloneDetailList(result[key], item);
      else if (item && typeof item === "object") result[key] = { ...item };
      else result[key] = item;
    });
    return result;
  }, {});
}

function BuildFinalRecommendedDocument(baseDocument, recommendationContext = {}) {
  const base = asObject(baseDocument);
  const context = asObject(recommendationContext);
  const missingFacts = cloneDetailList(base.missingFacts, context.missingFacts);
  const unresolvedConditions = cloneDetailList(
    base.unresolvedConditions,
    context.unresolvedConditions,
  );
  const unresolvedCount = cloneDetailList(missingFacts, unresolvedConditions).length
    || Number(context.unresolvedCount ?? base.unresolvedCount ?? 0);
  return {
    ...base,
    ...context,
    fields: cloneDetailList(base.fields, context.fields),
    requiredEvidence: cloneDetailList(base.requiredEvidence, context.requiredEvidence),
    regulations: cloneDetailList(base.regulations, context.regulations),
    celexReferences: cloneDetailList(base.celexReferences, context.celexReferences),
    officialLinks: cloneDetailList(base.officialLinks, context.officialLinks),
    verificationNotes: cloneDetailList(base.verificationNotes, context.verificationNotes),
    matchedConditions: cloneDetailList(base.matchedConditions, context.matchedConditions),
    missingFacts,
    unresolvedConditions,
    unresolvedCount,
    sourceMetadata: cloneSourceMetadata(base.sourceMetadata, context.sourceMetadata),
  };
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
        requiredLevelRaw: clean(source.required_level),
        requiredLevel: statusLabel(source.required_level),
        preparedBy: firstNonEmpty(source.prepared_by_ko, source.prepared_by),
        submittedTo: firstNonEmpty(source.submitted_to_ko, source.submitted_to),
        missingFacts: cloneDetailList(source.missing_facts),
        unresolvedConditions: cloneDetailList(source.unresolved_conditions),
        unresolvedCount: cloneDetailList(
          source.missing_facts,
          source.unresolved_conditions,
        ).length,
        fields: asList(source.fields)
          .map((field) => evidenceLabelKo(asObject(field).label_ko || asObject(field).label || asObject(field).field_key))
          .filter(Boolean),
        requiredEvidence: cloneDetailList(source.required_evidence, source.requiredEvidence),
        regulations: cloneDetailList(
          source.regulations,
          source.regulation_references,
          source.legal_bases,
        ),
        celexReferences: cloneDetailList(source.celex_references, source.celex_ids),
        officialLinks: cloneDetailList(source.official_links),
        verificationNotes: cloneDetailList(source.verification_notes),
        sourceMetadata: {
          ...asObject(source.source_metadata),
          documentCode: clean(source.document_code),
          decisionStatus: clean(source.decision_status),
          sourceBindings: cloneDetailList(source.source_bindings),
          preChecks: cloneDetailList(source.pre_checks),
          postRequirements: cloneDetailList(source.post_requirements),
          preTaricLinks: cloneDetailList(source.pre_taric_links),
          postTaricLinks: cloneDetailList(source.post_taric_links),
          taricCertificates: cloneDetailList(source.taric_certificates),
        },
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

const DOC_MODES_WHEN_APPLIES = new Set(["always_required_document", "conditional_required_document"]);
const DOC_MODES_WHEN_NOT_APPLIES = new Set(["always_required_document"]);
const CHECK_MODES_WHEN_APPLIES = new Set(["always_check"]);
const CHECK_MODES_WHEN_NOT_APPLIES = new Set(["always_check", "non_applicable_check"]);

function buildPreArrivalModel(baselineRows, requirementGroups, checkedGroups) {
  const baselineById = new Map(
    baselineRows
      .filter((row) => clean(row.documentId))
      .map((row) => [clean(row.documentId), row]),
  );
  const docs = new Map();

  function addDoc(key, baseDocument, recommendationContext) {
    if (!key) return;
    docs.set(
      key,
      BuildFinalRecommendedDocument(
        docs.get(key) || baseDocument,
        recommendationContext,
      ),
    );
  }

  baselineRows.forEach((row) => {
    if (!isRequiredLevel(row.requiredLevelRaw)) {
      return;
    }
    addDoc(`baseline:${row.documentId}`, row, {
      source: "기본 필수 서류",
      detail: row.fields.length ? joinList(row.fields) : "",
      baselineDocumentId: row.documentId,
      bucket: "baseline",
      recommendationStatus: "recommended",
      matchedConditions: ["기본 통관 준비서류"],
      recommendationReason: "기본 필수 통관서류로 포함됐습니다.",
    });
  });

  const groups = requirementGroups.map((group) => {
    const key = groupKey(group);
    const applies = Boolean(checkedGroups[key]);
    const docModes = applies ? DOC_MODES_WHEN_APPLIES : DOC_MODES_WHEN_NOT_APPLIES;
    const checkModes = applies ? CHECK_MODES_WHEN_APPLIES : CHECK_MODES_WHEN_NOT_APPLIES;
    const items = asList(group.preparationItemRows).map((item) => asObject(item));
    const documentItems = [];
    const checkItems = [];

    items.forEach((item) => {
      const mode = clean(item.recommendation_mode);
      const itemType = clean(item.item_type);
      const label = preparationItemLabel(item, baselineById);
      if (!label) {
        return;
      }
      if (itemType === "document" && docModes.has(mode)) {
        const baselineId = clean(item.baseline_document_id);
        const baselineDocument = baselineById.get(baselineId);
        const docKey = baselineId ? `baseline:${baselineId}` : `requirement:${label}`;
        const missingFacts = cloneDetailList(item.missing_facts);
        const unresolvedConditions = cloneDetailList(item.unresolved_conditions);
        addDoc(docKey, baselineDocument || {}, {
          documentName: label,
          source: baselineId
            ? (isRequiredLevel(baselineDocument?.requiredLevelRaw) ? "기본 필수 서류" : "조건부 기본 서류")
            : "수입요건 추가 서류",
          detail: clean(item.item_detail_ko),
          baselineDocumentId: baselineId,
          groupName: group.groupName,
          bucket: baselineId ? "baseline" : "requirement",
          recommendationStatus: "recommended",
          matchedConditions: unique(asList(group.codes).map((code) => code.whenRequired).filter(Boolean)),
          missingFacts,
          unresolvedConditions,
          recommendationReason: clean(item.item_detail_ko),
          requiredEvidence: group.requiredEvidenceItems,
          regulations: [...asList(group.legalBases), ...asList(group.regulationReferences)],
          celexReferences: group.celexIds,
          officialLinks: asList(group.officialLinkDetails).length
            ? group.officialLinkDetails
            : group.officialLinks,
          verificationNotes: [
            ...asList(group.verificationDetails),
            ...asList(group.verificationSources),
          ],
          sourceMetadata: {
            sourceType: clean(group.sourceType),
            groupId: clean(group.groupId),
            a2mCode: clean(group.a2mCode),
            measureTypes: cloneDetailList(group.measureTypes),
            sourceCodes: cloneDetailList(group.sourceCodes),
            certificateCodes: asList(group.codes).map((code) => clean(code.code)).filter(Boolean),
          },
        });
        documentItems.push({ label, detail: clean(item.item_detail_ko), mode });
        return;
      }
      if (itemType === "keep_check" && checkModes.has(mode)) {
        checkItems.push({ label, detail: clean(item.item_detail_ko), mode });
      }
    });

    return {
      ...group,
      key,
      applies,
      documentItems,
      checkItems,
    };
  });

  const finalDocuments = Array.from(docs.values());
  return {
    baselineDocuments: finalDocuments.filter((doc) => doc.bucket === "baseline"),
    requirementDocuments: finalDocuments.filter((doc) => doc.bucket === "requirement"),
    finalDocuments,
    groups,
  };
}

function BuildDocumentPackageViewModel(packageData) {
  const pkg = asObject(packageData);
  const certificateGroups = buildCertificateGroups(pkg);
  const requirementGroups = [
    ...certificateGroups,
    ...buildA2mGuidelineGroups(pkg),
  ];
  const dutyRows = buildDutyRows(pkg);
  const dutyPriority = buildDutyPriority(pkg);
  const baselineRows = buildBaselineRows(pkg, certificateGroups);
  return { certificateGroups, requirementGroups, dutyRows, dutyPriority, baselineRows };
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

export {
  DUTY_UNIT_LABELS,
  FLOW_KEYS,
  FLOW_ITEMS,
  REQUIREMENT_VIEW_KEYS,
  joinList,
  splitLines,
  stripListMarker,
  buildEvidenceSourceGroups,
  unique,
  statusLabel,
  isRequiredLevel,
  groupKey,
  buildCertificateGroups,
  buildA2mGuidelineGroups,
  buildDutyRows,
  buildDutyPriority,
  dutyPriorityCount,
  buildDutyBranches,
  BuildFinalRecommendedDocument,
  buildBaselineRows,
  buildPreArrivalModel,
  BuildDocumentPackageViewModel,
  extractUnitCodes,
};
