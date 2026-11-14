#!/usr/bin/env bash
# 중계 층 탐침 — 띄우기/끄기 (진단용 · 쓰는 법과 읽는 법: README.md)
#
#   브라우저 → :FRONT_PORT(TCP 중계 · quiet) → :NEXT_PORT(next start · PROXY_TRACE_LOG 켬) → :RELAY_PORT(TCP 중계) → :BACKEND_PORT(백엔드)
#
# 사용: scripts/proxy-probe/run.sh start <로그 폴더>    (frontend 폴더에서 · 백엔드는 미리 띄우고 · 프론트는 미리 next build)
#       scripts/proxy-probe/run.sh stop  <로그 폴더>    (start 가 띄운 프로세스만 끈다 — 다른 프로세스는 건드리지 않는다)
# 포트(기본): FRONT_PORT=3000 NEXT_PORT=3001 RELAY_PORT=8100 BACKEND_PORT=8000
# 쓰고 있는 포트가 있으면 띄우지 않고 멈춘다(무엇을 끌지는 사람이 정한다).
set -euo pipefail

cmd=${1:-}; dir=${2:-}
FRONT_PORT=${FRONT_PORT:-3000}; NEXT_PORT=${NEXT_PORT:-3001}; RELAY_PORT=${RELAY_PORT:-8100}; BACKEND_PORT=${BACKEND_PORT:-8000}
here=$(cd "$(dirname "$0")" && pwd)
frontend=$(cd "$here/../.." && pwd)

usage() { echo "사용: $0 start|stop <로그 폴더>" >&2; exit 2; }
[ -n "$cmd" ] && [ -n "$dir" ] || usage

busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

case "$cmd" in
  start)
    mkdir -p "$dir"; dir=$(cd "$dir" && pwd)
    [ -e "$dir/pids" ] && { echo "이미 띄운 기록이 있어요: $dir/pids — 먼저 '$0 stop $dir'" >&2; exit 1; }
    for p in "$FRONT_PORT" "$NEXT_PORT" "$RELAY_PORT"; do
      if busy "$p"; then echo "포트 $p 를 이미 쓰고 있어요 — 띄우지 않았어요(그 프로세스를 끌지는 직접 정하세요)." >&2; exit 1; fi
    done
    busy "$BACKEND_PORT" || { echo "백엔드 :$BACKEND_PORT 에 닿지 않아요 — 먼저 띄우세요." >&2; exit 1; }
    [ -d "$frontend/.next" ] || { echo "$frontend/.next 가 없어요 — 먼저 'npx next build'." >&2; exit 1; }
    : > "$dir/pids"
    ( setsid nohup node "$here/relay.mjs" "$RELAY_PORT" "$BACKEND_PORT" "$dir/be.log" > "$dir/relay_be.out" 2>&1 < /dev/null & echo $! >> "$dir/pids" )
    ( setsid nohup node "$here/relay.mjs" "$FRONT_PORT" "$NEXT_PORT" "$dir/fe.log" --quiet > "$dir/relay_fe.out" 2>&1 < /dev/null & echo $! >> "$dir/pids" )
    # `&` 는 setsid 하나에만 — 그래야 $! 가 새 무리(프로세스 그룹)의 머리라 stop 이 무리째 끈다(npx → sh → next-server).
    ( cd "$frontend" && { PROXY_TRACE_LOG="$dir/route.log" BACKEND_URL="http://localhost:$RELAY_PORT" \
        setsid nohup npx next start -p "$NEXT_PORT" > "$dir/web.log" 2>&1 < /dev/null & echo $! >> "$dir/pids"; } )
    for _ in $(seq 1 90); do
      code=$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$FRONT_PORT/api/backend/api/v1/macro/health" || true)
      [ "$code" = 200 ] && { echo "UP — 브라우저는 http://localhost:$FRONT_PORT · 기록: $dir/{route,fe,be}.log"; echo "분석: node $here/classify.mjs $dir"; exit 0; }
      sleep 1
    done
    echo "띄우지 못했어요(중계를 지난 /macro/health 가 200 이 아님: $code) — $dir/web.log 를 보세요. 띄운 것은 '$0 stop $dir' 로 끄세요." >&2; exit 1
    ;;
  stop)
    [ -f "$dir/pids" ] || { echo "$dir/pids 가 없어요 — 이 폴더로 띄운 적이 없어요." >&2; exit 1; }
    while read -r pid; do
      [ -n "$pid" ] || continue
      kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true   # setsid 로 띄워 제 무리(프로세스 그룹)째 끈다
    done < "$dir/pids"
    for _ in $(seq 1 20); do
      left=""; for p in "$FRONT_PORT" "$NEXT_PORT" "$RELAY_PORT"; do busy "$p" && left="$left $p"; done
      [ -z "$left" ] && { rm -f "$dir/pids"; echo "껐어요(이 폴더로 띄운 것만)."; exit 0; }
      sleep 0.5
    done
    echo "아직 포트를 쓰는 것이 있어요:$left — 이 폴더로 띄운 무리가 남았거나 다른 프로세스예요(pids 는 그대로 둠: $dir/pids)." >&2; exit 1
    ;;
  *) usage ;;
esac
