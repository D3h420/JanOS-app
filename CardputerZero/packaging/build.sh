#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile \
    "$ROOT/JanOS_app.py" "$ROOT/janos_core.py" "$ROOT/projectzero_commands.py" \
    "$ROOT/CardputerZero/app/"*.py
PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT/CardputerZero/scripts/sync_from_python.py" --check
if [[ -d "$ROOT/CardputerZero/tests" ]]; then
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ROOT" \
        python3 -m unittest discover -s "$ROOT/CardputerZero/tests" -p 'test_*.py'
fi

