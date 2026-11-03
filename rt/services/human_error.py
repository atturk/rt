"""
rt.services.human_error
Traduce gli errori tecnici e le eccezioni in messaggi comprensibili per l'utente,
mantenendo l'avviso di recupero parziale quando presente.
"""
import re
from typing import Optional

SUFFIX = "Le unità completate sono salvate: Riprova rifà solo quelle mancanti."


def human_error(text: Optional[str]) -> str:
    """Traduce un errore tecnico (da eccezione o log) in un messaggio chiaro per l'utente."""
    if not text:
        return ""

    text = str(text).strip()
    if not text:
        return ""

    has_suffix = SUFFIX in text

    # Punto 1: errore di rete o disconnessione
    if any(k in text for k in ("network_error", "RemoteDisconnected", "Connection aborted")):
        base = "Connessione al modello interrotta."
    # Punto 2: SetupError trascrizione macparakeet fallita
    elif "macparakeet" in text and "fallita" in text:
        m = re.search(r"fallita per ['\"«](.+?)['\"»]", text)
        if m:
            base = f"Non riesco a leggere l'audio «{m.group(1)}»."
        else:
            base = "Non riesco a leggere l'audio."
    # Punto 3: timeout
    elif "timeout" in text.lower():
        base = "Il modello non ha risposto in tempo."
    # Punto 4: tutto il resto senza prefisso della classe di errore
    else:
        base = text
        while re.match(r"^(?:[A-Za-z0-9_.]*(?:Error|Exception)):\s*", base):
            base = re.sub(r"^(?:[A-Za-z0-9_.]*(?:Error|Exception)):\s*", "", base).strip()

    if has_suffix and SUFFIX not in base:
        base = base.rstrip()
        if not base.endswith("."):
            base += "."
        base = f"{base} {SUFFIX}"

    return base
