#!/bin/sh
# Prepara la cartella dati (/data: config, DB, media, stato del bot; idempotente) e avvia
# il comando rt richiesto (api, worker, telegram-daemon...).
set -e
python /opt/rt/bin/rt data init >/dev/null
exec python /opt/rt/bin/rt "$@"
