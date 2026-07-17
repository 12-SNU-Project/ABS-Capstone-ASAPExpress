"""용어 브리지 — 자유어(한글 성분명) → 법정 영문 어휘 결정론 사상.

층위 원칙: 발산(상류 LLM)은 건드리지 않고, DTO 완성 직후 '허리'에서
수렴만 한다. LLM 0회 — 관세청 표준품명 사전(data/std_name_dictionary
.jsonl, 2,966쌍)의 2-gram 조회 + 매칭행 HS챕터 제목 토큰(법정 텍스트)을
계열 alias로 동반 ('돼지등갈비'→ch02→'meat/offal' — quant의
"meat of any kind" 조건이 요구하는 바로 그 다리).

적용 대상: composition_facts.ingredient_entries(한글명) →
  entry.term_aliases (+ hs6 태그) · ingredient_name 영문 병기
  ingredient_percentages 항목 → term_aliases (quant 판정기 소비 슬롯)

게이트: ASAP_TERM_BRIDGE (기본 ON, =0 복귀). 미등재 성분 = 무해 통과.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any

_DICT_CACHE: list[dict] | None = None
_CHAPTER_TOKENS: dict[str, list[str]] | None = None


def _nfc(t: object) -> str:
    return unicodedata.normalize("NFC", str(t or "")).strip()


def _load_dict() -> list[dict]:
    global _DICT_CACHE
    if _DICT_CACHE is not None:
        return _DICT_CACHE
    rows: list[dict] = []
    try:
        path = Path(__file__).resolve().parents[4] / "data" / "std_name_dictionary.jsonl"
        for line in path.read_text(encoding="utf-8").splitlines():
            rows.append(json.loads(line))
    except Exception:  # noqa: BLE001 — 사전 부재 = 브리지 전체 no-op
        rows = []
    _DICT_CACHE = rows
    return rows


def _chapter_tokens(hs2: str) -> list[str]:
    """챕터 법정 제목의 내용어 토큰 — 계열 alias ('meat', 'offal' 등)."""
    global _CHAPTER_TOKENS
    if _CHAPTER_TOKENS is None:
        table: dict[str, list[str]] = {}
        try:
            from sqlalchemy import text
            from db.db_session_manager import DbSessionManager
            m = DbSessionManager.GetInstance()
            stop = {"and", "the", "of", "or", "other", "for", "not", "their",
                    "thereof", "products", "articles", "preparations"}
            for r in m.FetchRows(text(
                    'SELECT chapter, chapter_title, chapter_keywords FROM "cn_chapter_index"'), {}):
                d = dict(r)
                ch = re.sub(r"\D", "", str(d.get("chapter") or ""))[:2].zfill(2)
                blob = f"{d.get('chapter_title') or ''} {d.get('chapter_keywords') or ''}".lower().replace(";", " ")
                toks = [w for w in re.findall(r"[a-z]{3,}", blob)[:24] if w not in stop]
                if ch:
                    table[ch] = list(dict.fromkeys(toks))[:10]
        except Exception:  # noqa: BLE001 — DB 불가 시 계열 alias 생략
            table = {}
        _CHAPTER_TOKENS = table
    return _CHAPTER_TOKENS.get(hs2, [])


# 사전 표기의 상태 접두어 — 성분 정체와 무관한 수식이라 정규화 시 제거
# ('냉동청양고추'와 '청양고추'는 같은 성분). 법정 상태어 소수 목록.
_STATE_PREFIX = re.compile(r"^(냉동|냉장|활|신선|건조|염장|훈제|자숙|유기농)\s*")


def _norm_key(text: str) -> str:
    s = re.sub(r"[^가-힣]", "", _nfc(text))
    prev = None
    while prev != s:
        prev = s
        s = _STATE_PREFIX.sub("", s)
    return s


_EXACT_INDEX: dict[str, list[int]] | None = None


def _exact_index() -> dict[str, list[int]]:
    global _EXACT_INDEX
    if _EXACT_INDEX is None:
        rows = _load_dict()
        idx: dict[str, list[int]] = {}
        for i, r in enumerate(rows):
            k = _norm_key(r.get("ko") or "")
            # [메인 병합 보존] 1자 품명('밤'→Chestnuts, '김'→Laver)도 등재 —
            # 정밀 '완전 일치'에서만 쓰이고, 포함·토큰 계층은 각자 ≥2 필터
            # 유지('김'⊂'김치' 오염 금지).
            if len(k) >= 1:
                idx.setdefault(k, []).append(i)
        _EXACT_INDEX = idx
    return _EXACT_INDEX


# ── curated 파생층 (Track 2) ────────────────────────────────────────
# 원천(관세청) 사전은 불변 잠금 — 원천 부재 어휘의 다리는 별도 파생층
# (data/curated_term_bridge.jsonl)에서만 온다. 행 자격: source='curated'
# ∧ approved_by 비어있지 않음(설계자 승인분만 유효). 조회는 원천 우선,
# 파생은 폴백이며 산출에 grade='derived'가 표기된다 — 소비부는 파생
# 매치에 ingredient_name 영문 병기를 하지 않아(원천 전용 특권) typed
# 게이트(field_hit 확정) 경로에 구조적으로 진입 불가, term_aliases
# (quant 슬롯) 지지만 가능한 2급 증거다. 생성·승인 공정은
# DB/curate_term_bridge.py (폐쇄 후보 집합 밖 en 등록 거부).
_CURATED_INDEX: dict[str, list[dict]] | None = None


def _curated_index() -> dict[str, list[dict]]:
    global _CURATED_INDEX
    if _CURATED_INDEX is None:
        idx: dict[str, list[dict]] = {}
        try:
            path = (Path(__file__).resolve().parents[4]
                    / "data" / "curated_term_bridge.jsonl")
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                if (str(r.get("source") or "") != "curated"
                        or not str(r.get("approved_by") or "").strip()):
                    continue  # 승인된 curated 행만 유효
                k = _norm_key(r.get("ko") or "")
                if len(k) >= 2 and str(r.get("en") or "").strip():
                    idx.setdefault(k, []).append(r)
        except Exception:  # noqa: BLE001 — 파생층 부재 = 폴백 없음(무해)
            idx = {}
        _CURATED_INDEX = idx
    return _CURATED_INDEX


def LookupAliases(name_ko: str, top: int = 2) -> list[dict]:
    """한글 성분명 → 법정 영문 (정밀 일치만 — 근사 매칭 금지).

    허용 판정: ①정규화 완전 일치 ②쿼리의 공백 토큰이 완전 일치
    ('유기농 밀가루'의 '밀가루'). 그 외는 빈손 — 틀린 대응을 각인하느니
    안 잇는다 (실측: 2-gram 근사는 '유기농 청양고추'를 유청단백에 붙였다).
    미일치 항목은 검수 큐로 적재해 사람이 사전을 보강한다.
    """
    rows = _load_dict()
    if not rows:
        return []
    idx = _exact_index()
    keys = [_norm_key(name_ko)]
    for tok in re.split(r"[\s/,()\[\]]+", _nfc(name_ko)):
        k = _norm_key(tok)
        if len(k) >= 2 and k not in keys:
            keys.append(k)
    hit_rows: list[int] = []
    for k in keys:
        if k in idx:
            hit_rows = idx[k][:top]
            break
    if not hit_rows:
        # [메인 병합 보존] 완전 포함 계층: 사전 키(관세청 품명 원형)가
        # 질의 안에 통째로 등장하면 인정 — '재첩살'⊇'재첩', '대구살'⊇'대구'.
        # 유사도가 아니라 키 원형의 부분 문자열 판정(결정론·창작 0 — 근사
        # 2-gram 사고와 다른 계층). 최장 키 1개 채택. 원천 유래이므로
        # curated 파생층보다 우선. 형태 접미어는 정체가 아니라 차단
        # ('밀가루'→'가루'="Powder; Flour" 오염 실측).
        form_generic = {"가루", "분말", "원액", "농축액", "엑기스",
                        "오일", "기름", "시럽", "소스"}
        best = ""
        for query in keys:
            for k in idx:
                if (len(k) >= 2 and k not in form_generic
                        and k in query and len(k) > len(best)):
                    best = k
        if best:
            hit_rows = idx[best][:top]
    if not hit_rows:
        # [Track 2] 원천 미등재 → curated 파생층 폴백 (승인분만, grade 표기)
        cidx = _curated_index()
        for k in keys:
            if k in cidx:
                out = []
                for r in cidx[k][:top]:
                    hs6 = str(r.get("hs6") or "")
                    out.append({
                        "en": str(r.get("en") or ""),
                        "hs6": hs6,
                        "chapter_terms": _chapter_tokens(hs6[:2]) if hs6 else [],
                        "grade": "derived",
                    })
                return out
        _enqueue_review(name_ko)
        return []
    out = []
    for i in hit_rows:
        r = rows[i]
        out.append({
            "en": r.get("en") or "",
            "hs6": r.get("hs6") or "",
            "chapter_terms": _chapter_tokens(str(r.get("hs6") or "")[:2]),
            "grade": "source",
        })
    return out


_REVIEW_SEEN: set[str] = set()


def _enqueue_review(name_ko: str) -> None:
    """미일치 성분명 → 검수 큐 (사람이 사전 보강 — 수기 교정 경로)."""
    key = _norm_key(name_ko)
    if not key or key in _REVIEW_SEEN:
        return
    _REVIEW_SEEN.add(key)
    try:
        path = Path(__file__).resolve().parents[4] / "data" / "std_name_review_queue.txt"
        with open(path, "a", encoding="utf-8") as f:
            f.write(_nfc(name_ko) + "\n")
    except Exception:  # noqa: BLE001
        pass


def ApplyTermBridge(pu: dict[str, Any]) -> dict[str, Any] | None:
    """PU dict의 composition entries·percentages에 법정 어휘 병기."""
    if (os.environ.get("ASAP_TERM_BRIDGE", "1") or "1").strip() == "0":
        return None
    cf = dict(pu.get("composition_facts") or {})
    entries = [e for e in (cf.get("ingredient_entries") or []) if isinstance(e, dict)]
    if not entries:
        return None
    bridged = 0
    for e in entries:
        name = _nfc(e.get("ingredient_name"))
        # 이미 영문 병기된 항목(COI name_en ' / ' 규약)은 한글부만 조회
        ko_part = name.split(" / ")[0]
        if not re.search(r"[가-힣]", ko_part) or e.get("term_aliases"):
            continue
        hits = LookupAliases(ko_part)
        if not hits:
            continue
        # entries에는 표준품명 영문만 — 챕터 계열 토큰(fish/meat…)을 여기
        # 실으면 lexical/binding 풀에 잡음이 유입된다(실측: 떡볶이 1점차
        # lexical 접전이 1904로 넘어감). 계열 토큰은 quant 전용(아래).
        aliases = list(dict.fromkeys(h["en"] for h in hits if h["en"]))[:4]
        if not aliases:
            continue
        e["term_aliases"] = aliases
        e["term_aliases_hs6"] = [h["hs6"] for h in hits if h["hs6"]][:2]
        derived = all(h.get("grade") == "derived" for h in hits)
        if derived:
            # [Track 2] 파생 매치는 2급 — ingredient_name 영문 병기는 원천
            # 전용 특권이다. 병기된 영문은 _field_tokens(ingredient_name만
            # 읽음)를 타고 typed 게이트(field_hit 확정)에 진입하므로, 파생
            # en을 병기하면 파생이 확정을 만들 수 있다. term_aliases(quant
            # 슬롯)만 태워 지지 자격으로 제한한다 — alias 계열과 동급.
            e["term_aliases_grade"] = "derived"
        elif " / " not in name and hits[0]["en"]:
            e["ingredient_name"] = f"{name} / {hits[0]['en']}"
        bridged += 1
    if not bridged:
        return None
    cf["ingredient_entries"] = entries
    # percentages 항목에도 aliases 탑재 — quant 판정기의 term_aliases 슬롯
    pcts = [dict(p) for p in (cf.get("ingredient_percentages") or []) if isinstance(p, dict)]
    for p in pcts:
        term = _nfc(p.get("term"))
        if not term or p.get("term_aliases"):
            continue
        hits = LookupAliases(term.split(" / ")[0])
        if hits:
            p["term_aliases"] = list(dict.fromkeys(
                [h["en"] for h in hits if h["en"]]
                + [t for h in hits for t in h["chapter_terms"][:5]]
            ))[:8]
    if pcts:
        cf["ingredient_percentages"] = pcts
    pu["composition_facts"] = cf
    return {"term_bridge": True, "entries_bridged": bridged}
