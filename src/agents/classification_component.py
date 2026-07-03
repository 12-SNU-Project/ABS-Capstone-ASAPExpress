"""
Classification_Component — delegates to ASAPExpress Stage 1 classifier.

Inside BasePipelineComponent.execute() this component:
  1. Reads InputEvidenceState from the Blackboard.
  2. Hands it to agents._external_classifier.run_external_classifier(),
     which runs the full ASAPExpress 7-step Stage 1 pipeline
     (retriever → context → evidence → request → LLM → validator →
     decision → traversal → recommendation).
  3. Translates the Stage1RecommendationReport back into candidate entries.

ASAPExpress code is loaded as-is via sys.path — no modifications.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass

from agents.candiate_classfier import (
    ExternalClassificationResult,
    run_external_classifier,
)
from agents.component_base import BasePipelineComponent
from agents.tools.taric_branch_resolver import TaricBranchResolverTool
from agents.blackboard import BlackboardStore, now_iso
from bussiness_logic.utils.json_types import JsonObject, JsonValue


def _read_field(
    obj: object,
    *names: str,
    default: JsonValue | object | None = None,
) -> JsonValue | object | None:
    """Read a field from a dict, dataclass, or object — tries each name."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        for n in names:
            if n in obj and obj[n] is not None:
                return obj[n]
        return default
    if is_dataclass(obj):
        obj = asdict(obj)
        for n in names:
            if n in obj and obj[n] is not None:
                return obj[n]
        return default
    for n in names:
        v = getattr(obj, n, None)
        if v is not None:
            return v
    return default


