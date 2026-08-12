"""TARIC branch pipeline models."""

from __future__ import annotations

from dataclasses import dataclass, field

from bussiness_logic.utils.json_types import JsonValue


def _desc(text: str) -> dict[str, str]:
    return {"description": text}


@dataclass(frozen=True, slots=True)
class CandidateTaricBranchSet:
    candidateId: str = field(metadata=_desc("원천 CandidateCodeSet 후보 ID"))
    candidateRank: int = field(metadata=_desc("분류 후보 순위"))
    hs6: str = field(metadata=_desc("후보 HS6"))
    cn8: str = field(metadata=_desc("후보 CN8"))
    branchStatus: str = field(metadata=_desc("TARIC10 branch 해석 상태"))
    primaryTaric10: str = field(default="", metadata=_desc("호환성용 대표 TARIC10"))
    primaryIsCompatibilityOnly: bool = field(
        default=True,
        metadata=_desc("대표 TARIC10이 법적 추천이 아닌 UI/API 호환값인지 여부"),
    )
    branchCount: int = field(default=0, metadata=_desc("CN8 하위 TARIC10 branch 수"))
    declarableBranchCount: int = field(default=0, metadata=_desc("신고 가능한 leaf branch 수"))
    branches: tuple[dict[str, JsonValue], ...] = field(
        default=(),
        metadata=_desc("CN8 하위 모든 TARIC10 branch 후보"),
    )
    resolutionNotes: tuple[str, ...] = field(default=(), metadata=_desc("해석 주석"))

    def ToTrace(self) -> dict[str, JsonValue]:
        return {
            "candidate_id": self.candidateId,
            "candidate_rank": self.candidateRank,
            "hs6": self.hs6,
            "cn8": self.cn8,
            "branch_status": self.branchStatus,
            "primary_taric10": self.primaryTaric10,
            "primary_is_compatibility_only": self.primaryIsCompatibilityOnly,
            "branch_count": self.branchCount,
            "declarable_branch_count": self.declarableBranchCount,
            "branches": [dict(branch) for branch in self.branches],
            "resolution_notes": list(self.resolutionNotes),
        }


@dataclass(frozen=True, slots=True)
class TaricBranchSet:
    taricBranchSetId: str = field(metadata=_desc("TARIC branch 묶음 ID"))
    productId: str = field(metadata=_desc("대상 상품 ID"))
    sourceCandidateSetId: str = field(metadata=_desc("원천 CandidateCodeSet ID"))
    candidateBranches: tuple[CandidateTaricBranchSet, ...] = field(
        metadata=_desc("분류 후보별 TARIC10 branch 묶음"),
    )

    def ToBlackboard(self, *, createdBy: str, createdAt: str) -> dict[str, JsonValue]:
        return {
            "object_type": "TaricBranchSet",
            "created_by": createdBy,
            "created_at": createdAt,
            "taric_branch_set_id": self.taricBranchSetId,
            "product_id": self.productId,
            "source_candidate_set_id": self.sourceCandidateSetId,
            "candidate_branches": [
                candidateBranch.ToTrace()
                for candidateBranch in self.candidateBranches
            ],
        }
