#!/usr/bin/env bash
set -euo pipefail

if [[ $# -eq 0 ]]; then
  echo 'Usage: bash ./run.sh --channel <channel-url|@handle> [--since YYYY-MM-DD|-1|0] [--output DIR] [--limit N] [--translate-to LANGUAGE] [--force]'
  echo 'Options: --since filters inclusively by upload date; -1 means yesterday and 0 means today. --output sets the result folder; --langs sets caption priority; --limit caps videos; --translate-to creates translated transcript copies; --force re-extracts and regenerates outputs.'
  exit 0
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
  PYTHON="$SCRIPT_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON="$(command -v python)"
else
  echo "Python 3.10+ is required and must be on PATH." >&2
  exit 127
fi

YT_RESEARCH_LAUNCHER=bash exec "$PYTHON" "$SCRIPT_DIR/run_research.py" "$@"