def _truthy_env(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


class ClassificationAgent(BasePipelineComponent):
    component_name = "Classification_Component"
    stage = "Classification"
    llm_model = "gemma4:26b"  # actual model selected by bridge.RuntimeAdapter

    def __init__(self) -> None:
        super().__init__()
        self._taric_resolver = TaricBranchResolverTool()

    def Run(self, store: BlackboardStore) -> None:
        bb = store.load()
        pes = bb.get("product_evidence_state") or {}
        if not pes:
            raise RuntimeError("No InputEvidenceState on the Blackboard.")
        self.ReadBlackBoard(pes["product_id"])
        routingContext = bb.get("routing_context")
        if isinstance(routingContext, dict):
            routingContextId = str(
                routingContext.get("routing_decision_id")
                or routingContext.get("routing_context_id")
                or ""
            )
            if routingContextId:
                self.ReadBlackBoard(routingContextId)
        else:
            routingContext = None

        # Staged narrowing (opt-in, ASAP_USE_STAGED_CLASSIFIER). Replaces the
        # one-shot external classifier with the hs4->hs6->cn8 narrowing tool.
        # Returns True only when it emitted a candidate set; otherwise we fall
        # through to run_external_classifier (flag-off / missing understanding /
        # staged failure / any error) so baseline behaviour is unchanged.
        if self._maybe_classify_staged(store, pes, routingContext, bb):
            return

        result: ExternalClassificationResult = run_external_classifier(
            pes,
            routing_context=routingContext,
        )

        # Cite candidates from the retriever (every shortlisted CN8).
        for c in result.citations:
            self.CreateCiteSource(
                c["source_table"], c["source_id"],
                snippet=c.get("snippet", ""),
                reason=c.get("reason", ""),
            )

        if result.llm_model:
            self.llm_model = result.llm_model

        if result.error:
            self.reason(f"ASAPExpress classifier returned error: {result.error}")
            self._emit_unresolved(
                store,
                pes,
                why=result.error,
            )
            return

        recommendation = result.recommendation
        if recommendation is None:
            self.reason("No Stage1RecommendationReport produced; emitting needs_more_facts.")
            self._emit_unresolved(
                store,
                pes,
                why="no_recommendation",
            )
            return

        # Extract candidate dicts from the Stage1 recommendation
        recommended = _read_field(recommendation, "recommendedCandidate") or {}
        retained = _read_field(recommendation, "retainedCandidates") or []

        emitted: list[JsonObject] = []
        recommendedCn8 = str(_read_field(recommended, "hs8", default="") or "")[:8]
        retainedByCn8 = {
            str(_read_field(candidate, "hs8", default="") or "")[:8]: candidate
            for candidate in retained
            if str(_read_field(candidate, "hs8", default="") or "")[:8]
        }
        for candidate in result.candidates[:5]:
            if len(emitted) >= 5:
                break
            candidateHs8 = str(_read_field(candidate, "hs8", default="") or "")
            candidateCn8 = candidateHs8[:8]
            hardCondition = self._build_hard_condition_projection(candidate)
            isRecommended = bool(recommendedCn8 and candidateCn8 == recommendedCn8)
            retainedCandidate = retainedByCn8.get(candidateCn8)
            reviewPayload = recommended if isRecommended else retainedCandidate or {}
            reason = _read_field(reviewPayload, "reason", "rationale", default="")
            emitted.append({
                "hs8": candidateHs8,
                "reason": reason or (
                    "LLM-recommended candidate."
                    if isRecommended
                    else "Static CN retrieval top5 candidate retained for comparison."
                ),
                "rank": len(emitted) + 1,
                "status": "proposed",
                "llm_recommended": isRecommended,
                "candidate_static_tree": self._build_candidate_static_tree(candidate),
                "hard_conditions": hardCondition["conditions"],
                "hard_condition_status": hardCondition["status"],
                "hard_condition_evidence": hardCondition["evidence"],
                "supporting_product_facts": self._read_text_list(
                    _read_field(
                        reviewPayload,
                        "supporting_product_facts",
                        "supportingProductFacts",
                        default=[],
                    ),
                    limit=5,
                ),
                "classification_evidence_refs": self._read_text_list(
                    _read_field(
                        reviewPayload,
                        "evidence_refs",
                        "evidenceRefs",
                        default=[],
                    ),
                    limit=8,
                ),
                "similar_ebti_cases": self._read_dict_list(
                    _read_field(
                        reviewPayload,
                        "similar_ebti_cases",
                        "similarEbtiCases",
                        default=[],
                    ),
                    limit=3,
                ),
            })

        decision_status = _read_field(result.decision_report, "decisionStatus", default="unknown")
        traversal_status = _read_field(result.traversal_report, "traversalStatus", default="unknown")
        self.reason(
            f"Stage 1 decision={decision_status} traversal={traversal_status}; "
            f"emitted {len(emitted)} candidate(s)."
        )

        if not emitted:
            self.reason("ASAPExpress returned no recommended/retained candidates.")
            why = f"no_recommendation_or_retained ({decision_status})"
            self._emit_unresolved(
                store,
                pes,
                why=why,
            )
            return

        ccs_id = store.next_id("ccs")
        ccs_candidates: list[JsonObject] = []
        for c in emitted:
            cn8 = (c["hs8"] or "")[:8]
            if not cn8.isdigit() or len(cn8) != 8:
                self.reason(f"Skipped invalid emitted CN8 candidate: {c.get('hs8')!r}.")
                continue
            taric_branches = self._resolve_taric_branches(cn8)
            selected_branch = self._select_taric_branch(taric_branches)
            taric10 = selected_branch.get("taric10") or ""
            if not taric10:
                self.reason(
                    f"No TARIC branch found for CN8={cn8}; taric10 left blank "
                    "instead of synthesizing cn8 + '00'."
                )
            cand_id = store.next_id("cand")
            ccs_candidates.append({
                "candidate_id": cand_id,
                "hs6": cn8[:6],
                "cn8": cn8,
                "taric10": taric10,
                "taric10_branch_candidates": taric_branches,
                "taric10_resolution_mode": (
                    "enumerate_all_under_cn8" if taric_branches else "no_taric_branch_found"
                ),
                "taric10_is_recommended": False,
                "taric10_branch_count": len(taric_branches),
                "rank": len(ccs_candidates) + 1,
                "status": c["status"],
                "candidate_source": "classifier",
                "llm_recommended": bool(c.get("llm_recommended")),
                "candidate_static_tree": c.get("candidate_static_tree") or {},
                "hard_conditions": c.get("hard_conditions") or "",
                "hard_condition_status": (
                    c.get("hard_condition_status") or "not_applicable"
                ),
                "hard_condition_evidence": list(
                    c.get("hard_condition_evidence") or [],
                ),
                "classification_basis": [str(c["reason"])[:600]],
                "supporting_product_facts": list(
                    c.get("supporting_product_facts") or [],
                ),
                "classification_evidence_refs": list(
                    c.get("classification_evidence_refs") or [],
                ),
                "similar_ebti_cases": list(c.get("similar_ebti_cases") or []),
                "classification_citations": list(self._ontology_reads),
                "required_facts": [],
                "unknowns": [],
            })
        if not ccs_candidates:
            self.reason("No valid emitted CN8 candidates remained after validation.")
            self._emit_unresolved(
                store,
                pes,
                why="no_valid_emitted_cn8",
            )
            return
        store.append("candidate_code_sets", {
            "object_type": "ClassificationCandidateSet",
            "created_by": self.component_name,
            "created_at": now_iso(),
            "candidate_set_id": ccs_id,
            "product_id": pes["product_id"],
            "candidates": ccs_candidates,
        })
        self.WriteBlackBoard(ccs_id)
        for c in ccs_candidates:
            self.WriteBlackBoard(c["candidate_id"])

    # ------------------------------------------------------------------
    # Staged narrowing (additive; opt-in). Emits a ClassificationCandidateSet in the
    # exact baseline shape so the Document downstream is unchanged.
    # Failure returns False -> run() falls back to run_external_classifier.
    # ------------------------------------------------------------------
    def _maybe_classify_staged(
        self,
        store: BlackboardStore,
        pes: JsonObject,
        routingContext: JsonObject | None,
        bb: JsonObject,
    ) -> bool:
        import os

        if not _truthy_env(os.environ.get("ASAP_USE_STAGED_CLASSIFIER")):
            return False
        try:
            product_facts = bb.get("product_understanding") or {}
            if not product_facts:
                self.reason("Staged classifier: no product_understanding; using external.")
                return False
            routing = routingContext if isinstance(routingContext, dict) else (
                bb.get("routing_context") or {}
            )

            from agents.tools.staged_classification import StagedClassificationTool

            staged = StagedClassificationTool().classify(
                product_facts=product_facts,
                routing_context=routing,
            )
            stages = staged.get("stages") or []
            candidates = staged.get("candidates") or []
            if not staged.get("ok") or not candidates:
                self.reason(
                    "Staged classifier fell back to external "
                    f"(error={staged.get('error') or 'no_candidates'})."
                )
                return False

            ccs_id = store.next_id("ccs")
            ccs_candidates: list[JsonObject] = []
            for candidate in candidates[:5]:
                cn8 = str(candidate.get("cn8") or "")[:8]
                if not cn8.isdigit() or len(cn8) != 8:
                    continue
                taric_branches = self._resolve_taric_branches(cn8)
                selected_branch = self._select_taric_branch(taric_branches)
                taric10 = selected_branch.get("taric10") or ""
                rank = len(ccs_candidates) + 1
                ccs_candidates.append({
                    "candidate_id": store.next_id("cand"),
                    "hs6": cn8[:6],
                    "cn8": cn8,
                    "taric10": taric10,
                    "taric10_branch_candidates": taric_branches,
                    "taric10_resolution_mode": (
                        "enumerate_all_under_cn8" if taric_branches else "no_taric_branch_found"
                    ),
                    "taric10_is_recommended": False,
                    "taric10_branch_count": len(taric_branches),
                    "rank": rank,
                    "status": "proposed",
                    "candidate_source": "staged_classifier",
                    "llm_recommended": rank == 1,
                    "candidate_static_tree": self._staged_static_tree(candidate),
                    "hard_conditions": "",
                    "hard_condition_status": "not_applicable",
                    "hard_condition_evidence": [],
                    "classification_basis": [self._staged_basis(candidate)],
                    "supporting_product_facts": [],
                    "classification_evidence_refs": [],
                    "similar_ebti_cases": [],
                    "classification_citations": list(getattr(self, "_ontology_reads", []) or []),
                    "required_facts": [],
                    "unknowns": [],
                })

            if not ccs_candidates:
                self.reason("Staged classifier produced no valid CN8; using external.")
                return False

            store.append("candidate_code_sets", {
                "object_type": "ClassificationCandidateSet",
                "created_by": self.component_name,
                "created_at": now_iso(),
                "candidate_set_id": ccs_id,
                "product_id": pes["product_id"],
                "candidates": ccs_candidates,
            })
            self.WriteBlackBoard(ccs_id)
            for c in ccs_candidates:
                self.WriteBlackBoard(c["candidate_id"])
            self.reason(
                f"Staged narrowing emitted {len(ccs_candidates)} candidate(s) "
                f"(hs4->hs6->cn8, {len(stages)} stages)."
            )
            return True
        except Exception as exc:  # noqa: BLE001 — never break; fall back to external
            self.reason(f"Staged classifier error ({exc!r}); using external.")
            return False

    def _staged_static_tree(self, candidate: JsonObject) -> JsonObject:
        nodes: list[JsonObject] = []
        for level, label in (("hs4", "HS4"), ("hs6", "HS6"), ("cn8", "CN8")):
            code = str(candidate.get(level) or "").strip()
            if not code:
                continue
            nodes.append({
                "level": level,
                "label": label,
                "code": code,
                "description": str(candidate.get("description") or "") if level == "cn8" else "",
                "score": float(candidate.get("score") or 0.0) if level == "cn8" else 0.0,
                "matched_keywords": [],
            })
        return {
            "total_score": float(candidate.get("score") or 0.0),
            "retrieval_sources": ["staged_narrowing"],
            "nodes": nodes,
        }

    def _staged_basis(self, candidate: JsonObject) -> str:
        desc = str(candidate.get("description") or "")[:160]
        verdict = str(candidate.get("quantitative_verdict") or "")
        base = f"Staged narrowing hs4->hs6->cn8 selected CN8={candidate.get('cn8')}: {desc}"
        if verdict and verdict != "neutral":
            base += f" [%-gate: {verdict}]"
        return base[:600]

    def _build_candidate_static_tree(self, candidate: object) -> JsonObject:
        codeHierarchy = _read_field(candidate, "codeHierarchy", "code_hierarchy", default={}) or {}
        if not isinstance(codeHierarchy, dict):
            codeHierarchy = {}
        scoreBreakdown = _read_field(candidate, "scoreBreakdown", "score_breakdown", default={}) or {}
        if not isinstance(scoreBreakdown, dict):
            scoreBreakdown = {}
        hardCondition = self._build_hard_condition_projection(candidate)
        hierarchyPoints = scoreBreakdown.get("hierarchy_level_points") or {}
        hierarchyMatches = scoreBreakdown.get("hierarchy_level_matches") or {}
        if not isinstance(hierarchyPoints, dict):
            hierarchyPoints = {}
        if not isinstance(hierarchyMatches, dict):
            hierarchyMatches = {}

        nodes: list[JsonObject] = []
        for level, label in (
            ("hs2", "HS2"),
            ("hs4", "HS4"),
            ("hs6", "HS6"),
            ("cn8", "CN8"),
        ):
            levelData = codeHierarchy.get(level) or {}
            if not isinstance(levelData, dict):
                levelData = {}
            code = str(levelData.get("code") or "").strip()
            if not code:
                continue
            nodes.append({
                "level": level,
                "label": label,
                "code": code,
                "description": str(levelData.get("description") or "").strip(),
                "score": hierarchyPoints.get(level) or (
                    _read_field(candidate, "score", default=0.0)
                    if level == "cn8"
                    else 0.0
                ),
                "matched_keywords": self._read_text_list(
                    hierarchyMatches.get(level),
                    limit=8,
                ),
            })

        return {
            "total_score": _read_field(candidate, "score", default=0.0) or 0.0,
            "retrieval_sources": self._read_text_list(
                _read_field(candidate, "retrievalSources", "retrieval_sources", default=[]),
                limit=4,
            ),
            "matched_keywords": self._read_text_list(
                _read_field(candidate, "matchedTerms", "matched_terms", default=[]),
                limit=12,
            ),
            "score_breakdown": {
                "include_rule_points": scoreBreakdown.get("include_rule_points") or 0.0,
                "search_keyword_points": scoreBreakdown.get("search_keyword_points") or 0.0,
                "description_points": scoreBreakdown.get("description_points") or 0.0,
                "semantic_score": scoreBreakdown.get("semantic_score"),
            },
            "hard_condition": hardCondition,
            "nodes": nodes,
        }

    def _build_hard_condition_projection(self, candidate: object) -> JsonObject:
        scoreBreakdown = _read_field(
            candidate,
            "scoreBreakdown",
            "score_breakdown",
            default={},
        ) or {}
        if not isinstance(scoreBreakdown, dict):
            scoreBreakdown = {}
        status = str(
            _read_field(
                candidate,
                "hardConditionStatus",
                "hard_condition_status",
                default=None,
            )
            or scoreBreakdown.get("hard_condition_status")
            or "not_applicable"
        ).strip() or "not_applicable"
        evidenceValue = _read_field(
            candidate,
            "hardConditionEvidence",
            "hard_condition_evidence",
            default=None,
        )
        if evidenceValue is None:
            evidenceValue = scoreBreakdown.get("hard_condition_evidence")
        return {
            "conditions": str(
                _read_field(
                    candidate,
                    "hardConditions",
                    "hard_conditions",
                    default="",
                )
                or ""
            ).strip(),
            "status": status,
            "evidence": self._read_text_list(evidenceValue, limit=8),
        }

    @staticmethod
    def _read_text_list(value: object, *, limit: int) -> list[str]:
        if not isinstance(value, (list, tuple)):
            return []
        return [
            str(item).strip()
            for item in value[:limit]
            if str(item).strip()
        ]

    @staticmethod
    def _read_dict_list(value: object, *, limit: int) -> list[JsonObject]:
        if not isinstance(value, (list, tuple)):
            return []
        return [
            dict(item)
            for item in value[:limit]
            if isinstance(item, dict)
        ]

    def _resolve_taric_branches(self, cn8: str) -> list[JsonObject]:
        if not cn8 or cn8 == "99999999":
            return []
        try:
            branches = self._taric_resolver.resolve(
                cn8,
                only_declarable_leaf=False,
                only_kr_applicable=False,
            )
        except Exception as exc:  # noqa: BLE001
            self.reason(f"TaricBranchResolverTool error for CN8={cn8}: {exc}")
            return []

        out = [b.to_dict() for b in branches]
        if out:
            self.CreateCiteSource(
                "taric_master_table",
                f"cn8={cn8}",
                snippet=f"{len(out)} TARIC10 branch candidate(s)",
                reason="TaricBranchResolverTool branch retrieval.",
            )
        return out

    # ------------------------------------------------------------------ helpers
    def _select_taric_branch(self, branches: list[JsonObject]) -> JsonObject:
        """Pick a compatibility primary TARIC10 from deterministic branches.

        This is not a legal recommendation. The full branch list remains on
        the candidate and Document_Component packages every branch. The primary
        value only preserves older UI/API paths that expect cand["taric10"].
        """
        if not branches:
            return {}

        def score(branch: JsonObject) -> tuple[int, int, int, int, int]:
            description = (branch.get("branch_description") or "").strip().lower()
            return (
                1 if branch.get("applies_to_origin_kr") else 0,
                1 if branch.get("is_declarable_leaf") else 0,
                0 if branch.get("needs_review") else 1,
                int(branch.get("measure_row_count") or 0),
                1 if description == "other" else 0,
            )

        selected = max(branches, key=score)
        out = dict(selected)
        out["selection_reason"] = (
            "Compatibility primary only, not a TARIC10 recommendation. "
            "All TARIC master branches under this CN8 are retained in "
            "taric10_branch_candidates; this primary prefers KR-applicable "
            "declarable leaves, then non-review branches, then measure coverage."
        )
        return out
    def _emit_unresolved(
        self,
        store: BlackboardStore,
        pes: dict,
        *,
        why: str,
    ) -> None:
        ccs_id = store.next_id("ccs")
        candidateCodeSet = {
            "object_type": "ClassificationCandidateSet",
            "created_by": self.component_name,
            "created_at": now_iso(),
            "candidate_set_id": ccs_id,
            "product_id": pes["product_id"],
            "classification_status": "needs_more_facts",
            "failure_reason": why,
            "shortlisted_candidates": list(self._ontology_reads),
            "candidates": [],
        }
        store.append("candidate_code_sets", candidateCodeSet)
        self.WriteBlackBoard(ccs_id)
        self.reason(
            f"Classification unresolved ({why}); wrote empty ClassificationCandidateSet "
            "instead of a synthetic 99999999 candidate."
        )

