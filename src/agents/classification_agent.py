"""
Classification_Agent — delegates to ASAPExpress Stage 1 classifier.

Inside BaseAgent.execute() this agent:
  1. Reads ProductEvidenceState from the Blackboard.
  2. Hands it to agents._external_classifier.run_external_classifier(),
     which runs the full ASAPExpress 7-step Stage 1 pipeline
     (retriever → context → evidence → request → LLM → validator →
     decision → traversal → recommendation).
  3. Translates the Stage1RecommendationReport back into CandidateCode
     entries and stamps citations + reasoning trace.

ASAPExpress code is loaded as-is via sys.path — no modifications.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass

from agents._external_classifier import (
    ExternalClassificationResult,
    run_external_classifier,
)
from agents.agent_base import BaseAgent
from agents.tools import TaricBranchResolverTool
from agents.blackboard import BlackboardStore, now_iso


def _read_field(obj, *names, default=None):
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


class ClassificationAgent(BaseAgent):
    agent_name = "Classification_Agent"
    stage = "Classification"
    llm_model = "gemma4:26b"  # actual model selected by bridge.RuntimeAdapter

    def __init__(self) -> None:
        super().__init__()
        self._taric_resolver = TaricBranchResolverTool()

    def run(self, store: BlackboardStore) -> None:
        bb = store.load()
        pes = bb.get("product_evidence_state") or {}
        if not pes:
            raise RuntimeError("No ProductEvidenceState on the Blackboard.")
        self.read_input(pes["product_id"])

        # Step 0 — handle pending challenges first. If another agent has
        # raised an open challenge against one of our candidates, write a
        # ChallengeResponse instead of running ASAPExpress Stage 1 again.
        open_challenges = self._read_open_challenges_for_me(bb)
        if open_challenges:
            self._respond_to_challenges(store, open_challenges)
            return

        result: ExternalClassificationResult = run_external_classifier(pes)

        # Cite candidates from the retriever (every shortlisted CN8).
        for c in result.citations:
            self.cite(
                c["source_table"], c["source_id"],
                snippet=c.get("snippet", ""),
                reason=c.get("reason", ""),
            )

        if result.prompt_text:
            self.record_prompt(result.prompt_text)
        if result.llm_model:
            self.llm_model = result.llm_model

        if result.error:
            self.reason(f"ASAPExpress classifier returned error: {result.error}")
            self._emit_unresolved(store, pes, why=result.error)
            return

        # Preserve the LLM response excerpt in reasoning_summary so the admin
        # viewer can debug Stage1ResponseValidator rejections.
        resp_snippet = (result.llm_response_text or "").strip()
        if resp_snippet:
            self.reason(f"LLM response[:300]: {resp_snippet[:300]!r}")

        recommendation = result.recommendation
        if recommendation is None:
            self.reason("No Stage1RecommendationReport produced; emitting needs_more_facts.")
            self._emit_unresolved(store, pes, why="no_recommendation")
            return

        # Extract candidate dicts from the Stage1 recommendation
        recommended = _read_field(recommendation, "recommendedCandidate") or {}
        retained = _read_field(recommendation, "retainedCandidates") or []

        emitted: list[dict] = []
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
            reason = (
                _read_field(recommended, "reason", "rationale", default="")
                if isRecommended
                else _read_field(retainedCandidate, "reason", "rationale", default="")
            )
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
            self._emit_unresolved(store, pes, why=why)
            return

        ccs_id = store.next_id("ccs")
        ccs_candidates: list[dict] = []
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
                "selected_taric10_reason": (
                    selected_branch.get("selection_reason")
                    if taric10 else "No TARIC10 branch resolved from current master table."
                ),
                "primary_taric10_reason": (
                    selected_branch.get("selection_reason")
                    if taric10 else "No TARIC10 branch resolved from current master table."
                ),
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
                "classification_basis": [str(c["reason"])[:300]],
                "classification_citations": list(self._ontology_reads),
                "required_facts": [],
                "unknowns": [],
            })
        if not ccs_candidates:
            self.reason("No valid emitted CN8 candidates remained after validation.")
            self._emit_unresolved(store, pes, why="no_valid_emitted_cn8")
            return
        store.append("candidate_code_sets", {
            "object_type": "CandidateCodeSet",
            "created_by": self.agent_name,
            "created_at": now_iso(),
            "candidate_set_id": ccs_id,
            "product_id": pes["product_id"],
            "candidates": ccs_candidates,
        })
        self.wrote(ccs_id)
        for c in ccs_candidates:
            self.wrote(c["candidate_id"])

    def _build_candidate_static_tree(self, candidate) -> dict:
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

        nodes: list[dict] = []
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

    def _build_hard_condition_projection(self, candidate) -> dict:
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
    def _read_text_list(value, *, limit: int) -> list[str]:
        if not isinstance(value, (list, tuple)):
            return []
        return [
            str(item).strip()
            for item in value[:limit]
            if str(item).strip()
        ]

    def _resolve_taric_branches(self, cn8: str) -> list[dict]:
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
            self.cite(
                "taric_master_table",
                f"cn8={cn8}",
                snippet=f"{len(out)} TARIC10 branch candidate(s)",
                reason="TaricBranchResolverTool branch retrieval.",
            )
        return out

    # ------------------------------------------------------------------ challenges
    def _collect_my_candidate_ids(self, bb: dict) -> set[str]:
        """All candidate IDs from CCS authored by this agent."""
        out: set[str] = set()
        for ccs in bb.get("candidate_code_sets") or []:
            if ccs.get("created_by") != self.agent_name:
                continue
            for c in ccs.get("candidates") or []:
                cid = c.get("candidate_id")
                if cid:
                    out.add(cid)
        return out

    def _select_taric_branch(self, branches: list[dict]) -> dict:
        """Pick a compatibility primary TARIC10 from deterministic branches.

        This is not a legal recommendation. The full branch list remains on
        the candidate and Document_Agent packages every branch. The primary
        value only preserves older UI/API paths that expect cand["taric10"].
        """
        if not branches:
            return {}

        def score(branch: dict) -> tuple:
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

    def _read_open_challenges_for_me(self, bb: dict) -> list[dict]:
        """Open challenges that target one of our candidates and were raised
        by someone else. We skip our own challenges and resolved ones.
        """
        my_cands = self._collect_my_candidate_ids(bb)
        if not my_cands:
            return []
        out: list[dict] = []
        for chg in bb.get("challenges") or []:
            if chg.get("status") != "open":
                continue
            if chg.get("raised_by") == self.agent_name:
                continue
            target = chg.get("target_candidate_id")
            if target and target in my_cands:
                out.append(chg)
        return out

    def _respond_to_challenges(
        self,
        store: BlackboardStore,
        challenges: list[dict],
    ) -> None:
        """For each open challenge against our candidate, write a single
        ChallengeResponse AND close the source challenge (status=resolved).

        Decision rule (stub):
          - challenge_type == measure_document_mismatch  → needs_more_facts
            (Classification cannot invent product facts on its own.)
          - any other type                                → needs_more_facts
            (until a richer decision policy is wired in.)
        """
        target_chg_ids = {chg["challenge_id"] for chg in challenges}
        bb = store.load()
        for chg in challenges:
            self.read_input(chg["challenge_id"])
            chg_type = chg.get("challenge_type") or "unknown"
            target_cand = chg.get("target_candidate_id") or "?"
            if chg_type == "measure_document_mismatch":
                reason_text = (
                    f"Candidate {target_cand} returned no TARIC measure rows. "
                    "Classification cannot reclassify without additional product "
                    "facts (composition pct, intended use, processing state, "
                    "establishment approval). Routing to the user."
                )
            else:
                reason_text = (
                    f"Acknowledged challenge {chg['challenge_id']} of type "
                    f"{chg_type}; no automatic action available — escalating."
                )

            resp_id = store.next_id("rsp")
            store.append("challenge_responses", {
                "object_type": "ChallengeResponse",
                "created_by": self.agent_name,
                "created_at": now_iso(),
                "response_id": resp_id,
                "responds_to": chg["challenge_id"],
                "action": "needs_more_facts",
                "reason": reason_text,
                "updates": [],
                "status": "resolved",
            })
            self.wrote(resp_id)
            self.reason(
                f"Wrote ChallengeResponse {resp_id} to {chg['challenge_id']} "
                f"({chg_type}, raised_by={chg.get('raised_by')}) → "
                "action=needs_more_facts."
            )
        # Close the source Challenges so Orchestrator does not count them
        # as still-open. store.append above re-loaded internally, so we
        # do a final load+save here to mutate challenges in place.
        bb = store.load()
        for c in bb.get("challenges") or []:
            if c.get("challenge_id") in target_chg_ids and c.get("status") == "open":
                c["status"] = "resolved"
        store.save(bb)

    # ------------------------------------------------------------------ helpers
    def _emit_unresolved(self, store: BlackboardStore, pes: dict, *, why: str) -> None:
        ccs_id = store.next_id("ccs")
        store.append("candidate_code_sets", {
            "object_type": "CandidateCodeSet",
            "created_by": self.agent_name,
            "created_at": now_iso(),
            "candidate_set_id": ccs_id,
            "product_id": pes["product_id"],
            "classification_status": "needs_more_facts",
            "failure_reason": why,
            "shortlisted_candidates": list(self._ontology_reads),
            "candidates": [],
        })
        self.wrote(ccs_id)
        self.reason(
            f"Classification unresolved ({why}); wrote empty CandidateCodeSet "
            "instead of a synthetic 99999999 candidate."
        )
