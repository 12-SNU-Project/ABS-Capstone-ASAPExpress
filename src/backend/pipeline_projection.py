"""Projection helpers for UI-facing pipeline API payloads."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from backend.api_contract import (
    ClassificationCandidateSetView,
    DocumentPackageSummaryView,
    RunSnapshotResponse,
)
from bussiness_logic.utils.json_types import JsonMapping, JsonObject


class PipelineRunResult(BaseModel):
    """UI가 기본으로 소비하는 pipeline 결과 DTO."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    runId: str = Field(alias="run_id")
    runDir: str = Field(default="", alias="run_dir")
    auditRef: JsonObject = Field(default_factory=dict, alias="audit_ref")
    candidateCodeSet: Optional[ClassificationCandidateSetView] = Field(
        default=None,
        alias="candidate_code_set",
    )
    userQuestions: list[JsonObject] = Field(
        default_factory=list,
        alias="user_questions",
    )
    documentPackage: Optional[DocumentPackageSummaryView] = Field(
        default=None,
        alias="document_package",
    )
    decision: Optional[JsonObject] = None
    componentResults: list[JsonObject] = Field(
        default_factory=list,
        alias="component_results",
    )

    @classmethod
    def FromPipelineOutput(
        cls,
        pipelineOutput: JsonMapping,
    ) -> "PipelineRunResult":
        runId = str(pipelineOutput.get("run_id") or "")
        runDir = str(pipelineOutput.get("run_dir") or "")
        decision = pipelineOutput.get("decision")
        documentPackage = pipelineOutput.get("document_package")
        blackboard = pipelineOutput.get("blackboard")
        userQuestions = pipelineOutput.get("user_questions")
        if not isinstance(userQuestions, list) and isinstance(blackboard, Mapping):
            userQuestions = blackboard.get("user_questions")
        return cls(
            run_id=runId,
            run_dir=runDir,
            audit_ref={
                "run_id": runId,
                "run_dir": runDir,
                "blackboard_available": bool(pipelineOutput.get("blackboard")),
                "component_run_count": len(pipelineOutput.get("component_runs") or []),
            },
            candidate_code_set=pipelineOutput.get("candidate_code_set"),
            user_questions=(
                list(userQuestions)
                if isinstance(userQuestions, list)
                else []
            ),
            document_package=(
                DocumentPackageProjector.PublicDocumentPackageSummary(documentPackage)
                if isinstance(documentPackage, Mapping)
                else documentPackage
            ),
            decision=decision,
            component_results=list(pipelineOutput.get("component_results") or []),
        )

    def ToUiDict(self) -> JsonObject:
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)


