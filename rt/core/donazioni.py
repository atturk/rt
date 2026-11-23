"""Configurazione dell'URL per sostenere RT (donazioni)."""

# Pagina Ko-fi: il sito la apre nel pannello sopra la pagina (iframe con hidefeed/embed).
DONAZIONI_URL = "https://ko-fi.com/attilio_o"


def donazioni_app_url(base: str | None = None) -> str:
    """Link che l'app apre nel browser: solo il modulo di donazione (/donate), senza feed."""
    base = (DONAZIONI_URL if base is None else base).rstrip("/")
    return f"{base}/donate" if base else ""
