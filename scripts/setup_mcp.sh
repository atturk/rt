#!/bin/bash
# Registra in Claude Code (sul Mac di prova) i due server MCP per far usare RT a Claude:
#   rt         -> scripts/rt_mcp.py: API, job, import, log ed export dell'RT installato
#   playwright -> browser per l'interfaccia web e la console (serve Node.js)
# Ambito "local": valgono solo per questa cartella del repository. Vedi docs/MCP.md.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
if ! command -v claude >/dev/null 2>&1; then
    echo "❌ Manca il comando 'claude' (Claude Code)." >&2
    exit 1
fi
claude mcp remove rt >/dev/null 2>&1 || true
claude mcp add rt -- /usr/bin/env python3 "$REPO/scripts/rt_mcp.py"
echo "✅ Server MCP 'rt' registrato."
if command -v npx >/dev/null 2>&1; then
    claude mcp remove playwright >/dev/null 2>&1 || true
    claude mcp add playwright -- npx -y @playwright/mcp@0.0.83 --isolated
    echo "✅ Server MCP 'playwright' registrato."
else
    echo "⚠️  Node.js non trovato: senza 'playwright' Claude usa solo l'API (installa Node con 'brew install node' e rilancia)."
fi
claude mcp list
