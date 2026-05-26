"""Ontology frontmatter data_sources를 실제 파일 리소스로 검증하는 resolver."""

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from eu_export.ontology.schema import OntologyDocument
from eu_export.utils import NormalizeWhitespace


@dataclass(frozen=True)
class OntologyDataSourceCheck:
    """frontmatter data_sources 항목 하나에 대한 파일/컬럼 검증 결과."""

    resourceId: str
    documentId: str
    relativeDocumentPath: str
    declaredPath: str
    resolvedPath: Optional[str] = None
    exists: bool = False
    format: Optional[str] = None
    tableName: Optional[str] = None
    primaryKey: Optional[str] = None
    requiredColumns: List[str] = field(default_factory=list)
    availableColumns: List[str] = field(default_factory=list)
    missingColumns: List[str] = field(default_factory=list)
    rowCount: Optional[int] = None
    primaryKeyPreview: List[str] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def isLoadable(self) -> bool:
        return self.exists and self.error is None and len(self.missingColumns) == 0

    def ToDict(self) -> Dict[str, Any]:
        return {
            "resource_id": self.resourceId,
            "document_id": self.documentId,
            "relative_document_path": self.relativeDocumentPath,
            "declared_path": self.declaredPath,
            "resolved_path": self.resolvedPath,
            "exists": self.exists,
            "format": self.format,
            "table_name": self.tableName,
            "primary_key": self.primaryKey,
            "required_columns": list(self.requiredColumns),
            "available_columns": list(self.availableColumns),
            "missing_columns": list(self.missingColumns),
            "row_count": self.rowCount,
            "primary_key_preview": list(self.primaryKeyPreview),
            "is_loadable": self.isLoadable,
            "error": self.error,
        }


@dataclass(frozen=True)
class OntologyResourceResolutionReport:
    """ontology data_sources 전체 확인 결과."""

    dataSourceChecks: List[OntologyDataSourceCheck] = field(default_factory=list)

    @property
    def totalCount(self) -> int:
        return len(self.dataSourceChecks)

    @property
    def loadableCount(self) -> int:
        return sum(1 for check in self.dataSourceChecks if check.isLoadable)

    @property
    def missingCount(self) -> int:
        return sum(1 for check in self.dataSourceChecks if not check.exists)

    @property
    def invalidCount(self) -> int:
        return sum(
            1
            for check in self.dataSourceChecks
            if check.exists and not check.isLoadable
        )

    @property
    def isValid(self) -> bool:
        return self.missingCount == 0 and self.invalidCount == 0

    def ToDict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.isValid,
            "total_count": self.totalCount,
            "loadable_count": self.loadableCount,
            "missing_count": self.missingCount,
            "invalid_count": self.invalidCount,
            "data_source_checks": [
                dataSourceCheck.ToDict()
                for dataSourceCheck in self.dataSourceChecks
            ],
        }


