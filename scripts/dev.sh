#!/usr/bin/env bash
# Copia "di lavoro" di RT per provare subito le modifiche di un branch, senza release.
#
#   scripts/dev.sh                 aggiorna il branch corrente, poi avvia API + worker finto + SPA
#   scripts/dev.sh --no-pull       avvia senza aggiornare
#
# Gira in una cartella isolata (dati di prova in $RT_DEV_DIR, default ~/.rt-dev) con il worker in
# mock: non tocca ~/.rt, i servizi launchd né le lezioni vere, e non chiama LLM a pagamento.
# La SPA si ricarica da sola a ogni modifica in frontend/ (Vite); per le modifiche al backend
# basta Ctrl+C e rilanciare. Porte: API 8766, SPA 5173.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEV_DIR="${RT_DEV_DIR:-$HOME/.rt-dev}"
API_PORT=8766
VENV="$ROOT/.venv-dev"
cd "$ROOT"

if [[ "${1:-}" != "--no-pull" ]]; then
  echo "▸ Aggiorno $(git rev-parse --abbrev-ref HEAD)…"
  git pull --ff-only
fi

# Dipendenze: reinstalla solo se i file delle dipendenze sono cambiati dall'ultima volta.
stamp() { cat requirements*.txt constraints.txt 2>/dev/null | shasum | cut -c1-12; }
if [[ ! -x "$VENV/bin/python" ]]; then
  echo "▸ Creo l'ambiente Python ($VENV)…"
  python3 -m venv "$VENV"
fi
if [[ "$(cat "$VENV/.stamp" 2>/dev/null)" != "$(stamp)" ]]; then
  echo "▸ Installo le dipendenze Python…"
  "$VENV/bin/pip" install -q -r requirements-dev.txt
  stamp > "$VENV/.stamp"
fi
if [[ ! -d frontend/node_modules || frontend/package-lock.json -nt frontend/node_modules/.package-lock.json ]]; then
  echo "▸ Installo le dipendenze della web app…"
  (cd frontend && npm ci --silent)
fi

# La SPA servita dall'API serve solo come ripiego: in sviluppo si usa Vite su :5173.
[[ -f frontend/dist/index.html ]] || (cd frontend && npm run -s build)

cleanup() { kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo "▸ Avvio API e worker finto su :$API_PORT (dati di prova in $DEV_DIR)…"
"$VENV/bin/python" scripts/e2e_server.py --port "$API_PORT" --dir "$DEV_DIR" &
STATE="$ROOT/frontend/e2e/.state/server.json"
for _ in $(seq 60); do
  curl -fs "http://127.0.0.1:$API_PORT/api/v1/health" >/dev/null 2>&1 && break
  sleep 1
done

TOKEN="$("$VENV/bin/python" -c "import json;print(json.load(open('$STATE'))['token'])")"
LINK="$(curl -fs -X POST -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:$API_PORT/api/v1/auth/login-link" \
  | "$VENV/bin/python" -c "import json,sys,urllib.parse as u;p=u.urlsplit(json.load(sys.stdin)['url']);print(u.urlunsplit(('http','localhost:5173',p.path,p.query,'')))")"

echo "▸ Avvio la web app con ricarica a caldo…"
(cd frontend && RT_API_URL="http://127.0.0.1:$API_PORT" npx vite --port 5173 --strictPort) &
sleep 2
echo
echo "  Apri: $LINK"
echo "  (Ctrl+C per fermare tutto)"
command -v open >/dev/null && open "$LINK"
wait
