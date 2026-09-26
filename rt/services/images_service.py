"""
rt.services.images_service
Controlli sulla richiesta di immagini (job add_images) prima di accodarla: SearXNG configurato
e unità della ricerca web presenti nella scaletta.
"""
from typing import List, Optional


class ImagesError(ValueError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code


SEARXNG_MISSING = "La ricerca di immagini sul web richiede SearXNG: configuralo in Impostazioni."


def searxng_configured() -> bool:
    from rt.core.config import load_config
    return bool((getattr(load_config(), "searxng_base_url", None) or "").strip())


def check_web_search(lesson_dir: str, unit_ids: Optional[List[str]], mock: bool = False) -> None:
    """Solleva ImagesError se la ricerca web non si può fare: SearXNG mancante (salvo mock) o
    unità che la scaletta non ha."""
    if not mock and not searxng_configured():
        raise ImagesError(409, "searxng_not_configured", SEARXNG_MISSING)
    if unit_ids:
        from rt.pipeline.add_images import outline_unit_ids
        from rt.pipeline.outline import load_outline
        try:
            known = set(outline_unit_ids(load_outline(lesson_dir)))
        except Exception:
            raise ImagesError(409, "outline_missing", "La lezione non ha ancora una scaletta.")
        unknown = sorted(set(unit_ids) - known)
        if unknown:
            raise ImagesError(422, "validation_error", f"Unità inesistenti nella scaletta: {', '.join(unknown)}.")
