#!/usr/bin/env bash
#
# @fileoverview KOOK 音乐机器人 Linux 一键启停脚本
# @description 自动创建虚拟环境、安装依赖、检查 FFmpeg，并以守护方式启动 Flask 服务
# @author Cursor
# @since 2026-08-23
#
# 用法:
#   ./serve.sh            后台启动（默认）
#   ./serve.sh start      后台启动
#   ./serve.sh run        前台运行，便于看实时日志
#   ./serve.sh stop       停止服务
#   ./serve.sh restart    重启服务
#   ./serve.sh status     查看运行状态
#   ./serve.sh logs       跟踪应用日志
#

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 兼容两种布局：KBot/MusicBot（run.py 在脚本同级）或旧的 仓库/Ubuntu
if [[ -f "${ROOT_DIR}/run.py" ]]; then
    APP_DIR="${ROOT_DIR}"
elif [[ -f "${ROOT_DIR}/Ubuntu/run.py" ]]; then
    APP_DIR="${ROOT_DIR}/Ubuntu"
else
    echo "[serve] 找不到 run.py"
    exit 1
fi
VENV_DIR="${APP_DIR}/venv"
VENV_PY="${VENV_DIR}/bin/python"
PID_FILE="${APP_DIR}/kook-music.pid"
LOG_FILE="${APP_DIR}/app.log"
ENV_FILE="${APP_DIR}/.env"

# 从 .env 读取 PORT，供状态检查与启动提示使用
read_env_port() {
    local port="8004"
    if [[ -f "${ENV_FILE}" ]]; then
        local line
        line="$(grep -E '^PORT=' "${ENV_FILE}" | tail -n 1 || true)"
        if [[ -n "${line}" ]]; then
            port="${line#PORT=}"
            port="${port//$'\r'/}"
        fi
    fi
    echo "${port}"
}

# 判断 PID 文件对应进程是否仍在运行
is_running() {
    if [[ ! -f "${PID_FILE}" ]]; then
        return 1
    fi
    local pid
    pid="$(cat "${PID_FILE}" 2>/dev/null || true)"
    if [[ -z "${pid}" ]]; then
        return 1
    fi
    if kill -0 "${pid}" 2>/dev/null; then
        return 0
    fi
    return 1
}

# 准备 Python 虚拟环境；作者仓库里的 venv 来自另一台机器，这里按本机重建
ensure_venv() {
    if [[ ! -x "${VENV_PY}" ]]; then
        echo "[serve] 正在创建 Python 虚拟环境..."
        rm -rf "${VENV_DIR}"
        python3 -m venv "${VENV_DIR}"
    fi

    # 关键依赖缺失时再安装，避免每次启动都跑 pip
    if ! "${VENV_PY}" -c "import flask, khl, dotenv, requests, psutil, flask_socketio" >/dev/null 2>&1; then
        echo "[serve] 正在安装 Python 依赖..."
        "${VENV_DIR}/bin/pip" install --upgrade pip
        "${VENV_DIR}/bin/pip" install -r "${APP_DIR}/requirements.txt"
    fi
}

# 检查 FFmpeg；缺失时尝试用 apt 安装（需要 root）
ensure_ffmpeg() {
    if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
        return 0
    fi

    echo "[serve] 未检测到 ffmpeg / ffprobe。"
    if [[ "$(id -u)" -eq 0 ]] && command -v apt-get >/dev/null 2>&1; then
        echo "[serve] 正在通过 apt 安装 ffmpeg..."
        apt-get update -y
        apt-get install -y ffmpeg
        return 0
    fi

    echo "[serve] 请先安装: apt-get update && apt-get install -y ffmpeg"
    exit 1
}

# 确认 Token 和 .env 已经就位
ensure_env() {
    if [[ ! -f "${ENV_FILE}" ]]; then
        echo "[serve] 缺少 ${ENV_FILE}，请先配置 BOT_TOKEN。"
        exit 1
    fi

    local token
    token="$(grep -E '^BOT_TOKEN=' "${ENV_FILE}" | tail -n 1 | cut -d= -f2- || true)"
    token="${token//$'\r'/}"
    if [[ -z "${token}" || "${token}" == "your_bot_token_here" ]]; then
        echo "[serve] .env 里的 BOT_TOKEN 未配置。"
        exit 1
    fi
}

