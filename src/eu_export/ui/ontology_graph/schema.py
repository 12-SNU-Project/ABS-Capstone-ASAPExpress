"""Ontology graph UI data schema."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class CandidateGraphNode:
    nodeId: str
    codeLevel: str
    code: str
    title: str
    description: str = ""
    candidateHs8: Optional[str] = None
    score: Optional[float] = None
    candidateData: Dict[str, Any] = field(default_factory=dict)
    x: float = 0.0
    y: float = 0.0


@dataclass(frozen=True)
class CandidateGraphEdge:
    sourceNodeId: str
    targetNodeId: str


@dataclass(frozen=True)
class CandidateGraphProduct:
    productName: str
    productDomain: str
    nodes: List[CandidateGraphNode] = field(default_factory=list)
    edges: List[CandidateGraphEdge] = field(default_factory=list)
    candidateCodes: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class CandidateGraphRunResult:
    productPageUrl: str
    productInputData: Dict[str, Any]
    pipelineResultData: Dict[str, Any]
    candidatesData: List[Dict[str, Any]]
    graphProduct: CandidateGraphProduct
    errors: List[str] = field(default_factory=list)

