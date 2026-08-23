#!/usr/bin/env bash
# 项目名称：KBot
# 用法：./serve.sh 或 ./serve.sh start  — 默认只启动 main（KBot.py + CS/Scheduled_tasks.py）
#       ./serve.sh {start/stop/restart/status/open} [main|order|broadcast|gsi|web|all]
# 特殊进程：./serve.sh {order/broadcast/gsi/web}
#
# changelog
# - 2026-08-22: 无参数视为 start main；优先使用项目 .venv (Author: KBot)
# - 2026-08-22: start/stop/restart/status 输出结构化入口信息，读 config/serve.ini (Author: KBot)
# - 2026-08-23: 启动/停止时回收同组残留进程，避免双开重复发卡片 (Author: KBot)

set -u

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SERVE_INI="$ROOT/config/serve.ini"
PID_FILE="$ROOT/.serve.pid"
SERVICE_GROUPS=(main order broadcast gsi web)

if [[ -n "${PYTHON_BIN:-}" ]]; then
  PYTHON="$PYTHON_BIN"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
else
  PYTHON="python3"
fi

# ---------------------------------------------------------------------------
# 配置读取
# ---------------------------------------------------------------------------

# 读取 serve.ini 指定 section 的 key；没有则输出空。不改写 $1，避免 awk 丢掉等号。
ini_get() {
  local section="$1" key="$2"
  [[ -f "$SERVE_INI" ]] || return 0
  awk -v section="[$section]" -v want="$key" '
    $0 ~ /^[ \t]*[;#]/ { next }
    $0 ~ /^[ \t]*\[/ {
      line = $0
      gsub(/^[ \t]+|[ \t]+$/, "", line)
      active = (line == section)
      next
    }
    active && index($0, "=") {
      line = $0
      sub(/^[ \t]+/, "", line)
      eq = index(line, "=")
      k = substr(line, 1, eq - 1)
      v = substr(line, eq + 1)
      gsub(/^[ \t]+|[ \t]+$/, "", k)
      gsub(/^[ \t]+|[ \t]+$/, "", v)
      if (k == want) { print v; exit }
    }
  ' "$SERVE_INI"
}

# 日志文件绝对路径：ini 的 common.log，相对路径相对仓库根。
log_path() {
  local raw
  raw="$(ini_get common log)"
  [[ -n "$raw" ]] || raw=".serve.log"
  if [[ "$raw" == /* ]]; then
    printf '%s\n' "$raw"
  else
    printf '%s\n' "$ROOT/$raw"
  fi
}

LOG="$(log_path)"

# 从 Flask app.run(host=..., port=...) 解析监听；源码没有则退回 ini。
listen_from_source() {
  local source_rel="$1" line host port
  [[ -n "$source_rel" && -f "$ROOT/$source_rel" ]] || return 1
  line="$(grep -E '^[[:space:]]*app\.run\(' "$ROOT/$source_rel" | tail -n 1)" || return 1
  [[ -n "$line" ]] || return 1
  host="$(printf '%s\n' "$line" | sed -n "s/.*host=['\"]\\([^'\"]*\\)['\"].*/\\1/p")"
  port="$(printf '%s\n' "$line" | sed -n "s/.*port=\\([0-9][0-9]*\\).*/\\1/p")"
  [[ -n "$host" && -n "$port" ]] || return 1
  printf '%s %s\n' "$host" "$port"
}

# 本机用于访问内网入口的 IPv4。
lan_host() {
  local configured
  configured="$(ini_get common lan_host)"
  if [[ -n "$configured" && "$configured" != auto ]]; then
    printf '%s\n' "$configured"
    return 0
  fi
  ip -4 route get 1.1.1.1 2>/dev/null | awk '{
    for (i = 1; i <= NF; i++) if ($i == "src") { print $(i + 1); exit }
  }'
}

# 保证路径以 / 开头并以 / 结尾，空路径保持为空。
normalize_path() {
  local path="$1"
  [[ -n "$path" ]] || return 0
  [[ "$path" == /* ]] || path="/$path"
  [[ "$path" == */ ]] || path="$path/"
  printf '%s\n' "$path"
}

# 解析某进程组的监听与三类入口 URL，写入 LISTEN_HOST/PORT 与 URL_*。
load_endpoints() {
  local group="$1" source_rel parsed ini_host ini_port path public_host public_scheme lan
  LISTEN_HOST=""
  LISTEN_PORT=""
  URL_LOCAL=""
  URL_LAN=""
  URL_PUBLIC=""
  source_rel="$(ini_get "$group" source)"
  ini_host="$(ini_get "$group" listen_host)"
  ini_port="$(ini_get "$group" listen_port)"
  if parsed="$(listen_from_source "$source_rel")"; then
    LISTEN_HOST="${parsed%% *}"
    LISTEN_PORT="${parsed##* }"
  else
    LISTEN_HOST="$ini_host"
    LISTEN_PORT="$ini_port"
  fi
  path="$(normalize_path "$(ini_get "$group" path)")"
  public_host="$(ini_get "$group" public_host)"
  [[ -n "$public_host" ]] || public_host="$(ini_get common public_host)"
  public_scheme="$(ini_get "$group" public_scheme)"
  [[ -n "$public_scheme" ]] || public_scheme="$(ini_get common public_scheme)"
  [[ -n "$public_scheme" ]] || public_scheme="https"
  lan="$(lan_host)"
  if [[ "$LISTEN_PORT" =~ ^[0-9]+$ ]]; then
    URL_LOCAL="http://localhost:${LISTEN_PORT}${path}"
    if [[ -n "$lan" ]]; then
      URL_LAN="http://${lan}:${LISTEN_PORT}${path}"
    fi
  fi
  # 整段 public_url 优先；否则仅 expose_public=1 的组才拼公网域名
  URL_PUBLIC="$(ini_get "$group" public_url)"
  if [[ -z "$URL_PUBLIC" && "$LISTEN_PORT" =~ ^[0-9]+$ && -n "$public_host" && "$(ini_get "$group" expose_public)" == "1" ]]; then
    URL_PUBLIC="${public_scheme}://${public_host}${path}"
  fi
}

# 打印入口/监听/日志；无 HTTP 的进程组对应行留空。
print_endpoints() {
  local group="$1" listen=""
  load_endpoints "$group"
  if [[ -n "$LISTEN_HOST" && -n "$LISTEN_PORT" ]]; then
    listen="${LISTEN_HOST}:${LISTEN_PORT}"
  fi
  printf '本机入口：%s\n' "$URL_LOCAL"
  printf '内网入口：%s\n' "$URL_LAN"
  printf '公网入口：%s\n' "$URL_PUBLIC"
  printf '监听：%s\n' "$listen"
  printf '日志：%s\n' "$LOG"
}

# ---------------------------------------------------------------------------
# 进程管理
# ---------------------------------------------------------------------------

programs_for() {
  case "$1" in
    main) printf '%s\n' "KBot.py" "CS/Scheduled_tasks.py" ;;
    order) printf '%s\n' "orderBot/order.py" ;;
    broadcast) printf '%s\n' "broadcast/broadcast.py" ;;
    gsi) printf '%s\n' "CS/GSI/GSI_server.py" "CS/GSI/GSI_message.py" ;;
    web) printf '%s\n' "CS/Web/API.py" ;;
    *) return 1 ;;
  esac
}

