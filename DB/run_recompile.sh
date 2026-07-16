#!/bin/zsh
# 술어 테이블 재컴파일 러너 — DB/에서 컴파일 관련 실행을 일원화.
# 컴파일러 본체는 import 경로 때문에 src/agents/tools/에 남는다.
#
# 기본 = Nomenclature 트리 원천 (DB/artifacts/nomenclature_tree.jsonl,
#        suffix 80/10·20 명시 계층 — 경로 추측 없음)
# 사용:
#   ./DB/run_recompile.sh              # 트리 원천 + apply
#   ./DB/run_recompile.sh --dry-run    # DB 반영 없이 산출만
#   ./DB/run_recompile.sh --legacy     # 구 방식(cn_table 경로 + enrich-h6)
set -e
cd "$(dirname "$0")/.."

echo "── ASAP_ 환경 오염 점검 ──"
env | grep '^ASAP_' || echo "(깨끗)"

# zsh는 기본 단어분리를 안 한다 — 문자열 "--tree-source --cnen"이 통짜
# 인자 하나로 전달돼 두 플래그가 전부 무시됐다(07-16 실측: 로그에 '트리
# 원천'·'CNEN 수확' 라인 부재). 배열로 선언해야 인자별로 전달된다.
SOURCE_FLAG=(--tree-source --cnen)
[[ "$*" == *--legacy* ]] && SOURCE_FLAG=(--enrich-h6)
APPLY=(--apply)
[[ "$*" == *--dry-run* ]] && APPLY=()

LOG="DB/artifacts/recompile_$(date +%y%m%d_%H%M).log"
PYTHONPATH=src /opt/anaconda3/envs/asap/bin/python -u -m bussiness_logic.classification.offline.branch_decision_compiler $SOURCE_FLAG $APPLY 2>&1 | tee "$LOG"
echo "── 로그: $LOG ──"
