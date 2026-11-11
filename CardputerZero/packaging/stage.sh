#!/usr/bin/env bash
set -euo pipefail
: "${STAGE:?}"
: "${APP_INSTALL_DIR:?}"
: "${INSTALL_PREFIX:?}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEST="$STAGE$APP_INSTALL_DIR"
mkdir -p "$DEST" "$STAGE$INSTALL_PREFIX/bin" "$STAGE$INSTALL_PREFIX/share/images"

# The package always receives the current shared Python source. CardputerZero
# contains no copied command/protocol catalog.
tar -C "$ROOT" --exclude='__pycache__' --exclude='*.pyc' -cf - \
    JanOS_app.py janos_core.py projectzero_commands.py requirements.txt \
    CardputerZero/__init__.py CardputerZero/app CardputerZero/generated | tar -C "$DEST" -xf -

install -m 0755 "$ROOT/CardputerZero/packaging/janos-cardputer" \
    "$STAGE$INSTALL_PREFIX/bin/janos-cardputer"
install -m 0644 "$ROOT/CardputerZero/packaging/icon.xpm" \
    "$STAGE$INSTALL_PREFIX/share/images/janos-cardputer.xpm"

