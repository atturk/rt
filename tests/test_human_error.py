from rt.services.human_error import human_error


def test_human_error_network_error():
    err1 = "…il modello openai/gpt-6-luna ha dato errore (network_error): ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))…"
    assert human_error(err1) == "Connessione al modello interrotta."

    err2 = "Connection aborted by peer"
    assert human_error(err2) == "Connessione al modello interrotta."

    err3 = "RemoteDisconnected('no response')"
    assert human_error(err3) == "Connessione al modello interrotta."


def test_human_error_macparakeet_failed():
    err = "SetupError: Trascrizione macparakeet-cli JSON fallita per 'finto-audio.mp3' (codice uscita: 1). Dettagli errore:"
    assert human_error(err) == "Non riesco a leggere l'audio «finto-audio.mp3»."


def test_human_error_timeout():
    err = "LLM request failed: timeout after 60s"
    assert human_error(err) == "Il modello non ha risposto in tempo."


def test_human_error_fallback_strips_class_prefix():
    err = "SetupError: Impossibile creare la cartella temporanea."
    assert human_error(err) == "Impossibile creare la cartella temporanea."

    err2 = "RuntimeError: Qualcosa è andato storto"
    assert human_error(err2) == "Qualcosa è andato storto"


def test_human_error_preserves_suffix():
    err = "SetupError: Trascrizione macparakeet-cli JSON fallita per 'lezione.m4a' (codice uscita: 1). Le unità completate sono salvate: Riprova rifà solo quelle mancanti."
    assert human_error(err) == "Non riesco a leggere l'audio «lezione.m4a». Le unità completate sono salvate: Riprova rifà solo quelle mancanti."

    err2 = "network_error: connection drop. Le unità completate sono salvate: Riprova rifà solo quelle mancanti."
    assert human_error(err2) == "Connessione al modello interrotta. Le unità completate sono salvate: Riprova rifà solo quelle mancanti."

    err3 = "RuntimeError: Errore generico. Le unità completate sono salvate: Riprova rifà solo quelle mancanti."
    assert human_error(err3) == "Errore generico. Le unità completate sono salvate: Riprova rifà solo quelle mancanti."


def test_human_error_empty():
    assert human_error(None) == ""
    assert human_error("") == ""