class DocumentPackageProjector:
    @staticmethod
    def PublicDocumentPackage(documentPackage: JsonMapping) -> JsonObject:
        return {
            key: value
            for key, value in documentPackage.items()
            if key != "raw_document_package"
        }

    @staticmethod
    def PublicDocumentPackageSummary(documentPackage: JsonMapping) -> JsonObject:
        checklistSummary = documentPackage.get("checklist_summary") or {}
        if not isinstance(checklistSummary, Mapping):
            checklistSummary = {}
        productFacts = documentPackage.get("product_facts") or {}
        if not isinstance(productFacts, Mapping):
            productFacts = {}
        requiredDocuments = documentPackage.get("required_documents") or []
        if not isinstance(requiredDocuments, list):
            requiredDocuments = []
        return DocumentPackageSummaryView(
            document_package_id=documentPackage.get("document_package_id"),
            candidate_id=documentPackage.get("candidate_id"),
            taric10=documentPackage.get("taric10"),
            cn8=documentPackage.get("cn8"),
            taric10_branch_index=documentPackage.get("taric10_branch_index"),
            taric10_branch_count=documentPackage.get("taric10_branch_count"),
            taric10_resolution_mode=documentPackage.get("taric10_resolution_mode"),
            taric10_is_recommended=documentPackage.get("taric10_is_recommended"),
            required_document_count=int(
                documentPackage.get("required_document_count")
                or len(requiredDocuments)
            ),
            summary=(
                dict(documentPackage.get("summary"))
                if isinstance(documentPackage.get("summary"), Mapping)
                else {}
            ),
            checklist_summary={
                "counts": dict(checklistSummary.get("counts") or {}),
                "missing_facts": list(checklistSummary.get("missing_facts") or [])[:40],
            },
            product_facts=dict(productFacts),
            missing_facts=list(documentPackage.get("missing_facts") or [])[:40],
            backtracking_signals=[
                dict(signal)
                for signal in list(documentPackage.get("backtracking_signals") or [])[:8]
                if isinstance(signal, Mapping)
            ],
        ).ToDict()

    def PublicDocumentPackagesFromBlackboard(
        self,
        blackboard: JsonMapping,
    ) -> list[JsonObject]:
        packages = blackboard.get("document_packages") or []
        if not isinstance(packages, list):
            return []
        return [
            self.PublicDocumentPackageSummary(package)
            for package in packages
            if isinstance(package, Mapping)
        ]

    def ExtractDocumentPackages(
        self,
        resultData: JsonMapping,
    ) -> list[JsonObject]:
        packages = resultData.get("document_packages")
        if isinstance(packages, list):
            return [
                self.PublicDocumentPackageSummary(package)
                for package in packages
                if isinstance(package, Mapping)
            ]
        package = resultData.get("document_package")
        if isinstance(package, Mapping):
            return [self.PublicDocumentPackageSummary(package)]
        return []