group_pid() {
  local group="$1" saved_group saved_pid
  [[ -f "$PID_FILE" ]] || return 1
  while IFS=: read -r saved_group saved_pid; do
    if [[ "$saved_group" == "$group" && "$saved_pid" =~ ^[0-9]+$ ]] && kill -0 "$saved_pid" 2>/dev/null; then
      printf '%s\n' "$saved_pid"
      return 0
    fi
  done <"$PID_FILE"
  return 1
}

prune_pids() {
  [[ -f "$PID_FILE" ]] || return 0
  local temporary saved_group saved_pid
  temporary="$(mktemp /tmp/kbot-serve-pids.XXXXXX)"
  while IFS=: read -r saved_group saved_pid; do
    if [[ "$saved_pid" =~ ^[0-9]+$ ]] && kill -0 "$saved_pid" 2>/dev/null; then
      printf '%s:%s\n' "$saved_group" "$saved_pid" >>"$temporary"
    fi
  done <"$PID_FILE"
  if [[ -s "$temporary" ]]; then mv "$temporary" "$PID_FILE"; else rm -f "$temporary" "$PID_FILE"; fi
}

run_group() {
  local group="$1" program
  local children=()
  cd "$ROOT" || exit 1
  cleanup() {
    trap - TERM INT EXIT
    kill "${children[@]}" 2>/dev/null || true
    wait "${children[@]}" 2>/dev/null || true
  }
  trap cleanup TERM INT EXIT
  printf '\n[%s] 启动进程组：%s\n' "$(date '+%F %T')" "$group"
  while IFS= read -r program; do
    printf '[%s] 启动 %s\n' "$(date '+%F %T')" "$program"
    "$PYTHON" -u "$program" &
    children+=("$!")
  done < <(programs_for "$group")
  wait
}

