#!/bin/zsh
# ASAP 백엔드 재시작 스크립트.
# 주의: 재시작하면 진행 중인 run과 메모리의 run 기록이 사라진다.
#       분류가 돌고 있지 않을 때 사용할 것. (admin 페이지는 디스크 폴백이
#       있어 과거 run의 blackboard는 계속 조회 가능)
cd "$(dirname "$0")"

pid=$(lsof -tnP -iTCP:8060 -sTCP:LISTEN 2>/dev/null)
if [ -n "$pid" ]; then
  echo "기존 백엔드(PID $pid) 종료..."
  kill "$pid"
  for i in {1..20}; do
    lsof -tnP -iTCP:8060 -sTCP:LISTEN >/dev/null 2>&1 || break
    sleep 0.5
  done
fi

echo "백엔드 시작 (http://127.0.0.1:8060)"
exec python asap_app.py