class InputProcessingViewProjector:
    def CompactInputFacts(self, rawInput: JsonMapping) -> JsonObject:
        compact = {
            key: value
            for key, value in rawInput.items()
            if key
            not in {
                "ocr_text",
                "ingredient_list",
                "reconstructed_fact_texts",
                "reconstructed_product_facts",
                "unresolved_product_facts",
                "product_fact_conflicts",
                "input_reconstruction",
            }
        }
        for textListKey in (
            "ocr_text",
            "ingredient_list",
            "reconstructed_fact_texts",
        ):
            if textListKey not in rawInput:
                continue
            textList = rawInput.get(textListKey) or []
            if isinstance(textList, list):
                compact[f"{textListKey}_count"] = len(textList)
                compact[f"{textListKey}_char_count"] = sum(
                    len(str(item)) for item in textList
                )
                if textListKey == "reconstructed_fact_texts":
                    compact[textListKey] = [
                        str(item)[:500] for item in textList[:24]
                    ]

        for recordListKey in (
            "reconstructed_product_facts",
            "unresolved_product_facts",
            "product_fact_conflicts",
        ):
            recordList = rawInput.get(recordListKey)
            if isinstance(recordList, list):
                compact[f"{recordListKey}_count"] = len(recordList)

        composition = rawInput.get("composition")
        if isinstance(composition, list) and len(composition) > 24:
            compact["composition"] = composition[:24]
            compact["composition_count"] = len(composition)
        inputReconstruction = rawInput.get("input_reconstruction")
        if isinstance(inputReconstruction, Mapping):
            compact["input_reconstruction_available"] = True
            compact["input_reconstruction_mode"] = inputReconstruction.get("mode")
            compact["input_reconstruction_error"] = inputReconstruction.get("error")
            compact["reconstructed_table_count"] = (
                inputReconstruction.get("reconstructed_table_count")
                or len(inputReconstruction.get("reconstructed_tables") or [])
            )
            compact["reconstructed_fact_count"] = (
                inputReconstruction.get("fact_count")
                or len(inputReconstruction.get("reconstructed_product_facts") or [])
            )
        return compact

    def BuildSnapshotInputProcessingView(
        self,
        resultData: JsonMapping,
    ) -> JsonObject:
        existingView = resultData.get("input_processing_view")
        if isinstance(existingView, Mapping):
            return self._CompactInputProcessingView(existingView)
        return {}

    def BuildInputProcessingViewFromBlackboard(
        self,
        blackboard: JsonMapping,
    ) -> JsonObject:
        productEvidenceState = blackboard.get("product_evidence_state") or {}
        if not isinstance(productEvidenceState, Mapping):
            return {}
        observedFacts = productEvidenceState.get("observed_facts") or {}
        if not isinstance(observedFacts, Mapping):
            return {}
        return self.BuildInputProcessingViewFromFacts(observedFacts)

    def BuildInputProcessingViewFromFacts(
        self,
        facts: JsonMapping,
    ) -> JsonObject:
        if not isinstance(facts, Mapping):
            return {}

        sourceUrls = facts.get("source_urls") or []
        if isinstance(sourceUrls, str):
            sourceUrls = [sourceUrls] if sourceUrls.strip() else []
        if not isinstance(sourceUrls, list):
            sourceUrls = []
        url = str(facts.get("url") or (sourceUrls[0] if sourceUrls else "") or "")
        inputReconstruction = facts.get("input_reconstruction") or {}
        if not isinstance(inputReconstruction, Mapping):
            inputReconstruction = {}
        hasBasicInfo = any(
            str(value).strip()
            for value in (
                facts.get("product_name"),
                facts.get("description"),
                url,
            )
        )
        hasReconstruction = any(
            inputReconstruction.get(key)
            for key in (
                "source_evidence_preview",
                "reconstructed_tables",
                "reconstructed_product_facts",
                "reconstructed_fact_texts",
            )
        )
        hasStructuredFacts = any(
            facts.get(key)
            for key in (
                "reconstructed_product_facts",
                "reconstructed_fact_texts",
            )
        )
        if not (hasBasicInfo or hasReconstruction or hasStructuredFacts):
            return {}

        reconstructionWarnings = inputReconstruction.get("warnings") or []
        if not isinstance(reconstructionWarnings, list):
            reconstructionWarnings = []
        factWarnings = facts.get("warnings") or []
        if not isinstance(factWarnings, list):
            factWarnings = []
        warnings = list(dict.fromkeys(
            str(item)
            for item in [*reconstructionWarnings, *factWarnings]
            if str(item).strip()
        ))

        inputProcessingView = {
            "page_product_facts": {
                "product_name": facts.get("product_name") or "",
                "description": facts.get("description") or "",
                "url": url,
                "source_urls": [str(item) for item in sourceUrls if str(item).strip()],
                "ingredients": facts.get("ingredients") or [],
                "intended_use": facts.get("intended_use") or "",
                "origin_country": facts.get("origin_country") or "",
            },
            "detail_evidence_rows": inputReconstruction.get(
                "source_evidence_preview",
                [],
            ),
            "reconstructed_detail_tables": inputReconstruction.get(
                "reconstructed_tables",
                [],
            ),
            "reconstructed_product_facts": (
                inputReconstruction.get("reconstructed_product_facts")
                or facts.get("reconstructed_product_facts")
                or []
            ),
            "reconstructed_fact_texts": (
                inputReconstruction.get("reconstructed_fact_texts")
                or facts.get("reconstructed_fact_texts")
                or []
            ),
            "unresolved_product_facts": (
                inputReconstruction.get("unresolved_product_facts")
                or facts.get("unresolved_product_facts")
                or []
            ),
            "reconstruction_evidence_traces": (
                inputReconstruction.get("evidence_traces")
                or inputReconstruction.get("reconstruction_evidence_traces")
                or facts.get("reconstruction_evidence_traces")
                or []
            ),
            "missing_fact_reasons": (
                inputReconstruction.get("missing_fact_reasons")
                or facts.get("missing_fact_reasons")
                or []
            ),
            "product_fact_conflicts": (
                inputReconstruction.get("product_fact_conflicts")
                or facts.get("product_fact_conflicts")
                or []
            ),
            "warnings": warnings,
            "evidence_source_labels": inputReconstruction.get("source_ref_labels") or {},
            "reconstruction_status": {
                "mode": inputReconstruction.get("mode") or "",
                "used_llm_reconstruction": bool(
                    inputReconstruction.get("used_llm_reconstruction"),
                ),
                "fallback_reason": inputReconstruction.get("fallback_reason") or "",
                "error": inputReconstruction.get("error") or "",
                "detail_table_count": (
                    inputReconstruction.get("reconstructed_table_count")
                    or len(inputReconstruction.get("reconstructed_tables") or [])
                ),
                "classification_fact_count": (
                    inputReconstruction.get("fact_count")
                    or len(inputReconstruction.get("reconstructed_product_facts") or [])
                ),
                "classification_text_line_count": (
                    inputReconstruction.get("fact_text_count")
                    or len(inputReconstruction.get("reconstructed_fact_texts") or [])
                ),
            },
        }
        return self._CompactInputProcessingView(inputProcessingView)

    def BuildInputProcessingSummary(
        self,
        blackboard: JsonMapping,
    ) -> JsonObject:
        productEvidenceState = blackboard.get("product_evidence_state") or {}
        if not isinstance(productEvidenceState, Mapping):
            return {}
        observedFacts = productEvidenceState.get("observed_facts") or {}
        if not isinstance(observedFacts, Mapping):
            observedFacts = {}
        ocrText = observedFacts.get("ocr_text") or []
        composition = observedFacts.get("composition") or []
        inferredFacts = productEvidenceState.get("inferred_facts") or []
        summary = {
            "product_id": productEvidenceState.get("product_id"),
            "product_name": observedFacts.get("product_name"),
            "ocr_text_count": len(ocrText) if isinstance(ocrText, list) else 0,
            "composition_count": len(composition) if isinstance(composition, list) else 0,
            "inferred_fact_count": (
                len(inferredFacts) if isinstance(inferredFacts, list) else 0
            ),
            "unknowns": productEvidenceState.get("unknowns") or [],
        }
        inputReconstruction = observedFacts.get("input_reconstruction")
        if isinstance(inputReconstruction, Mapping):
            summary["input_reconstruction_available"] = True
            summary["input_reconstruction_mode"] = inputReconstruction.get("mode")
            summary["reconstructed_table_count"] = (
                inputReconstruction.get("reconstructed_table_count")
                or len(inputReconstruction.get("reconstructed_tables") or [])
            )
            summary["reconstructed_fact_count"] = (
                inputReconstruction.get("fact_count")
                or len(inputReconstruction.get("reconstructed_product_facts") or [])
            )
        return summary

    def _CompactInputProcessingView(
        self,
        inputProcessingView: JsonMapping,
    ) -> JsonObject:
        basicInfo = inputProcessingView.get("page_product_facts") or {}
        if not isinstance(basicInfo, Mapping):
            basicInfo = {}
        reconstruction = inputProcessingView.get("reconstruction_status") or {}
        if not isinstance(reconstruction, Mapping):
            reconstruction = {}

        return {
            "page_product_facts": {
                "product_name": str(basicInfo.get("product_name") or ""),
                "description": str(basicInfo.get("description") or "")[:1000],
                "url": str(basicInfo.get("url") or ""),
                "source_urls": self._CompactTextList(
                    basicInfo.get("source_urls"),
                    limit=8,
                    textLimit=700,
                ),
                "ingredients": self._CompactMappingList(
                    basicInfo.get("ingredients"),
                    limit=20,
                    textLimit=100,
                ),
                "intended_use": str(basicInfo.get("intended_use") or ""),
                "origin_country": str(basicInfo.get("origin_country") or ""),
            },
            "detail_evidence_rows": self._CompactMappingList(
                inputProcessingView.get("detail_evidence_rows"),
                limit=12,
                textLimit=700,
            ),
            "reconstructed_detail_tables": self._CompactReconstructedTables(
                inputProcessingView.get("reconstructed_detail_tables"),
            ),
            "reconstructed_product_facts": self._CompactMappingList(
                inputProcessingView.get("reconstructed_product_facts"),
                limit=80,
                textLimit=700,
            ),
            "reconstructed_fact_texts": self._CompactTextList(
                inputProcessingView.get("reconstructed_fact_texts"),
                limit=80,
                textLimit=700,
            ),
            "unresolved_product_facts": self._CompactMappingList(
                inputProcessingView.get("unresolved_product_facts"),
                limit=40,
                textLimit=700,
            ),
            "reconstruction_evidence_traces": self._CompactMappingList(
                inputProcessingView.get("reconstruction_evidence_traces"),
                limit=80,
                textLimit=700,
            ),
            "missing_fact_reasons": self._CompactMappingList(
                inputProcessingView.get("missing_fact_reasons"),
                limit=40,
                textLimit=700,
            ),
            "product_fact_conflicts": self._CompactTextList(
                inputProcessingView.get("product_fact_conflicts"),
                limit=20,
                textLimit=700,
            ),
            "warnings": self._CompactTextList(
                inputProcessingView.get("warnings"),
                limit=20,
                textLimit=700,
            ),
            "evidence_source_labels": self._CompactTextMapping(
                inputProcessingView.get("evidence_source_labels"),
                textLimit=200,
            ),
            "reconstruction_status": dict(reconstruction),
        }

    def _CompactTextList(
        self,
        records: object,
        *,
        limit: int,
        textLimit: int,
    ) -> list[str]:
        if isinstance(records, str):
            records = [records]
        if not isinstance(records, list):
            return []
        return [
            str(item)[:textLimit]
            for item in records[:limit]
            if str(item).strip()
        ]

    def _CompactTextMapping(
        self,
        records: object,
        *,
        textLimit: int,
    ) -> dict[str, str]:
        if not isinstance(records, Mapping):
            return {}
        return {
            str(key): str(value)[:textLimit]
            for key, value in records.items()
        }

    def _CompactMappingList(
        self,
        records: object,
        *,
        limit: int,
        textLimit: int,
    ) -> list[JsonObject]:
        if not isinstance(records, list):
            return []
        return [
            {
                str(key): str(value)[:textLimit]
                if isinstance(value, str)
                else value
                for key, value in record.items()
            }
            for record in records[:limit]
            if isinstance(record, Mapping)
        ]

    def _CompactReconstructedTables(self, tables: object) -> list[JsonObject]:
        if not isinstance(tables, list):
            return []
        compactTables: list[JsonObject] = []
        for table in tables[:8]:
            if not isinstance(table, Mapping):
                continue
            rows = table.get("rows") or []
            compactTable = {
                key: value
                for key, value in table.items()
                if key != "rows"
            }
            compactTable["rows"] = self._CompactMappingList(
                rows,
                limit=80,
                textLimit=700,
            )
            compactTables.append(compactTable)
        return compactTables


