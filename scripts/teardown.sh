#!/usr/bin/env bash
# =============================================================================
# teardown.sh — Clean up: disable all servers and clean containers
# =============================================================================
set -euo pipefail

GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC}  $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }

info "Disabling all MCP servers..."
docker mcp server reset 2>/dev/null || true
ok "All servers disabled"

info "Cleaning up any lingering MCP containers..."
docker ps -a --filter "label=com.docker.mcp" --format "{{.ID}}" 2>/dev/null | xargs -r docker rm -f 2>/dev/null || true
ok "Containers cleaned"

echo ""
echo -e "${GREEN}✅ Teardown complete.${NC}"
echo ""
