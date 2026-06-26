"""
Document_Agent — candidate TARIC10 branch(es) → 5-section document package,
regulatory domain, and backtracking signals.

Owned tools:
  - document_package resolver (taric10 → raw measures/certs/duty/CELEX)
  - DomainRouterTool      (cn8 + product facts → regulatory domain)

Output schema (Blackboard.document_packages, schema unconfirmed — minimal
fields for now):

  {
    "document_package_id": "dp_001",
    "candidate_id": "cand_001",
    "cn8": "19023010", "taric10": "1902301010",
    "customs_check_items":      [...],   # 세관확인사항 (control measures)
    "basic_duty":               {...},   # 기본관세 (Third country duty)
    "preferential_evidence":    [...],   # 우대증빙 (FTA / preferential origin)
    "required_documents":       [...],   # 요구서류 (C/N/L-class certs)
    "product_regulations":      [...],   # 제품규제 (domain-derived)
    "missing_facts":            [...],
    "external_lookup":          [...],
    "celex_basis":              [...],
    "backtracking_signals":     [...],   # → Classification 재검토 신호
  }

LLM 호출 없음 — current MVP. CELEX 본문 해석/카드 생성 LLM 통합은 후속.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from agents.agent_base import BaseAgent
from agents.document_package import get_document_package
from agents.tools.domain_router import DomainRouterTool
from agents.blackboard import BlackboardStore, now_iso


# ---------------------------------------------------------------------------
# Measure type → section bucket
# ---------------------------------------------------------------------------
_CONTROL_KEYWORDS = (
    "Veterinary", "CITES", "GMO", "Phytosanitary",
    "Luxury", "Sanction", "fishing", "Import control",
    "Export control", "Surveillance",
)
_DUTY_KEYWORDS = (
    "Third country duty",
    "Customs Union Duty",
    "Autonomous tariff",
    "Supplementary unit",
)
_PREFERENTIAL_KEYWORDS = (
    "Tariff preference",
    "Customs Union",
    "Preferential tariff quota",
    "Preferential",
)


def _classify_measure(measure_type: str) -> str:
    """One of: customs_check / basic_duty / preferential / other."""
    mt = measure_type or ""
    if any(k in mt for k in _CONTROL_KEYWORDS):
        return "customs_check"
    if any(k in mt for k in _PREFERENTIAL_KEYWORDS):
        return "preferential"
    if any(k in mt for k in _DUTY_KEYWORDS):
        return "basic_duty"
    return "other"


# ---------------------------------------------------------------------------
# Certificate prefix → document classification
# (재사용: agents/document_package.cert_category 와 동일 의미)
# ---------------------------------------------------------------------------
def _cert_kind(code: str) -> str:
    code = (code or "").strip().upper()
    if code.startswith("Y"):
        return "exemption_declaration"
    if code.startswith("C"):
        return "mandatory_certificate"
    if code.startswith("N"):
        return "national_document"
    if code.startswith("U"):
        return "preferential_origin"
    if code.startswith("L"):
        return "import_license"
    return "other"


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


# ---------------------------------------------------------------------------
# Document_Agent
# ---------------------------------------------------------------------------
class DocumentAgent(BaseAgent):
    agent_name = "Document_Agent"
    stage = "Document_Recommendation"
    llm_model = None  # MVP: deterministic. CELEX 해석 LLM 후속.

    def __init__(self, *, include_celex_excerpt: bool = False) -> None:
        super().__init__()
        self._include_celex_excerpt = include_celex_excerpt
        self._domain_tool = DomainRouterTool()

    def run(self, store: BlackboardStore) -> None:
        bb = store.load()
        pes = bb.get("product_evidence_state") or {}
        ccs_list = bb.get("candidate_code_sets") or []
        if not pes:
            raise RuntimeError("Document_Agent requires a ProductEvidenceState.")
        if not ccs_list:
            self.reason("No CandidateCodeSet present; nothing to package.")
            return
        latest = ccs_list[-1]
        self.read_input(latest["candidate_set_id"])

        product_facts = pes.get("observed_facts") or {}

        for cand in latest["candidates"]:
            self.read_input(cand["candidate_id"])
            cn8 = (cand.get("cn8") or "").strip()
            taric_targets = self._taric_targets_for_candidate(cand)

            # Sentinel: needs_more_facts candidates → no package, only signal.
            if (cand.get("status") or "").strip() != "proposed" or not taric_targets:
                self._emit_unresolved_package(store, cand)
                continue

            for target in taric_targets:
                taric10 = target["taric10"]
                cand_for_target = {**cand, "taric10": taric10}

                # 1. Raw TARIC measure package
                try:
                    raw = asdict(get_document_package(
                        taric10,
                        include_celex_excerpt=self._include_celex_excerpt,
                    ))
                except Exception as e:  # noqa: BLE001
                    self.reason(f"document package resolver error for {taric10}: {e}")
                    self._emit_unresolved_package(store, cand_for_target, reason=f"tool_error: {e}")
                    continue

                requirements_raw = raw.get("requirements") or []
                self.cite(
                    "taric_master_table",
                    f"goods_code_10={taric10}",
                    snippet=f"{raw.get('total_measure_rows')} measure rows / "
                            f"{len(requirements_raw)} requirement groups",
                    reason="document package resolver source.",
                )

                # 2. Regulatory domain (fast-path)
                measure_hints = [r.get("measure_type") for r in requirements_raw if r.get("measure_type")]
                dom = self._domain_tool.route(
                    cn8=cn8, product_facts=product_facts, measure_type_hints=measure_hints,
                )
                for ev in dom.evidence:
                    self.cite("Domain_Scope_Routes", str(ev.get("chapter") or ev.get("source") or ""),
                              snippet=str(ev)[:100], reason="DomainRouterTool evidence.")

                # 3. Bucket measures into 5 sections
                customs, duties, preferential = self._bucket_requirements(requirements_raw)

                required_documents = self._extract_required_documents(requirements_raw)
                product_regulations = self._build_product_regulations(dom)
                basic_duty = self._pick_basic_duty(duties, raw)

                # 4. CELEX basis (collect all legal bases referenced)
                celex_basis = self._collect_celex(requirements_raw)

                # 5. Backtracking signals
                backtracking = self._backtracking_signals(cand_for_target, raw, dom)

                # 6. Missing facts
                missing_facts = list(dom.missing_facts)
                if not requirements_raw:
                    missing_facts.append("no_taric_requirements_found")
                if dom.is_ambiguous:
                    missing_facts.append("regulatory_domain_ambiguous")

                dp_id = store.next_id("dp")
                dp = {
                    **self._public_raw_package_fields(raw),
                    "object_type": "DocumentPackage",
                    "created_by": self.agent_name,
                    "created_at": now_iso(),
                    "document_package_id": dp_id,
                    "candidate_id": cand["candidate_id"],
                    "cn8": cn8,
                    "taric10": taric10,
                    "taric10_branch": target.get("branch"),
                    "taric10_branch_index": target.get("branch_index"),
                    "taric10_branch_count": target.get("branch_count"),
                    "taric10_resolution_mode": target.get("resolution_mode"),
                    "taric10_is_recommended": False,

                    "customs_check_items": customs,
                    "basic_duty": basic_duty,
                    "preferential_evidence": preferential,
                    "required_documents": required_documents,
                    "product_regulations": product_regulations,

                    "missing_facts": missing_facts,
                    "external_lookup": self._suggest_external(dom),
                    "celex_basis": celex_basis,
                    "backtracking_signals": backtracking,

                    "summary": {
                        "duty": (basic_duty or {}).get("rate") or "see preferential",
                        "main_requirements": [d["title"] for d in required_documents[:5]],
                        "domains": dom.domains,
                        "unknowns": list(missing_facts),
                    },
                    "conflicts": [],
                }
                store.append("document_packages", dp)
                self.wrote(dp_id)
                branch_label = (
                    f"branch {target.get('branch_index')}/{target.get('branch_count')}"
                    if target.get("branch_count", 0) > 1
                    else "single branch"
                )
                self.reason(
                    f"DocumentPackage {dp_id} for cand={cand['candidate_id']} "
                    f"({taric10}, {branch_label}): customs={len(customs)} duties={len(duties)} "
                    f"pref={len(preferential)} reqs={len(required_documents)} "
                    f"product_rules={len(product_regulations)} "
                    f"domains={dom.domains}"
                    + (f" backtrack={len(backtracking)}" if backtracking else "")
                )

    # ------------------------------------------------------------------ helpers
    def _taric_targets_for_candidate(self, cand: dict) -> list[dict[str, Any]]:
        branches = cand.get("taric10_branch_candidates") or []
        targets: list[dict[str, Any]] = []
        seen: set[str] = set()
        if branches:
            for branch in branches:
                taric10 = _compact_text(branch.get("taric10"))
                if not taric10 or taric10.startswith("99999999") or taric10 in seen:
                    continue
                seen.add(taric10)
                targets.append({
                    "taric10": taric10,
                    "branch": dict(branch),
                    "resolution_mode": cand.get("taric10_resolution_mode") or "enumerate_all_under_cn8",
                })
        else:
            taric10 = _compact_text(cand.get("taric10"))
            if taric10 and not taric10.startswith("99999999"):
                targets.append({
                    "taric10": taric10,
                    "branch": None,
                    "resolution_mode": cand.get("taric10_resolution_mode") or "single_taric10",
                })

        count = len(targets)
        for index, target in enumerate(targets, start=1):
            target["branch_index"] = index
            target["branch_count"] = count
        return targets

    @staticmethod
    def _public_raw_package_fields(raw: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in raw.items()
            if key not in {"object_type", "created_by", "created_at", "document_package_id", "candidate_id"}
        }

    def _bucket_requirements(self, raw_requirements: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
        customs, duties, preferential = [], [], []
        for req in raw_requirements:
            mt = req.get("measure_type") or ""
            bucket = _classify_measure(mt)
            item = {
                "measure_type": mt,
                "applies_to_korea": req.get("applies_to_korea", False),
                "origins": req.get("origins") or [],
                "duty": req.get("duty") or {},
                "legal_base": req.get("legal_base"),
                "celex_id": (req.get("celex") or {}).get("celex_id") if isinstance(req.get("celex"), dict) else None,
                "cert_codes": [c.get("code") for c in (req.get("certificates") or [])],
            }
            if bucket == "customs_check":
                customs.append(item)
            elif bucket == "basic_duty":
                duties.append(item)
            elif bucket == "preferential":
                preferential.append(item)
            else:
                # 'other' bucket goes into customs_check by default (catch-all)
                customs.append(item)
        return customs, duties, preferential

    def _extract_required_documents(self, raw_requirements: list[dict]) -> list[dict]:
        seen: dict[str, dict] = {}
        for req in raw_requirements:
            for c in req.get("certificates") or []:
                code = (c.get("code") or "").strip()
                if not code:
                    continue
                kind = _cert_kind(code)
                # exemption_declaration / preferential_origin 는 별도 section
                if kind in ("exemption_declaration", "preferential_origin"):
                    continue
                if code in seen:
                    continue
                seen[code] = {
                    "doc_kind": kind,
                    "code": code,
                    "title": c.get("description") or code,
                    "required_when": req.get("measure_type") or "",
                    "celex_id": (req.get("celex") or {}).get("celex_id") if isinstance(req.get("celex"), dict) else None,
                }
        return list(seen.values())

    def _build_product_regulations(self, dom) -> list[dict]:
        out: list[dict] = []
        # Map each domain to its rule family + scope (rough MVP — real CELEX
        # binding 후속 step 에서).
        family_map = {
            "food":            {"family": "EU 2017/625 + 178/2002", "scope": "human consumption food"},
            "animal_origin":   {"family": "EU 853/2004 + CHED-P (Reg 2021/632)", "scope": "products of animal origin"},
            "cosmetics":       {"family": "EU 1223/2009 (Cosmetics Regulation)", "scope": "cosmetic products"},
            "cites":           {"family": "EU 338/97 (CITES implementation)", "scope": "CITES-listed species"},
            "hazardous":       {"family": "EU REACH 1907/2006 + CLP 1272/2008", "scope": "chemical substances"},
            "pharmaceutical":  {"family": "EU 2001/83 (medicinal products)", "scope": "human/veterinary medicines"},
            "sanctions":       {"family": "EU sanctions regulations (varies)", "scope": "restricted destinations/items"},
            "dual_use":        {"family": "EU 2021/821 (dual-use)", "scope": "dual-use items"},
            "other":           {"family": "n/a", "scope": "general goods"},
            "unknown":         {"family": "n/a", "scope": "unknown"},
        }
        for d in dom.domains:
            meta = family_map.get(d, family_map["other"])
            out.append({
                "domain": d,
                "rule_family": meta["family"],
                "scope": meta["scope"],
                "applies": "applies" if dom.confidence >= 0.7 else "possibly_applies",
                "missing_facts": list(dom.missing_facts),
            })
        return out

    def _collect_celex(self, raw_requirements: list[dict]) -> list[dict]:
        seen: dict[str, dict] = {}
        for req in raw_requirements:
            celex = req.get("celex") or {}
            if not isinstance(celex, dict):
                continue
            cid = (celex.get("celex_id") or "").strip()
            if cid and cid not in seen:
                seen[cid] = {
                    "celex_id": cid,
                    "title": celex.get("title") or "",
                    "match_status": celex.get("match_status") or "matched_ok",
                    "for_measure_type": req.get("measure_type"),
                }
        return list(seen.values())

    def _suggest_external(self, dom) -> list[dict]:
        out: list[dict] = []
        if "food" in dom.domains:
            out.append({"name": "EU TRACES system", "url": "https://traces.ec.europa.eu/"})
        if "animal_origin" in dom.domains:
            out.append({"name": "EU approved establishment list",
                        "url": "https://food.ec.europa.eu/safety/biological-safety/food-hygiene/establishments_en"})
        if "cosmetics" in dom.domains:
            out.append({"name": "CPNP (Cosmetic Products Notification Portal)",
                        "url": "https://ec.europa.eu/growth/sectors/cosmetics/cpnp_en"})
        if "cites" in dom.domains:
            out.append({"name": "CITES species database",
                        "url": "https://speciesplus.net/"})
        return out

    def _pick_basic_duty(self, duties: list[dict], raw: dict) -> dict:
        # Prefer 'Third country duty' as the canonical basic_duty.
        for d in duties:
            if "Third country duty" in (d.get("measure_type") or ""):
                return {
                    "rate": (d.get("duty") or {}).get("rate") or (d.get("duty") or {}).get("text"),
                    "measure_type": d["measure_type"],
                    "legal_base": d.get("legal_base"),
                    "celex_id": d.get("celex_id"),
                }
        if duties:
            d = duties[0]
            return {
                "rate": (d.get("duty") or {}).get("rate") or (d.get("duty") or {}).get("text"),
                "measure_type": d["measure_type"],
                "legal_base": d.get("legal_base"),
                "celex_id": d.get("celex_id"),
            }
        return {}

    def _backtracking_signals(self, cand: dict, raw: dict, dom) -> list[dict]:
        signals: list[dict] = []
        # 1. No measure rows → 분류 잘못 가능
        if not raw.get("has_data"):
            signals.append({
                "type": "no_measures_for_taric10",
                "candidate_id": cand["candidate_id"],
                "reason": (
                    f"TARIC10 {cand.get('taric10')} returned no current measure rows. "
                    "Verify the selected TARIC branch is the right leaf."
                ),
            })
        # 2. 도메인 ambiguous → 분류에 영향
        if dom.is_ambiguous:
            signals.append({
                "type": "domain_ambiguous",
                "candidate_id": cand["candidate_id"],
                "reason": (
                    f"Regulatory domain unresolved (domains={dom.domains}); ingredient "
                    "ratio likely required."
                ),
                "missing_facts": list(dom.missing_facts),
            })
        return signals

    def _emit_unresolved_package(
        self,
        store: BlackboardStore,
        cand: dict,
        *,
        reason: str = "candidate_unresolved",
    ) -> None:
        """For needs_more_facts / 99999999 candidates, emit a stub package with
        only the backtracking signal — no measure pretense."""
        dp_id = store.next_id("dp")
        store.append("document_packages", {
            "object_type": "DocumentPackage",
            "created_by": self.agent_name,
            "created_at": now_iso(),
            "document_package_id": dp_id,
            "candidate_id": cand["candidate_id"],
            "cn8": cand.get("cn8"),
            "taric10": cand.get("taric10"),
            "customs_check_items": [],
            "basic_duty": {},
            "preferential_evidence": [],
            "required_documents": [],
            "product_regulations": [],
            "has_data": False,
            "requirements": [],
            "checklist_summary": {},
            "missing_facts": ["candidate_unresolved"],
            "external_lookup": [],
            "celex_basis": [],
            "backtracking_signals": [{
                "type": "candidate_not_classified",
                "candidate_id": cand["candidate_id"],
                "reason": reason,
            }],
            "summary": {
                "duty": "unknown",
                "main_requirements": [],
                "domains": ["unknown"],
                "unknowns": ["candidate_unresolved"],
            },
            "conflicts": [],
        })
        self.wrote(dp_id)
        self.reason(
            f"Empty package for unresolved cand {cand['candidate_id']} ({reason}); "
            "emitted backtracking signal."
        )
