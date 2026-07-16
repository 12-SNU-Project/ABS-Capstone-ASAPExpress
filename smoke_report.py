"""22건 스모크 채점표 — ◎(top1)/○(top3)/✗(+오답코드), recovery·validator 마커."""
import glob
import json
import re

ROOT = "/Users/snu/Asap_Lab/artifacts/kurly-market-smoke"
LEVELS = (("hs2", 2), ("hs4", 4), ("hs6", 6), ("cn8", 8))


def digits(v):
    d = re.sub(r"\D", "", str(v or ""))
    # HS 코드는 짝수 자릿수(6/8/10) — 엑셀 숫자 변환으로 앞 0이 소실되면
    # 홀수가 된다(답지 실측: 0710805920→710805920). 0 복원.
    if d and len(d) % 2 == 1:
        d = "0" + d
    return d


answers = {}
names = {}
# 1차 소스: 답지 CSV (URL→pid, EU HS CODE) — summary 아티팩트가 깨져도 채점 가능
import csv as _csv
try:
    with open("/Users/snu/Asap_Lab/data/EU_HS_test.csv", encoding="utf-8-sig") as f:
        for row in _csv.reader(f):
            url = next((c for c in row if "kurly" in str(c)), "")
            code = next((c for c in row if re.fullmatch(r"\d{6,10}", str(c).strip())), "")
            m = re.search(r"(?:products|goods)/([A-Za-z0-9]+)", url)
            if m and code:
                pid = m.group(1)
                pid = pid if pid.isdigit() else f"global-{pid}"
                answers[pid] = digits(code)
except Exception:
    pass
for it in json.load(open(f"{ROOT}/runtime-smoke-summary.json")):
    ar = (it.get("classification_smoke") or {}).get("answer_recall") or {}
    a = ar.get("answer") or {}
    pid = a.get("product_id") or ""
    nm = str((it.get("product") or {}).get("product_name") or "")
    if pid and a.get("taric10"):
        answers[pid] = digits(a.get("taric10"))
        names[pid] = nm
    elif nm and "쪽갈비" in nm:
        answers["5037259"] = "160249"
        names["5037259"] = nm
answers.setdefault("5037259", "160249")
names.setdefault("5037259", "[마더푸드] 쪽갈비 2종*")

rows = []
agg = {lvl: [0, 0, 0] for lvl, _ in LEVELS}  # top1, top3, evaluated
rec_total = rec_hit = 0
val_fired = val_override = val_keep = 0
for pid, ans in answers.items():
    runs = sorted(glob.glob(f"{ROOT}/{pid}/classification-smoke/*/blackboard.json"))
    if not runs:
        continue
    bb = json.load(open(runs[-1]))
    if pid not in names or not names.get(pid):
        nm_bb = str((bb.get("product_understanding") or {}).get("product_name") or "")
        if nm_bb:
            names[pid] = nm_bb
    ccs = (bb.get("candidate_code_sets") or [{}])[-1]
    cands = [digits(c.get("cn8"))[:8] for c in (ccs.get("candidates") or []) if digits(c.get("cn8"))]
    tr = ccs.get("classification_trace") or {}
    recov = ccs.get("recovery_candidates") or tr.get("recovery_candidates") or []
    val = tr.get("validator") or {}
    nm = names.get(pid, pid)

    marks = []
    for lvl, w in LEVELS:
        if len(ans) < w:
            marks.append("    ·   ")
            continue
        agg[lvl][2] += 1
        top1 = bool(cands) and cands[0][:w] == ans[:w]
        top3 = any(c[:w] == ans[:w] for c in cands[:3])
        agg[lvl][0] += int(top1)
        agg[lvl][1] += int(top3)
        if top1:
            marks.append("◎       ")
        elif top3:
            marks.append(f"○ {cands[0][:w] if cands else '-':<7}")
        else:
            marks.append(f"✗ {cands[0][:w] if cands else '-':<7}")
    tail = ""
    if recov:
        rec_total += 1
        hit = any(ans.startswith(digits(r.get("code"))[:6][:len(ans)]) or
                  digits(r.get("code")).startswith(ans[:6]) for r in recov)
        if hit:
            rec_hit += 1
            tail += " R!"
        else:
            tail += f" r{len(recov)}"
    if val.get("fired"):
        val_fired += 1
        v = str(val.get("verdict") or "")
        scope = str(val.get("cn8") or val.get("code") or val.get("chapter") or val.get("heading") or "")
        if val.get("applied"):
            val_override += 1
            tail += f" V:{v.replace('promote_candidate', 'promote').replace('promote_recovery', 'promote')}" + (f"→{scope}" if scope else "")
        else:
            val_keep += 1
            tail += " V:keep" if v == "keep" else f" V:{v}(미적용)"
    rows.append((nm, ans, marks, tail))

print(f"{'상품':<34}{'정답':<12}{'hs2':<10}{'hs4':<10}{'hs6':<10}{'cn8':<10}")
print("-" * 92)
for nm, ans, marks, tail in rows:
    print(f"{nm[:32]:<34}{ans:<12}" + "".join(marks) + tail)
n = agg["hs2"][2]
print(f"\n채점 {n}건 (◎=top1  ○=top3진입  ✗=miss)")
for lvl, _ in LEVELS:
    t1, t3, ev = agg[lvl]
    if ev:
        print(f"   {lvl}  top1  {t1}/{ev} ({t1 / ev * 100:.0f}%)   top3  {t3}/{ev} ({t3 / ev * 100:.0f}%)")
print(f"  recovery: 기록 {rec_total}건 중 정답 지목 {rec_hit}건")
print(f"  validator: 발동 {val_fired}건 (override {val_override}, keep/미적용 {val_keep})")
