# Collegare Open WebUI a RT (AP1)

RT 4.2.5 include un'API locale di sola lettura (`/api/v1/readonly`) pensata per essere collegata come Action (Tool) in Open WebUI, che gira sullo stesso Mac (`127.0.0.1`).

L'API permette all'assistente di:
1. **Cercare nelle lezioni** con ricerca full-text SQLite FTS5 e filtri per materia e date (`searchLessons`)
2. **Elencare le lezioni** registrate (`listLessons`)
3. **Leggere la scaletta** di una lezione con le sue unità (`getLessonOutline`)
4. **Leggere il testo completo** di una specifica unità (`getLessonUnit`)

---

## 1. Generare la chiave di sola lettura

1. Apri RT nel browser e vai in **Impostazioni › Accesso da iPhone** (oppure `/impostazioni/accesso`).
2. Nella sezione **API di sola lettura (Open WebUI)** clicca **Genera chiave**.
3. Copia la chiave mostrata (prefisso `rt_ro_...`). Questa chiave viene mostrata una sola volta.

> [!NOTE]
> La chiave di sola lettura è separata dal token di amministrazione di RT e può solo interrogare e leggere lezioni. Non permette modifiche, avvii di job né eliminazioni.

---

## 2. Configurare l'Action in Open WebUI

1. In Open WebUI, apri il menu **Workspace › Actions** (oppure **Tools** a seconda della versione).
2. Crea una nuova Action e seleziona **Import OpenAPI Spec**.
3. Inserisci l'URL della specifica OpenAPI di RT:
   ```text
   http://127.0.0.1:8765/api/v1/readonly/openapi.json
   ```
4. Nelle impostazioni di autenticazione dell'Action:
   - Tipo: **Bearer** (o API Key in Header `Authorization`)
   - Token: incolla la chiave `rt_ro_...` generata al punto 1.
5. Salva l'Action.

---

## 3. Utilizzo nella chat

Quando chiedi a Open WebUI informazioni su argomenti spiegati a lezione (es. *"Cosa ha detto il professore sull'emocromo?"* o *"Quali unità compongono la lezione di biochimica?"*), il modello utilizzerà automaticamente i tool:
- `searchLessons` per trovare le lezioni e le unità rilevanti;
- `getLessonUnit` per leggere il contenuto delle unità trovate e rispondere con precisione basandosi sui tuoi appunti e registrazioni.

---

## Sicurezza e vincoli di rete

- **Loopback obbligatorio**: Per motivi di sicurezza l'endpoint `/api/v1/readonly` accetta connessioni esclusivamente da `127.0.0.1` / `::1` (il Mac locale).
- **Revoca immediata**: Dalla stessa schermata in Impostazioni puoi cliccare **Revoca** o **Rigenera chiave** in qualsiasi momento per invalidare la chiave precedente.
