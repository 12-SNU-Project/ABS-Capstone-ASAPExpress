"""CO 로더 — 원산지증명서(Certificate of Origin) 폼(asap-co-v1)의 로딩·주입.

COI(coi_loader)가 '함량'을 채운다면 CO는 '학명(species)·원료별 원산지'를
채운다. 두 문서는 상보적이다 — COI는 composition_facts의 percent·entries,
CO는 species_source 축이 읽는 어휘(학명·통칭)와 origin.

착지 필드(설계): species_source 조건은 아래 통합 집합을 읽는다 —
  identity_hints.* ; composition_facts.ingredient_classes ;
  composition_facts.principal_ingredient ; composition_facts.ingredient_entries
따라서 CO의 학명·통칭은 composition_facts.ingredient_classes(+entries의
name_en 보강)에 실어야 species/identity 조건이 소비한다. origin은 entries의
origin 필드와 별도 origin_facts에 기록(관세 조치 결정 변수 — 코드 아님).

게이트: ASAP_CO_FORM_DIR (=0 이면 OFF). 부재·빈 폼은 no-op — CO 없이도
파이프라인은 그대로 돈다(COI無 케이스와 동일 규율).

원칙 경계(설계자 확정 07-18): CO의 종·원산지는 species_source·원산지 축
전용이다. 정체(identity) 축 관여 금지 — COI '성분 물량 납치'의 재발 방지를
레인 탄생 시점에 잠근다. 원산지는 TARIC10 조치(특혜·덤핑) 결정 변수이지
코드 판별 변수가 아님을 스키마에서 구분 기록한다.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any


def _nfc(text: object) -> str:
    return unicodedata.normalize("NFC", str(text or "")).strip()


def _form_dir() -> Path | None:
    """CO 폼 디렉토리. ASAP_CO_FORM_DIR로 오버라이드. =0 이면 OFF.

    기본값은 없다(COI와 달리 상시 ON 아님) — 명시적 지정 시에만 로드.
    """
    raw = (os.environ.get("ASAP_CO_FORM_DIR") or "").strip()
    if raw in ("0", "off", "false"):
        return None
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_dir() else None


def LoadCoForm(path: Path | str) -> dict | None:
    """asap-co-v1 폼 파일 로드. 스키마 위반·파싱 실패는 None."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if str(data.get("co_form_version") or "").startswith("asap-co-v"):
        return data
    return None


def _load_map(root: Path) -> dict[str, list[str]]:
    """product_map.csv(제품명→co_file) 또는 디렉토리 스캔."""
    mapping: dict[str, list[str]] = {}
    map_path = root / "product_map.csv"
    if map_path.exists():
        import csv
        with map_path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                name = _nfc(row.get("제품명") or row.get("product_name"))
                files = str(row.get("co_file") or "").strip()
                if name and files:
                    mapping[name] = [x.strip() for x in files.split(";") if x.strip()]
    if not mapping:
        for p in sorted(root.glob("co_*.json")):
            form = LoadCoForm(p)
            if form:
                mapping.setdefault(_nfc(form.get("product_name")), []).append(p.name)
    return mapping


def FindFormForProduct(product_name: str) -> dict | None:
    root = _form_dir()
    if root is None:
        return None
    mapping = _load_map(root)
    fnames = mapping.get(_nfc(product_name))
    if not fnames:
        return None
    forms = []
    for fname in fnames:
        form = LoadCoForm(root / fname)
        if form:
            forms.append(form)
    if not forms:
        return None
    if len(forms) == 1:
        return forms[0]
    merged = dict(forms[0])
    items: list[dict] = []
    for f in forms:
        items.extend(f.get("items") or [])
    merged["items"] = items
    return merged


_TAXONOMY_CACHE: list[dict] = []


def _taxonomy() -> dict:
    """상품 분류학 자원(asap-taxonomy-v1) — 종·통칭 → 상위 분류·관세 등록어.

    관세 조문은 'mollusc'·'aquatic invertebrate'·'fish' 같은 **상위 분류
    어휘**로 묻는데 문서(CO)는 'octopus' 같은 **종 수준 사실**만 준다.
    그 사슬을 잇지 않으면 종을 아무리 정확히 적어도 조문의 질문에 답할
    수 없다(합성 감사 실측: 판정 가능률 24%, 결손 146/165가 이 유형).
    자원은 공지 생물분류 + cn_table heading 등록어 대응만 — 임의 저작 0.
    """
    if _TAXONOMY_CACHE:
        return _TAXONOMY_CACHE[0]
    data: dict = {}
    try:
        path = (Path(__file__).resolve().parents[4] / "data" / "taxonomy"
                / "commodity_taxonomy.json")
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — 자원 부재 = 확장 없음(기존 동작)
        data = {}
    _TAXONOMY_CACHE.append(data)
    return data


