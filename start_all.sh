#!/usr/bin/env bash
# macOS / Linux 一键启动（对应 start_all.bat）
# 用法: ./start_all.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PORT="${DAILY_ATTENDANCE_REPORT_API_PORT:-8787}"
PYTHON="${PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
  elif command -v python >/dev/null 2>&1; then
    PYTHON=python
  else
    echo "未找到 python3 / python，请先安装 Python 或设置 PYTHON=..."
    exit 1
  fi
fi

ollama_bin() {
  if [[ -x "$ROOT/tools/ollama/ollama" ]]; then
    echo "$ROOT/tools/ollama/ollama"
  elif command -v ollama >/dev/null 2>&1; then
    command -v ollama
  fi
}

ngrok_bin() {
  if [[ -x "$ROOT/tools/ngrok/ngrok" ]]; then
    echo "$ROOT/tools/ngrok/ngrok"
  elif [[ -x "$ROOT/tools/ngrok/ngrok.exe" ]]; then
    echo "$ROOT/tools/ngrok/ngrok.exe"
  elif command -v ngrok >/dev/null 2>&1; then
    command -v ngrok
  fi
}

ollama_running() {
  curl -sf "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1
}

open_mac_terminal() {
  local cmd="$1"
  local title="${2:-attendance}"
  osascript <<APPLESCRIPT
tell application "Terminal"
  do script "$cmd"
  activate
end tell
APPLESCRIPT
}

run_bg() {
  local name="$1"
  shift
  mkdir -p "$ROOT/logs"
  local log="$ROOT/logs/${name}.log"
  nohup "$@" >>"$log" 2>&1 &
  echo "  后台 PID $!，日志: $log"
}

# macOS：新开 Terminal 窗口；Linux 等：后台 + logs/
launch() {
  local label="$1"
  local cmd="$2"
  if [[ "$(uname -s)" == "Darwin" ]] && command -v osascript >/dev/null 2>&1; then
    local escaped
    escaped=$(printf '%s' "$cmd" | sed 's/\\/\\\\/g; s/"/\\"/g')
    open_mac_terminal "$escaped" "$label"
    echo "  已在新 Terminal 窗口启动: $label"
  else
    echo "  $label（后台）"
    run_bg "$label" bash -c "$cmd"
  fi
}

echo "[1/3] 启动 Ollama（OCR/AI 识别依赖）"
if ollama_running; then
  echo "  Ollama 已在运行 (http://127.0.0.1:11434)，跳过"
else
  OLLAMA="$(ollama_bin || true)"
  if [[ -z "${OLLAMA:-}" ]]; then
    echo "  未找到 ollama。请执行: brew install ollama"
  else
    launch "attendance-ollama" "$OLLAMA serve"
  fi
fi

echo "[2/3] 启动主程序"
launch "attendance-main" "cd \"$ROOT\" && $PYTHON main.py"

echo "[3/3] 启动 ngrok -> 127.0.0.1:$PORT"
NGROK="$(ngrok_bin || true)"
if [[ -z "${NGROK:-}" ]]; then
  echo "  未找到 ngrok。"
  echo "  请 brew install ngrok/ngrok/ngrok，或将 ngrok 放到 tools/ngrok/"
  echo "  首次使用: ngrok config add-authtoken <你的token>"
else
  launch "attendance-ngrok" "$NGROK http $PORT"
fi

echo ""
echo "已尝试启动: Ollama / main.py / ngrok"
echo "若打卡 AI 不可用，请确认 ollama serve 正常且端口 11434 可访问。"
echo "班次 Web 需把 ngrok 的 HTTPS 地址写入 .env 的 SHIFT_WEB_APP_PUBLIC_URL 后重启 main.py。"
