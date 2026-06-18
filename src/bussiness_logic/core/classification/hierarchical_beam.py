"""CN 계층 인덱스와 결정적 Beam 선택 규칙."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence


HIERARCHY_LEVEL_HS2 = "hs2"
HIERARCHY_LEVEL_HS4 = "hs4"
HIERARCHY_LEVEL_HS6 = "hs6"
HIERARCHY_LEVEL_CN8 = "cn8"
HIERARCHY_LEVELS = (
    HIERARCHY_LEVEL_HS2,
    HIERARCHY_LEVEL_HS4,
    HIERARCHY_LEVEL_HS6,
    HIERARCHY_LEVEL_CN8,
)


@dataclass(frozen=True, slots=True)
class HierarchyBeamConfig:
    """부모별 Beam 폭과 레벨별 전역 상한."""

    hs2PerParent: int = 3
    hs4PerParent: int = 3
    hs6PerParent: int = 3
    hs2GlobalLimit: int = 3
    hs4GlobalLimit: int = 9
    hs6GlobalLimit: int = 18
    semanticSlotsPerParent: int = 1

    def GetPerParentLimit(self, level: str) -> int:
        if level == HIERARCHY_LEVEL_HS2:
            return self.hs2PerParent
        if level == HIERARCHY_LEVEL_HS4:
            return self.hs4PerParent
        if level == HIERARCHY_LEVEL_HS6:
            return self.hs6PerParent
        raise ValueError(f"Unsupported Beam level: {level}")

    def GetGlobalLimit(self, level: str) -> int:
        if level == HIERARCHY_LEVEL_HS2:
            return self.hs2GlobalLimit
        if level == HIERARCHY_LEVEL_HS4:
            return self.hs4GlobalLimit
        if level == HIERARCHY_LEVEL_HS6:
            return self.hs6GlobalLimit
        raise ValueError(f"Unsupported Beam level: {level}")


@dataclass(frozen=True, slots=True)
class CnHierarchyNode:
    """CN table에서 중복 제거한 단일 계층 노드."""

    domainScope: str
    level: str
    code: str
    parentCode: str
    row: Mapping[str, str]
    childDescriptionText: str = ""
    childKeywordText: str = ""


@dataclass(frozen=True, slots=True)
class HierarchyNodeScore:
    """한 계층 노드의 정적 점수와 근거."""

    node: CnHierarchyNode
    score: float
    includePoints: float = 0.0
    keywordPoints: float = 0.0
    descriptionPoints: float = 0.0
    includeMatches: tuple[str, ...] = ()
    keywordMatches: tuple[str, ...] = ()
    descriptionMatches: tuple[str, ...] = ()
    primaryMatches: tuple[str, ...] = ()
    secondaryMatches: tuple[str, ...] = ()
    weakMatches: tuple[str, ...] = ()
    matchedTerms: tuple[str, ...] = ()
    excludedTerms: tuple[str, ...] = ()
    hardConditionStatus: str = "not_applicable"
    hardConditionEvidence: tuple[str, ...] = ()
    semanticScore: float | None = None
    semanticMatches: tuple[Mapping[str, object], ...] = ()

    @property
    def primaryMatchCount(self) -> int:
        return len(self.primaryMatches)

    @property
    def secondaryMatchCount(self) -> int:
        return len(self.secondaryMatches)

    @property
    def isExcluded(self) -> bool:
        return bool(self.excludedTerms) or self.hardConditionStatus == "contradicted"


@dataclass(frozen=True, slots=True)
class HierarchyBeamPath:
    """루트부터 현재 노드까지의 누적 경로."""

    domainScope: str
    nodes: tuple[HierarchyNodeScore, ...] = ()
    retrievalSources: tuple[str, ...] = ("heuristic",)

    @property
    def currentNode(self) -> HierarchyNodeScore:
        if not self.nodes:
            raise ValueError("Empty Beam path has no current node.")
        return self.nodes[-1]

    @property
    def cumulativeScore(self) -> float:
        return round(sum(nodeScore.score for nodeScore in self.nodes), 6)

    @property
    def primaryMatchCount(self) -> int:
        return sum(nodeScore.primaryMatchCount for nodeScore in self.nodes)

    @property
    def secondaryMatchCount(self) -> int:
        return sum(nodeScore.secondaryMatchCount for nodeScore in self.nodes)

    def Extend(
        self,
        nodeScore: HierarchyNodeScore,
        *,
        semanticSelected: bool = False,
    ) -> "HierarchyBeamPath":
        retrievalSources = list(self.retrievalSources)
        if semanticSelected and "semantic" not in retrievalSources:
            retrievalSources.append("semantic")
        return HierarchyBeamPath(
            domainScope=self.domainScope,
            nodes=(*self.nodes, nodeScore),
            retrievalSources=tuple(retrievalSources),
        )

    def ReadCode(self, level: str) -> str:
        for nodeScore in self.nodes:
            if nodeScore.node.level == level:
                return nodeScore.node.code
        return ""


@dataclass(frozen=True, slots=True)
class HierarchyLevelSelection:
    """한 부모 아래에서 점수화된 노드와 semantic recall 코드를 묶는다."""

    nodeScores: tuple[HierarchyNodeScore, ...]
    semanticCodes: tuple[str, ...] = ()
    residualCodes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class HierarchySearchBoundary:
    """백트래킹 시 레벨별 허용·제외 코드 범위를 고정한다."""

    allowedCodesByLevel: Mapping[str, frozenset[str]] = field(
        default_factory=dict,
    )
    excludedCodesByLevel: Mapping[str, frozenset[str]] = field(
        default_factory=dict,
    )

    def Allows(self, level: str, code: str) -> bool:
        allowedCodes = self.allowedCodesByLevel.get(level)
        if allowedCodes is not None and code not in allowedCodes:
            return False
        return code not in self.excludedCodesByLevel.get(level, frozenset())


class CnHierarchyIndex:
    """CN leaf 행을 부모-자식 계층 인덱스로 변환한다."""

    def __init__(
        self,
        rowsByDomainScope: Mapping[str, Sequence[Mapping[str, str]]],
    ) -> None:
        rowByIdentity: dict[tuple[str, str, str], Mapping[str, str]] = {}
        parentByIdentity: dict[tuple[str, str, str], str] = {}
        childDescriptionsByIdentity: dict[
            tuple[str, str, str],
            set[str],
        ] = {}
        childKeywordsByIdentity: dict[
            tuple[str, str, str],
            set[str],
        ] = {}
        for domainScope, rows in rowsByDomainScope.items():
            for row in rows:
                codes = self._ReadCodes(row)
                if any(not codes[level] for level in HIERARCHY_LEVELS):
                    continue
                parentByLevel = {
                    HIERARCHY_LEVEL_HS2: "",
                    HIERARCHY_LEVEL_HS4: codes[HIERARCHY_LEVEL_HS2],
                    HIERARCHY_LEVEL_HS6: codes[HIERARCHY_LEVEL_HS4],
                    HIERARCHY_LEVEL_CN8: codes[HIERARCHY_LEVEL_HS6],
                }
                for level in HIERARCHY_LEVELS:
                    code = codes[level]
                    parentCode = parentByLevel[level]
                    identity = (domainScope, level, code)
                    rowByIdentity.setdefault(identity, row)
                    parentByIdentity.setdefault(identity, parentCode)
                    childDescription, childKeywords = (
                        self._ReadImmediateChildTexts(row, level)
                    )
                    if childDescription:
                        childDescriptionsByIdentity.setdefault(
                            identity,
                            set(),
                        ).add(childDescription)
                    if childKeywords:
                        childKeywordsByIdentity.setdefault(
                            identity,
                            set(),
                        ).add(childKeywords)

        childrenByKey: dict[
            tuple[str, str, str],
            dict[str, CnHierarchyNode],
        ] = {}
        for identity, row in rowByIdentity.items():
            domainScope, level, code = identity
            parentCode = parentByIdentity[identity]
            key = (domainScope, level, parentCode)
            childrenByKey.setdefault(key, {})[code] = CnHierarchyNode(
                domainScope=domainScope,
                level=level,
                code=code,
                parentCode=parentCode,
                row=row,
                childDescriptionText="; ".join(
                    sorted(childDescriptionsByIdentity.get(identity, ())),
                ),
                childKeywordText="; ".join(
                    sorted(childKeywordsByIdentity.get(identity, ())),
                ),
            )
        self._childrenByKey = {
            key: tuple(
                nodesByCode[code]
                for code in sorted(nodesByCode)
            )
            for key, nodesByCode in childrenByKey.items()
        }
        nodesByDomainAndLevel: dict[
            tuple[str, str],
            list[CnHierarchyNode],
        ] = {}
        for children in self._childrenByKey.values():
            for node in children:
                nodesByDomainAndLevel.setdefault(
                    (node.domainScope, node.level),
                    [],
                ).append(node)
        self._nodesByDomainAndLevel = {
            key: tuple(sorted(nodes, key=lambda node: node.code))
            for key, nodes in nodesByDomainAndLevel.items()
        }

    def GetChildren(
        self,
        domainScope: str,
        level: str,
        parentCode: str = "",
    ) -> tuple[CnHierarchyNode, ...]:
        return self._childrenByKey.get(
            (domainScope, level, parentCode),
            (),
        )

    def GetNodes(
        self,
        domainScope: str,
        level: str,
    ) -> tuple[CnHierarchyNode, ...]:
        return self._nodesByDomainAndLevel.get((domainScope, level), ())

    def _ReadCodes(self, row: Mapping[str, str]) -> dict[str, str]:
        return {
            HIERARCHY_LEVEL_HS2: (
                row.get("chapter", "")
                or row.get("hs2_code", "")
            ).strip(),
            HIERARCHY_LEVEL_HS4: (
                row.get("heading", "")
                or row.get("hs4_code", "")
            ).strip(),
            HIERARCHY_LEVEL_HS6: (
                row.get("subheading", "")
                or row.get("hs6_code", "")
            ).strip(),
            HIERARCHY_LEVEL_CN8: (
                row.get("cn", "")
                or row.get("hs8", "")
                or row.get("cn8", "")
            ).strip(),
        }

    def _ReadImmediateChildTexts(
        self,
        row: Mapping[str, str],
        level: str,
    ) -> tuple[str, str]:
        if level == HIERARCHY_LEVEL_HS2:
            return (
                row.get("heading_description", "").strip(),
                row.get("heading_keywords", "").strip(),
            )
        if level == HIERARCHY_LEVEL_HS4:
            return (
                row.get("subheading_description", "").strip(),
                row.get("subheading_keywords", "").strip(),
            )
        if level == HIERARCHY_LEVEL_HS6:
            return (
                (
                    row.get("cn_description", "")
                    or row.get("hs8_description", "")
                    or row.get("cn8_description", "")
                ).strip(),
                row.get("cn_keywords", "").strip(),
            )
        return "", ""

    def _JoinValues(self, *values: str) -> str:
        return "; ".join(value.strip() for value in values if value.strip())


class HierarchyBeamSelector:
    """정적 상위 후보와 semantic recall 슬롯을 결정적으로 병합한다."""

    def SelectForParent(
        self,
        parentPath: HierarchyBeamPath,
        nodeScores: Sequence[HierarchyNodeScore],
        *,
        limit: int,
        semanticCodes: Sequence[str] = (),
        semanticSlots: int = 0,
        residualCodes: Sequence[str] = (),
        preferredCodes: Sequence[str] = (),
    ) -> list[HierarchyBeamPath]:
        if limit <= 0:
            return []

        eligibleScores = [
            nodeScore
            for nodeScore in nodeScores
            if not nodeScore.isExcluded
        ]
        sortedScores = sorted(eligibleScores, key=self._BuildNodeRankKey)
        semanticCodeSet = set(semanticCodes)
        semanticCandidates = [
            nodeScore
            for nodeScore in sortedScores
            if nodeScore.node.code in semanticCodeSet
        ]
        residualCodeSet = set(residualCodes)
        residualCandidates = [
            nodeScore
            for nodeScore in sortedScores
            if (
                nodeScore.node.code in residualCodeSet
                and nodeScore.node.code not in semanticCodeSet
            )
        ]
        reservedSlotCount = min(semanticSlots, len(semanticCandidates))
        if residualCandidates and reservedSlotCount < limit:
            reservedSlotCount += 1
        staticLimit = max(0, limit - reservedSlotCount)

        preferredCodeSet = set(preferredCodes)
        selectedScores = [
            nodeScore
            for nodeScore in sortedScores
            if nodeScore.node.code in preferredCodeSet
        ][:staticLimit]
        selectedCodes = {nodeScore.node.code for nodeScore in selectedScores}
        for nodeScore in sortedScores:
            if len(selectedScores) >= staticLimit:
                break
            if nodeScore.node.code in selectedCodes:
                continue
            selectedScores.append(nodeScore)
            selectedCodes.add(nodeScore.node.code)

        for semanticCandidate in semanticCandidates:
            if len(selectedScores) >= limit:
                break
            if semanticCandidate.node.code in selectedCodes:
                continue
            selectedScores.append(semanticCandidate)
            selectedCodes.add(semanticCandidate.node.code)

        for residualCandidate in residualCandidates:
            if len(selectedScores) >= limit:
                break
            if residualCandidate.node.code in selectedCodes:
                continue
            selectedScores.append(residualCandidate)
            selectedCodes.add(residualCandidate.node.code)

        for nodeScore in sortedScores:
            if len(selectedScores) >= limit:
                break
            if nodeScore.node.code in selectedCodes:
                continue
            selectedScores.append(nodeScore)
            selectedCodes.add(nodeScore.node.code)

        return [
            parentPath.Extend(
                nodeScore,
                semanticSelected=nodeScore.node.code in semanticCodeSet,
            )
            for nodeScore in selectedScores
        ]

    def PruneGlobal(
        self,
        paths: Sequence[HierarchyBeamPath],
        limit: int,
    ) -> list[HierarchyBeamPath]:
        if limit <= 0:
            return []
        return sorted(paths, key=self._BuildPathRankKey)[:limit]

    def _BuildNodeRankKey(
        self,
        nodeScore: HierarchyNodeScore,
    ) -> tuple[float, int, int, str]:
        return (
            -nodeScore.score,
            -nodeScore.primaryMatchCount,
            -nodeScore.secondaryMatchCount,
            nodeScore.node.code,
        )

    def _BuildPathRankKey(
        self,
        path: HierarchyBeamPath,
    ) -> tuple[float, int, int, str, str]:
        return (
            -path.cumulativeScore,
            -path.primaryMatchCount,
            -path.secondaryMatchCount,
            path.domainScope,
            path.currentNode.node.code,
        )


HierarchyLevelLoader = Callable[
    [str, str, str],
    HierarchyLevelSelection,
]


class HierarchyBeamSearch:
    """HS2→HS4→HS6 공통 Beam 전개를 수행한다."""

    def __init__(
        self,
        config: HierarchyBeamConfig,
        selector: HierarchyBeamSelector | None = None,
    ) -> None:
        self._config = config
        self._selector = selector or HierarchyBeamSelector()

    def Search(
        self,
        domainScopes: Sequence[str],
        levelLoader: HierarchyLevelLoader,
        *,
        preferredHs4Codes: Sequence[str] = (),
        boundary: HierarchySearchBoundary | None = None,
    ) -> list[HierarchyBeamPath]:
        paths = [
            HierarchyBeamPath(domainScope=domainScope)
            for domainScope in domainScopes
        ]
        for level in (
            HIERARCHY_LEVEL_HS2,
            HIERARCHY_LEVEL_HS4,
            HIERARCHY_LEVEL_HS6,
        ):
            expandedPaths: list[HierarchyBeamPath] = []
            for parentPath in paths:
                parentCode = (
                    ""
                    if level == HIERARCHY_LEVEL_HS2
                    else parentPath.currentNode.node.code
                )
                selection = levelLoader(
                    parentPath.domainScope,
                    level,
                    parentCode,
                )
                nodeScores = selection.nodeScores
                semanticCodes = selection.semanticCodes
                residualCodes = selection.residualCodes
                if boundary is not None:
                    nodeScores = tuple(
                        nodeScore
                        for nodeScore in nodeScores
                        if boundary.Allows(level, nodeScore.node.code)
                    )
                    allowedNodeCodes = {
                        nodeScore.node.code for nodeScore in nodeScores
                    }
                    semanticCodes = tuple(
                        code
                        for code in semanticCodes
                        if code in allowedNodeCodes
                    )
                    residualCodes = tuple(
                        code
                        for code in residualCodes
                        if code in allowedNodeCodes
                    )
                expandedPaths.extend(
                    self._selector.SelectForParent(
                        parentPath,
                        nodeScores,
                        limit=self._config.GetPerParentLimit(level),
                        semanticCodes=semanticCodes,
                        semanticSlots=self._config.semanticSlotsPerParent,
                        residualCodes=residualCodes,
                        preferredCodes=(
                            preferredHs4Codes
                            if level == HIERARCHY_LEVEL_HS4
                            else ()
                        ),
                    )
                )
            paths = self._selector.PruneGlobal(
                expandedPaths,
                self._config.GetGlobalLimit(level),
            )
            if not paths:
                break
        return paths