def ExpandTaxonomy(terms: list[str]) -> list[str]:
    """통칭·학명 목록 → 상위 분류 랭크 + 관세 등록어(중복 제거).

    결정론: 문자열 포함 매칭만(임계·점수 없음). 매칭 실패는 무확장.
    """
    entries = (_taxonomy().get("entries") or [])
    low = " ".join(_nfc(t).lower() for t in terms if t)
    out: list[str] = []
    for entry in entries:
        for key in entry.get("match") or []:
            if str(key).lower() in low:
                out.extend(str(x) for x in (entry.get("ranks") or []))
                out.extend(str(x) for x in (entry.get("tariff_terms") or []))
                break
    return list(dict.fromkeys(out))


def _species_tokens(item: dict) -> list[str]:
    """한 CO 항목에서 species/identity 조건이 소비할 어휘.

    통칭·학명 + **분류학 확장**(상위 분류·관세 등록어). 확장이 없으면
    'octopus'는 있는데 'mollusc' 질문에 답을 못 한다.
    """
    out: list[str] = []
    for key in ("ingredient_en", "common_name_en", "scientific_name"):
        val = _nfc(item.get(key))
        if val:
            out.append(val)
    out.extend(ExpandTaxonomy(out))
    return list(dict.fromkeys(out))


def ApplyCoForm(pu: dict[str, Any], form: dict | None = None) -> int:
    """PU dict의 composition_facts에 CO의 학명·통칭·원산지를 주입.

    반환: 주입 항목 수(0=no-op). 기존값 보존(가산) — COI가 채운 entries·
    ingredient_classes를 덮지 않고 종 어휘만 보강한다.
    """
    if _form_dir() is None and form is None:
        return 0
    if form is None:
        form = FindFormForProduct(str(pu.get("product_name") or ""))
    items = (form or {}).get("items") or []
    if not items:
        return 0

    cf = dict(pu.get("composition_facts") or {})
    classes = list(cf.get("ingredient_classes") or [])
    seen = {_nfc(c).lower() for c in classes}
    origin_facts: list[dict] = list(cf.get("origin_facts") or [])
    injected = 0
    # entries에 학명 name_en 보강(같은 재료명 매칭 시)
    entries = [e for e in (cf.get("ingredient_entries") or []) if isinstance(e, dict)]
    entry_by_key = {}
    for e in entries:
        key = _nfc(e.get("ingredient_name")).split(" / ")[0].split(" (")[0].lower()
        entry_by_key.setdefault(key, e)

    for item in items:
        toks = _species_tokens(item)
        for t in toks:
            if t.lower() not in seen:
                classes.append(t)
                seen.add(t.lower())
                injected += 1
        # origin은 species_source 판별이 아니라 조치 변수 — 별도 평면 기록
        origin = _nfc(item.get("origin_country") or item.get("origin"))
        if origin:
            origin_facts.append({
                "ingredient": _nfc(item.get("ingredient_ko") or item.get("ingredient_en")),
                "origin": origin,
                "scientific_name": _nfc(item.get("scientific_name")),
                "provenance": "CO",
                "role": "tariff_measure_input",  # 코드 아님 — 특혜·덤핑 결정
            })
        # 매칭 entries에 학명 병기(존재 시)
        ko = _nfc(item.get("ingredient_ko")).lower()
        sci = _nfc(item.get("scientific_name"))
        if ko and sci and ko in entry_by_key:
            e = entry_by_key[ko]
            name = _nfc(e.get("ingredient_name"))
            if sci.lower() not in name.lower():
                e["ingredient_name"] = f"{name} [{sci}]"
                e["scientific_name"] = sci
            if not e.get("origin"):
                e["origin"] = _nfc(item.get("origin_country") or item.get("origin"))

    if injected or origin_facts:
        cf["ingredient_classes"] = classes
        if origin_facts:
            cf["origin_facts"] = origin_facts
        cf["ingredient_entries"] = entries
        pu["composition_facts"] = cf
    return injected
