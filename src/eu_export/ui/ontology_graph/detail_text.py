"""Detail text builder for ontology graph UI."""

import json
from typing import Any, List, Mapping, Optional

from eu_export.ui.ontology_graph.graph_data import CandidateGraphLoader
from eu_export.ui.ontology_graph.schema import (
    CandidateGraphNode,
    CandidateGraphProduct,
    CandidateGraphRunResult,
)


class CandidateGraphDetailTextBuilder:
    """후보 그래프와 점수 산출 과정을 우측 상세 패널 텍스트로 변환한다."""

    def BuildProductOverviewText(
        self,
        product: CandidateGraphProduct,
        runResult: Optional[CandidateGraphRunResult] = None,
    ) -> str:
        lines = [
            "상품: {0}".format(product.productName),
            "도메인: {0}".format(product.productDomain),
            "후보 수: {0}".format(len(product.candidateCodes)),
            "",
            "CN8 후보:",
        ]
        for candidateCode in product.candidateCodes:
            lines.append("- {0}".format(candidateCode))
        lines.extend(
            [
                "",
                "마우스 조작:",
                "- 노드 드래그: 후보 계층 위치 이동",
                "- 휠: 확대/축소",
                "- 우클릭 또는 중클릭 드래그: 캔버스 이동",
                "- 노드 클릭: 상세 정보 확인",
            ]
        )
        if runResult is not None:
            lines.extend(self.BuildRunDashboardText(runResult))
        return "\n".join(lines)

    def BuildRunDashboardText(
        self,
        runResult: CandidateGraphRunResult,
    ) -> List[str]:
        pipelineData = runResult.pipelineResultData
        graphLoader = CandidateGraphLoader()
        collectionResult = graphLoader.ReadMapping(
            pipelineData.get("collection_result"),
        )
        parsedPage = graphLoader.ReadMapping(
            collectionResult.get("parsed_product_page"),
        )
        productNoticeFieldCount = parsedPage.get("product_notice_field_count")
        if not isinstance(productNoticeFieldCount, int):
            productNoticeFieldCount = len(
                parsedPage.get("product_notice_fields", []) or [],
            )
        steps = pipelineData.get("steps", [])
        lines = [
            "",
            "실행 대시보드",
            "URL: {0}".format(runResult.productPageUrl),
            "상품고시 필드 수: {0}".format(
                productNoticeFieldCount,
            ),
            "OCR fallback 필요: {0}".format(
                parsedPage.get("requires_ocr_fallback"),
            ),
            "OCR 텍스트 길이: {0}".format(
                len(str(pipelineData.get("combined_ocr_text") or "")),
            ),
            "오류 수: {0}".format(len(runResult.errors)),
            "",
            "파이프라인 단계:",
        ]
        if isinstance(steps, list):
            for step in steps:
                if not isinstance(step, Mapping):
                    continue
                lines.append(
                    "- {0}: {1} ({2})".format(
                        step.get("step_name"),
                        "성공" if step.get("succeeded") else "실패",
                        step.get("message") or "",
                    )
                )
        lines.extend(["", "후보 점수 요약:"])
        for candidateData in runResult.candidatesData:
            lines.append(
                "- {0}: score={1}, include={2}, search={3}, "
                "desc={4}, exclude={5}".format(
                    candidateData.get("hs8"),
                    candidateData.get("score"),
                    len(candidateData.get("include_rule_matches", []) or []),
                    len(candidateData.get("search_keyword_matches", []) or []),
                    len(candidateData.get("description_matches", []) or []),
                    len(candidateData.get("exclude_rule_matches", []) or []),
                )
            )
        return lines

    def BuildNodeDetailText(self, graphNode: CandidateGraphNode) -> str:
        lines = [
            "노드: {0}".format(graphNode.title.replace("\n", " / ")),
            "레벨: {0}".format(graphNode.codeLevel.upper()),
            "코드: {0}".format(graphNode.code),
            "설명: {0}".format(graphNode.description or "-"),
        ]
        if graphNode.codeLevel != "cn8":
            return "\n".join(lines)

        candidateData = graphNode.candidateData
        lines.extend(
            [
                "",
                "후보 산출 정보",
                "점수: {0}".format(candidateData.get("score")),
                "HS6: {0}".format(candidateData.get("hs6_code")),
                "human review 필요: {0}".format(
                    candidateData.get("needs_human_review"),
                ),
                "",
                "점수 계산",
                json.dumps(
                    candidateData.get("score_breakdown", {}),
                    ensure_ascii=False,
                    indent=2,
                ),
                "",
                "include_rule_matches:",
                self.BuildListText(candidateData.get("include_rule_matches")),
                "",
                "search_keyword_matches:",
                self.BuildListText(candidateData.get("search_keyword_matches")),
                "",
                "description_matches:",
                self.BuildListText(candidateData.get("description_matches")),
                "",
                "exclude_rule_matches:",
                self.BuildListText(candidateData.get("exclude_rule_matches")),
                "",
                "hard_conditions:",
                str(candidateData.get("hard_conditions") or "-"),
                "",
                "combined_description:",
                str(candidateData.get("combined_description") or "-"),
            ]
        )
        return "\n".join(lines)

    def BuildListText(self, value: Any) -> str:
        if not isinstance(value, list) or not value:
            return "- 없음"
        return "\n".join(
            "- {0}".format(item)
            for item in value
        )
