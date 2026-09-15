"""
rt.core.ui_theme
Gestione e applicazione del tema Textual (scuro/chiaro) per l'interfaccia da terminale.
"""

from typing import Optional, Any
from rt.core.config import load_config, RTConfig

THEME_MAP = {
    "dark": "textual-dark",
    "light": "textual-light",
}


def resolve_textual_theme(theme_choice: Optional[str] = None) -> str:
    """Mappa la preferenza utente ('dark'/'light') al nome di tema Textual effettivo."""
    clean = (theme_choice or "dark").lower().strip()
    return THEME_MAP.get(clean, "textual-dark")


def get_configured_textual_theme(cfg: Optional[RTConfig] = None) -> str:
    """Restituisce il tema Textual configurato (o caricato da config se cfg non fornito)."""
    if cfg is None:
        cfg = load_config()
    theme_val = getattr(getattr(cfg, "ui", None), "theme", "dark")
    return resolve_textual_theme(theme_val)


def apply_saved_theme(app: Any, cfg: Optional[RTConfig] = None) -> None:
    """Imposta il tema Textual sull'App specificata in base alla configurazione salvata."""
    try:
        theme_name = get_configured_textual_theme(cfg)
        app.theme = theme_name
    except Exception:
        pass
