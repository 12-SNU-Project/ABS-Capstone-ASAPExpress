"""TARIC branch resolution component.

Classification owns CN8 candidate selection. This component promotes the
deterministic CN8 -> TARIC10 branch universe into its own Blackboard object
so anti-dumping/countervailing duty, additional-code, and certificate-code
checks do not depend on a single compatibility TARIC10 value.
"""
from __future__ import annotations

from typing import Any

from bussiness_logic.pipeline.blackboard import BlackboardStore, now_iso
from bussiness_logic.pipeline.component_base import BasePipelineComponent
from bussiness_logic.pipeline.model.schema import CandidateTaricBranchSet, TaricBranchSet
from bussiness_logic.classification.services.taric_branch_resolver import TaricBranchResolverTool
from bussiness_logic.utils.json_types import JsonObject


class TaricBranchResolutionComponent(BasePipelineComponent):
    component_name = "Taric_Branch_Resolution_Component"
    stage = "Taric_Branch_Resolution"
    llm_model = None

    def __init__(self) -> None:
        super().__init__()
        self._taric_resolver = TaricBranchResolverTool()

    def Run(self, store: BlackboardStore) -> None:
        bb = store.load()
        candidateSets = bb.get("candidate_code_sets") or []
        if not candidateSets:
            self.reason("No CandidateCodeSet present; nothing to resolve.")
            return

        latest = candidateSets[-1]
        candidateSetId = str(latest.get("candidate_set_id") or "")
        productId = str(latest.get("product_id") or "")
        self.ReadBlackBoard(candidateSetId)

        candidateBranches: list[CandidateTaricBranchSet] = []
        for cand in latest.get("candidates") or []:
            if not isinstance(cand, dict):
                continue
            candidateId = str(cand.get("candidate_id") or "")
            if candidateId:
                self.ReadBlackBoard(candidateId)
            cn8 = self._cn8(cand)
            if not cn8:
                continue

            branches = self._branch_dicts(cand.get("taric10_branch_candidates"))
            notes: list[str] = []
            if branches:
                notes.append("reused classification candidate taric10_branch_candidates")
            else:
                branches = self._resolve_branches(cn8)
                notes.append("resolved branches from taric_master_table")

            selected = self._select_primary_branch(branches)
            declarableCount = sum(1 for branch in branches if branch.get("is_declarable_leaf"))
            status = self._branch_status(branches, declarableCount)
            candidateBranches.append(
                CandidateTaricBranchSet(
                    candidateId=candidateId,
                    candidateRank=int(cand.get("rank") or len(candidateBranches) + 1),
                    hs6=str(cand.get("hs6") or cn8[:6]),
                    cn8=cn8,
                    branchStatus=status,
                    primaryTaric10=str(selected.get("taric10") or cand.get("taric10") or ""),
                    branchCount=len(branches),
                    declarableBranchCount=declarableCount,
                    branches=tuple(branches),
                    resolutionNotes=tuple(notes),
                )
            )

        if not candidateBranches:
            self.reason("No valid CN8 candidates remained for TARIC branch resolution.")
            return

        tbsId = store.next_id("tbs")
        obj = TaricBranchSet(
            taricBranchSetId=tbsId,
            productId=productId,
            sourceCandidateSetId=candidateSetId,
            candidateBranches=tuple(candidateBranches),
        ).ToBlackboard(
            createdBy=self.component_name,
            createdAt=now_iso(),
        )
        store.append("taric_branch_sets", obj)
        self.WriteBlackBoard(tbsId)
        self.reason(
            f"TaricBranchSet {tbsId}: resolved {len(candidateBranches)} candidate(s), "
            f"{sum(cb.branchCount for cb in candidateBranches)} branch row(s)."
        )

    def _resolve_branches(self, cn8: str) -> list[JsonObject]:
        try:
            branches = self._taric_resolver.resolve(
                cn8,
                only_declarable_leaf=False,
                only_kr_applicable=False,
            )
        except Exception as exc:  # noqa: BLE001
            self.reason(f"TaricBranchResolverTool error for CN8={cn8}: {exc}")
            return []
        out = [branch.to_dict() for branch in branches]
        if out:
            self.CreateCiteSource(
                "taric_master_table",
                f"cn8={cn8}",
                snippet=f"{len(out)} TARIC10 branch candidate(s)",
                reason="TaricBranchResolutionComponent branch retrieval.",
            )
        return out

    @staticmethod
    def _cn8(candidate: JsonObject) -> str:
        raw = str(candidate.get("cn8") or candidate.get("hs8") or "")[:8]
        return raw if raw.isdigit() and len(raw) == 8 else ""

    @staticmethod
    def _branch_dicts(value: Any) -> list[JsonObject]:
        if not isinstance(value, list):
            return []
        out: list[JsonObject] = []
        for item in value:
            if isinstance(item, dict):
                taric10 = str(item.get("taric10") or "")
                if taric10 and not taric10.startswith("99999999"):
                    out.append(dict(item))
        return out

    @staticmethod
    def _branch_status(branches: list[JsonObject], declarable_count: int) -> str:
        if not branches:
            return "no_taric_branch_found"
        if declarable_count == 0:
            return "non_declarable_only"
        if declarable_count == 1:
            return "single_declarable_leaf"
        return "multiple_declarable_leaves"

    @staticmethod
    def _select_primary_branch(branches: list[JsonObject]) -> JsonObject:
        """Compatibility-only primary; the full branch list remains authoritative."""
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

        selected = dict(max(branches, key=score))
        selected["selection_reason"] = (
            "Compatibility primary only, not a TARIC10 recommendation. "
            "All TARIC master branches under this CN8 are retained."
        )
        return selected