class UnderstandingViewProjector:
    """현행 blackboard DTO(ProductUnderstandingPackage/Hs2RoutingDecision)를
    필드명 그대로 UI에 노출하는 컴팩트 뷰."""

    _IDENTITY_HINT_KEYS = (
        "translated_product_name",
        "commercial_identity",
        "normalized_tariff_description",
        "ingredient_class",
        "food_form",
        "processing_state",
        "intended_use",
        "identity_terms",
        "product_form_terms",
        "chapter_hint_terms",
        "chapter_hint_status",
        "chapter_hint_basis",
        "chapter_hint_source_terms",
        "domain_hints",
        "confidence",
        "needs_review",
        "understanding_mode",
        "llm_error",
    )

    _ROUTING_KEYS = (
        "allowed_hs2",
        "blocked_hs2",
        "enforce_hs2_boundary",
        "fallback_allowed",
        "domain_scopes",
        "pre_gate_domains",
        "missing_facts",
        "routing_basis",
    )

    def BuildProductUnderstandingView(
        self,
        blackboard: JsonMapping,
    ) -> JsonObject:
        productUnderstanding = blackboard.get("product_understanding")
        if not isinstance(productUnderstanding, Mapping):
            return {}
        view: JsonObject = {
            "understanding_id": productUnderstanding.get("understanding_id"),
            "product_id": productUnderstanding.get("product_id"),
            "product_name": productUnderstanding.get("product_name"),
            "short_description": str(
                productUnderstanding.get("short_description") or ""
            )[:500],
            "routing_terms": self._TextList(
                productUnderstanding.get("routing_terms"), limit=24,
            ),
            "blocked_routing_terms": self._TextList(
                productUnderstanding.get("blocked_routing_terms"), limit=24,
            ),
            "excluded_from_routing_terms": self._TextList(
                productUnderstanding.get("excluded_from_routing_terms"), limit=24,
            ),
            "unknowns": self._TextList(
                productUnderstanding.get("unknowns"), limit=12,
            ),
            "reconstructed_fact_text_count": len(
                productUnderstanding.get("reconstructed_fact_texts") or [],
            ),
            "reconstructed_product_fact_count": len(
                productUnderstanding.get("reconstructed_product_facts") or [],
            ),
        }
        identityHints = productUnderstanding.get("identity_hints")
        if isinstance(identityHints, Mapping):
            view["identity_hints"] = {
                key: identityHints.get(key)
                for key in self._IDENTITY_HINT_KEYS
                if identityHints.get(key) not in (None, "", [], ())
            }
        distilledIdentity = productUnderstanding.get("distilled_identity")
        if isinstance(distilledIdentity, Mapping):
            view["distilled_identity"] = {
                key: distilledIdentity.get(key)
                for key in (
                    "commercial_identity",
                    "normalized_description",
                    "identity_terms",
                    "product_form_signal_terms",
                    "processing_signal_terms",
                )
                if distilledIdentity.get(key) not in (None, "", [], ())
            }
        compositionFacts = productUnderstanding.get("composition_facts")
        if isinstance(compositionFacts, Mapping):
            view["composition_facts"] = dict(compositionFacts)
        encyclopediaEvidence = productUnderstanding.get("encyclopedia_evidence")
        if isinstance(encyclopediaEvidence, Mapping):
            view["encyclopedia_evidence"] = {
                key: encyclopediaEvidence.get(key)
                for key in ("quality_status", "source_title", "source_url")
                if encyclopediaEvidence.get(key) not in (None, "", [], ())
            }
        coiEvidence = productUnderstanding.get("coi_evidence")
        if isinstance(coiEvidence, Mapping):
            view["coi_evidence"] = {
                "matched_documents": [
                    str(item)[:200]
                    for item in list(coiEvidence.get("matched_documents") or [])[:8]
                ],
                "matched_texts": [
                    str(item)[:300]
                    for item in list(coiEvidence.get("matched_texts") or [])[:8]
                ],
                "match_scores": list(coiEvidence.get("match_scores") or [])[:8],
                "error": str(coiEvidence.get("error") or ""),
            }
        return view

    def BuildRoutingView(self, blackboard: JsonMapping) -> JsonObject:
        routingContext = blackboard.get("routing_context")
        if not isinstance(routingContext, Mapping):
            return {}
        view: JsonObject = {
            key: routingContext.get(key)
            for key in self._ROUTING_KEYS
            if routingContext.get(key) is not None
        }
        chapterDetails = routingContext.get("candidate_chapter_details")
        if isinstance(chapterDetails, list) and chapterDetails:
            view["candidate_chapter_details"] = [
                dict(detail)
                for detail in chapterDetails[:8]
                if isinstance(detail, Mapping)
            ]
        return view

    @staticmethod
    def _TextList(records: object, *, limit: int) -> list[str]:
        if not isinstance(records, (list, tuple)):
            return []
        return [str(item) for item in list(records)[:limit] if str(item).strip()]


