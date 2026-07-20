"""Decision-table evaluator (runtime, no LLM).

Implements the designer model: at a branching point, check each sibling's
compiled CONDITIONS against the bound ProductUnderstandingFacts fields.

  confirmed   every condition of the code answered true  -> that code wins
  violated    any condition answered false               -> code is out
  undecided   conditions unanswerable (missing data)     -> lexical fallback

Confirmation requires the BOUND FIELD to answer (alias-expanded for
species/contains) — a broad-pool match is not enough to confirm (precision:
a stray OCR token must not certify a code). Violation uses the broad pool
(recall: an exclusion must be caught wherever the token lives) with
whole-phrase semantics ("common wheat flour" needs every content word).

Degrades to {} on any DB failure; the sidecar's absence turns the whole
layer off.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Mapping

from bussiness_logic.classification.rules.branch_predicate_evaluator import _aliases, _dig, _field_tokens, _stem

_TOKEN = re.compile(r"[a-z]+")

# boolean 필드의 법조문 어휘 선언 — 필드명(wrapper/dough)과 조건어(stuffed)의
# 레지스터 갭을 잇는 필드 수준 사전. 제품·코드 하드코딩이 아니라 "이 boolean이
# 답하는 법조문 단어"의 정의다 (군만두 190220 'stuffed' ↔ wrapper=True 실측 갭).
_BOOLEAN_REGISTER = {
    "contains_wrapper_or_dough": frozenset({"stuffed", "filled"}),
    "contains_sauce_or_broth": frozenset({"sauce", "broth"}),
}
_UN_PREFIX = ("un", "non")

# binding-v1: (cond_type|leaf) 확정 자격을 손 규칙이 아니라 실측 정밀도로.
# artifacts/binding_v1.json (캘리브레이터 산출물). 파일 부재/게이트 OFF면
# 손 규칙(_TYPED_LEAVES 계열) 폴백. 임계는 env로 노출:
#   ASAP_BINDING_MIN_N (기본 10) / ASAP_BINDING_MIN_PRECISION (기본 0.25
#   — 형제 ~10개 기준 무작위 10%의 2.5배 lift)
_binding_cache: list[dict] = []


def _binding_table() -> dict:
    if not _binding_cache:
        import pathlib
        loaded = {}
        try:
            path = os.environ.get("ASAP_BINDING_V1_PATH") or str(
                pathlib.Path(__file__).resolve().parents[4] / "artifacts" / "binding_v1.json")
            data = json.loads(open(path, encoding="utf-8").read())
            min_n = int(os.environ.get("ASAP_BINDING_MIN_N", "10"))
            min_p = float(os.environ.get("ASAP_BINDING_MIN_PRECISION", "0.25"))
            for key, v in (data.get("pairs") or {}).items():
                if int(v.get("n", 0)) >= min_n and float(v.get("precision", 0)) >= min_p:
                    loaded[key] = True
        except Exception:  # noqa: BLE001 — 산출물 부재 = 손 규칙 폴백
            loaded = {}
        _binding_cache.append(loaded)
    return _binding_cache[0]


def _polarity_conflict(value_tokens: frozenset, state_tokens: set) -> bool:
    """un-/non- 형태론 극성: 조건 'uncooked' vs 상태 'cooked' → 충돌.

    정확한 형태론 쌍만 판정 — 'prepared'가 'uncooked'를 위반하는 식의 인접
    개념 추론은 하지 않는다(요리 상태 vs 구성품 상태 서열 미해결).
    """
    for v in value_tokens:
        for pref in _UN_PREFIX:
            if v.startswith(pref) and len(v) > len(pref) + 2 and v[len(pref):] in state_tokens:
                return True
        if any(pref + v in state_tokens for pref in _UN_PREFIX):
            return True
    return False
# 확정(confirmed) 자격을 줄 수 있는 typed 경로(단수·저오염 필드).
# NTD·identity_terms 같은 자유서술 다토큰 필드는 부수 요소('soup' 등)가
# 섞여 확정 정밀도 17%(정 7/오 33) 실측 — 이들 '단독' 히트는 확정 불가.
# ingredient_class는 제외: 'cereal' 같은 류(class) 값은 1901~1905 전부에
# 해당해 확정 근거로 판별력이 없다 — 오발동 6건 중 5건이 이 경로 실측.
# 점수 경쟁(+3)에는 계속 참여하고 확정(+50) 자격만 없다.
# ingredient_classes(복수)·contains_sauce_or_broth 제외 — 동족 원칙:
# 류값(fish/mollusc)은 1601~1605 전부에 걸리고(오발동 3건 실측, 'cereal'
# 사태의 복수형 재발), "국물이 있다"(boolean T)는 "국물요리다"(정체)가
# 아니다(2104 확정 정1/오7 실측). 두 신호 모두 +3 증거와 위반 판정은
# 유지하고 확정(+50) 자격만 없다. wrapper는 구조 판별력이 있어 유지.
_TYPED_LEAVES = frozenset({
    "food_form", "processing_state",
    "principal_ingredient", "contains_wrapper_or_dough",
})
_ALIAS_AXES = frozenset({
    "species", "contains",  # 구세대 명칭 호환
    "species_source", "material_composition", "product_identity",
})


def LoadBranchDecisions(
    level: str,
    parent_codes: tuple[str, ...],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """{parent -> {then_code -> [condition rows]}}; {} on failure/absence."""
    if not parent_codes:
        return {}
    version = (os.environ.get("ASAP_DECISION_VERSION", "parser-v1") or "").strip()
    try:
        from sqlalchemy import bindparam, text

        from db.db_session_manager import DbSessionManager

        manager = DbSessionManager.GetInstance()
        params = {"level": level, "parents": tuple(parent_codes), "version": version}
        # [11회차-2 §1-A] 구판 폴백 SELECT 소멸 — role/grade 컬럼 부재
        # 시절의 호환 경로(P1-B)를 제거했다. 현행 테이블 23,881행은
        # role·grade를 전부 보유(dry 컴파일 행 키 실측). 폴백이 살아
        # 있으면 grade SELECT 누락 사고(9회차 판례 상한 무작동)가
        # '조용한 성공'으로 위장된다 — 컬럼 사고는 아래 except로 층 off
        # (사이드카 부재와 동일 취급)로 드러나야 한다.
        rows = manager.FetchRows(
            text(
                'SELECT branch_id, seq, then_code, cond_type, dto_field, op,'
                ' value, source_text, role, grade, alt_group'
                ' FROM "branch_decision_index"'
                " WHERE level = :level AND branch_id IN :parents AND version = :version"
                " ORDER BY branch_id, seq"
            ).bindparams(bindparam("parents", expanding=True)),
            params,
        )
    except Exception:  # noqa: BLE001 — sidecar absent = layer off
        return {}
    out: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for row in rows:
        data = dict(row)
        parent = str(data.get("branch_id") or "")
        code = str(data.get("then_code") or "")
        out.setdefault(parent, {}).setdefault(code, []).append(data)
    return out


def _phrase_sets(value_json: str) -> list[set[str]]:
    try:
        values = json.loads(str(value_json or "null"))
    except Exception:  # noqa: BLE001
        return []
    phrases: list[set[str]] = []
    for value in values or []:
        toks = {_stem(t) for t in _TOKEN.findall(str(value).lower()) if len(t) >= 3}
        if toks:
            phrases.append(toks)
    return phrases


def EvaluateCodeDecision(
    conditions: list[Mapping[str, Any]],
    product_facts: Mapping[str, Any] | None,
    fact_tokens: frozenset[str] | set[str],
    percentages: list[Any],
    quant_verdict_fn,
) -> tuple[str, list[dict[str, str]]]:
    """('confirmed'|'violated'|'undecided', detail) for ONE code's conditions."""
    pool = set(fact_tokens)
    detail: list[dict[str, str]] = []
    answers: list[str] = []
    _grp_answers: dict[str, list[str]] = {}
    _alt_on = (os.environ.get("ASAP_ALT_GROUP_OR", "1") or "1").strip() != "0"
    # [P1-D3] 백과(encyclopedia) 유래 토큰 — 검색 API 잡음(무관 문서)이
    # 지각 필드로 유입돼 확정을 만든 사고(전골 2104 confirmed 55 실측:
    # 백과 서술의 soup/broth가 정체 조건을 확정). 원천 구분이 필드에서
    # 소실되므로 근사한다: 백과 entries 텍스트 토큰 중 1차 원천(상품명·
    # 상세·페이지 재구성 서술)에 등장하지 않는 것만 '백과 전유'로 본다.
    # 백과 전유 토큰이 성립시킨 매치는 확정(+50) 자격을 잃고 지지(+3)만
    # 유지 — typed_gate_blocked·alias_hit 선례와 동일 원칙.
    # ASAP_DECISION_ENC_CAP=0 복귀.
    enc_exclusive: frozenset = frozenset()
    if product_facts and (os.environ.get(
            "ASAP_DECISION_ENC_CAP", "1") or "1").strip() != "0":
        enc_toks: set = set()
        for e in _dig(product_facts, "encyclopedia_evidence.entries") or []:
            if isinstance(e, dict):
                for t in (e.get("title"), e.get("description")):
                    enc_toks |= {_stem(w) for w in _TOKEN.findall(str(t or "").lower())
                                 if len(w) >= 3}
        if enc_toks:
            primary: set = set()
            for path in ("product_name", "short_description",
                         "classification_text",
                         "identity_hints.translated_product_name"):
                primary |= _field_tokens(product_facts, path)
            for t in _dig(product_facts, "reconstructed_fact_texts") or []:
                primary |= {_stem(w) for w in _TOKEN.findall(str(t).lower())
                            if len(w) >= 3}
            enc_exclusive = frozenset(enc_toks - primary)
    for cond in conditions:
        cond_type = str(cond.get("cond_type") or "")
        op = str(cond.get("op") or "")
        dto_field = str(cond.get("dto_field") or "")
        # [P1-D1] qualifier(그룹 공통 자격층)는 순위 합산 불참 — true 지지도
        # violated 감점도 없다. 판별이 아니라 소속이기 때문(조상 헤더 텍스트
        # 를 형제 개별 조건으로 실었던 R5 청양고추 사고의 구조적 처방).
        # answers에 넣지 않으므로 확정/위반/미결 집계에 완전 불참.
        if str(cond.get("role") or "").strip() == "qualifier":
            detail.append({"cond": cond_type, "op": op, "verdict": "skipped",
                           "field": dto_field.split(";")[0][:40],
                           "why": "qualifier_rank_excluded",
                           "value": str(cond.get("value") or "")[:80]})
            continue
        verdict = "undecided"
        why = ""
        if op == "quant_gate":
            result = quant_verdict_fn(str(cond.get("source_text") or ""), percentages)
            verdict = {"satisfies": "true", "violates": "false"}.get(
                (result or {}).get("verdict"), "undecided")
            why = (result or {}).get("reason", "") or (
                "no_percentages" if not percentages else "threshold_unparsed")
            # 임계를 파싱 못 했으면 충족 판정 불가 — satisfies가 새어 나와
            # 확정 자격(quant true)을 주던 버그의 가드 (떡볶이 19022010
            # 54점 확정 실측: 값=null·threshold_unparsed인데 true).
            if verdict == "true" and ("unparsed" in why or "no_percentages" in why):
                verdict = "undecided"
                why += ";quant_unparsed_guard"
        elif op == "not_contains":
            phrases = _phrase_sets(str(cond.get("value")))
            judge_pool = pool
            why_suffix = ""
            if str(cond.get("role") or "").strip() == "eliminator":
                # [P2-1] 거울 배제 이중 가드 — 잔반의 eliminator가 광역 풀
                # 잡음에 위반당하면 승격 경로가 원천 봉쇄된다 (프로덕션
                # 실측: 백과 유래 'sweet'가 청양고추 59의 not_contains
                # ['sweet pepper']를 위반시켜 잔반 미승격).
                # ② 판정 풀을 이 조건의 bound 정체 필드로 한정 — 정체
                #    질문은 정체 필드가 답한다 (원리 2). 필드 침묵 시에도
                #    광역 풀로 돌아가지 않는다(침묵은 위반 근거가 아니다).
                # ① 그 풀에서 백과 전유 토큰 차감 — 3급 증거는 위반 확정
                #    자격이 없다 (원리 1: 백과 잡음은 identity_terms까지
                #    침투하므로 ②만으로는 부족 — 전골 실측).
                if dto_field and dto_field != "*tokens*":
                    judge_pool = set(_field_tokens(product_facts, dto_field))
                judge_pool = judge_pool - enc_exclusive
            if any(p <= judge_pool for p in phrases):
                verdict = "false"
                why = "exclusion_present_in_pool"
            else:
                why = "exclusion_absent"
                if judge_pool is not pool and any(p <= pool for p in phrases):
                    # 가드가 광역 풀 위반을 실제로 막았음을 노출 (실증용)
                    why_suffix = ";broad_pool_hit_guarded"
            why += why_suffix
        elif op == "has_token":
            phrases = _phrase_sets(str(cond.get("value")))
            bound = _field_tokens(product_facts, str(cond.get("dto_field") or ""))
            # ── 극성 평가 (ASAP_DECISION_POLARITY, 기본 ON) ──
            polarity_on = (os.environ.get(
                "ASAP_DECISION_POLARITY", "1") or "1").strip() != "0"
            if polarity_on:
                all_value_toks = frozenset(tk for ph in phrases for tk in ph)
                pol_done = False
                # B. boolean 레지스터: False면 해당 어휘 조건 위반, True면 히트
                for leaf, register in _BOOLEAN_REGISTER.items():
                    if not (all_value_toks & register):
                        continue
                    # sauce/broth '함유'는 정체가 아니다 — 조리식품 대부분이
                    # sauce=True라 판별력 0인데 2104(수프)의 정체 조건 'broth'
                    # 를 확정해 비빔장을 수프로 만들었다(실측). 정체 축에서는
                    # 이 레지스터의 승격·위반 모두 미적용(lexical 폴백).
                    # wrapper↔stuffed는 구조=정체라 유지(190220 정답 경로).
                    if (
                        leaf == "contains_sauce_or_broth"
                        and cond_type in ("product_identity", "intended_use_function")
                    ):
                        continue
                    flag = _dig(product_facts, f"composition_facts.{leaf}")
                    # wrapper 의미 분리(팀장 안건 적용): '도우로 만듦'과 '속을
                    # 채움'은 다른 사실인데 wrapper=True가 stuffed/filled로
                    # 직승격되어 떡이 stuffed로 읽혔다(골든 실측). True 승격은
                    # DTO 어딘가에 채움 서술(stuff-/fill- 형태)이 실재할 때만
                    # 허용, 없으면 레지스터를 건너뛰고 lexical 평가로 폴백.
                    # False(위반) 쪽은 그대로 — 도우 자체가 없으면 stuffed일 수
                    # 없다. ASAP_WRAPPER_SEMANTICS=0 구판 복귀.
                    if (
                        flag is True
                        and leaf == "contains_wrapper_or_dough"
                        and (os.environ.get("ASAP_WRAPPER_SEMANTICS", "1") or "1").strip() != "0"
                    ):
                        corrob = _field_tokens(
                            product_facts,
                            "identity_hints.identity_terms;"
                            "identity_hints.product_form_terms;"
                            "identity_hints.normalized_tariff_description",
                        )
                        if not any(tk.startswith(("stuff", "fill")) for tk in corrob):
                            break  # 레지스터 미적용 → lexical 폴백
                    if flag is True:
                        verdict, why, pol_done = "true", f"field_hit:{leaf}", True
                    elif flag is False:
                        # False 위반의 거울상 가드: 정체 lane이 해당 어휘를
                        # 긍정 서술하는데 boolean만 False면 두 lane의 모순
                        # (파서 미충전 가능성) — 위반 대신 lexical 폴백.
                        # 실측: 군만두 wrapper=False 오충전이 identity의
                        # 'stuffed pasta' 4증거를 -100으로 뒤집어 190219 어부지리.
                        # 같은 ASAP_WRAPPER_SEMANTICS 게이트로 복귀.
                        if (os.environ.get("ASAP_WRAPPER_SEMANTICS", "1") or "1").strip() != "0":
                            corrob = _field_tokens(
                                product_facts,
                                "identity_hints.identity_terms;"
                                "identity_hints.product_form_terms;"
                                "identity_hints.normalized_tariff_description",
                            )
                            prefixes = tuple({tok[:5] for tok in register})
                            if any(tk.startswith(prefixes) for tk in corrob):
                                break  # lane 모순 — 레지스터 미적용
                        verdict, why, pol_done = "false", f"polarity:{leaf}=False", True
                    break
                # A. un-/non- 형태론: typed 상태 필드와의 극성 충돌만 위반
                if not pol_done:
                    state_toks = _field_tokens(
                        product_facts,
                        "identity_hints.processing_state;composition_facts.processing_state",
                    )
                    if state_toks and _polarity_conflict(all_value_toks, state_toks):
                        verdict, why, pol_done = "false", "polarity:morphology", True
                if pol_done:
                    answers.append(verdict)
                    detail.append({"cond": cond_type, "op": op, "verdict": verdict,
                                   "field": dto_field.split(";")[0][:40], "why": why,
                                   "value": str(cond.get("value") or "")[:80]})
                    continue
            if cond_type in _ALIAS_AXES:
                alias = _aliases()
                bound = bound | {c for t in bound for c in alias.get(t, ())}
            if any(p <= bound for p in phrases):
                verdict = "true"
                # 확정 자격 심사용: 바인딩의 어느 '경로'가 실제로 답했는가
                # (identity_terms 단독 히트인지 typed 필드 히트인지 구분)
                # alias 상위어 확정 금지(기본 ON): capsicum→'vegetable' 같은
                # 상위어 확장 매치가 binding 자격쌍을 타고 +50 확정을 만든다
                # (청양고추 0703 confirmed 51 실측). 직접 매치만 field_hit로
                # 자격을 얻고, alias 경유 매치는 alias_hit로 표기되어 확정
                # 자격에서 자동 탈락(+3 증거는 유지).
                # ASAP_ALIAS_CONFIRM_GUARD=0 복귀.
                alias_guard = (os.environ.get(
                    "ASAP_ALIAS_CONFIRM_GUARD", "1") or "1").strip() != "0"
                hit_paths = []
                alias_paths = []
                for path in dto_field.split(";"):
                    path = path.strip()
                    ptoks = _field_tokens(product_facts, path)
                    expanded = ptoks
                    if cond_type in _ALIAS_AXES:
                        expanded = ptoks | {c for t in ptoks for c in _aliases().get(t, ())}
                    if any(p <= ptoks for p in phrases):
                        hit_paths.append(path.rsplit(".", 1)[-1])
                    elif any(p <= expanded for p in phrases):
                        alias_paths.append(path.rsplit(".", 1)[-1])
                if not alias_guard:
                    hit_paths, alias_paths = hit_paths + alias_paths, []
                # [P1-D3] 매치를 성립시킨 구문 전부가 백과 전유 토큰에 기대는
                # 히트는 확정 자격 경로(field_hit)를 박탈 — why가 field_hit로
                # 시작하지 않으면 typed 게이트를 통과할 수 없어 +50이 원천
                # 차단되고, verdict true의 지지(+3)만 남는다(상한은 staged).
                enc_capped = False
                # [6회차 B] 판례(grade=precedent) 매치는 2급 — 당국 판정문
                # 어휘라도 개별 사건의 서술이지 법정 판별 조건이 아니다.
                # why가 field_hit이 아니면 typed 게이트 통과 불가 → 확정
                # 원천 차단, verdict true(+3 지지)는 유지 (enc/alias 계보).
                if str(cond.get("grade") or "") == "precedent":
                    why = "precedent_hit:" + ",".join(
                        (hit_paths or alias_paths or ["pool"])[:3])
                    enc_capped = True
                if not enc_capped and enc_exclusive:
                    matched_phrases = [p for p in phrases if p <= bound]
                    if matched_phrases and all(
                            p & enc_exclusive for p in matched_phrases):
                        why = "encyclopedia_hit:" + ",".join(
                            (hit_paths or alias_paths or ["pool"])[:3])
                        enc_capped = True
                # 단일 경로로는 부분 매치뿐인데 합집합으로만 성립한 히트는
                # 'union'으로 표시 — 서로 다른 필드의 파편이 합쳐진 약한 근거
                if enc_capped:
                    pass
                elif hit_paths:
                    why = "field_hit:" + ",".join(hit_paths[:3])
                elif alias_paths:
                    why = "alias_hit:" + ",".join(alias_paths[:3])
                else:
                    why = "field_hit:union"
            elif not bound:
                why = "field_empty"       # 답안지 부재 — DTO가 이 질문에 침묵
            else:
                why = "field_no_match"    # 필드는 찼는데 값 불일치 (어휘 갭/오답)
        # [12회차 3-수리] 그룹 조건은 answers에 직접 넣지 않고 버킷으로
        # 모은다. 종전엔 루프 뒤에서 conditions 인덱스로 answers를
        # 필터했는데, **answers는 skipped 조건을 담지 않아 인덱스가
        # 어긋났다** — 그래서 그룹 OR이 서명만 남기고 실판정에는
        # 반영되지 않았다(0710 undecided의 진짜 원인).
        _alt_g = str(cond.get("alt_group") or "")
        if _alt_g and _alt_on:
            _grp_answers.setdefault(_alt_g, []).append(verdict)
        else:
            answers.append(verdict)
        det_entry = {"cond": cond_type, "op": op, "verdict": verdict,
                     "field": dto_field.split(";")[0][:40], "why": why,
                     "value": str(cond.get("value") or "")[:80],
                     "alt_group": str(cond.get("alt_group") or "")}
        # [기록 의무화] 근거 등급은 항상 서명 — 판례(precedent)는 원천 사건
        # 결정번호(source_text의 BTI: 접두)까지 병기한다 (UI 노출·감사 실물).
        _grade = str(cond.get("grade") or "").strip()
        if _grade:
            det_entry["grade"] = _grade
            if _grade == "precedent":
                _src = str(cond.get("source_text") or "")
                if _src.startswith("BTI:"):
                    det_entry["refs"] = _src[4:].split(",")[:4]
        detail.append(det_entry)
    # [12회차-2 A안] alt_group OR 판정 — 같은 그룹(교대 원자)의 조건은
    # 하나만 참이면 그룹이 충족된다. 조문의 'A or B'를 AND로 컴파일해
    # 확정이 구조적으로 불가능하던 결함(0710 냉동 생채소: uncooked ∧
    # steaming 동시 요구·1905 떡·1604 구이)의 처방. 그룹 밖 조건은
    # 종전대로 누적(AND). 서명: alt_group_or:<그룹ID>.
    if _grp_answers:
        for _g_id, _vs_g in _grp_answers.items():
            if "true" in _vs_g:
                answers.append("true")
                for _d_g2 in detail:
                    if str(_d_g2.get("alt_group") or "") == _g_id:
                        _d_g2["why"] = (str(_d_g2.get("why") or "")
                                        + f";alt_group_or:{_g_id}")
            elif all(v == "false" for v in _vs_g):
                answers.append("false")   # 전 원자 위반 = 그룹 위반
            else:
                answers.append("undecided")
    if "false" in answers:
        return "violated", detail
    if answers and all(a == "true" for a in answers):
        # typed 게이트: true의 근거 중 typed 경로 히트(또는 정량 게이트
        # 충족)가 하나는 있어야 확정. 자유서술 필드 단독 확정은 강등 —
        # 점수 경쟁(술어 +3)은 유지되고 +50 확정만 잃는다.
        # ASAP_DECISION_TYPED_GATE=0으로 이전(77% 커밋) 시맨틱 복귀.
        gate_on = (os.environ.get("ASAP_DECISION_TYPED_GATE", "1") or "1").strip() != "0"
        # 상태형 단독 확정 금지(동족 원칙 3호 — ingredient_class·NTD 제한과
        # 같은 계보): 'prepared' 같은 상태값은 조리식품 전부가 가져서 단독
        # 확정 자격이 없다 (실측: 오발동 21건 중 2102 효모 등 다수가 상태
        # 단독). 상태는 정체(identity/species/material) true를 전제로만
        # 확정을 가른다. ASAP_DECISION_STATE_ALONE=1 복귀.
        state_types = {"processing_method", "preservation_state",
                       "physical_form", "condition_quality"}
        if gate_on and (os.environ.get(
                "ASAP_DECISION_STATE_ALONE", "0") or "0").strip() != "1":
            true_types = {d["cond"] for d in detail if d["verdict"] == "true"}
            if true_types and true_types <= state_types:
                for d in detail:
                    if d["verdict"] == "true":
                        d["why"] += ";state_alone_blocked"
                return "undecided", detail
        # typed 자격은 '정체 계열' 조건의 typed 히트에서만 나온다 — 상태
        # 조건의 typed 히트(processing_state)가 자격을 대신 채우면 상태(공통)
        # +류값(공통) 조합이 확정을 통과한다 (1605 오발동 3건 실측: 상태
        # true가 자격을 주고 material은 ingredient_classes 비typed 히트).
        # 서열 소비 1탄: true의 근거 어휘가 '부수 성분'(entries 2순위 이하
        # ·accessory 보고)에만 있고 주성분·1순위와 무관하면 확정 자격 박탈
        # (+3 증거는 유지). "성분에 있다"≠"그 성분의 제품이다"의 서열 판정.
        # ASAP_DECISION_ORDER_GUARD=0 복귀.
        order_guard_on = (os.environ.get(
            "ASAP_DECISION_ORDER_GUARD", "1") or "1").strip() != "0"
        principal_toks: set = set()
        accessory_toks: set = set()
        rank_by_tok: dict = {}  # 서열 2탄: 토큰 → 최상 order_index
        if order_guard_on and product_facts:
            entries = _dig(product_facts, "composition_facts.ingredient_entries") or []
            for e in entries:
                if not isinstance(e, dict):
                    continue
                toks = {_stem(w) for w in _TOKEN.findall(str(e.get("ingredient_name") or "").lower()) if len(w) >= 3}
                rank = int(e.get("order_index") or 99)
                for tk in toks:
                    rank_by_tok[tk] = min(rank, rank_by_tok.get(tk, 99))
                if rank == 1:
                    principal_toks |= toks
                else:
                    accessory_toks |= toks
            for extra in ("identity_hints.principal_ingredient_guess",
                          "composition_facts.principal_ingredient"):
                principal_toks |= _field_tokens(product_facts, extra)
            for a in _dig(product_facts, "identity_hints.accessory_ingredients") or []:
                accessory_toks |= {_stem(w) for w in _TOKEN.findall(str(a).lower()) if len(w) >= 3}
            accessory_toks -= principal_toks

        def _value_toks(d: dict) -> set:
            try:
                vals = json.loads(str(d.get("value") or "null")) or []
            except Exception:
                return set()
            return {_stem(w) for v in vals for w in _TOKEN.findall(str(v).lower()) if len(w) >= 3}

        def _accessory_only(d: dict) -> bool:
            if not accessory_toks:
                return False
            vt = _value_toks(d)
            return bool(vt) and not (vt & principal_toks) and bool(vt & accessory_toks)

        # 서열 2탄(연속 가중, 기본 OFF): 근거 어휘의 최상 표기 순위 r로
        # 지지도 1/r를 매긴다. 1탄의 이분법(1위 아니면 전부 부수)이 재첩국·
        # 전골처럼 정체 성분이 2순위인 상품을 일괄 박탈하는 것을 완화 —
        # 2순위(1/2)는 자격 유지, 3순위 이하(≤1/3)만 박탈.
        # ASAP_DECISION_ORDER_WEIGHT=1 활성.
        order_weight_on = (os.environ.get(
            "ASAP_DECISION_ORDER_WEIGHT", "0") or "0").strip() != "0"

        def _order_weight(d: dict) -> float:
            vt = _value_toks(d)
            if not vt:
                return 0.0
            if vt & principal_toks:
                return 1.0
            ranks = [rank_by_tok[tk] for tk in vt if tk in rank_by_tok]
            return (1.0 / min(ranks)) if ranks else 0.0

        binding = _binding_table() if (os.environ.get(
            "ASAP_BINDING_V1", "1") or "1").strip() != "0" else {}
        if binding:
            # 측정 산출물 모드: (cond|leaf) 쌍의 실측 정밀도가 자격을 준다.
            # [12회차 §C] provenance 편입 — 자격 키를 (cond|field)에서
            # **(cond|field|provenance)** 로 확장한다. 같은 'mollusc'라도
            # 문서 기계 도출분(COI 정규화·CO 학명)과 LLM 추측분은 신뢰도가
            # 다르며, 출처는 이미 실물로 보유한다(composition_provenance ·
            # source: coi_normalized). 순환 고착 처방: 문서 출처가 있으면
            # 자격 후보, 없으면 무자격 → 정보 부실 시 보수적 퇴화(서비스
            # 안전). 확장 키가 표에 없으면 종전 (cond|field) 키로 낙하해
            # 하위호환(재캘리브레이션 전에도 회귀 0).
            _prov = str((_dig(product_facts,
                              "composition_facts.composition_provenance")
                         or "")).strip()
            if not _prov:
                # 상위 스탬프 부재 시 entry 단위 source 서명 실물로 낙하
                # (신 3런 실측: 상위 0·entries 전 케이스 coi_normalized).
                _srcs = {str((_e_p or {}).get("source") or "").strip()
                         for _e_p in (_dig(product_facts,
                                           "composition_facts.ingredient_entries")
                                      or [])
                         if isinstance(_e_p, dict)}
                _srcs.discard("")
                if len(_srcs) == 1:
                    _prov = next(iter(_srcs))

            def _binding_hit(d_b: dict) -> bool:
                # [12회차 B] why에는 OR 서명(;alt_group_or:…)이 뒤따를 수
                # 있다 — ';' 앞까지만 leaf다([3-수리] 서명 도입의 잠복
                # 결함: 그룹 조건이 typed 자격을 잃던 사인).
                for leaf in (d_b["why"].removeprefix("field_hit:")
                             .split(";")[0].split(",")):
                    leaf = leaf.strip()
                    if not leaf:
                        continue
                    if _prov and f"{d_b['cond']}|{leaf}|{_prov}" in binding:
                        return True
                    if f"{d_b['cond']}|{leaf}" in binding:
                        return True
                return False

            typed_ok = any(
                (d["op"] == "quant_gate" and d["verdict"] == "true")
                or (d["verdict"] == "true" and _binding_hit(d))
                for d in detail
            )
        else:
            typed_ok = any(
                (d["op"] == "quant_gate" and d["verdict"] == "true")
                or (d["verdict"] == "true"
                    and d["cond"] not in state_types
                    and any(leaf in _TYPED_LEAVES
                            for leaf in d["why"].removeprefix("field_hit:")
                            .split(";")[0].split(",")))
                for d in detail
            )
        if gate_on and typed_ok and order_guard_on:
            id_trues = [d for d in detail
                        if d["verdict"] == "true" and d["cond"] not in state_types]
            if order_weight_on:
                if id_trues:
                    weights = [_order_weight(d) for d in id_trues]
                    for d, w in zip(id_trues, weights):
                        d["why"] += f";order_w={w:.2f}"
                    if all(0.0 < w <= 1.0 / 3.0 for w in weights):
                        for d in id_trues:
                            d["why"] += ";order_weight_blocked"
                        return "undecided", detail
            elif id_trues and all(_accessory_only(d) for d in id_trues):
                for d in id_trues:
                    d["why"] += ";accessory_only_blocked"
                return "undecided", detail
        if gate_on and not typed_ok:
            for d in detail:
                if d["verdict"] == "true":
                    d["why"] += ";typed_gate_blocked"
            return "undecided", detail
        return "confirmed", detail
    # 부분 충족(일부 true, 일부 미결)은 확정도 탈락도 아니다 — 법조문상
    # 모든 조건이 맞아야 그 코드다.
    return "undecided", detail
