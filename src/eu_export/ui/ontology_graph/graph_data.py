"""Candidate graph data loading and hierarchy conversion."""

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from eu_export.ui.ontology_graph.schema import (
    CandidateGraphEdge,
    CandidateGraphNode,
    CandidateGraphProduct,
)


class CandidateGraphLoader:
    """ontology smoke summary 또는 후보 payload를 GUI graph 데이터로 변환한다."""

    LEVEL_ORDER = ["hs2", "hs4", "hs6", "cn8"]
    LEVEL_TITLES = {
        "hs2": "HS2",
        "hs4": "HS4",
        "hs6": "HS6",
        "cn8": "CN8",
    }

    def Load(self, summaryPath: Path) -> List[CandidateGraphProduct]:
        if not summaryPath.exists():
            raise FileNotFoundError(str(summaryPath))

        with summaryPath.open("r", encoding="utf-8") as summaryFile:
            summaryData = json.load(summaryFile)

        candidateSummary = self.ReadMapping(
            summaryData.get("classification_candidate_summary"),
        )
        productItems = self.ReadMappingList(candidateSummary.get("products"))
        return [
            self.BuildProductGraph(productItem)
            for productItem in productItems
        ]

    def BuildProductGraph(
        self,
        productItem: Mapping[str, Any],
    ) -> CandidateGraphProduct:
        productInput = self.ReadMapping(productItem.get("product_input"))
        candidates = self.ReadMappingList(productItem.get("candidates"))
        productName = self.ReadString(productInput.get("product_name")) or "상품명 없음"
        productDomain = self.ReadString(productInput.get("product_domain")) or "unknown"

        nodeDataById: Dict[str, Dict[str, Any]] = {}
        edgeKeys: set[Tuple[str, str]] = set()
        candidateCodes: List[str] = []

        for candidate in candidates:
            hierarchyNodeIds: List[str] = []
            for level in self.LEVEL_ORDER:
                code, description = self.ReadHierarchyLevel(candidate, level)
                if code == "":
                    continue

                nodeId = "{0}:{1}".format(level, code)
                if nodeId not in nodeDataById:
                    nodeDataById[nodeId] = {
                        "node_id": nodeId,
                        "code_level": level,
                        "code": code,
                        "description": description,
                        "candidate_hs8": None,
                        "score": None,
                        "candidate_data": {},
                    }

                if level == "cn8":
                    nodeDataById[nodeId]["candidate_hs8"] = (
                        self.ReadString(candidate.get("hs8")) or code
                    )
                    nodeDataById[nodeId]["score"] = self.ReadOptionalFloat(
                        candidate.get("score"),
                    )
                    nodeDataById[nodeId]["candidate_data"] = dict(candidate)
                    candidateCodes.append(nodeDataById[nodeId]["candidate_hs8"])

                hierarchyNodeIds.append(nodeId)

            for index in range(1, len(hierarchyNodeIds)):
                edgeKeys.add((hierarchyNodeIds[index - 1], hierarchyNodeIds[index]))

        return CandidateGraphProduct(
            productName=productName,
            productDomain=productDomain,
            nodes=self.BuildPositionedNodes(nodeDataById),
            edges=[
                CandidateGraphEdge(
                    sourceNodeId=sourceNodeId,
                    targetNodeId=targetNodeId,
                )
                for sourceNodeId, targetNodeId in sorted(edgeKeys)
            ],
            candidateCodes=candidateCodes,
        )

    def BuildPositionedNodes(
        self,
        nodeDataById: Mapping[str, Mapping[str, Any]],
    ) -> List[CandidateGraphNode]:
        nodes: List[CandidateGraphNode] = []
        for levelIndex, level in enumerate(self.LEVEL_ORDER):
            levelNodeData = [
                nodeData
                for nodeData in nodeDataById.values()
                if nodeData.get("code_level") == level
            ]
            levelNodeData.sort(key=lambda nodeData: str(nodeData.get("code") or ""))
            levelHeight = max(1, len(levelNodeData))
            for rowIndex, nodeData in enumerate(levelNodeData):
                code = self.ReadString(nodeData.get("code")) or ""
                title = "{0} {1}".format(self.LEVEL_TITLES[level], code)
                if level == "cn8" and nodeData.get("score") is not None:
                    title = "{0}\nscore {1}".format(title, nodeData["score"])
                nodes.append(
                    CandidateGraphNode(
                        nodeId=self.ReadString(nodeData.get("node_id")) or "",
                        codeLevel=level,
                        code=code,
                        title=title,
                        description=self.ReadString(
                            nodeData.get("description"),
                        ) or "",
                        candidateHs8=self.ReadString(
                            nodeData.get("candidate_hs8"),
                        ),
                        score=self.ReadOptionalFloat(nodeData.get("score")),
                        candidateData=dict(
                            self.ReadMapping(nodeData.get("candidate_data")),
                        ),
                        x=80.0 + levelIndex * 310.0,
                        y=90.0 + rowIndex * 150.0 - (levelHeight - 1) * 35.0,
                    )
                )
        return nodes

    def ReadHierarchyLevel(
        self,
        candidate: Mapping[str, Any],
        level: str,
    ) -> Tuple[str, str]:
        hierarchy = self.ReadMapping(candidate.get("code_hierarchy"))
        levelData = self.ReadMapping(hierarchy.get(level))
        code = self.ReadString(levelData.get("code"))
        description = self.ReadString(levelData.get("description"))
        if code is None:
            code = self.ReadString(candidate.get("{0}_code".format(level)))
        if description is None:
            description = self.ReadString(candidate.get("{0}_description".format(level)))
        if level == "cn8":
            code = code or self.ReadString(candidate.get("hs8_code"))
            description = description or self.ReadString(
                candidate.get("hs8_description"),
            )
        return code or "", description or ""

    def ReadMapping(self, value: Any) -> Mapping[str, Any]:
        if isinstance(value, Mapping):
            return value
        return {}

    def ReadMappingList(self, value: Any) -> List[Mapping[str, Any]]:
        if not isinstance(value, list):
            return []
        return [
            item
            for item in value
            if isinstance(item, Mapping)
        ]

    def ReadString(self, value: Any) -> Optional[str]:
        if isinstance(value, str) and value.strip() != "":
            return value.strip()
        return None

    def ReadOptionalFloat(self, value: Any) -> Optional[float]:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None
        return None