class PipelineOutputProjector:
    def __init__(
        self,
        inputProcessingProjector: InputProcessingViewProjector,
        documentPackageProjector: DocumentPackageProjector,
    ) -> None:
        self._inputProcessingProjector = inputProcessingProjector
        self._documentPackageProjector = documentPackageProjector
        self._understandingProjector = UnderstandingViewProjector()

    def BuildPipelineResultProjection(
        self,
        pipelineOutput: JsonMapping,
    ) -> JsonObject:
        result = PipelineRunResult.FromPipelineOutput(pipelineOutput).ToUiDict()
        result.update(self.CompactPipelineResult(pipelineOutput))
        return result

    def CompactPipelineResult(self, pipelineResult: JsonMapping) -> JsonObject:
        blackboard = pipelineResult.get("blackboard")
        compact = {
            key: value
            for key, value in pipelineResult.items()
            if key
            not in {
                "blackboard",
                "component_runs",
                "raw_document_package",
                "events",
                "facts",
            }
        }
        if isinstance(blackboard, Mapping):
            inputProcessingSummary = (
                self._inputProcessingProjector.BuildInputProcessingSummary(blackboard)
            )
            if inputProcessingSummary:
                compact["input_processing_summary"] = inputProcessingSummary
            inputProcessingView = (
                self._inputProcessingProjector.BuildInputProcessingViewFromBlackboard(
                    blackboard,
                )
            )
            if inputProcessingView:
                compact["input_processing_view"] = inputProcessingView
            productUnderstandingView = (
                self._understandingProjector.BuildProductUnderstandingView(blackboard)
            )
            if productUnderstandingView:
                compact["product_understanding_view"] = productUnderstandingView
            routingView = self._understandingProjector.BuildRoutingView(blackboard)
            if routingView:
                compact["routing_view"] = routingView
            userQuestions = blackboard.get("user_questions")
            if isinstance(userQuestions, list):
                compact["user_questions"] = list(userQuestions)
        documentPackage = compact.get("document_package")
        if isinstance(documentPackage, Mapping):
            compact["document_package"] = (
                self._documentPackageProjector.PublicDocumentPackageSummary(documentPackage)
            )
        if isinstance(blackboard, Mapping):
            documentPackages = (
                self._documentPackageProjector.PublicDocumentPackagesFromBlackboard(
                    blackboard,
                )
            )
            if documentPackages:
                compact["document_packages"] = documentPackages
        return compact

