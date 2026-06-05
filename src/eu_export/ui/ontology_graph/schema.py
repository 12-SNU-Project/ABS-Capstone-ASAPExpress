"""Ontology graph UI data schema."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class CandidateGraphCodeLevel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: Optional[str] = None
    description: Optional[str] = None


class CandidateGraphCodeHierarchy(BaseModel):
    model_config = ConfigDict(extra="ignore")

    hs2: CandidateGraphCodeLevel = Field(default_factory=CandidateGraphCodeLevel)
    hs4: CandidateGraphCodeLevel = Field(default_factory=CandidateGraphCodeLevel)
    hs6: CandidateGraphCodeLevel = Field(default_factory=CandidateGraphCodeLevel)
    cn8: CandidateGraphCodeLevel = Field(default_factory=CandidateGraphCodeLevel)


class CandidateGraphCandidate(BaseModel):
    model_config = ConfigDict(extra="allow")

    rank: int = 0
    hs8: Optional[str] = None
    hs6_code: Optional[str] = None
    score: Optional[float] = None
    code_hierarchy: CandidateGraphCodeHierarchy = Field(
        default_factory=CandidateGraphCodeHierarchy,
    )
    score_breakdown: Dict[str, Any] = Field(default_factory=dict)
    match_counts: Dict[str, int] = Field(default_factory=dict)


class CandidateGraphProductInputPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    product_name: Optional[str] = None
    product_domain: Optional[str] = None
    domain_scopes: List[str] = Field(default_factory=list)


class CandidateGraphProductPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    product_input: CandidateGraphProductInputPayload = Field(
        default_factory=CandidateGraphProductInputPayload,
    )
    candidates: List[CandidateGraphCandidate] = Field(default_factory=list)
    candidate_scores: List[CandidateGraphCandidate] = Field(default_factory=list)


class CandidateGraphPipelineStepPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    step_name: Optional[str] = None
    succeeded: bool = True
    message: str = ""


class CandidateGraphPipelineResultPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    product_page_url: Optional[str] = None
    parsed_product_page: Dict[str, Any] = Field(default_factory=dict)
    collection_summary: Dict[str, Any] = Field(default_factory=dict)
    rendered_page_evidence_summary: Optional[Dict[str, Any]] = None
    ocr_summary: Dict[str, Any] = Field(default_factory=dict)
    combined_ocr_text: str = ""
    steps: List[CandidateGraphPipelineStepPayload] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class CandidateGraphNode(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    nodeId: str
    codeLevel: str
    code: str
    title: str
    description: str = ""
    candidateHs8: Optional[str] = None
    score: Optional[float] = None
    candidateData: Optional[CandidateGraphCandidate] = None
    x: float = 0.0
    y: float = 0.0


class CandidateGraphEdge(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    sourceNodeId: str
    targetNodeId: str


class CandidateGraphProduct(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    productName: str
    productDomain: str
    nodes: List[CandidateGraphNode] = Field(default_factory=list)
    edges: List[CandidateGraphEdge] = Field(default_factory=list)
    candidateCodes: List[str] = Field(default_factory=list)


class CandidateGraphRunResult(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    productPageUrl: str
    productInputData: CandidateGraphProductInputPayload
    pipelineResultData: CandidateGraphPipelineResultPayload
    candidatesData: List[CandidateGraphCandidate]
    graphProduct: CandidateGraphProduct
    errors: List[str] = Field(default_factory=list)
