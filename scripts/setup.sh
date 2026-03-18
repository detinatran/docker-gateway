#!/usr/bin/env bash
# =============================================================================
# setup.sh — Enable MCP servers and configure secrets
#
# Servers: github · atlassian (Jira + Confluence) · fetch
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "${SCRIPT_DIR}")"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC}  $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  🐳 Docker MCP Gateway Demo — Setup${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo ""

# ─── Pre-flight ──────────────────────────────────────────────────────────────
info "Checking prerequisites..."

if ! command -v docker &>/dev/null; then
  error "Docker is not installed. Please install Docker Desktop."
  exit 1
fi

if ! docker mcp version &>/dev/null; then
  error "'docker mcp' CLI plugin not found. Need Docker Desktop 4.59+."
  exit 1
fi

MCP_VERSION=$(docker mcp version 2>/dev/null)
ok "docker mcp ${MCP_VERSION} found"

# ─── Reset ───────────────────────────────────────────────────────────────────
info "Resetting existing server config..."
docker mcp server reset 2>/dev/null || true
ok "Clean slate"

# ─── Enable 3 servers ────────────────────────────────────────────────────────
info "Enabling servers from Docker MCP catalog..."

docker mcp server enable github
ok "Enabled: github (26 tools — repos, issues, PRs, search)"

docker mcp server enable atlassian
ok "Enabled: atlassian (73 tools — Jira + Confluence)"

docker mcp server enable fetch
ok "Enabled: fetch (1 tool — URL content fetching)"

echo ""
info "Enabled servers:"
docker mcp server ls
echo ""

# ─── Secrets + Config from .env ──────────────────────────────────────────────
ENV_FILE="${PROJECT_DIR}/.env"
MCP_CONFIG_FILE="${HOME}/.docker/mcp/config.yaml"

if [ -f "${ENV_FILE}" ]; then
  info "Loading credentials from .env..."
  set -a
  source "${ENV_FILE}"
  set +a

  # ── GitHub secret ──
  if [ -n "${GITHUB_TOKEN:-}" ] && [ "${GITHUB_TOKEN}" != "ghp_your_token_here" ]; then
    printf "%s" "${GITHUB_TOKEN}" | docker mcp secret set github.personal_access_token 2>/dev/null \
      && ok "GitHub token → secret store" \
      || warn "Could not set GitHub token"
  else
    warn "No GITHUB_TOKEN — GitHub uses public API (rate-limited)"
  fi

  # ── Jira/Atlassian secrets (API tokens) ──
  JIRA_USER="${JIRA_USERNAME:-${JIRA_EMAIL:-}}"

  if [ -n "${JIRA_API_TOKEN:-}" ] && [ "${JIRA_API_TOKEN}" != "your_api_token_here" ]; then
    printf "%s" "${JIRA_API_TOKEN}" | docker mcp secret set atlassian.jira.api_token 2>/dev/null \
      && ok "JIRA_API_TOKEN → secret store" \
      || warn "Could not set JIRA_API_TOKEN"
    printf "%s" "${JIRA_API_TOKEN}" | docker mcp secret set atlassian.confluence.api_token 2>/dev/null || true
  else
    warn "No JIRA_API_TOKEN — Jira tools won't authenticate"
  fi

  # ── Jira/Atlassian config (URL + username → config.yaml) ──
  # These are NON-SECRET config values that gateway templates inject as env vars.
  # Format must match catalog templates: {{atlassian.jira.url}}, {{atlassian.jira.username}}
  if [ -n "${JIRA_URL:-}" ] && [ "${JIRA_URL}" != "https://your-company.atlassian.net" ]; then
    CONF_URL="${JIRA_URL}/wiki"
    cat > "${MCP_CONFIG_FILE}" << YAMLEOF
atlassian:
  jira:
    url: "${JIRA_URL}"
    username: "${JIRA_USER}"
  confluence:
    url: "${CONF_URL}"
    username: "${JIRA_USER}"
YAMLEOF
    ok "Jira config → ${MCP_CONFIG_FILE}"
    info "  JIRA_URL = ${JIRA_URL}"
    info "  JIRA_USER = ${JIRA_USER}"
  else
    warn "No JIRA_URL — Jira/Confluence tools won't connect"
  fi
else
  warn "No .env file found. Copy .env.example to .env and add your keys."
  warn "  cp .env.example .env && \$EDITOR .env"
fi

# ─── Python venv ─────────────────────────────────────────────────────────────
VENV_DIR="${PROJECT_DIR}/.venv"
if [ ! -d "${VENV_DIR}" ]; then
  info "Creating Python virtual environment..."
  python3 -m venv "${VENV_DIR}"
  ok "venv created at .venv/"
fi

info "Installing Python dependencies..."
"${VENV_DIR}/bin/pip" install -q -r "${PROJECT_DIR}/client/requirements.txt"
ok "MCP SDK installed"

# ─── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✅ Setup Complete!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo ""
info "3 MCP servers: github (26 tools) · atlassian (73 tools) · fetch (1 tool)"
info "Each server runs in its own isolated Docker container"
echo ""
info "Next steps:"
echo "  1. Verify:  ./scripts/verify.sh"
echo "  2. Run:     .venv/bin/python client/main.py"
echo ""
