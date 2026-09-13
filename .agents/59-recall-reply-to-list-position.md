# Task 59 — `/recall <N>` in risposta al messaggio di `/list` usa N come posizione nella lista

Indipendente dagli altri task attivi. Nel progetto RT (/Users/attilioturco/Desktop/trt),
implementa direttamente, senza produrre un piano preliminare.

## Contesto

Oggi `/recall <query>` (`rt/telegram/daemon.py::handle_recall_command`, righe 198+) risolve la
query per data/parola chiave nel titolo (`resolve_recall_query`,
`rt/telegram/lesson_query.py`), con disambiguazione se ci sono più corrispondenze. L'utente
vuole un percorso più rapido: se manda `/recall <N>` **in risposta diretta** al messaggio che
`/list` ha appena inviato (quello con l'elenco numerato di lezioni), `N` deve essere interpretato
come la **posizione nella lista** mostrata in quel messaggio specifico, indipendentemente da
cosa contenga la query testuale standard — anche se altre lezioni "contengono" N nel titolo o
nella data, in questo caso specifico N è inequivocabile (posizione nella lista che l'utente ha
sott'occhio).

`handle_list_command` (`rt/telegram/daemon.py`, riga 144) oggi invia il testo della lista
(`render_lesson_list_text(scoped, ...)`, riga 190) ma non salva né il `message_id` del messaggio
inviato né l'elenco `scoped` (l'ordine esatto delle lezioni numerate) per poterlo poi
recuperare quando arriva una risposta.

## Modifica

### 1. In `handle_list_command`: persisti l'associazione message_id -> elenco lezioni

Cattura il `message_id` del messaggio inviato da `update.effective_message.reply_text(...)`
(verifica cosa ritorna l'oggetto `Message` di `python-telegram-bot` — ha un attributo
`.message_id`). Salva una mappatura persistente (breve durata è accettabile, es. la stessa
scadenza/meccanismo già usato per altro stato pending in `rt/telegram/registry.py` — leggi
quel modulo per capire il pattern esistente più adatto, es. `register_pending`/
`resolve_pending`, e riusalo invece di inventare un meccanismo di storage nuovo se già adatto)
da quel `message_id` all'elenco ORDINATO di percorsi lezione (`scoped`, nello stesso ordine
usato per numerarle in `render_lesson_list_text` — verifica quell'ordine esatto).

### 2. In `handle_recall_command`: rileva la risposta al messaggio di lista

All'inizio della funzione, controlla se il messaggio in arrivo è una risposta
(`update.effective_message.reply_to_message`, se non `None` ha un `.message_id`). Se lo è,
cerca quel `message_id` nella mappatura salvata al punto 1. Se trovato E la query
(`context.args`) è un singolo numero intero puro (es. `"11"`, non `"11 novembre"` o simile —
verifica che sia interpretabile come `int` senza ambiguità), usalo come indice 1-based
nell'elenco salvato per quel messaggio: se l'indice è valido (`1 <= N <= len(elenco)`), avvia
direttamente il recall su quella lezione (stesso percorso di `start_recall_via_telegram` già
usato per il caso senza argomenti), SALTANDO interamente `resolve_recall_query` e la sua
eventuale disambiguazione. Se l'indice non è valido (fuori range), rispondi con un messaggio
d'errore chiaro invece di ripiegare silenziosamente sulla ricerca testuale normale (evita
ambiguità: se l'utente ha risposto alla lista con un numero, si aspetta un comportamento
posizionale, non un fallback silenzioso a un comportamento diverso).

Se il messaggio NON è una risposta alla lista (nessun match nella mappatura, o non è affatto
una reply), mantieni il comportamento attuale invariato (ricerca per data/parola chiave).

## Test

- Test che verifica che `/list` salvi correttamente la mappatura message_id -> elenco lezioni
  nell'ordine giusto.
- Test che verifica che `/recall 11` in risposta al messaggio di lista risolva esattamente alla
  lezione in posizione 11 (1-based), anche quando esistono altre lezioni che conterrebbero "11"
  nel titolo o nella data.
- Test che verifica che `/recall 11` SENZA essere in risposta al messaggio di lista mantenga il
  comportamento attuale (ricerca testuale, eventuale disambiguazione).
- Test che verifica il caso di indice fuori range (es. `/recall 99` in risposta a una lista di
  20 elementi) produca un messaggio d'errore chiaro, non un fallback silenzioso.
- Test che verifica che una query non puramente numerica (es. `/recall 11 novembre`) in risposta
  alla lista NON venga trattata come posizionale (mantiene la ricerca testuale normale).

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`).

Non toccare `resolve_recall_query`/la ricerca testuale esistente: resta invariata per tutti i
casi che non sono una risposta diretta al messaggio di `/list`.

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Se hai un bot Telegram di test disponibile: crea più lezioni fittizie, manda `/list`,
   rispondi al messaggio con `/recall <N>` per un N che ambiguamente esisterebbe anche nella
   ricerca testuale normale, verifica che venga scelta la lezione in posizione N.