# 后台启动 Flask + KOOK 机器人
cmd_start() {
    if is_running; then
        echo "[serve] 服务已在运行，PID=$(cat "${PID_FILE}")"
        exit 0
    fi

    ensure_env
    ensure_ffmpeg
    ensure_venv

    cd "${APP_DIR}"
    echo "[serve] 启动 KOOK 音乐机器人..."
    # setsid 脱离当前 shell 进程组，避免脚本结束后服务被一起收掉
    setsid "${VENV_PY}" run.py >> "${LOG_FILE}" 2>&1 < /dev/null &
    echo $! > "${PID_FILE}"
    sleep 1

    if is_running; then
        local port
        port="$(read_env_port)"
        echo "[serve] 启动成功，PID=$(cat "${PID_FILE}")"
        echo "[serve] 控制台: http://127.0.0.1:${port}  （外网用服务器 IP:${port}）"
        echo "[serve] 日志: ${LOG_FILE}"
    else
        echo "[serve] 启动失败，请查看日志: ${LOG_FILE}"
        exit 1
    fi
}

# 前台运行，Ctrl+C 结束
cmd_run() {
    if is_running; then
        echo "[serve] 后台服务已在运行，PID=$(cat "${PID_FILE}")。请先 ./serve.sh stop"
        exit 1
    fi

    ensure_env
    ensure_ffmpeg
    ensure_venv

    cd "${APP_DIR}"
    echo "[serve] 前台启动，按 Ctrl+C 停止"
    exec "${VENV_PY}" run.py
}

# 停止后台进程
cmd_stop() {
    if ! is_running; then
        echo "[serve] 服务未运行"
        rm -f "${PID_FILE}"
        return 0
    fi

    local pid
    pid="$(cat "${PID_FILE}")"
    echo "[serve] 正在停止 PID=${pid} ..."
    kill "${pid}" 2>/dev/null || true

    local i
    for i in $(seq 1 20); do
        if ! kill -0 "${pid}" 2>/dev/null; then
            break
        fi
        sleep 0.3
    done

    if kill -0 "${pid}" 2>/dev/null; then
        echo "[serve] 进程未退出，发送 SIGKILL"
        kill -9 "${pid}" 2>/dev/null || true
    fi

    rm -f "${PID_FILE}"
    echo "[serve] 已停止"
}

# 打印运行状态
cmd_status() {
    local port
    port="$(read_env_port)"
    if is_running; then
        echo "[serve] 运行中 PID=$(cat "${PID_FILE}")  端口=${port}"
    else
        echo "[serve] 未运行"
        return 1
    fi
}

# 跟踪应用日志
cmd_logs() {
    if [[ ! -f "${LOG_FILE}" ]]; then
        echo "[serve] 还没有日志文件: ${LOG_FILE}"
        exit 1
    fi
    tail -n 80 -f "${LOG_FILE}"
}

usage() {
    cat <<EOF
用法: $(basename "$0") [start|run|stop|restart|status|logs]

  start     后台启动（默认）
  run       前台运行
  stop      停止
  restart   重启
  status    查看状态
  logs      跟踪日志
EOF
}

main() {
    if [[ ! -d "${APP_DIR}" ]]; then
        echo "[serve] 找不到 Linux 服务端目录: ${APP_DIR}"
        exit 1
    fi

    local action="${1:-start}"
    case "${action}" in
        start) cmd_start ;;
        run|fg) cmd_run ;;
        stop) cmd_stop ;;
        restart) cmd_stop; cmd_start ;;
        status) cmd_status ;;
        logs|log) cmd_logs ;;
        -h|--help|help) usage ;;
        *)
            echo "[serve] 未知命令: ${action}"
            usage
            exit 1
            ;;
    esac
}

main "$@"
