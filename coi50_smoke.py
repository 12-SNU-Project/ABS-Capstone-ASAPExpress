"""COI 정규화 폼 주입 스모크 — 식품 50건 (EU_HS_test2.csv).

에셋 배선:
  제품명                     -> identity_lane (PU의 LLM 재구성)
  LLM 재구성 + 정규화 COI    -> composition_lane
     · ingredient_entries  = 정규화 COI entries (role/section/sub 포함)
     · principal_ingredient / accessory_ingredients = 폼의 후보 필드
  주입 시점: ProductUnderstanding 직후, Hs2Routing 이전 (blackboard 패치)

정답: EU_HS_test2.csv의 'EU HS CODE' 컬럼 (hs2/hs4/hs6/cn8 채점).
COI 매핑: data/coi_normalized/product_map.csv (coi_normalize.py 산출,
수기 교정 반영됨) — coi_file 빈 행은 COI 없이 돈다(대조군 겸용).

실행:
  PYTHONPATH=src python coi50_smoke.py --limit 5     # 파일럿
  PYTHONPATH=src python coi50_smoke.py --limit 0     # 전량 50건
  PYTHONPATH=src python coi50_smoke.py --no-coi      # 대조군 (COI 미주입)
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
ANSWER_CSV = PROJECT_ROOT / "data" / "EU_HS_test2.csv"
COI_DIR = PROJECT_ROOT / "data" / "coi_normalized"
ARTIFACT_ROOT = PROJECT_ROOT / "artifacts" / "coi50-smoke"
LEVELS = (("hs2", 2), ("hs4", 4), ("hs6", 6), ("cn8", 8))


def _digits(v: object) -> str:
    return re.sub(r"\D", "", str(v or ""))


def _nfc(t: object) -> str:
    return unicodedata.normalize("NFC", str(t or "")).replace("\xa0", " ").strip()


def _load_coi_map() -> dict[str, dict]:
    """제품명(NFC) → 정규화 COI 폼."""
    out: dict[str, dict] = {}
    map_path = COI_DIR / "product_map.csv"
    if not map_path.exists():
        return out
    for r in csv.DictReader(open(map_path, encoding="utf-8-sig")):
        name, fnames = _nfc(r.get("제품명")), str(r.get("coi_file") or "").strip()
        if not name or not fnames:
            continue
        forms = []
        for fname in fnames.split(";"):
            path = COI_DIR / fname.strip()
            if path.exists():
                try:
                    forms.append(json.loads(path.read_text(encoding="utf-8")))
                except Exception:  # noqa: BLE001
                    continue
        if len(forms) == 1:
            out[name] = forms[0]
        elif forms:
            out[name] = _merge_forms(forms)
    return out


def _merge_forms(forms: list[dict]) -> dict:
    """다중 COI(구성품별 제조사 상이) → 결합 폼.

    각 COI가 하나의 구획이 된다: 밀키트의 {어묵 COI, 김치 COI, 면 COI,
    소스 COI} → 주성분 후보 = 각 COI의 대표. 확정은 주입점 교차·%가 한다.
    """
    merged = {
        "coi_form_version": forms[0].get("coi_form_version"),
        "source_file": "; ".join(str(f.get("source_file")) for f in forms),
        "product_name_hint": forms[0].get("product_name_hint"),
        "folder_hint": forms[0].get("folder_hint"),
        "sections": [], "entries": [],
        "principal_candidates": [], "principal_ingredient": "",
        "accessory_ingredients": [],
        "coverage": "full" if any(f.get("coverage") == "full" for f in forms) else "sauce_only",
        "parse_status": "ok",
    }
    order = 0
    for f in forms:
        hint = str(f.get("product_name_hint") or "")[:14]
        for e in f.get("entries") or []:
            order += 1
            e2 = dict(e)
            e2["order_index"] = order
            e2["section"] = f"{hint}:{e.get('section') or ''}".strip(":")
            merged["entries"].append(e2)
        for s in f.get("sections") or []:
            tag = f"{hint}:{s}"
            if tag not in merged["sections"]:
                merged["sections"].append(tag)
        if f.get("coverage") == "full":
            for c in f.get("principal_candidates") or []:
                if c not in merged["principal_candidates"]:
                    merged["principal_candidates"].append(c)
        for a in f.get("accessory_ingredients") or []:
            if a not in merged["accessory_ingredients"]:
                merged["accessory_ingredients"].append(a)
    merged["principal_candidates"] = merged["principal_candidates"][:4]
    merged["accessory_ingredients"] = merged["accessory_ingredients"][:8]
    return merged


def _coi_to_pipeline_entries(form: dict) -> list[dict]:
    """정규화 폼 entries → composition lane ingredient_entries 계약."""
    rows = []
    for e in form.get("entries") or []:
        name = str(e.get("name_ko") or e.get("name_raw") or "")
        subs = [s for s in (e.get("sub_ingredients") or []) if s]
        pct = e.get("percent")
        try:
            pct = float(pct) if pct not in (None, "") else None
        except (TypeError, ValueError):
            pct = None
        try:
            oi = int(e.get("order_index") or 0) or None
        except (TypeError, ValueError):
            oi = None
        en = str(e.get("name_en") or "").strip()
        display = name if not subs else f"{name} ({', '.join(subs)})"
        if en:
            display = f"{display} / {en}"
        rows.append({
            "ingredient_name": display,
            "component": e.get("section") or "",
            "role": e.get("role") or "other",
            "percent": pct,
            "order_index": oi,
            "origin": e.get("origin") or "",
            "source": "coi_normalized",
        })
    return rows


_RECON_SERVICE = None


def _reconstruct(product_name: str, coi_form: dict | None) -> tuple[list[str], list[dict]]:
    """제품명(+COI 원문)을 증거로 LLM 재구성 — kurly 파이프라인과 동일 서비스.

    반환: (fact_texts, product_facts). 실패는 빈 값(no-op) — COI 주입과
    독립이라 재구성이 죽어도 체인은 돈다.
    """
    global _RECON_SERVICE
    try:
        from bussiness_logic.input_process.reconstruction import (
            InputEvidencePackage, InputEvidenceRecord, ProductInputReconstructionService,
        )
        from bussiness_logic.bridge.runtime_adapter import BuildPipelineRuntimeAdapter
        if _RECON_SERVICE is None:
            _RECON_SERVICE = ProductInputReconstructionService(
                runtimeAdapter=BuildPipelineRuntimeAdapter())
        records = [InputEvidenceRecord(
            evidence_id="ev_001", source_type="notice",
            text=f"제품명: {product_name}", source_ref="product_name")]
        if coi_form:
            # 원문 평탄 텍스트는 유의사항·하위 성분('굴추출물농축액')까지
            # fact로 승격시켜 identity를 오염시킨다(실측: 비빔장→1603 추출물).
            # 대신 정규화 폼을 구조 텍스트로 렌더 — 구획/성분/%/role만.
            lines = []
            for e in (coi_form.get("entries") or [])[:30]:
                seg = f"{e.get('section') or ''} | {e.get('name_raw') or e.get('name_ko')}"
                if e.get("percent"):
                    seg += f" | {e['percent']}%"
                lines.append(seg)
            if lines:
                records.append(InputEvidenceRecord(
                    evidence_id="ev_coi_form", source_type="table_ocr",
                    text="원재료 구성(정규화 COI):\n" + "\n".join(lines),
                    source_ref="coi_normalized_form"))
        result = _RECON_SERVICE.ReconstructFromEvidencePackage(
            InputEvidencePackage(records=records))
        fact_texts = [f.ToFactText() for f in result.productFacts if f.ToFactText()]
        product_facts = [
            {"field_name": f.fieldName, "value": f.normalizedValue}
            for f in result.productFacts if f.normalizedValue
        ]
        return fact_texts, product_facts
    except Exception as error:  # noqa: BLE001 — 재구성 실패는 no-op
        print(f"    (재구성 실패: {type(error).__name__}: {str(error)[:60]})")
        return [], []


def run_chain(raw_input: dict, run_dir: Path, coi_form: dict | None) -> tuple[list[str], dict]:
    from bussiness_logic.pipeline.blackboard import BlackboardStore
    from bussiness_logic.input_process.components.evidence_intake import EvidenceIntakeComponent
    from bussiness_logic.product.components.product_understanding import ProductUnderstandingComponent
    from bussiness_logic.classification.components.hs2_routing import Hs2RoutingComponent
    from bussiness_logic.classification.components.classification import ClassificationComponent

    store = BlackboardStore.create(
        runtime_mode="smoke", run_id="run_001",
        run_dir=run_dir, validate_on_write=False,
    )
    injected = {"coi_injected": False, "coi_entries": 0}
    for component in (
        EvidenceIntakeComponent(raw_input),
        ProductUnderstandingComponent(),
        Hs2RoutingComponent(),
        ClassificationComponent(),
    ):
        result = component.Execute(store)
        if not result.success:
            return [], injected
        # PU 직후: 정규화 COI를 composition lane에 주입 (라우팅 전)
        if isinstance(component, ProductUnderstandingComponent) and coi_form:
            bb = store.load()
            pu = bb.get("product_understanding") or {}
            cf = dict(pu.get("composition_facts") or {})
            entries = _coi_to_pipeline_entries(coi_form)
            if entries:
                # 가산 주입: 재구성(라벨 파서)이 채운 entries를 보존하고 COI를
                # 뒤에 더한다 — 'LLM_reconstruction + COI'의 문자 그대로.
                existing = [e for e in (cf.get("ingredient_entries") or [])
                            if isinstance(e, dict)]
                seen_names = {str(e.get("ingredient_name") or "").strip() for e in existing}
                added = [e for e in entries
                         if str(e.get("ingredient_name") or "").strip() not in seen_names]
                cf["ingredient_entries"] = existing + added
                # 표기 1위는 '후보'일 뿐이다 — identity(정체)와 토큰이 겹칠
                # 때만 주성분으로 확정 주입 (재첩국 clam↔Marsh Clam Broth ✓,
                # 군만두 dumpling↔당면 ✗→후보 병기만). 겹침 판정은 원문
                # 부분문자열 + 영문 토큰 겹침 둘 다 인정.
                cands = [str(c) for c in (coi_form.get("principal_candidates") or []) if c]
                cands_en = [str(c) for c in (coi_form.get("principal_candidates_en") or [])]
                form_principal = str(coi_form.get("principal_ingredient") or "")
                # 후보 1~3 중 identity와 교차하는 것을 주성분으로 결정
                # ('김치 우동 전골' × {김치,우동면,육수} → 우동면). %가
                # 붙은 후보가 있으면 % 최대가 교차보다 우선(법정 서열).
                if cands and not form_principal:
                    ih0 = pu.get("identity_hints") or {}
                    id_text0 = " ".join([
                        str(ih0.get("principal_ingredient_guess") or ""),
                        *[str(x) for x in (ih0.get("identity_terms") or [])],
                        str(ih0.get("normalized_tariff_description") or ""),
                        str(pu.get("product_name") or ""),
                    ]).lower()
                    by_pct = [(e.get("percent") or 0, str(e.get("ingredient_name") or ""))
                              for e in entries if any(str(c) in str(e.get("ingredient_name") or "") for c in cands)]
                    by_pct = [x for x in by_pct if x[0]]
                    if by_pct and len(by_pct) >= 2:
                        form_principal = max(by_pct)[1]
                    else:
                        id_toks0 = {w for w in re.findall(r"[a-z가-힣]{2,}", id_text0)}
                        for ci, c in enumerate(cands):
                            en = cands_en[ci] if ci < len(cands_en) else ""
                            cl = (c + " " + en).lower()
                            ctoks = {w for w in re.findall(r"[a-z가-힣]{2,}", cl)}
                            # 양방향 포함: 후보 토큰이 정체 텍스트에 있거나
                            # ('우동면'⊃'우동'), 정체 토큰이 후보에 있거나
                            # ('꼬막' ⊂ '새꼬막살') — 한글 접두·복합어 대응.
                            crossed0 = (
                                any(tk in id_text0 for tk in ctoks)
                                or any(it in cl for it in id_toks0 if len(it) >= 2)
                            )
                            if crossed0:
                                form_principal = c
                                break
                if cands:
                    cf["coi_principal_candidates"] = cands
                if form_principal:
                    ih = pu.get("identity_hints") or {}
                    id_text = " ".join([
                        str(ih.get("principal_ingredient_guess") or ""),
                        *[str(x) for x in (ih.get("identity_terms") or [])],
                        str(ih.get("normalized_tariff_description") or ""),
                    ]).lower()
                    ptoks = {w for w in re.findall(r"[a-z가-힣]{2,}", form_principal.lower())}
                    crossed = any(tk in id_text for tk in ptoks)
                    if crossed:
                        cf["principal_ingredient"] = form_principal
                    else:
                        cf["coi_principal_candidates"] = [form_principal]
                if coi_form.get("accessory_ingredients"):
                    cf["accessory_ingredients"] = coi_form["accessory_ingredients"]
                # 구획 role은 boolean lane의 상위 정보 — wrapper/sauce 구획이
                # 실재하면 대응 boolean도 폼 근거로 동기화한다
                roles = {e["role"] for e in entries}
                if "wrapper" in roles:
                    cf["contains_wrapper_or_dough"] = True
                if "sauce" in roles:
                    cf["contains_sauce_or_broth"] = True
                if "broth" in roles:
                    cf["contains_sauce_or_broth"] = True
                pu["composition_facts"] = cf
                bb["product_understanding"] = pu
                store.save(bb)
                injected = {"coi_injected": True, "coi_entries": len(entries)}
    bb = store.load()
    code_sets = bb.get("candidate_code_sets") or []
    latest = code_sets[-1] if code_sets else {}
    return [
        _digits(c.get("cn8"))[:8]
        for c in (latest.get("candidates") or [])
        if _digits(c.get("cn8"))
    ], injected


def main() -> int:
    import os
    # 구식 COI 경로 강제 차단 — ASAP_COI_ROOT가 셸에 남아 있으면 PU의
    # 기존 로더가 몰래 entries·주성분('정제수')을 채워 A/B 대조가 오염된다
    # (실측: no-coi 런에 coi 출처 16개). 이 스모크의 COI는 정규화 폼만.
    if os.environ.pop("ASAP_COI_ROOT", None):
        print("(주의: ASAP_COI_ROOT 감지 — 이 스모크에서는 구식 COI 경로를 차단한다)")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--no-coi", action="store_true", help="대조군: COI 미주입")
    args = ap.parse_args()

    coi_map = {} if args.no_coi else _load_coi_map()
    rows = []
    for r in csv.DictReader(open(ANSWER_CSV, encoding="utf-8-sig")):
        name = _nfc(r.get("제품명"))
        answer = _digits(r.get("EU HS CODE"))[:8]
        if not name or len(answer) < 6:
            continue
        rows.append({"name": name, "answer": answer.ljust(8, "0")[:8]})
    print(f"유효 {len(rows)}건 | COI 매핑 보유 {sum(1 for r in rows if r['name'] in coi_map)}건"
          f"{' (COI 미주입 대조군 모드)' if args.no_coi else ''}")
    rows = rows[args.offset:]
    if args.limit:
        rows = rows[: args.limit]

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    agg = {s: {n: Counter() for n, _ in LEVELS} for s in ("전체", "COI有", "COI無")}
    n_by = Counter()
    results = []
    for index, row in enumerate(rows):
        form = coi_map.get(row["name"])
        fact_texts, product_facts = _reconstruct(row["name"], form)
        raw_input = {
            "product_name": row["name"],
            "description": "",
            "reconstructed_fact_texts": fact_texts,
            "reconstructed_product_facts": product_facts,
            "source_urls": [],
        }
        run_dir = ARTIFACT_ROOT / stamp / f"row{args.offset + index}"
        try:
            candidates, inj = run_chain(raw_input, run_dir, form)
        except Exception as error:  # noqa: BLE001
            print(f"  ! {row['name'][:24]}: {type(error).__name__}: {str(error)[:80]}")
            candidates, inj = [], {"coi_injected": False}
        bucket = "COI有" if inj.get("coi_injected") else "COI無"
        n_by["전체"] += 1
        n_by[bucket] += 1
        marks = []
        for level, width in LEVELS:
            top1 = bool(candidates) and candidates[0][:width] == row["answer"][:width]
            top3 = any(c[:width] == row["answer"][:width] for c in candidates[:3])
            for scope in ("전체", bucket):
                agg[scope][level]["top1"] += int(top1)
                agg[scope][level]["top3"] += int(top3)
            marks.append("O" if top1 else ("o" if top3 else "X"))
        results.append({**row, "coi": inj, "candidates": candidates[:3], "marks": marks})
        print(f"  [{args.offset + index}] {'/'.join(marks)} {row['name'][:26]:<28} "
              f"답={row['answer']} top1={candidates[0] if candidates else '-'} "
              f"{'COI' + str(inj.get('coi_entries', 0)) if inj.get('coi_injected') else 'noCOI'}")

    print(f"\n=== COI50 스모크 ({n_by['전체']}건) ===")
    for scope in ("전체", "COI有", "COI無"):
        m = n_by[scope]
        if not m:
            continue
        parts = []
        for level, _ in LEVELS:
            t1, t3 = agg[scope][level]["top1"], agg[scope][level]["top3"]
            parts.append(f"{level} {t1}/{m}({t1 / m * 100:.0f}%)·top3 {t3}")
        print(f"  [{scope} {m}건] {'  '.join(parts)}")
    out = ARTIFACT_ROOT / stamp / "coi50-summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"n": n_by["전체"], "no_coi_mode": args.no_coi,
                               "results": results}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"→ {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
