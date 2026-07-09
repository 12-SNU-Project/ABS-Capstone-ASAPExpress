(function () {
  "use strict";

  const STATUS = {
    required: ["필요", "#b91c1c", "#fef2f2"],
    conditional: ["조건부", "#9a3412", "#fff7ed"],
    pending: ["판단보류", "#475569", "#f8fafc"],
    exempted: ["면제", "#166534", "#f0fdf4"],
  };

  const CONTROL_GUIDELINE_FIELDS = [
    "control_guideline_title_ko",
    "control_guideline_summary_ko",
    "control_guideline_decision_basis_ko",
    "control_guideline_applicable_docs_ko",
    "control_guideline_exemption_docs_ko",
    "control_guideline_required_facts_ko",
    "control_guideline_legal_basis_ko",
    "control_guideline_source_refs",
  ];

  const LEGACY_GUIDELINE_BLOCK_LABELS = {
    control_guideline_decision_basis_ko: "판단 기준",
    control_guideline_applicable_docs_ko: "대상 시 서류",
    control_guideline_exemption_docs_ko: "비대상 시 서류",
    control_guideline_required_facts_ko: "준비/확인 자료",
    control_guideline_legal_basis_ko: "법령 근거",
    control_guideline_source_refs: "법령/데이터 출처",
  };

  function compactText(value) {
    return String(value || "").trim();
  }

  function firstText() {
    for (let i = 0; i < arguments.length; i += 1) {
      const text = compactText(arguments[i]);
      if (text) {
        return text;
      }
    }
    return "";
  }

  function cleanCode(value) {
    return compactText(value).replace(/\D/g, "");
  }

  function normalizeCertificateCode(value) {
    return compactText(value).toUpperCase().replace(/[^A-Z0-9]/g, "");
  }

  function normalizeDocumentCode(value) {
    return compactText(value).toUpperCase().replace(/[^A-Z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  }

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    const nextAttrs = attrs || {};
    Object.keys(nextAttrs).forEach(function (key) {
      const value = nextAttrs[key];
      if (value === null || value === undefined || value === false) {
        return;
      }
      if (key === "className") {
        node.className = value;
      } else if (key === "style" && typeof value === "object") {
        Object.assign(node.style, value);
      } else if (key === "dataset" && typeof value === "object") {
        Object.assign(node.dataset, value);
      } else {
        node.setAttribute(key, String(value));
      }
    });
    appendChildren(node, children);
    return node;
  }

  function appendChildren(node, children) {
    const list = Array.isArray(children) ? children : [children];
    list.forEach(function (child) {
      if (child === null || child === undefined || child === false) {
        return;
      }
      if (Array.isArray(child)) {
        appendChildren(node, child);
      } else if (child instanceof Node) {
        node.appendChild(child);
      } else {
        node.appendChild(document.createTextNode(String(child)));
      }
    });
  }

  function statusBadge(status) {
    const entry = STATUS[status || "pending"] || ["검토", "#475569", "#f8fafc"];
    return el(
      "span",
      {
        className: "badge",
        style: {
          color: entry[1],
          backgroundColor: entry[2],
          border: `1px solid ${entry[1]}33`,
        },
      },
      entry[0],
    );
  }

  function isControlMeasure(req) {
    const measureType = compactText(req && req.measure_type);
    const lower = measureType.toLowerCase();
    return (
      [
        "Import control",
        "Import restriction",
        "Veterinary",
        "CITES",
        "GMO",
        "Phytosanitary",
        "REACH",
      ].some(function (key) {
        return measureType.indexOf(key) >= 0;
      }) ||
      ["fishing", "luxury", "sanction", "restriction", "surveillance", "control"].some(function (key) {
        return lower.indexOf(key) >= 0;
      })
    );
  }

  function isPreferentialMeasure(req) {
    const measureType = compactText(req && req.measure_type);
    return ["Tariff preference", "Customs Union", "Preferential"].some(function (key) {
      return measureType.indexOf(key) >= 0;
    });
  }

  function isDutyMeasure(req) {
    const measureType = compactText(req && req.measure_type);
    return ["duty", "Duty", "Tariff", "Preference", "Preferential", "Customs Union", "Supplementary"].some(function (key) {
      return measureType.indexOf(key) >= 0;
    });
  }

  function isBaseDutyMeasure(req) {
    if (isPreferentialMeasure(req)) {
      return false;
    }
    const measureType = compactText(req && req.measure_type);
    return ["Third country duty", "Additional duties", "Supplementary unit", "duty", "Duty"].some(function (key) {
      return measureType.indexOf(key) >= 0;
    });
  }

  function dutyRate(req) {
    if (!req) {
      return "없음";
    }
    return (req.duty && req.duty.rate) || req.rate || "조건부";
  }

  function findMeasure(measures, needles) {
    return (measures || []).find(function (measure) {
      const measureType = compactText(measure && measure.measure_type);
      return needles.some(function (needle) {
        return measureType.indexOf(needle) >= 0;
      });
    }) || null;
  }

  function documentsFromChecklist(checklist) {
    const documents = checklist && checklist.documents;
    if (Array.isArray(documents)) {
      return documents.filter(function (document) {
        return document && typeof document === "object";
      });
    }
    if (!documents || typeof documents !== "object") {
      return [];
    }
    const out = [];
    const seen = new Set();
    Object.keys(documents).forEach(function (status) {
      const names = Array.isArray(documents[status]) ? documents[status] : [];
      names.forEach(function (name) {
        const text = compactText(name);
        if (!text || seen.has(text)) {
          return;
        }
        seen.add(text);
        out.push({
          document_code: text.toUpperCase().replace(/[^A-Z0-9]+/g, "_").replace(/^_+|_+$/g, "") || text,
          document_name_ko: text,
          decision_status: status || "conditional",
          required_level: status || "conditional",
          prepared_by: "exporter / seller / logistics party",
          submitted_to: "EU importer / customs broker",
        });
      });
    });
    return out;
  }

  function splitDisplayFields(value) {
    if (Array.isArray(value)) {
      return value.map(compactText).filter(Boolean);
    }
    return compactText(value)
      .split(/[;,\n]/g)
      .map(compactText)
      .filter(Boolean);
  }

  function buildContext(pkg) {
    const sourcePkg = (!Array.isArray(pkg && pkg.requirements) && pkg && pkg.raw_document_package)
      ? pkg.raw_document_package
      : (pkg || {});
    const requirements = Array.isArray(sourcePkg && sourcePkg.requirements) ? sourcePkg.requirements : [];
    const checklist = sourcePkg && sourcePkg.checklist_summary && typeof sourcePkg.checklist_summary === "object"
      ? sourcePkg.checklist_summary
      : {};
    const kr = requirements.filter(function (req) {
      return req && typeof req === "object" && req.applies_to_korea;
    });
    const baselineDocuments = Array.isArray(checklist.document_binding_cards)
      ? checklist.document_binding_cards
      : documentsFromChecklist(checklist);
    const controls = [];
    const duties = [];
    const productPre = [];
    const productPost = [];

    kr.forEach(function (req) {
      const measureType = compactText(req.measure_type);
      const details = Array.isArray(req.detailed_requirements) ? req.detailed_requirements : [];
      if (
        measureType === "Baseline document requirements" ||
        measureType === "Product regulatory requirements" ||
        measureType === "Pre-TARIC screening requirements"
      ) {
        details.forEach(function (detail) {
          const sourceLayer = compactText(detail && detail.source_layer);
          if (sourceLayer === "pre_taric" || sourceLayer === "pre_taric_gate") {
            productPre.push(detail);
          } else if (sourceLayer === "chapter_route_seed") {
            productPost.push(detail);
          } else if (sourceLayer === "product_domain_seed") {
            productPost.push(detail);
          }
        });
        return;
      }
      if (isControlMeasure(req)) {
        controls.push(req);
      } else if (isDutyMeasure(req)) {
        duties.push(req);
      } else {
        duties.push(req);
      }
    });

    if (!requirements.length && sourcePkg && sourcePkg.document_view && sourcePkg.document_view.sections) {
      const sections = sourcePkg.document_view.sections;
      const customsBucket = sections.customs_check_items && Array.isArray(sections.customs_check_items.render_bucket)
        ? sections.customs_check_items.render_bucket
        : [];
      customsBucket.forEach(function (req) {
        if (req && typeof req === "object" && req.applies_to_korea && isControlMeasure(req)) {
          controls.push(req);
        }
      });
      const dutyBuckets = []
        .concat(sections.basic_duty && Array.isArray(sections.basic_duty.render_bucket) ? sections.basic_duty.render_bucket : [])
        .concat(sections.preferential_evidence && Array.isArray(sections.preferential_evidence.render_bucket) ? sections.preferential_evidence.render_bucket : []);
      dutyBuckets.forEach(function (req) {
        if (req && typeof req === "object" && req.applies_to_korea) {
          duties.push(req);
        }
      });
    }

    if (!baselineDocuments.length && Array.isArray(sourcePkg && sourcePkg.required_documents)) {
      sourcePkg.required_documents.forEach(function (doc) {
        if (doc && typeof doc === "object" && (doc.document_name_ko || doc.document_name || doc.document_code)) {
          baselineDocuments.push(doc);
        }
      });
    }

    if (!productPre.length && !productPost.length && Array.isArray(sourcePkg && sourcePkg.product_regulations)) {
      sourcePkg.product_regulations.forEach(function (detail) {
        if (!detail || typeof detail !== "object") {
          return;
        }
        const sourceLayer = compactText(detail.source_layer);
        if (sourceLayer === "pre_taric" || sourceLayer === "pre_taric_gate") {
          productPre.push(detail);
        } else {
          productPost.push(detail);
        }
      });
    }

    const baseDutyMeasures = duties.filter(isBaseDutyMeasure);
    const preferentialMeasures = duties.filter(isPreferentialMeasure);
    const thirdCountry = findMeasure(duties, ["Third country duty"]);
    const ftaPref = findMeasure(duties, ["Tariff preference", "Customs Union"]);
    const additionalDuty = findMeasure(duties, ["Additional duties"]);

    return {
      controls,
      duties: baseDutyMeasures.concat(preferentialMeasures),
      baseDutyMeasures,
      preferentialMeasures,
      thirdCountry,
      ftaPref,
      additionalDuty,
      baselineDocuments,
      productPre,
      productPost,
    };
  }

  function guidanceAllowsKoreaRecommendation(guidance) {
    const value = guidance && guidance.include_in_korea_export_recommendation;
    if (value === null || value === undefined || value === "") {
      return true;
    }
    if (typeof value === "boolean") {
      return value;
    }
    return ["true", "t", "1", "yes", "y"].indexOf(String(value).trim().toLowerCase()) >= 0;
  }

  function certificateDisplayTitle(cert) {
    const guidance = cert.guidance || {};
    return firstText(
      guidance.display_title_ko,
      guidance.guidance_title,
      guidance.certificate_description,
      cert.description,
      cert.code,
    );
  }

  function certificateDisplayDescription(cert) {
    const guidance = cert.guidance || {};
    return firstText(
      guidance.display_description_ko,
      guidance.when_required,
      guidance.certificate_description,
      cert.description,
    );
  }

  function certificateGroupKey(cert) {
    const guidance = cert.guidance || {};
    return firstText(guidance.control_document_group_id, guidance.control_document_group_name_ko, cert.code);
  }

  function certificateGroupTitle(cert) {
    const guidance = cert.guidance || {};
    return firstText(
      guidance.control_document_group_name_ko,
      guidance.display_description_ko,
      guidance.display_title_ko,
      guidance.guidance_title,
      cert.description,
      cert.code,
    );
  }

  function mergeControlGuideline(group, guidance) {
    CONTROL_GUIDELINE_FIELDS.forEach(function (field) {
      if (!compactText(group.guideline[field]) && compactText(guidance && guidance[field])) {
        group.guideline[field] = guidance[field];
      }
    });
    if (!group.guideline.control_guideline_blocks_ko && guidance && guidance.control_guideline_blocks_ko) {
      group.guideline.control_guideline_blocks_ko = guidance.control_guideline_blocks_ko;
    }
    if (!group.guideline.control_guideline_summary_ko && guidance && guidance.control_guideline_summary_ko) {
      group.guideline.control_guideline_summary_ko = guidance.control_guideline_summary_ko;
    }
    if (!group.guideline.control_guideline_decision_cards && guidance && guidance.control_guideline_decision_cards) {
      group.guideline.control_guideline_decision_cards = guidance.control_guideline_decision_cards;
    }
    if (!group.guideline.control_guideline_exclusion_list && guidance && guidance.control_guideline_exclusion_list) {
      group.guideline.control_guideline_exclusion_list = guidance.control_guideline_exclusion_list;
    }
    if (!group.guideline.control_guideline_hide_items && guidance && guidance.control_guideline_hide_items) {
      group.guideline.control_guideline_hide_items = true;
    }
  }

  function normalizeGuidelineBlocks(value) {
    if (!value) {
      return [];
    }
    let parsed = value;
    if (typeof value === "string") {
      try {
        parsed = JSON.parse(value);
      } catch (_error) {
        return [];
      }
    }
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed.map(function (block) {
      if (!block || typeof block !== "object") {
        return null;
      }
      const title = firstText(block.title, block.heading, block.label);
      const body = firstText(block.body, block.content, block.text, block.description);
      if (!title || !body) {
        return null;
      }
      return { title, body };
    }).filter(Boolean);
  }

  function normalizeGuidelineDecisionCards(value) {
    if (!Array.isArray(value)) {
      return [];
    }
    return value.map(function (card) {
      if (!card || typeof card !== "object") {
        return null;
      }
      const code = firstText(card.document_code, card.code);
      const title = firstText(card.document_title, card.title, card.document_name);
      if (!code && !title) {
        return null;
      }
      return {
        label: firstText(card.label, card.status, "확인 대상"),
        documentCode: code,
        documentTitle: title,
        when: firstText(card.when, card.condition, card.applies_when),
        prepare: firstText(card.prepare, card.body, card.description),
        legalBasis: firstText(card.legal_basis, card.basis, card.source),
      };
    }).filter(Boolean);
  }

  function normalizeGuidelineExclusionList(value) {
    if (!value || typeof value !== "object") {
      return null;
    }
    const items = Array.isArray(value.items)
      ? value.items.map(compactText).filter(Boolean)
      : [];
    if (!items.length) {
      return null;
    }
    return {
      title: firstText(value.title, "제외품목 리스트"),
      intro: firstText(value.intro, value.description),
      items,
      legalBasis: firstText(value.legal_basis, value.basis, value.source),
    };
  }

  function guidelineBasisFromBlocks(blocks) {
    const basis = (blocks || []).find(function (block) {
      return compactText(block && block.title).indexOf("근거") >= 0;
    });
    return firstText(basis && basis.body);
  }

  function autoDecisionLabel(item) {
    const code = compactText(item && item.code).toUpperCase();
    const text = `${compactText(item && item.title)} ${compactText(item && item.description)}`;
    if (
      code.charAt(0) === "Y" ||
      /비대상|비해당|면제|예외|개인|소량|재반입|경유/.test(text)
    ) {
      return "비대상/예외 시 확인";
    }
    if (/허가|증명|신고|CHED|COI|CITES|FLEGT|Kimberley|킴벌리/.test(text)) {
      return "규정 대상 시 준비";
    }
    return "조건 충족 시 확인";
  }

  function autoDecisionPrepare(item) {
    const code = compactText(item && item.code).toUpperCase();
    const title = firstText(item && item.title, "해당 서류");
    if (code.charAt(0) === "Y") {
      return `${title}에 해당하는 비대상/예외 근거를 성분표, 제조공정도, 원재료 정보, 용도 자료로 정리합니다.`;
    }
    return `${title}가 필요한 대상인지 확인하고, 수입자와 제출 방식, 발급 주체, 제출 시점을 확인합니다.`;
  }

  function autoDecisionCardsFromItems(group, blocks) {
    const legalBasis = guidelineBasisFromBlocks(blocks);
    return (group.items || []).map(function (item) {
      return {
        label: autoDecisionLabel(item),
        documentCode: item.code,
        documentTitle: item.title,
        when: item.description,
        prepare: autoDecisionPrepare(item),
        legalBasis,
      };
    });
  }

  function decisionCardTone(card) {
    const text = `${compactText(card && card.label)} ${compactText(card && card.documentCode)} ${compactText(card && card.documentTitle)} ${compactText(card && card.when)}`;
    if (/비대상|비해당|면제|예외|개인|소량|Y[0-9]/.test(text)) {
      return "exempt";
    }
    if (/대상|준비|허가|증명|신고|CHED|COI|C[0-9]|N[0-9]|L[0-9]/.test(text)) {
      return "required";
    }
    return "neutral";
  }

  function decisionCardSortValue(card) {
    const tone = decisionCardTone(card);
    if (tone === "required") {
      return 0;
    }
    if (tone === "neutral") {
      return 1;
    }
    return 2;
  }

  function splitNumberedSteps(text) {
    const value = compactText(text);
    if (!/\d+\.\s*/.test(value)) {
      return [];
    }
    return value
      .split(/(?=\d+\.\s*)/g)
      .map(function (part) {
        const match = compactText(part).match(/^(\d+)\.\s*(.+)$/);
        return match ? { number: match[1], text: match[2] } : null;
      })
      .filter(Boolean);
  }

  function renderGuidelineBlockBody(block) {
    const steps = splitNumberedSteps(block && block.body);
    if (steps.length > 1) {
      return el("ol", { className: "control-guideline-steps" }, steps.map(function (step) {
        return el("li", { value: step.number }, step.text);
      }));
    }
    return el("div", { className: "control-guideline-text" }, block.body);
  }

  function guidelineFromLibrary(library, code, currentGuidance) {
    const normalizedCode = normalizeCertificateCode(code);
    const cert = library && library.certificates && library.certificates[normalizedCode];
    const groups = library && library.groups ? library.groups : {};
    const currentGroupId = firstText(currentGuidance && currentGuidance.control_document_group_id);
    const certGroupId = firstText(cert && cert.group_id);
    const groupId = currentGroupId && groups[currentGroupId]
      ? currentGroupId
      : (certGroupId && groups[certGroupId] ? certGroupId : firstText(currentGroupId, certGroupId));
    const group = groupId && groups ? groups[groupId] : null;
    const title = firstText(
      group && group.title,
      cert && cert.title,
      currentGuidance && currentGuidance.display_title_ko,
      currentGuidance && currentGuidance.guidance_title,
    );
    const summary = firstText(
      group && group.summary,
      cert && cert.description,
      currentGuidance && currentGuidance.display_description_ko,
      currentGuidance && currentGuidance.when_required,
    );
    const blocks = normalizeGuidelineBlocks(group && group.blocks);
    const certBlocks = normalizeGuidelineBlocks(cert && cert.blocks);
    return {
      display_title_ko: cert && cert.title,
      display_description_ko: cert && cert.description,
      control_document_group_id: firstText(cert && cert.group_id, currentGuidance && currentGuidance.control_document_group_id),
      control_document_group_name_ko: firstText(cert && cert.group_name_ko, currentGuidance && currentGuidance.control_document_group_name_ko),
      control_guideline_title_ko: title,
      control_guideline_summary_ko: summary,
      control_guideline_blocks_ko: blocks.length ? blocks : certBlocks,
      control_guideline_decision_cards: group && group.decision_cards,
      control_guideline_exclusion_list: group && group.exclusion_list,
      control_guideline_hide_items: Boolean(group || certBlocks.length),
    };
  }

  function applyControlGuidelineLibrary(packageData, library) {
    if (!packageData || !library) {
      return packageData;
    }
    const sourcePkg = (!Array.isArray(packageData.requirements) && packageData.raw_document_package)
      ? packageData.raw_document_package
      : packageData;
    (Array.isArray(sourcePkg.requirements) ? sourcePkg.requirements : []).forEach(function (req) {
      (Array.isArray(req.certificates) ? req.certificates : []).forEach(function (cert) {
        const existing = cert.guidance && typeof cert.guidance === "object" ? cert.guidance : {};
        cert.guidance = Object.assign({}, existing, guidelineFromLibrary(library, cert.code, existing));
      });
    });
    return packageData;
  }

  function controlCertificateGroups(cx) {
    const groups = new Map();
    (cx.controls || []).forEach(function (req) {
      const measureType = compactText(req.measure_type) || "Control measure";
      const legalBase = compactText(req.legal_base);
      (Array.isArray(req.certificates) ? req.certificates : []).forEach(function (cert) {
        const guidance = cert.guidance || {};
        if (!guidanceAllowsKoreaRecommendation(guidance)) {
          return;
        }
        const code = compactText(cert.code).toUpperCase();
        if (!code) {
          return;
        }
        const key = certificateGroupKey(cert);
        if (!groups.has(key)) {
          groups.set(key, {
            key,
            title: certificateGroupTitle(cert),
            description: firstText(guidance.display_description_ko, guidance.when_required),
            priority: guidance.recommendation_priority,
            items: new Map(),
            measures: new Set(),
            legalBases: new Set(),
            guideline: {},
          });
        }
        const group = groups.get(key);
        mergeControlGuideline(group, guidance);
        group.measures.add(measureType);
        if (legalBase) {
          group.legalBases.add(legalBase);
        }
        if (!group.items.has(code)) {
          group.items.set(code, {
            code,
            title: certificateDisplayTitle(cert),
            description: certificateDisplayDescription(cert),
            category: cert.category || "",
          });
        }
      });
    });

    return Array.from(groups.values())
      .map(function (group) {
        return Object.assign({}, group, {
          items: Array.from(group.items.values()).sort(function (a, b) {
            return compactText(a.code).localeCompare(compactText(b.code));
          }),
          measures: Array.from(group.measures).sort(),
          legalBases: Array.from(group.legalBases).sort(),
        });
      })
      .sort(function (a, b) {
        const priorityA = Number.isFinite(Number(a.priority)) ? Number(a.priority) : 999;
        const priorityB = Number.isFinite(Number(b.priority)) ? Number(b.priority) : 999;
        if (priorityA !== priorityB) {
          return priorityA - priorityB;
        }
        return compactText(a.title).localeCompare(compactText(b.title));
      });
  }

  function scenarioCertCodes(requirements, categories) {
    const out = [];
    const seen = new Set();
    (requirements || []).forEach(function (req) {
      (Array.isArray(req.certificates) ? req.certificates : []).forEach(function (cert) {
        const category = cert.category || "unknown";
        const code = compactText(cert.code);
        if (!code || (categories && categories.indexOf(category) < 0) || seen.has(code)) {
          return;
        }
        seen.add(code);
        out.push(code);
      });
    });
    return out;
  }

  function scenarioParts(cx) {
    const controlGroups = controlCertificateGroups(cx);
    const visibleControlCodes = [];
    controlGroups.forEach(function (group) {
      (group.items || []).forEach(function (item) {
        if (item.code) {
          visibleControlCodes.push(item.code);
        }
      });
    });
    const mandatoryCategories = ["mandatory_certificate", "national_document", "import_license"];
    const controlCertCodes = visibleControlCodes.filter(function (code) {
      return (cx.controls || []).some(function (req) {
        return (Array.isArray(req.certificates) ? req.certificates : []).some(function (cert) {
          return cert.code === code && mandatoryCategories.indexOf(cert.category || "unknown") >= 0;
        });
      });
    });
    const ftaRequirements = cx.ftaPref ? [cx.ftaPref] : [];
    return {
      controlGroups,
      thirdCountry: cx.thirdCountry,
      ftaPref: cx.ftaPref,
      controlCertCodes: controlCertCodes.length ? controlCertCodes : visibleControlCodes,
      allControlCodes: visibleControlCodes,
      ftaCodes: scenarioCertCodes(ftaRequirements, ["preferential_origin"]) || scenarioCertCodes(ftaRequirements),
      hasControlRequirements: Boolean(visibleControlCodes.length || (cx.controls || []).length),
    };
  }

  function defaultScenarioValues(cx) {
    const parts = scenarioParts(cx);
    const values = [];
    if (!parts.hasControlRequirements) {
      values.push("controls_ready");
    }
    if (parts.ftaPref) {
      values.push("kr_fta_requested");
    }
    return values;
  }

  function renderControlDocumentWindow(cx) {
    const groups = controlCertificateGroups(cx);
    return el("div", { className: "scenario-window control-doc-window" }, [
      el("div", { className: "scenario-window-head" }, [
        el("div", { className: "scenario-window-title" }, "Control 서류 확인"),
        el("div", { className: "scenario-window-count" }, groups.length ? `${groups.length}개 묶음` : "0개"),
      ]),
      groups.length
        ? el("div", { className: "control-doc-groups" }, groups.map(renderControlGroup))
        : el("div", { className: "card-meta" }, "이 TARIC 코드에서 한국 수출 기준으로 표시할 control certificate/declaration 코드가 없습니다."),
    ]);
  }

  function scenarioCard(title, duty, basis, actions, colorClass, certCodes, dutyReq) {
    return el("div", { className: `scenario-card ${colorClass}` }, [
      el("div", { className: "card-title" }, title),
      el("div", { className: "card-meta" }, basis || "-"),
      el("div", { className: "scenario-duty" }, duty || "-"),
      el("ul", { className: "scenario-actions" }, (actions || []).filter(Boolean).map(function (action) {
        return el("li", null, action);
      })),
      el("div", { className: "card-meta", style: { marginTop: "9px" } }, `세부 서류/선언 코드 ${(certCodes || []).length}개`),
    ]);
  }

  function renderScenarioDecision(packageData, cx, selectedValues) {
    const parts = scenarioParts(cx);
    const selected = new Set(selectedValues || []);
    const krFtaRequested = selected.has("kr_fta_requested");
    const controlsReady = selected.has("controls_ready") || !parts.hasControlRequirements;
    let card;
    if (!controlsReady) {
      card = scenarioCard(
        "세율 적용 결과: Control 서류 확인 필요",
        "서류 확인 전 진행 불가",
        "필수 certificate/declaration 또는 비대상 근거가 준비되지 않은 상태입니다.",
        [
          "세율 적용 전에 Control 서류 충족 여부를 먼저 확인해야 합니다.",
          "Control 서류 확인 영역에서 연결된 TARIC 코드와 준비 문서를 확인하세요.",
        ],
        "red",
        parts.allControlCodes,
      );
    } else if (krFtaRequested && parts.ftaPref) {
      card = scenarioCard(
        "세율 적용 결과: FTA 우대세율 적용",
        dutyRate(parts.ftaPref),
        parts.ftaPref.measure_type || "Tariff preference",
        [
          "원산지 기준 충족자료와 원산지 신고문안을 준비합니다.",
          "기본 제출서류에는 원산지/가격/수량/운송정보가 일관되게 들어가야 합니다.",
        ],
        "green",
        parts.ftaCodes.concat(parts.allControlCodes),
        parts.ftaPref,
      );
    } else {
      card = scenarioCard(
        "세율 적용 결과: 기본관세 적용",
        dutyRate(parts.thirdCountry),
        (parts.thirdCountry && parts.thirdCountry.measure_type) || "Third country duty",
        [
          "FTA 우대세율을 쓰지 않거나 확인되지 않은 경우의 기본 시나리오입니다.",
          "기본 제출서류와 control 서류/비대상 근거는 별도로 준비합니다.",
        ],
        "amber",
        parts.allControlCodes,
        parts.thirdCountry,
      );
    }
    return el("div", null, card);
  }

  function renderControlCheckHelp(cx) {
    const groups = controlCertificateGroups(cx);
    return el("details", { className: "scenario-detail control-check-detail" }, [
      el("summary", null, [
        "Control 서류 확인",
        el("span", { className: "card-meta", style: { marginLeft: "8px" } }, groups.length ? `${groups.length}개 묶음` : "표시 대상 없음"),
      ]),
      el("div", { className: "card-meta", style: { margin: "6px 0 10px" } }, "TARIC control measure에 붙은 C/Y 등 certificate/declaration 코드와 비대상 선언을 바로 확인합니다."),
      renderControlDocumentWindow(cx),
    ]);
  }

  function checkedValues(container) {
    return Array.from(container.querySelectorAll("input[type='checkbox']")).filter(function (input) {
      return input.checked;
    }).map(function (input) {
      return input.value;
    });
  }

  function renderScenarioControls(packageData, cx) {
    const parts = scenarioParts(cx);
    const defaults = new Set(defaultScenarioValues(cx));
    const decisionSlot = el("div", { className: "scenario-decision-slot" });
    const checkboxPanel = el("div", { className: "scenario-checkboxes" }, [
      checkboxRow(
        parts.hasControlRequirements ? "Control 서류 준비 완료/비대상 근거 확보" : "Control 서류 대상 없음",
        "controls_ready",
        defaults.has("controls_ready"),
        !parts.hasControlRequirements,
      ),
      checkboxRow(
        parts.ftaPref ? "한국 원산지 FTA 우대세율 조건 충족" : "한국 원산지 우대세율 후보 없음",
        "kr_fta_requested",
        defaults.has("kr_fta_requested"),
        !parts.ftaPref,
      ),
    ]);
    const refreshDecision = function () {
      decisionSlot.replaceChildren(renderScenarioDecision(packageData || {}, cx, checkedValues(checkboxPanel)));
    };
    checkboxPanel.addEventListener("change", refreshDecision);
    refreshDecision();
    return el("div", { className: "scenario-shell" }, [
      el("div", { className: "scenario-head" }, [
        el("div", { className: "scenario-code" }, [
          el("div", { className: "metric-label" }, "TARIC CODE"),
          el("div", { className: "metric-value", style: { color: "#6d3fd6", fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" } }, packageData.taric10 || "-"),
          el("div", { className: "card-meta" }, `CN8: ${packageData.cn8 || "-"}`),
        ]),
        el("div", null, [
          el("div", { className: "card-title" }, "세율 시나리오"),
          el("div", { className: "card-meta" }, "원산지 우대세율 조건과 control 서류 준비 여부를 체크해 적용 세율 시나리오를 확인합니다."),
          checkboxPanel,
        ]),
      ]),
      decisionSlot,
      renderControlCheckHelp(cx),
    ]);
  }

  function renderOverview(packageData) {
    const cx = buildContext(packageData || {});
    const shell = el("div", null, [
      renderScenarioControls(packageData || {}, cx),
      renderOverviewSummary(cx),
    ]);
    return shell;
  }

  function checkboxRow(label, value, checked, disabled) {
    const input = el("input", { type: "checkbox", value, checked: checked ? "checked" : null, disabled: disabled ? "disabled" : null });
    input.checked = Boolean(checked);
    input.disabled = Boolean(disabled);
    return el("label", null, [input, label]);
  }

  function renderOverviewSummary(cx) {
    const controlGroups = controlCertificateGroups(cx);
    const baselineResult = baselineRecommendationRows(cx.baselineDocuments, controlGroups);
    const baselineRows = baselineResult[0];
    const productRows = productRecommendationRows(cx, baselineResult[1]);
    const documentCount = baselineRows.length + productRows.length;
    const rows = [
      ["Control 서류", `${controlGroups.length}개 묶음`, "한국 수출 기준으로 표시되는 TARIC certificate/declaration 묶음"],
      ["제출 서류", `${documentCount}개`, `기본 준비 서류 ${baselineRows.length}개 · 제품 관련 서류 ${productRows.length}개`],
    ];
    return el("div", { className: "document-overview-brief" }, [
      el("div", { className: "document-overview-title" }, "검토 요약"),
      el("div", { className: "document-table-wrap" }, el("table", { className: "document-overview-table" }, el("tbody", null, rows.map(function (row) {
        return el("tr", null, [
          el("th", null, row[0]),
          el("td", { className: "document-overview-count" }, row[1]),
          el("td", null, row[2]),
        ]);
      })))),
    ]);
  }

  function documentDedupeKey() {
    return Array.from(arguments)
      .map(function (value) {
        return compactText(value).toLowerCase();
      })
      .filter(Boolean)
      .join(" ")
      .replace(/[^a-z0-9가-힣]+/g, "");
  }

  function renderControlGuideline(group) {
    const guideline = group.guideline || {};
    const jsonBlocks = normalizeGuidelineBlocks(guideline.control_guideline_blocks_ko);
    const configuredDecisionCards = normalizeGuidelineDecisionCards(guideline.control_guideline_decision_cards);
    const decisionCards = configuredDecisionCards.length
      ? configuredDecisionCards
      : autoDecisionCardsFromItems(group, jsonBlocks);
    const sortedDecisionCards = decisionCards.slice().sort(function (a, b) {
      const toneDiff = decisionCardSortValue(a) - decisionCardSortValue(b);
      if (toneDiff !== 0) {
        return toneDiff;
      }
      return compactText(a.documentCode).localeCompare(compactText(b.documentCode));
    });
    const exclusionList = normalizeGuidelineExclusionList(guideline.control_guideline_exclusion_list);
    const legacyBlocks = Object.keys(LEGACY_GUIDELINE_BLOCK_LABELS).map(function (field) {
      return {
        title: LEGACY_GUIDELINE_BLOCK_LABELS[field],
        body: guideline[field],
      };
    }).filter(function (block) {
      return compactText(block.body);
    });
    const blocks = jsonBlocks.length ? jsonBlocks : legacyBlocks;
    const hasGuideline = CONTROL_GUIDELINE_FIELDS.some(function (field) {
      return compactText(guideline[field]);
    }) || blocks.length || sortedDecisionCards.length || exclusionList;
    if (!hasGuideline) {
      return null;
    }
    return el("details", { className: "control-guideline" }, [
      el("summary", { className: "control-guideline-summary-button" }, [
        el("span", { className: "control-guideline-button-text" }, "가이드라인"),
        el("span", { className: "control-guideline-button-subtext" }, "서류별 판단 기준과 준비 자료"),
      ]),
      el("div", { className: "control-guideline-body" }, [
        compactText(guideline.control_guideline_summary_ko)
          ? el("div", { className: "control-guideline-summary" }, guideline.control_guideline_summary_ko)
          : null,
        sortedDecisionCards.length
          ? el("div", { className: "control-guideline-decision-grid" }, sortedDecisionCards.map(function (card) {
            return el("div", { className: `control-guideline-decision-card ${decisionCardTone(card)}` }, [
              el("div", { className: "control-guideline-decision-label" }, card.label),
              el("div", { className: "control-guideline-decision-doc" }, [
                card.documentCode ? el("span", { className: "control-guideline-doc-code" }, card.documentCode) : null,
                el("span", null, card.documentTitle || "서류명 확인 필요"),
              ]),
              card.when ? el("div", { className: "control-guideline-decision-row" }, [
                el("span", null, "조건"),
                el("p", null, card.when),
              ]) : null,
              card.prepare ? el("div", { className: "control-guideline-decision-row" }, [
                el("span", null, "준비"),
                el("p", null, card.prepare),
              ]) : null,
              card.legalBasis ? el("div", { className: "control-guideline-decision-basis" }, [
                el("span", null, "근거"),
                el("p", null, card.legalBasis),
              ]) : null,
            ]);
          }))
          : null,
        exclusionList
          ? el("div", { className: "control-guideline-exclusion" }, [
            el("div", { className: "control-guideline-title" }, exclusionList.title),
            exclusionList.intro ? el("div", { className: "control-guideline-text" }, exclusionList.intro) : null,
            el("ul", { className: "control-guideline-exclusion-list" }, exclusionList.items.map(function (item) {
              return el("li", null, item);
            })),
            exclusionList.legalBasis ? el("div", { className: "control-guideline-source" }, `근거: ${exclusionList.legalBasis}`) : null,
          ])
          : null,
        blocks.length
          ? el("div", { className: "control-guideline-block-grid" }, blocks.map(function (block) {
            return el("div", { className: "control-guideline-block" }, [
              el("div", { className: "control-guideline-title" }, block.title),
              renderGuidelineBlockBody(block),
            ]);
          }))
          : null,
      ]),
    ]);
  }

  function shouldHideControlItems(group) {
    return Boolean(group && group.guideline && group.guideline.control_guideline_hide_items);
  }

  function renderControlGroup(group) {
    const hideItems = shouldHideControlItems(group);
    const items = hideItems ? [] : (group.items || []).map(function (item) {
      return el("div", { className: "control-doc-item" }, [
        el("div", { className: "control-doc-code" }, item.code || "-"),
        el("div", { className: "control-doc-copy" }, [
          el("div", { className: "control-doc-name" }, item.title || "서류명 확인 필요"),
          el("div", { className: "control-doc-desc" }, item.description || "-"),
        ]),
      ]);
    });
    return el("div", { className: "control-doc-group" }, [
      el("div", { className: "control-doc-group-head" }, [
        el("div", { className: "control-doc-group-title" }, group.title || "Control 서류 묶음"),
        el(
          "div",
          { className: "control-doc-group-desc" },
          group.description || "TARIC control measure에 연결된 certificate/declaration 코드입니다.",
        ),
      ]),
      hideItems ? null : el("div", { className: "control-doc-items" }, items),
      renderControlGuideline(group),
      group.measures && group.measures.length
        ? el("div", { className: "control-doc-meta" }, group.measures.slice(0, 3).join(" · "))
        : null,
    ]);
  }

  function controlDedupeIndex(controlGroups) {
    const keys = new Set();
    const codes = new Set();
    const addKey = function () {
      const key = documentDedupeKey.apply(null, arguments);
      if (key) {
        keys.add(key);
      }
    };
    (controlGroups || []).forEach(function (group) {
      addKey(group.title, group.description, group.key);
      (group.items || []).forEach(function (item) {
        const code = compactText(item.code).toUpperCase();
        if (code) {
          codes.add(code);
        }
        addKey(item.code, item.title, item.description);
        addKey(item.title);
      });
    });
    return { keys, codes };
  }

  function baselineOverlapsControl(doc, controlIndex) {
    const controlCodes = controlIndex && controlIndex.codes ? controlIndex.codes : new Set();
    const controlKeys = controlIndex && controlIndex.keys ? controlIndex.keys : new Set();
    const taricCertificates = Array.isArray(doc && doc.taric_certificates) ? doc.taric_certificates : [];
    if (taricCertificates.some(function (code) {
      return controlCodes.has(compactText(code).toUpperCase());
    })) {
      return true;
    }
    const docKeys = [
      documentDedupeKey(doc && doc.document_code, doc && doc.document_name_ko, doc && doc.document_name),
      documentDedupeKey(doc && doc.document_name_ko),
      documentDedupeKey(doc && doc.document_name),
      documentDedupeKey(doc && doc.document_code),
    ].filter(Boolean);
    return docKeys.some(function (key) {
      return controlKeys.has(key);
    });
  }

  function baselineRecommendationRows(documents, controlGroups) {
    const rows = [];
    const seen = new Set();
    const controlIndex = controlDedupeIndex(controlGroups);
    (documents || []).forEach(function (doc) {
      if (baselineOverlapsControl(doc, controlIndex)) {
        return;
      }
      const key = documentDedupeKey(doc.document_code, doc.document_name_ko, doc.document_name);
      if (key && seen.has(key)) {
        return;
      }
      if (key) {
        seen.add(key);
      }
      rows.push({
        status: doc.decision_status || doc.required_level || "conditional",
        documentName: doc.document_name_ko || doc.document_name || doc.document_code || "문서명 없음",
        code: doc.document_code || "",
        preparedBy: firstText(doc.prepared_by_ko, doc.prepared_by, "-"),
        submittedTo: firstText(doc.submitted_to_ko, doc.submitted_to, "-"),
        fields: splitDisplayFields(firstText(doc.field_keys_ko, doc.field_examples_ko, doc.field_keys)),
        exampleForms: doc.example_forms || {},
      });
    });
    return [rows, seen];
  }

  function productRecommendationRows(cx, seen) {
    const rows = [];
    (cx.productPost || []).forEach(function (detail) {
      const documentName = firstText(
        detail.required_document,
        detail.document_name_ko,
        detail.document_name,
        detail.required_action,
      );
      const key = documentDedupeKey(documentName);
      if (!documentName || (key && seen.has(key))) {
        return;
      }
      if (key) {
        seen.add(key);
      }
      rows.push({
        status: detail.decision_status || detail.required_level || "conditional",
        documentName,
        code: detail.domain_route || detail.domain || "",
        type: detail.requirement_type || detail.source_layer || "-",
        action: firstText(detail.required_action, detail.when_required, detail.rationale, "제품 facts 기준 추가 확인 대상"),
      });
    });
    return rows;
  }

  function renderTableSection(title, description, headers, rows, renderRow, emptyText) {
    return el("div", { className: "document-recommend-section" }, [
      el("div", { className: "document-recommend-section-head" }, [
        el("div", { className: "document-recommend-section-title" }, title),
        el("div", { className: "document-recommend-section-desc" }, description),
      ]),
      el("div", { className: "document-table-wrap" }, rows.length
        ? el("table", { className: "document-checklist-table" }, [
          el("thead", null, el("tr", null, headers.map(function (header) {
            return el("th", null, header);
          }))),
          el("tbody", null, rows.map(renderRow)),
        ])
        : el("div", { className: "card-meta" }, emptyText)),
    ]);
  }

  function renderBaselineRow(row) {
    const pdfPath = compactText(row.exampleForms && row.exampleForms.pdf);
    return el("tr", null, [
      el("td", null, statusBadge(row.status)),
      el("td", null, [
        el("div", { className: "document-cell-title" }, row.documentName),
        el("div", { className: "document-cell-code" }, row.code),
      ]),
      el("td", { className: "document-party-route" }, [
        el("div", { className: "document-party" }, row.preparedBy),
        el("div", { className: "document-party-arrow" }, "→"),
        el("div", { className: "document-party" }, row.submittedTo),
      ]),
      el("td", null, row.fields && row.fields.length
        ? el("details", { className: "document-field-detail" }, [
          el("summary", null, `상세 필드 ${row.fields.length}개`),
          el("table", { className: "document-field-table" }, [
            el("tbody", null, row.fields.map(function (field, index) {
              return el("tr", null, [
                el("th", null, String(index + 1)),
                el("td", null, field),
              ]);
            })),
          ]),
        ])
        : el("span", { className: "card-meta" }, "필드 정보 없음")),
      el("td", null, pdfPath
        ? el("a", { className: "document-example-link", href: pdfPath, target: "_blank", rel: "noreferrer" }, "PDF")
        : el("span", { className: "card-meta" }, "예시 없음")),
    ]);
  }

  function renderProductRow(row) {
    return el("tr", null, [
      el("td", null, statusBadge(row.status)),
      el("td", null, [
        el("div", { className: "document-cell-title" }, row.documentName),
        el("div", { className: "document-cell-code" }, row.code),
      ]),
      el("td", null, row.type),
      el("td", { className: "document-cell-missing" }, row.action),
    ]);
  }

  function renderDocumentRecommendation(packageData) {
    const cx = buildContext(packageData || {});
    const controlGroups = controlCertificateGroups(cx);
    const baselineResult = baselineRecommendationRows(cx.baselineDocuments, controlGroups);
    const baselineRows = baselineResult[0];
    const productRows = productRecommendationRows(cx, baselineResult[1]);
    const totalCount = controlGroups.length + baselineRows.length + productRows.length;
    const taric10 = cleanCode(packageData && packageData.taric10);

    return el("div", { className: "document-recommend-layout", dataset: { taric10 } }, [
      el("div", { className: "document-checklist-intro" }, [
        el("div", { className: "section-title" }, "제출 서류"),
        el(
          "div",
          { className: "document-checklist-description" },
          `TARIC control 묶음 ${controlGroups.length}개 · 기본 준비 서류 ${baselineRows.length}개 · 제품 관련 서류 ${productRows.length}개`,
        ),
        el("div", { className: "card-meta" }, `중복 제거 후 총 ${totalCount}개 항목`),
      ]),
      renderTableSection(
        "기본 준비 서류",
        "baseline_document_master 기준으로 항상 먼저 확인할 통관 기본 서류입니다.",
        ["상태", "문서", "작성 → 제출", "필드 예시", "시각자료 예시"],
        baselineRows,
        renderBaselineRow,
        "기본 준비 서류가 없습니다.",
      ),
      el("div", { className: "document-recommend-section" }, [
        el("div", { className: "document-recommend-section-title" }, "TARIC control 서류"),
        el(
          "div",
          { className: "document-recommend-section-desc" },
          "현재 TARIC control measure에 붙은 C/Y 등 certificate/declaration 코드를 테이블의 묶음 기준으로 정리했습니다.",
        ),
        el(
          "div",
          { className: "control-doc-groups" },
          controlGroups.length
            ? controlGroups.map(renderControlGroup)
            : el("div", { className: "card-meta" }, "한국 수출 기준으로 표시할 control 코드가 없습니다."),
        ),
      ]),
      renderTableSection(
        "제품 관련 서류",
        "상품 facts와 CN/TARIC 분류 결과에서 연결된 제품별 추가 확인 서류입니다.",
        ["상태", "문서", "구분", "조건/조치"],
        productRows,
        renderProductRow,
        "제품 facts 기준 추가 서류가 없습니다.",
      ),
    ]);
  }

  function renderTaricDetail(packageData) {
    const overviewPanel = el("div", { className: "taric-js-panel", dataset: { panel: "overview" } }, renderOverview(packageData || {}));
    const recommendationPanel = el(
      "div",
      { className: "taric-js-panel", dataset: { panel: "recommendation" }, style: { display: "none" } },
      renderDocumentRecommendation(packageData || {}),
    );
    const overviewButton = el("button", { type: "button", className: "taric-js-tab active", dataset: { panel: "overview" } }, "전체 결론");
    const recommendationButton = el("button", { type: "button", className: "taric-js-tab", dataset: { panel: "recommendation" } }, "제출 서류");
    const shell = el("div", { className: "taric-js-detail" }, [
      el("div", { className: "taric-js-tabs" }, [overviewButton, recommendationButton]),
      overviewPanel,
      recommendationPanel,
    ]);
    const switchPanel = function (panel) {
      shell.querySelectorAll(".taric-js-tab").forEach(function (button) {
        button.classList.toggle("active", button.dataset.panel === panel);
      });
      shell.querySelectorAll(".taric-js-panel").forEach(function (node) {
        node.style.display = node.dataset.panel === panel ? "" : "none";
      });
    };
    shell.querySelectorAll(".taric-js-tab").forEach(function (button) {
      button.addEventListener("click", function () {
        switchPanel(button.dataset.panel);
      });
    });
    return shell;
  }

  function mount(target, packageData) {
    const root = typeof target === "string" ? document.querySelector(target) : target;
    if (!root) {
      throw new Error("document recommendation mount target not found");
    }
    root.replaceChildren(renderTaricDetail(packageData || {}));
    return root;
  }

  async function fetchPackage(apiBaseUrl, runId, taric10) {
    const base = compactText(apiBaseUrl).replace(/\/+$/, "");
    const response = await fetch(`${base}/api/runs/${encodeURIComponent(runId)}/document-packages/${encodeURIComponent(taric10)}`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.message || payload.error || "document_package_fetch_failed");
    }
    return payload.document_package || payload;
  }

  window.AsapDocumentRecommendation = {
    applyControlGuidelineLibrary,
    buildContext,
    controlCertificateGroups,
    render: renderDocumentRecommendation,
    renderOverview,
    renderTaricDetail,
    mount,
    fetchPackage,
  };
}());
