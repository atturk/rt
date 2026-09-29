"""
rt.services.errors
Errori di dominio dei servizi: dicono *cosa* è andato storto (codice stabile, messaggio per
l'utente, dettagli) e di che *tipo* è (kind), senza sapere nulla di HTTP. L'API li traduce
in risposte {"error": {...}} con un solo handler (rt.api.errors); la CLI e il bot possono
mostrarne il messaggio. Così il motore resta indipendente dalle interfacce (RT4-A0).
"""
from typing import Any


class ServiceError(Exception):
    """Errore di dominio con un codice stabile (es. "lesson_not_found")."""

    kind = "invalid"

    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


class NotFound(ServiceError):
    """La risorsa richiesta non esiste."""
    kind = "not_found"


class Conflict(ServiceError):
    """L'operazione è in conflitto con lo stato attuale (lezione occupata, duplicato...)."""
    kind = "conflict"


class Invalid(ServiceError):
    """Dati in ingresso non validi."""
    kind = "invalid"


class TooLarge(ServiceError):
    """I dati superano un limite di dimensione."""
    kind = "too_large"


class Unavailable(ServiceError):
    """Una dipendenza locale (es. il database) non è disponibile."""
    kind = "unavailable"


class UpstreamFailed(ServiceError):
    """Un servizio esterno (es. Telegram) ha risposto con un errore."""
    kind = "upstream"
