#!/usr/bin/env bash
# =============================================================================
# verify.sh — Verify Gateway config and show server info
# =============================================================================
set -euo pipefail

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC}  $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  🔍 MCP Gateway Demo — Verification${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo ""

# ─── 1. Check enabled servers ────────────────────────────────────────────────
info "Enabled MCP servers:"
docker mcp server ls 2>&1
echo ""

# ─── 2. Show server details ─────────────────────────────────────────────────
for server in github atlassian fetch; do
  info "Server '${server}' tools:"
  docker mcp server inspect "${server}" 2>&1 | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    tools = data.get('tools', [])
    for t in tools:
        status = '✓' if t.get('enabled', True) else '✗'
        print(f\"  {status} {t['name']:<30} {t.get('description', '')[:60]}\")
    print(f\"  ({len(tools)} tools total)\")
except: pass
" 2>/dev/null || warn "Could not inspect ${server}"
  echo ""
done

# ─── 3. Check secrets ────────────────────────────────────────────────────────
info "Configured secrets:"
docker mcp secret ls 2>&1 || warn "Could not list secrets"
echo ""

# ─── 4. Check Python venv ────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "${SCRIPT_DIR}")"
VENV="${PROJECT_DIR}/.venv"

if [ -f "${VENV}/bin/python" ]; then
  MCP_VER=$("${VENV}/bin/python" -c "import mcp; print(mcp.__version__)" 2>/dev/null || echo "?")
  ok "Python venv ready, MCP SDK v${MCP_VER}"
else
  warn "Python venv not found. Run ./scripts/setup.sh first."
fi

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✅ Verification Complete${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo ""
info "To run the demo:"
echo "  .venv/bin/python client/main.py"
echo ""
