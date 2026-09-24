# Review contestuale: proposta di implementazione

L'ispirazione visiva è un editor con commenti [nel margine del documento](https://dribbble.com/shots/27059959-Manage-comments-in-doc-editor) e [ancorati al testo](https://dribbble.com/shots/16697778-Inline-comments). La navigazione delle lezioni resta una sidebar sovrapposta a sinistra; il pannello review si apre a destra e riduce lo spazio della dashboard. Il documento e il lettore audio restano visibili.

## Flusso

1. «N issue da valutare» apre il pannello destro sulla lezione corrente. L'elenco compatto mostra tipo di errore, unità e stato, ordinabile per unità oppure per tipo. Non ripete claim e proposta per intero.
2. Il clic su una issue porta alla sua unità nel documento. Se il claim ha un'ancora verificata, evidenzia il passaggio e apre una scheda contestuale. La scheda mostra claim, proposta modificabile, motivazione, eventuale `diplomatic_question` e un confronto prima/dopo.
3. «Accetta» salva nel ledger comune la proposta originale, oppure salva come `edited` il testo modificato. «Mantieni originale» e «Riapri» conservano le regole e l'audit già usati dalla review web. Dopo la decisione si aggiorna il contatore e si seleziona la prossima issue.
4. L'audio si ascolta dal lettore principale, usando i timestamp del documento. La scheda review non contiene un secondo player.

## Vincolo dei dati da risolvere prima dell'evidenziazione inline

`ScienceIssue` contiene `unit_id`, `claim`, `suggested_fix`, `reason` e `diplomatic_question`, ma non gli offset del claim nel documento. Nelle quattro lezioni di prova tutte le 51 issue trovano la propria unità, mentre solo 31 claim compaiono esattamente nel testo di quell'unità. Una ricerca testuale o fuzzy non deve evidenziare una frase sbagliata: per le altre 20 issue il primo incremento deve mostrare un marcatore sull'unità, con claim e proposta nella scheda. L'evidenziazione precisa richiede un'ancora stabile (ID unità, versione del draft e intervallo del testo canonico) prodotta o verificata dal backend.

Il rendering del documento deve conservare gli ID delle unità; le decisioni continuano a passare da `submit_review_decision` e `undo_web_decision`. Prima di rimuovere la schermata review attuale, verificare tutte le azioni, incluse le issue ASR senza sostituzione testuale automatica, i testi modificati e l'annullamento.