class PipelineSnapshotProjector:
    def __init__(
        self,
        inputProcessingProjector: InputProcessingViewProjector,
    ) -> None:
        self._inputProcessingProjector = inputProcessingProjector

    def BuildUiResult(
        self,
        snapshot: JsonMapping,
        runId: str,
    ) -> JsonObject:
        baseResult = snapshot.get("result") or snapshot.get("partial_result") or {}
        resultData = self._CompactSnapshotResult(baseResult)
        documentPackages = resultData.get("document_packages")
        if isinstance(documentPackages, list):
            resultData["document_packages"] = [
                DocumentPackageProjector.PublicDocumentPackageSummary(package)
                for package in documentPackages
                if isinstance(package, Mapping)
            ]
        snapshotPackages = snapshot.get("document_packages")
        if isinstance(snapshotPackages, list) and not resultData.get("document_packages"):
            resultData["document_packages"] = [
                DocumentPackageProjector.PublicDocumentPackageSummary(package)
                for package in snapshotPackages
                if isinstance(package, Mapping)
            ]
        resultData["job_id"] = runId
        resultData["job_status"] = snapshot.get("status")
        resultData["events"] = snapshot.get("events") or []
        resultData["request"] = self._BuildRequestView(snapshot)
        inputProcessingView = (
            self._inputProcessingProjector.BuildSnapshotInputProcessingView(resultData)
        )
        if inputProcessingView:
            resultData["input_processing_view"] = inputProcessingView
        if snapshot.get("error"):
            resultData["error"] = str(snapshot.get("error") or "")
        return RunSnapshotResponse.model_validate(resultData).ToDict()

    def _CompactSnapshotResult(self, result: object) -> JsonObject:
        if not isinstance(result, Mapping):
            return {}
        allowedKeys = {
            "run_id",
            "run_dir",
            "audit_ref",
            "candidate_code_set",
            "user_questions",
            "document_package",
            "document_packages",
            "decision",
            "component_results",
            "input_processing_summary",
            "input_processing_view",
            "product_understanding_view",
            "routing_view",
        }
        return {
            key: value
            for key, value in result.items()
            if key in allowedKeys
        }

    def _BuildRequestView(self, snapshot: JsonMapping) -> JsonObject:
        facts = snapshot.get("facts")
        return {
            "query": str(snapshot.get("query") or ""),
            "facts": dict(facts) if isinstance(facts, Mapping) else {},
        }


