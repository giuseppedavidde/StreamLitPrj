#!/usr/bin/env bash
# setup.sh — Clone opencode-skills dependency and install trading-mcp-server.
#
# Usage:
#   ./setup.sh              # clone opencode-skills into vendor/ and install
#   ./setup.sh --link       # symlink to sibling repo (local dev)
#
# GitHub: https://github.com/anomalyco/opencode-skills

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENDOR_DIR="${SCRIPT_DIR}/vendor"
OCS_DIR="${VENDOR_DIR}/opencode-skills"
OCS_REPO="https://github.com/anomalyco/opencode-skills.git"
VENV_DIR="${SCRIPT_DIR}/.venv"

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

log()  { echo -e "${GREEN}[setup]${NC} $*"; }
err()  { echo -e "${RED}[error]${NC} $*" >&2; }

# -- CLI args ----------------------------------------------------------------
LINK_MODE=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --link) LINK_MODE=true; shift ;;
        *) err "Unknown arg: $1"; exit 1 ;;
    esac
done

# -- Resolve opencode-skills -------------------------------------------------
find_ocs() {
    if [ "$LINK_MODE" = true ]; then
        SIBLING="$(cd "${SCRIPT_DIR}/../.." && pwd)/opencode-skills"
        if [ -d "$SIBLING" ]; then
            echo "$SIBLING"
            return 0
        fi
    fi
    echo ""
}

if [ -d "$OCS_DIR" ]; then
    log "opencode-skills already in vendor/ — pulling latest..."
    git -C "$OCS_DIR" pull --ff-only
else
    SIBLING="$(find_ocs)"
    if [ -n "$SIBLING" ]; then
        log "Linking sibling repo: $SIBLING -> $OCS_DIR"
        ln -s "$SIBLING" "$OCS_DIR"
    else
        log "Cloning opencode-skills into vendor/..."
        git clone --depth 1 "$OCS_REPO" "$OCS_DIR"
    fi
fi

# -- Install trading-mcp-server ----------------------------------------------
if [ ! -d "$VENV_DIR" ]; then
    log "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

PIP="$VENV_DIR/bin/pip"
PYTHON="$VENV_DIR/bin/python3"

log "Installing trading-mcp-server (editable mode)..."
$PIP install -e "${OCS_DIR}/mcp" -q

log "Installing Streamlit dependencies..."
$PIP install -r "${SCRIPT_DIR}/requirements.txt" -q

# -- Verify ------------------------------------------------------------------
log "Verifying imports..."
$PYTHON -c "from trading_mcp.analysis.scanner import process_ticker; print('  trading_mcp OK')" || {
    err "trading_mcp import failed. Check PYTHONPATH."
    exit 1
}

$PYTHON -c "import streamlit; print('  streamlit OK')" || {
    err "streamlit import failed."
    exit 1
}

log "Setup complete!"
echo ""
echo "  Run:  streamlit run app.py"
echo ""
