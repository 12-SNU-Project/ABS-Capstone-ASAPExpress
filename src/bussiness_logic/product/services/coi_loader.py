"""COI xlsx evidence loader."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable


import os

PROJECT_ROOT = Path(__file__).resolve().parents[4]
# ASAP_COI_ROOT로 오버라이드 가능 — 실물 46파일은 현재 ~/ASAP_A/test에 있다
DEFAULT_COI_ROOT = Path(
    os.environ.get("ASAP_COI_ROOT")
    or PROJECT_ROOT / "test" / "COI(식품원재료풀이)"
)
TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")
INDEX_PREFIX_RE = re.compile(r"^\s*([0-9,\s]+)\.")


@dataclass(frozen=True, slots=True)
class CoiEvidence:
    path: Path
    text: str
    matchedScore: int = 0


def NormalizeText(value: object) -> str:
    return unicodedata.normalize("NFC", " ".join(str(value or "").split()))


def EvidenceTokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in TOKEN_RE.findall(NormalizeText(text))
        if len(token) >= 2
    }


def _IndicesFromParent(path: Path) -> set[int]:
    match = INDEX_PREFIX_RE.match(path.parent.name)
    if match is None:
        return set()
    return {
        int(chunk)
        for chunk in match.group(1).replace(" ", "").split(",")
        if chunk.isdigit()
    }


def _XlsxPaths(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        path
        for path in root.rglob("*.xlsx")
        if not path.name.startswith("~$")
    )


def _ScorePath(path: Path, *, caseIndex: int | None, productName: str) -> int:
    score = 0
    if caseIndex is not None and caseIndex in _IndicesFromParent(path):
        score += 100
    haystack = f"{path.parent.name} {path.stem}"
    score += len(EvidenceTokens(productName) & EvidenceTokens(haystack)) * 10
    if "수출가능" in path.name:
        score += 4
    if "수정" in path.name or "최종" in path.name:
        score += 2
    if "복사" in path.name or "copy" in path.name.lower():
        score -= 1
    return score


def FindCoiPath(
    *,
    caseIndex: int | None,
    productName: str,
    coiRoot: Path = DEFAULT_COI_ROOT,
) -> Path | None:
    scored = [
        (_ScorePath(path, caseIndex=caseIndex, productName=productName), path)
        for path in _XlsxPaths(coiRoot)
    ]
    if not scored:
        return None
    scored.sort(key=lambda item: (-item[0], str(item[1])))
    score, path = scored[0]
    return path if score > 0 else None


def _CellToText(value: object) -> str:
    if value is None:
        return ""
    text = NormalizeText(value)
    if not text or text.lower() in {"none", "nan"}:
        return ""
    return text


def FlattenXlsxText(
    path: Path,
    *,
    maxChars: int = 8000,
    maxRowsPerSheet: int = 220,
) -> str:
    try:
        from openpyxl import load_workbook
    except ModuleNotFoundError as exc:
        raise RuntimeError("openpyxl is required to read COI xlsx files") from exc

    workbook = load_workbook(path, read_only=True, data_only=True)
    parts: list[str] = []
    try:
        for sheet in workbook.worksheets:
            rowsAdded = 0
            parts.append(f"[sheet] {sheet.title}")
            for row in sheet.iter_rows(values_only=True):
                values = [_CellToText(value) for value in row]
                values = [value for value in values if value]
                if not values:
                    continue
                parts.append(" | ".join(values))
                rowsAdded += 1
                if rowsAdded >= maxRowsPerSheet:
                    parts.append("[sheet_truncated]")
                    break
                if sum(len(part) + 1 for part in parts) >= maxChars:
                    return "\n".join(parts)[:maxChars]
    finally:
        workbook.close()
    return "\n".join(parts)[:maxChars]


@lru_cache(maxsize=256)
def _CachedFlatten(pathText: str, maxChars: int) -> str:
    return FlattenXlsxText(Path(pathText), maxChars=maxChars)


def LoadCoiEvidence(
    *,
    caseIndex: int | None,
    productName: str,
    coiRoot: Path = DEFAULT_COI_ROOT,
    maxChars: int = 8000,
) -> CoiEvidence | None:
    path = FindCoiPath(
        caseIndex=caseIndex,
        productName=productName,
        coiRoot=coiRoot,
    )
    if path is None:
        return None
    return CoiEvidence(
        path=path,
        text=_CachedFlatten(str(path), maxChars),
        matchedScore=_ScorePath(path, caseIndex=caseIndex, productName=productName),
    )


_HEADER_KEYS = ("품명", "성분", "함량")
_PERCENT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%?")


def _FindTableSheet(workbook):
    """유효 헤더(품명·성분·함량)를 가진 시트 중 데이터 행이 가장 많은 것.

    실물 COI는 다중 시트에 예시 시트가 섞여 있다(1~2번째가 작성 예시인
    파일 실측). 시트명에 '예시'가 있으면 제외하고, 헤더 시그니처로 표를
    찾은 뒤 데이터 행수가 최대인 시트를 고른다 — 순수 결정론 선별.
    """
    best = None  # (data_rows, sheet, header_row_idx, colmap)
    for sheet in workbook.worksheets:
        if "예시" in str(sheet.title):
            continue
        header_idx, colmap = None, {}
        for i, row in enumerate(sheet.iter_rows(values_only=True)):
            cells = {j: NormalizeText(v).lower() for j, v in enumerate(row) if v is not None}
            hits: dict[str, int] = {}
            for j, v in cells.items():
                # 실물 변형 흡수: 영문 헤더(목란), N차 원재료 열(차려낸)
                if ("품명" in v or "product name" in v or v.startswith("구분")) and "품명" not in hits:
                    hits["품명"] = j
                if ("성분" in v or v == "ingredient" or "1차 원재료" in v) and "성분" not in hits:
                    hits["성분"] = j
                if ("함량" in v or "content" in v) and "함량" not in hits:
                    hits["함량"] = j
            if "품명" in hits and "성분" in hits:
                header_idx = i
                # 재료명(하위 단계)·원산지 열도 있으면 기록
                colmap = hits
                for j, v in cells.items():
                    if "재료명" in v or "breakdown" in v:
                        colmap.setdefault("재료명", j)
                    if "원산지" in v or "origin" in v:
                        colmap.setdefault("원산지", j)
                break
            if i > 120:
                break
        if header_idx is None:
            continue
        data_rows = 0
        for i, row in enumerate(sheet.iter_rows(values_only=True)):
            if i <= header_idx:
                continue
            if any(v is not None for v in row):
                data_rows += 1
            if i > header_idx + 400:
                break
        if best is None or data_rows > best[0]:
            best = (data_rows, sheet, header_idx, colmap)
    return best


def ParseCoiComposition(path: Path, *, maxEntries: int = 60) -> list[dict]:
    """COI 원료풀이 표 → 구조화 성분 엔트리 (표기순 = 함량 내림차순 규칙).

    반환: [{ingredient_name, component, percent, order_index, origin,
            source: "coi"}] — composition lane의 ingredient_entries와
    같은 소비 계약. 실패는 빈 목록(no-op).
    """
    try:
        from openpyxl import load_workbook
    except ModuleNotFoundError:
        return []
    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
    except Exception:  # noqa: BLE001 — 손상 파일 = 증거 없음
        return []
    try:
        found = _FindTableSheet(workbook)
        if not found:
            return []
        _n, sheet, header_idx, colmap = found
        c_comp = colmap.get("품명")
        c_ing = colmap.get("성분")
        c_pct = colmap.get("함량")
        c_org = colmap.get("원산지")
        entries: list[dict] = []
        component = ""
        order = 0
        for i, row in enumerate(sheet.iter_rows(values_only=True)):
            if i <= header_idx or len(entries) >= maxEntries:
                continue
            def cell(j):
                if j is None or j >= len(row):
                    return ""
                return NormalizeText(row[j])
            comp_v, ing_v = cell(c_comp), cell(c_ing)
            if comp_v:
                component = comp_v.replace("\n", " ")
            if not ing_v:
                continue  # 하위 단계(재료명)만 있는 행은 1차 성분이 아님
            percent = None
            m = _PERCENT_RE.search(cell(c_pct))
            if m:
                try:
                    percent = float(m.group(1).replace(",", "."))
                except ValueError:
                    percent = None
            order += 1
            entries.append({
                "ingredient_name": ing_v,
                "component": component,
                "percent": percent,
                "order_index": order,
                "origin": cell(c_org),
                "source": "coi",
            })
        return entries
    finally:
        workbook.close()


def SummarizeCoiMatches(
    rows: Iterable[tuple[int | None, str]],
    *,
    coiRoot: Path = DEFAULT_COI_ROOT,
) -> list[dict[str, object]]:
    return [
        {
            "case_index": caseIndex,
            "product_name": productName,
            "coi_path": str(
                FindCoiPath(
                    caseIndex=caseIndex,
                    productName=productName,
                    coiRoot=coiRoot,
                )
                or ""
            ),
        }
        for caseIndex, productName in rows
    ]