class PipelineEventProjector:
    def __init__(
        self,
        inputProcessingProjector: InputProcessingViewProjector,
        outputProjector: PipelineOutputProjector,
    ) -> None:
        self._inputProcessingProjector = inputProcessingProjector
        self._outputProjector = outputProjector

    def CompactEvent(self, event: JsonMapping) -> JsonObject:
        eventData = dict(event)
        rawInput = eventData.pop("raw_input", None)
        inputProcessingView = (
            self._inputProcessingProjector.BuildInputProcessingViewFromFacts(rawInput)
            if isinstance(rawInput, Mapping)
            else {}
        )
        if isinstance(rawInput, Mapping):
            eventData["collected_input_summary"] = (
                self._inputProcessingProjector.CompactInputFacts(rawInput)
            )
        partialResult = eventData.get("partial_result")
        if isinstance(partialResult, Mapping):
            compactPartialResult = self._outputProjector.CompactPipelineResult(
                partialResult,
            )
            if inputProcessingView and "input_processing_view" not in compactPartialResult:
                compactPartialResult["input_processing_view"] = inputProcessingView
            eventData["partial_result"] = compactPartialResult
        elif inputProcessingView:
            eventData["partial_result"] = {
                "input_processing_view": inputProcessingView,
            }
        return eventData