# 杀掉本组残留的 __run 与业务脚本，keep 及其子进程除外。
# PID 文件丢失时旧进程仍会活着，不收就会双开、卡片连发。
reap_stale_group() {
  local group="$1" keep="${2:-}" pid program child
  local -A kept=()
  if [[ -n "$keep" ]]; then
    kept["$keep"]=1
    while read -r child; do
      [[ -n "$child" ]] || continue
      kept["$child"]=1
      while read -r pid; do
        [[ -n "$pid" ]] || continue
        kept["$pid"]=1
      done < <(pgrep -P "$child" 2>/dev/null || true)
    done < <(pgrep -P "$keep" 2>/dev/null || true)
  fi
  while read -r pid; do
    [[ -n "$pid" && -z "${kept[$pid]:-}" ]] || continue
    kill -TERM "$pid" 2>/dev/null || true
  done < <(pgrep -f -- "$ROOT/serve.sh __run $group" 2>/dev/null || true)
  while IFS= read -r program; do
    while read -r pid; do
      [[ -n "$pid" && -z "${kept[$pid]:-}" ]] || continue
      kill -TERM "$pid" 2>/dev/null || true
    done < <(pgrep -f -- "-u $program" 2>/dev/null || true)
  done < <(programs_for "$group")
}

# 启动一组。成功时把 PID 写到 stdout。
start_one() {
  local group="$1" process_id
  programs_for "$group" >/dev/null || { printf '未知进程组：%s\n' "$group" >&2; return 2; }
  if process_id="$(group_pid "$group")"; then
    reap_stale_group "$group" "$process_id"
    printf '%s\n' "$process_id"
    return 0
  fi
  prune_pids
  reap_stale_group "$group"
  sleep 1
  setsid "$ROOT/serve.sh" __run "$group" >>"$LOG" 2>&1 &
  process_id=$!
  printf '%s:%s\n' "$group" "$process_id" >>"$PID_FILE"
  sleep 1
  if kill -0 "$process_id" 2>/dev/null; then
    printf '%s\n' "$process_id"
    return 0
  fi
  prune_pids
  return 1
}

# 停止一组。原先在跑则打印 PID 到 stdout；未运行返回 3。
stop_one() {
  local group="$1" process_id count
  if process_id="$(group_pid "$group")"; then
    kill -TERM -- "-$process_id" 2>/dev/null || kill -TERM "$process_id" 2>/dev/null || true
    for count in {1..20}; do kill -0 "$process_id" 2>/dev/null || break; sleep .25; done
    if kill -0 "$process_id" 2>/dev/null; then
      printf '%s\n' "$process_id" >&2
      return 1
    fi
    prune_pids
    reap_stale_group "$group"
    printf '%s\n' "$process_id"
    return 0
  fi
  reap_stale_group "$group"
  prune_pids
  return 3
}

print_group_header() {
  local group="$1" multi="$2"
  if [[ "$multi" == 1 ]]; then
    printf '[%s]\n' "$group"
  fi
}

# start：已启动 + 入口；已在跑也视为已启动。
cmd_start() {
  local group="${1:-main}" result=0 item process_id multi=0
  command -v "$PYTHON" >/dev/null || { printf '找不到 %s。\n' "$PYTHON" >&2; return 1; }
  command -v setsid >/dev/null || { printf '找不到 setsid。\n' >&2; return 1; }
  mkdir -p "$(dirname "$LOG")"
  touch "$LOG"
  if [[ "$group" == all ]]; then
    multi=1
    for item in "${SERVICE_GROUPS[@]}"; do
      print_group_header "$item" "$multi"
      if process_id="$(start_one "$item")"; then
        printf '已启动 PID %s\n' "$process_id"
        print_endpoints "$item"
      else
        printf '启动失败\n日志：%s\n' "$LOG" >&2
        result=1
      fi
      printf '\n'
    done
    return "$result"
  fi
  if process_id="$(start_one "$group")"; then
    printf '已启动 PID %s\n' "$process_id"
    print_endpoints "$group"
  else
    printf '启动失败\n日志：%s\n' "$LOG" >&2
    return 1
  fi
}

