"""Ontology RAG 계층의 데이터 계약."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class OntologyDocumentKind(str, Enum):
    """ontology loader가 읽은 원본 문서의 형식."""

    MARKDOWN = "markdown"
    YAML = "yaml"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class OntologyDocument:
    """Markdown/YAML ontology 문서 하나를 나타내는 원본 단위."""

    documentId: str
    sourcePath: str
    relativePath: str
    title: Optional[str] = None
    content: str = ""
    frontmatter: Dict[str, Any] = field(default_factory=dict)
    documentKind: OntologyDocumentKind = OntologyDocumentKind.UNKNOWN

    def ToDict(self) -> Dict[str, Any]:
        return {
            "document_id": self.documentId,
            "source_path": self.sourcePath,
            "relative_path": self.relativePath,
            "title": self.title,
            "content": self.content,
            "content_length": len(self.content),
            "frontmatter": dict(self.frontmatter),
            "document_kind": self.documentKind.value,
        }


@dataclass(frozen=True)
class OntologyChunk:
    """검색과 LLM 컨텍스트 주입에 사용할 문서 조각."""

    chunkId: str
    documentId: str
    sourcePath: str
    relativePath: str
    text: str
    headingPath: List[str] = field(default_factory=list)
    tokenEstimate: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def ToContextText(self) -> str:
        headingText = " > ".join(self.headingPath)
        headerLines = [
            f"[source] {self.relativePath}",
            f"[document_id] {self.documentId}",
        ]
        if headingText:
            headerLines.append(f"[heading] {headingText}")

        return "\n".join([*headerLines, "", self.text]).strip()

    def ToDict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunkId,
            "document_id": self.documentId,
            "source_path": self.sourcePath,
            "relative_path": self.relativePath,
            "text": self.text,
            "text_length": len(self.text),
            "heading_path": list(self.headingPath),
            "token_estimate": self.tokenEstimate,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class OntologyRetrievalResult:
    """검색 결과 청크와 랭킹 근거."""

    chunk: OntologyChunk
    score: float
    matchedTerms: List[str] = field(default_factory=list)

    def ToDict(self) -> Dict[str, Any]:
        return {
            "chunk": self.chunk.ToDict(),
            "score": self.score,
            "matched_terms": list(self.matchedTerms),
        }


@dataclass(frozen=True)
class PackagedOntologyContext:
    """LLM 요청에 넣을 수 있도록 예산 안에 묶은 ontology context."""

    contextChunks: List[str] = field(default_factory=list)
    selectedResults: List[OntologyRetrievalResult] = field(default_factory=list)
    totalTokenEstimate: int = 0
    omittedResultCount: int = 0
    warnings: List[str] = field(default_factory=list)

    def ToDict(self) -> Dict[str, Any]:
        return {
            "context_chunks": list(self.contextChunks),
            "selected_results": [
                selectedResult.ToDict() for selectedResult in self.selectedResults
            ],
            "total_token_estimate": self.totalTokenEstimate,
            "omitted_result_count": self.omittedResultCount,
            "warnings": list(self.warnings),
        }
