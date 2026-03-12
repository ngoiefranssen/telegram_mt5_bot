#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/home/julia/Elements/Person project/Creation Bots trading/telegram_mt5_bot"
PYTHON_BIN="$PROJECT_DIR/venv/bin/python"
BOT_FILE="$PROJECT_DIR/bot_vps_gram_mt.py"
LOG_FILE="$PROJECT_DIR/trading_bot.log"
PROCESS_PATTERN="bot_vps_gram_mt.py"

if pgrep -f "$PROCESS_PATTERN" > /dev/null 2>&1; then
  exit 0
fi

cd "$PROJECT_DIR"
nohup "$PYTHON_BIN" "$BOT_FILE" >> "$LOG_FILE" 2>&1 &