# stop：只输出已停止 / 未运行。
cmd_stop() {
  local group="${1:-all}" result=0 item process_id rc multi=0
  if [[ "$group" == all ]]; then
    multi=1
    for item in "${SERVICE_GROUPS[@]}"; do
      print_group_header "$item" "$multi"
      process_id="$(stop_one "$item")"
      rc=$?
      if [[ "$rc" -eq 0 ]]; then
        printf '已停止 PID %s\n' "$process_id"
      elif [[ "$rc" -eq 3 ]]; then
        printf '未运行\n'
      else
        printf '停止超时 PID %s\n' "$process_id" >&2
        result=1
      fi
    done
    return "$result"
  fi
  process_id="$(stop_one "$group")"
  rc=$?
  if [[ "$rc" -eq 0 ]]; then
    printf '已停止 PID %s\n' "$process_id"
  elif [[ "$rc" -eq 3 ]]; then
    printf '未运行\n'
  else
    printf '停止超时 PID %s\n' "$process_id" >&2
    return 1
  fi
}

# restart：已停止 + 已启动 + 入口。
cmd_restart() {
  local group="${1:-main}" result=0 item old_pid new_pid rc multi=0
  command -v "$PYTHON" >/dev/null || { printf '找不到 %s。\n' "$PYTHON" >&2; return 1; }
  command -v setsid >/dev/null || { printf '找不到 setsid。\n' >&2; return 1; }
  mkdir -p "$(dirname "$LOG")"
  touch "$LOG"
  if [[ "$group" == all ]]; then
    multi=1
    for item in "${SERVICE_GROUPS[@]}"; do
      print_group_header "$item" "$multi"
      old_pid="$(stop_one "$item")"
      rc=$?
      if [[ "$rc" -eq 0 ]]; then
        printf '已停止 PID %s\n' "$old_pid"
      elif [[ "$rc" -eq 3 ]]; then
        printf '未运行\n'
      else
        printf '停止超时 PID %s\n' "$old_pid" >&2
        result=1
        continue
      fi
      if new_pid="$(start_one "$item")"; then
        printf '已启动 PID %s\n' "$new_pid"
        print_endpoints "$item"
      else
        printf '启动失败\n日志：%s\n' "$LOG" >&2
        result=1
      fi
      printf '\n'
    done
    return "$result"
  fi
  old_pid="$(stop_one "$group")"
  rc=$?
  if [[ "$rc" -eq 0 ]]; then
    printf '已停止 PID %s\n' "$old_pid"
  elif [[ "$rc" -eq 3 ]]; then
    printf '未运行\n'
  else
    printf '停止超时 PID %s\n' "$old_pid" >&2
    return 1
  fi
  if new_pid="$(start_one "$group")"; then
    printf '已启动 PID %s\n' "$new_pid"
    print_endpoints "$group"
  else
    printf '启动失败\n日志：%s\n' "$LOG" >&2
    return 1
  fi
}

# status：运行中/未运行 + 入口。
cmd_status() {
  local wanted="${1:-all}" item process_id found=0 multi=0
  prune_pids
  if [[ "$wanted" == all ]]; then
    multi=1
  fi
  for item in "${SERVICE_GROUPS[@]}"; do
    [[ "$wanted" == all || "$wanted" == "$item" ]] || continue
    print_group_header "$item" "$multi"
    if process_id="$(group_pid "$item")"; then
      found=1
      printf '运行中 PID %s\n' "$process_id"
    else
      printf '未运行\n'
    fi
    print_endpoints "$item"
    if [[ "$multi" == 1 ]]; then
      printf '\n'
    fi
  done
  ((found))
}

open_web() {
  cmd_start web || return
  load_endpoints web
  local url="${URL_LOCAL:-http://127.0.0.1:5000/web/}"
  if command -v xdg-open >/dev/null; then xdg-open "$url" >/dev/null 2>&1 &
  elif command -v open >/dev/null; then open "$url" >/dev/null 2>&1 &
  fi
}

case "${1:-start}" in
  start) cmd_start "${2:-main}" ;;
  stop) cmd_stop "${2:-all}" ;;
  restart) cmd_restart "${2:-main}" ;;
  status) cmd_status "${2:-all}" ;;
  open) open_web ;;
  order|broadcast|gsi|web) cmd_start "$1" ;;
  __run) run_group "$2" ;;
  *) printf '用法：%s {start/stop/restart/status/open} [main|order|broadcast|gsi|web|all]\n' "$0" >&2; exit 2 ;;
esac
