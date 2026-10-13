"""Misure delle fonti e riepilogo dell'ultimo aggiornamento riuscito."""
import os
import subprocess
from datetime import datetime, timezone
from pydantic import BaseModel
from typing import Literal

from rt.core.sources import Source, load_sources
from rt.core.lesson_paths import lesson_path
from rt.core.update_history import has_update_snapshot
from rt.pipeline.source_update import _read_state, _write_state, _duration, sources_pending
from rt.storage import fs


class SourceView(Source):
    nome: str
    durata_s: float | None = None
    pagine: int | None = None
    parole: int | None = None
    usata: bool


class LastUpdate(BaseModel):
    modo: Literal["extend", "rebuild"]
    unita_nuove: int
    unita_cambiate: int
    il: str


def sources_view(lesson_dir):
    from rt.core.source_selection import selection
    sources = load_sources(lesson_dir)
    state = _read_state(lesson_dir)
    used = state.get("used", [s.id for s in sources if s.id == "src_000001"]
                     if fs.isfile(lesson_path(lesson_dir, "segments.json")) else [])
    views = []
    for source in sources:
        values = source.model_dump()
        values.update(nome="Appunti" if source.tipo == "appunti" else os.path.basename(source.file),
                      usata=source.id in used)
        path = os.path.join(lesson_dir, source.file)
        if source.tipo == "appunti":
            with fs.open(path, encoding="utf-8") as stream:
                values["parole"] = len(stream.read().split())
        elif source.tipo == "materiale":
            from rt.core.materials import cached_pages, page_count
            cached = cached_pages(lesson_dir, source)
            values["pagine"] = len(cached) if cached is not None else page_count(path)
        elif source.tipo == "audio":
            values["durata_s"] = state.get("sources", {}).get(source.id, {}).get("duration")
            if values["durata_s"] is None:
                try:
                    values["durata_s"] = _duration(path)
                except (OSError, ValueError, subprocess.SubprocessError):
                    pass
        views.append(SourceView(**values))
    return {"sources": views, "has_unused_sources": sources_pending(lesson_dir),
            "can_undo": has_update_snapshot(lesson_dir),
            "ultimo_aggiornamento": state.get("ultimo_aggiornamento"),
            **selection(lesson_dir)}


def record_update_summary(lesson_dir, mode, old_outline, outline, selected):
    old = {u.id for m in old_outline.macro_sections for u in m.units} if old_outline else set()
    new = {u.id for m in outline.macro_sections for u in m.units}
    state = _read_state(lesson_dir)
    state["ultimo_aggiornamento"] = {"modo": mode, "unita_nuove": len(new - old),
        "unita_cambiate": len(set(selected) & old), "il": datetime.now(timezone.utc).isoformat()}
    changes = state.setdefault("unit_changed_at", {})
    for uid in (old | new if mode == "rebuild" else set(selected)):
        changes[uid] = state["ultimo_aggiornamento"]["il"]
    _write_state(lesson_dir, state)
