# Novità di RT

## 4.2.4b2 — 2026-10-09

### Novità

- Documento finale e registro degli errori aggiornati automaticamente dopo decisioni, annullamenti e salvataggi, con un solo job per lezione e tre secondi dall’ultimo cambio.

- La verifica riceve un contesto fisso della lezione prima delle unità: titolo, materia, docente, argomenti e scaletta.

- Schema vincolato della verifica su OpenRouter e Google; DeepSeek mantiene JSON con validazione locale obbligatoria.

- La verifica restituisce citazioni e sostituzioni esatte con uno schema piccolo; i passaggi non ritrovati restano non ancorati, senza chiamate di riparazione.

- Le unità già finite si possono decidere e riaprire mentre la verifica prosegue sulle altre.
- Verifica fino a quattro unità in parallelo, con issue disponibili appena ciascuna unità termina.
- La verifica controlla il testo risolto, conserva tutte le decisioni e riconosce i rifiuti sullo stesso passaggio anche con citazioni diverse.
- Le correzioni si applicano solo al passaggio ancorato della propria unità; le decisioni non ritrovate restano da riconfermare.
- Le lezioni esistenti ricevono le ancore alla prima lettura, senza chiamate al modello e con testo risolto identico.
- Issue e decisioni conservano l’ancora e la provenienza; registro DB aggiornato senza perdere i campi storici.
- Ancore testuali per ritrovare citazioni ripetute, spostate o parzialmente riscritte senza allargare il passaggio.

### Correzioni

- I token del prompt letti dalla cache sono salvati nelle chiamate e conteggiati al prezzo della cache quando noto; il contesto fisso è marcato per OpenRouter con Anthropic e Gemini.

- Le decisioni si vedono subito nel pannello; si ricaricano solo issue, unità della verifica e documento, con ripristino in caso di errore.
- Testo risolto e configurazione in cache, aggiornati quando cambiano bozza, issue, modifiche a mano o decisioni.
- Lock della lezione con proprietario e rinnovo: verifiche e decisioni concorrenti conservano tutti gli aggiornamenti.
- Testo, icone ed evidenziazioni leggibili con i colori Irlen anche nel tema scuro, in zen e lettura veloce.

## 4.2.4b1 — 2026-10-09

### Novità

- Modalità zen nello Studio, con barra a scomparsa e filtro Irlen condiviso con la lettura veloce.
- Linguetta per passare alla lezione precedente o successiva dello stesso giorno o della stessa materia.
- Cambio lezione dai lati del titolo e con swipe su iPhone, anche per le lezioni non ancora rielaborate.
- Classificatore unico nelle Impostazioni, con modalità e modello personalizzabili per ciascun job.
- Pannello Classificatore a griglia, con correzioni manuali e classificazione delle unità cambiate.
- Novità delle versioni consultabili in Impostazioni › Info.

### Correzioni

- Le scorciatoie dello Studio conservano la posizione nel testo, anche tornando dal ripasso.
- Le frecce per cambiare lezione rispettano editor, campi, menu, selezioni e player audio.
- Ridotte le letture ripetute e le chiamate del classificatore; cache per prefiltro e deriva.

### Cambiamenti

- Tasti dello Studio: Z per la zen, D per le domande, E per l'evidenziatore, G per la gomma e ⇧E per il colore.
- Le impostazioni esistenti del classificatore vengono migrate automaticamente.
- Le note delle release GitHub provengono da questo changelog, incluso negli aggiornamenti con rt -u.

Per le versioni precedenti: [release di GitHub](https://github.com/atturk/rt/releases).