class OntologyResourceResolver:
    """frontmatter data_sources의 CSV 파일 존재와 컬럼 계약을 확인한다."""

    def __init__(
        self,
        ontologyRootPath: str | Path,
        projectRootPath: Optional[str | Path] = None,
    ) -> None:
        self.ontologyRootPath = Path(ontologyRootPath)
        self.projectRootPath = (
            Path(projectRootPath)
            if projectRootPath is not None
            else self.ontologyRootPath.parent
        )

    def Resolve(
        self,
        documents: Sequence[OntologyDocument],
    ) -> OntologyResourceResolutionReport:
        checks: List[OntologyDataSourceCheck] = []
        for document in documents:
            for dataSource in self._ReadDataSources(document):
                checks.append(self._CheckDataSource(document, dataSource))

        return OntologyResourceResolutionReport(dataSourceChecks=checks)

    def _CheckDataSource(
        self,
        document: OntologyDocument,
        dataSource: Dict[str, Any],
    ) -> OntologyDataSourceCheck:
        resourceId = self._ReadString(dataSource.get("resource_id")) or "unknown"
        declaredPath = self._ReadString(dataSource.get("path")) or ""
        resourceFormat = self._ReadString(dataSource.get("format"))
        tableName = self._ReadString(dataSource.get("table_name"))
        primaryKey = self._ReadString(dataSource.get("primary_key"))
        requiredColumns = self._ReadStringList(dataSource.get("required_columns"))
        resolvedPath = self._ResolvePath(declaredPath)

        if resolvedPath is None:
            return OntologyDataSourceCheck(
                resourceId=resourceId,
                documentId=document.documentId,
                relativeDocumentPath=document.relativePath,
                declaredPath=declaredPath,
                exists=False,
                format=resourceFormat,
                tableName=tableName,
                primaryKey=primaryKey,
                requiredColumns=requiredColumns,
                missingColumns=list(requiredColumns),
                error="data source file does not exist",
            )

        if resourceFormat != "csv":
            return OntologyDataSourceCheck(
                resourceId=resourceId,
                documentId=document.documentId,
                relativeDocumentPath=document.relativePath,
                declaredPath=declaredPath,
                resolvedPath=str(resolvedPath),
                exists=True,
                format=resourceFormat,
                tableName=tableName,
                primaryKey=primaryKey,
                requiredColumns=requiredColumns,
                error=f"unsupported data source format: {resourceFormat}",
            )

        return self._CheckCsvDataSource(
            document=document,
            resourceId=resourceId,
            declaredPath=declaredPath,
            resolvedPath=resolvedPath,
            resourceFormat=resourceFormat,
            tableName=tableName,
            primaryKey=primaryKey,
            requiredColumns=requiredColumns,
        )

    def _CheckCsvDataSource(
        self,
        document: OntologyDocument,
        resourceId: str,
        declaredPath: str,
        resolvedPath: Path,
        resourceFormat: Optional[str],
        tableName: Optional[str],
        primaryKey: Optional[str],
        requiredColumns: List[str],
    ) -> OntologyDataSourceCheck:
        try:
            with resolvedPath.open("r", encoding="utf-8-sig", newline="") as csvFile:
                reader = csv.DictReader(csvFile)
                availableColumns = list(reader.fieldnames or [])
                missingColumns = [
                    column
                    for column in requiredColumns
                    if column not in availableColumns
                ]
                primaryKeyPreview: List[str] = []
                rowCount = 0
                for row in reader:
                    rowCount += 1
                    if (
                        primaryKey is not None
                        and primaryKey in row
                        and len(primaryKeyPreview) < 5
                    ):
                        value = NormalizeWhitespace(row.get(primaryKey) or "")
                        if value:
                            primaryKeyPreview.append(value)

                if primaryKey is not None and primaryKey not in availableColumns:
                    missingColumns = [*missingColumns, primaryKey]

                return OntologyDataSourceCheck(
                    resourceId=resourceId,
                    documentId=document.documentId,
                    relativeDocumentPath=document.relativePath,
                    declaredPath=declaredPath,
                    resolvedPath=str(resolvedPath),
                    exists=True,
                    format=resourceFormat,
                    tableName=tableName,
                    primaryKey=primaryKey,
                    requiredColumns=requiredColumns,
                    availableColumns=availableColumns,
                    missingColumns=sorted(set(missingColumns)),
                    rowCount=rowCount,
                    primaryKeyPreview=primaryKeyPreview,
                )
        except Exception as error:
            return OntologyDataSourceCheck(
                resourceId=resourceId,
                documentId=document.documentId,
                relativeDocumentPath=document.relativePath,
                declaredPath=declaredPath,
                resolvedPath=str(resolvedPath),
                exists=True,
                format=resourceFormat,
                tableName=tableName,
                primaryKey=primaryKey,
                requiredColumns=requiredColumns,
                error=str(error),
            )

    def _ReadDataSources(
        self,
        document: OntologyDocument,
    ) -> List[Dict[str, Any]]:
        dataSources = document.frontmatter.get("data_sources")
        if not isinstance(dataSources, list):
            return []
        return [
            dataSource
            for dataSource in dataSources
            if isinstance(dataSource, dict)
        ]

    def _ResolvePath(self, declaredPath: str) -> Optional[Path]:
        if declaredPath == "":
            return None

        candidatePaths = [
            self.ontologyRootPath / declaredPath,
            self.projectRootPath / declaredPath,
        ]
        for candidatePath in candidatePaths:
            if candidatePath.exists():
                return candidatePath
        return None

    def _ReadString(self, value: Any) -> Optional[str]:
        if not isinstance(value, str):
            return None
        normalizedValue = NormalizeWhitespace(value)
        return normalizedValue or None

    def _ReadStringList(self, value: Any) -> List[str]:
        if isinstance(value, str):
            normalizedValue = NormalizeWhitespace(value)
            return [normalizedValue] if normalizedValue else []
        if isinstance(value, list):
            values: List[str] = []
            for item in value:
                normalizedItem = self._ReadString(item)
                if normalizedItem is not None:
                    values.append(normalizedItem)
            return values
        return []
