# Come modificare la guida di RT

Questa pagina spiega come modificare, aggiungere e organizzare i contenuti della guida di RT.

## 1. Pagine della guida: ordine, aggiunta e rinomina

L'elenco e l'ordine delle pagine sono definiti nel file `docs/guida/indice.yml`.
Ogni voce corrisponde a un file `.md` nella stessa cartella (senza l'estensione `.md`):

```yaml
- file: index
- file: installazione
- file: nuova-pagina
```

- **Per cambiare l'ordine**: sposta le righe nell'ordine desiderato.
- **Per aggiungere una nuova pagina**:
  1. Crea il file `docs/guida/nome-pagina.md`.
  2. Inserisci in cima il titolo con `# Nome della pagina`.
  3. Aggiungi `- file: nome-pagina` in `indice.yml` nella posizione in cui vuoi farla apparire.
- **Per togliere una pagina**: rimuovi la riga da `indice.yml`. Il file `.md` non verrà mostrato né nell'app né nel sito.

## 2. Sezioni e ancore automatiche

All'interno di ogni file markdown, dividi il testo in sezioni usando `##`:

```markdown
## Requisiti di sistema
```

L'ancora per i collegamenti diretti nasce automaticamente dal titolo (in minuscolo, senza accenti, spazi sostituiti da trattini). Nell'esempio sopra, l'ancora sarà `#requisiti-di-sistema`.

## 3. Immagini

Metti i file delle immagini (formati `.png`, `.jpg`, `.webp`, `.gif`) nella cartella `docs/guida/immagini/`.
Per inserire un'immagine nel testo, scrivi su una riga a sé:

```markdown
![Schermata principale di RT](immagini/schermata-principale.png)
```

Se l'immagine non viene trovata, RT mostra il testo alternativo in corsivo senza bloccare la lettura.

## 4. Riquadri in evidenza (Note, Consigli, Avvisi)

Per evidenziare informazioni importanti, usa i riquadri con `>` all'inizio della riga:

- **Nota informativa**:
  ```markdown
  > [!NOTE]
  > RT salva tutti i dati in locale sul tuo computer.
  ```
- **Consiglio**:
  ```markdown
  > [!TIP]
  > Puoi premere F1 in qualsiasi momento per aprire la guida.
  ```
- **Avviso o attenzione**:
  ```markdown
  > [!WARNING]
  > Prima di eliminare una lezione, assicurati di aver esportato gli appunti importanti.
  ```

## 5. Link tra le pagine e alle sezioni

Per inserire un collegamento a un'altra pagina della guida o a una sezione specifica:

```markdown
Per i dettagli completi, consulta la [guida all'installazione](/guida/installazione#macos).
```

Il formato è `[testo visibile](/guida/<pagina>#<ancora>)` oppure `[testo visibile](/guida/<pagina>)`.
