# Piano: porte e convivenza con altre app su Tailscale Serve

Branch: `agy/4.3.9-porte` (parte da `claude/rt-4.3.9-beta`). Solo codice e test unitari, niente verifiche
nell'app. Commit e push sul branch. Prima di tutto: `git pull` del branch.

Contesto: chi usa Tailscale Serve per altre app vuole la root `https://<mac>.ts.net/` (porta 443) libera per
una Home, e RT su una porta HTTPS dedicata: `tailscale serve --bg --https=8765 http://127.0.0.1:8765`
→ `https://<mac>.ts.net:8765`. RT resta sulla root `/` della sua porta: niente subpath `/rt`.
Il backend lo rileva già (`rt/core/tailscale.py` `tailnet_address`). Mancano i pezzi qui sotto.

## 1. QR: l'indirizzo salvato non deve nascondere una porta Tailscale cambiata
`frontend/src/lib/deviceLogin.ts` `preferredOrigin(saved, here, tailnet)` restituisce sempre `saved` se
utilizzabile. Cambia la firma in `preferredOrigin(saved, here, tailnet, serve = false)`:
- se `serve` è true, `tailnet` c'è, `saved` ha lo **stesso hostname** di `tailnet` ma origin diversa
  (porta diversa) → restituisci `tailnet`.
- tutto il resto invariato. Se l'utente ha scritto nel campo (`typed`), vince sempre quello che ha scritto.
`frontend/src/components/settings/device-access.tsx` (TailscalePanel) passa `tailnet?.serve`.
Test in `frontend/src/lib/deviceLogin.test.ts`: salvato `https://mac.ts.net`, tailnet
`https://mac.ts.net:8765` con serve → tailnet; senza serve → salvato; hostname diverso (es. altra VPN) →
salvato.

## 2. Porta locale reale al posto di 8765 fisso
- `rt/api/routers/system.py` `TailnetInfo`: nuovo campo `local_port: int` (Field con descrizione: porta
  locale su cui ascolta RT). `system_tailnet` lo riempie con la porta già calcolata (`port`) anche quando
  Tailscale manca (`TailnetInfo(local_port=port)`).
- `device-access.tsx`: gli avvisi «Tailscale Serve non è attivo» e «Funnel» usano `local_port` (fallback
  8765). L'avviso «Serve non attivo» propone il comando che **non occupa la 443**:
  `tailscale serve --bg --https=<porta> http://127.0.0.1:<porta>`. Aggiungi una riga breve sotto:
  «Con <code>tailscale serve --bg <porta></code> RT prende invece l'indirizzo senza porta (443).»
  L'avviso «Funnel» invece deve agire sulla porta HTTPS su cui il Funnel è attivo, cioè quella di
  `tailnet.origin` (443 se l'origin non ha porta): `tailscale serve --bg --https=<porta https> http://127.0.0.1:<local_port>`
  (con 443 basta `tailscale serve --bg <local_port>`). Altrimenti si crea un'altra porta e il Funnel resta acceso.
  Aggiorna l'hint del campo indirizzo: «Con Tailscale Serve è `https://nome-computer.tailnet.ts.net:<porta>`
  (o senza porta se RT usa la 443).»
- Stesso file, sezione API di sola lettura: il fallback `'http://127.0.0.1:8765/api/v1/readonly'` usa
  `window.location.port`/`local_port` invece di 8765 fisso (`info?.base_url` resta la prima scelta).
- `docs/WEB.md` (paragrafo «Da iPhone o da un altro dispositivo») `docs/open-webui.md` e la guida in `docs/guida/` se ne parla
  (cerca `tailscale serve`): metti come comando consigliato `tailscale serve --bg --https=8765 http://127.0.0.1:8765`
  (indirizzo `https://nome-mac.tailnet.ts.net:8765`), spiega in una frase che `tailscale serve --bg 8765` usa
  invece la 443 (comodo se sul Mac non ci sono altre app), e che se RT usa un'altra porta (Impostazioni)
  va messa quella.
- Rigenera `docs/openapi.json` (`python scripts/export_openapi.py`) e `frontend/src/api/schema.d.ts`
  (`npm run gen:api` in `frontend/`). Aggiorna i mock/test che costruiscono `TailnetInfo`.
- Test: `tests/test_tailscale.py` o i test di `system_tailnet`: `local_port` presente con e senza Tailscale.
  Vitest in `device-access.test.tsx`: con `local_port: 9000` e `serve: false` l'avviso mostra `--https=9000`.

## 3. Porta locale visibile (solo lettura, il cambio dall'app arriva dopo)
Niente campo per cambiarla in questa beta: `restart_process` riparte con lo stesso `--port`, su Windows il server
nascosto resterebbe sulla porta vecchia, e cambiarla rompe Serve, Open WebUI e gli indirizzi salvati.
- In `device-access.tsx`, pannello Tailscale, una riga piccola: «RT ascolta su questo computer sulla porta
  <code>{local_port}</code>.» con accanto il comando consigliato
  `tailscale serve --bg --https=<porta> http://127.0.0.1:<porta>` e un pulsante «Copia» (stesso stile del copia
  della sezione API di sola lettura). Usa `local_port` del punto 2.
- Vitest: con `local_port: 9000` compaiono la porta e il comando con 9000.

## 4. Cookie `Secure` dietro Tailscale Serve
`rt/api/routers/system.py` `open_browser_session` (righe ~268-278): oggi `secure = request.url.scheme == "https"`,
sempre false dietro Serve. Nuova funzione `_https_request(request)`: true se `request.url.scheme == "https"`,
oppure se il client TCP è loopback (`127.0.0.1`/`::1`, usa `_is_loopback` di `rt.api.readonly_auth`) **e**
`request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower() == "https"`.
Non attivare `--proxy-headers` in uvicorn e non toccare `readonly_auth.is_local_request`.
Usa la stessa funzione anche per `delete_cookie` se serve passare `secure`.
Test: loopback + `X-Forwarded-Proto: https` → `Secure` nell'header Set-Cookie; client non loopback con lo stesso
header → senza `Secure`; richiesta http locale → senza `Secure`.

## Chiusura
- `CHANGELOG.md`: nella sezione della prossima beta (crea `## 4.3.9b7` sopra la b6 se non c'è, stesso stile)
  in Novità «Comando Tailscale consigliato su porta dedicata (lascia libera la 443 per altre app)»; in Correzioni «Il QR segue la porta attuale di Tailscale Serve»,
  «Cookie di accesso sicuri (Secure) quando RT è aperto via Tailscale Serve»; in Novità anche «La pagina Accesso
  mostra la porta di RT e il comando Tailscale da copiare». Non cambiare `VERSION`.
- Esegui: `pytest -q` sui test toccati, `npx vitest run`, `npx oxlint --deny-warnings`, `npm run build`,
  `npm run -s check:bundle` in `frontend/`.
- Commit piccoli, uno per punto, push su `agy/4.3.9-porte`.