class PipelineResultProjector:
    """Facade preserving RunRegistry's projection API while separating concerns."""

    def __init__(self) -> None:
        self._inputProcessingProjector = InputProcessingViewProjector()
        self._documentPackageProjector = DocumentPackageProjector()
        self._outputProjector = PipelineOutputProjector(
            self._inputProcessingProjector,
            self._documentPackageProjector,
        )
        self._snapshotProjector = PipelineSnapshotProjector(
            self._inputProcessingProjector,
        )
        self._eventProjector = PipelineEventProjector(
            self._inputProcessingProjector,
            self._outputProjector,
        )

    def BuildUiResult(
        self,
        snapshot: JsonMapping,
        runId: str,
    ) -> JsonObject:
        return self._snapshotProjector.BuildUiResult(snapshot, runId)

    def BuildPipelineResultProjection(
        self,
        pipelineOutput: JsonMapping,
    ) -> JsonObject:
        return self._outputProjector.BuildPipelineResultProjection(pipelineOutput)

    def CompactEvent(self, event: JsonMapping) -> JsonObject:
        return self._eventProjector.CompactEvent(event)

    def CompactInputFacts(self, rawInput: JsonMapping) -> JsonObject:
        return self._inputProcessingProjector.CompactInputFacts(rawInput)

    def PublicDocumentPackage(self, documentPackage: JsonMapping) -> JsonObject:
        return self._documentPackageProjector.PublicDocumentPackage(documentPackage)

    def ExtractDocumentPackages(
        self,
        resultData: JsonMapping,
    ) -> list[JsonObject]:
        return self._documentPackageProjector.ExtractDocumentPackages(resultData)
