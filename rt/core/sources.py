"""Registro ordinato delle fonti immutabili, comune a cartelle e lezioni nel DB."""
import json
import os
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from rt.core.idempotency import compute_file_sha256
from rt.core.lesson_paths import lesson_path
from rt.core.state import read_info_yaml
from rt.core.lesson_lock import lesson_locked
from rt.storage import fs


class Source(BaseModel):
    id: str
    tipo: Literal["audio", "appunti", "materiale"]
    file: str
    impronta: str
    aggiunta_il: str
    ordine: int = Field(ge=1)
    rimossa_il: str | None = None


def _save(lesson_dir: str, sources: list[Source]) -> None:
    path = lesson_path(lesson_dir, "sources.json")
    # Le scritture delle fonti attive (aggiunta e riordino) conservano le tolte.
    if fs.isfile(path):
        with fs.open(path, encoding="utf-8") as stream:
            removed = [Source.model_validate(item) for item in json.load(stream)
                       if item.get("rimossa_il") and item["id"] not in {s.id for s in sources}]
        sources = [*sources, *removed]
    with fs.open(path + ".tmp", "w", encoding="utf-8") as stream:
        json.dump([s.model_dump() for s in sources], stream, ensure_ascii=False, indent=2)
    fs.replace(path + ".tmp", path)


@lesson_locked
def load_sources(lesson_dir: str, *, include_removed: bool = False) -> list[Source]:
    """Crea soltanto il registro se assente; non modifica i file storici.
    Un registro vuoto non si salva: durante il setup info.yaml non ha ancora l'audio, e un
    registro vuoto scritto allora lo avrebbe nascosto per sempre (lo si ricostruisce qui)."""
    path = lesson_path(lesson_dir, "sources.json")
    info = read_info_yaml(lesson_path(lesson_dir, "info.yaml"))
    audio = info.get("file_audio")
    if fs.isfile(path):
        with fs.open(path, encoding="utf-8") as stream:
            items = json.load(stream)
        if items or not audio or not fs.isfile(os.path.join(lesson_dir, audio)):
            return [Source.model_validate(item) for item in items
                    if include_removed or not item.get("rimossa_il")]
    sources = []
    if audio:
        sources.append(Source(
            id="src_000001", tipo="audio", file=audio,
            impronta=compute_file_sha256(os.path.join(lesson_dir, audio)),
            aggiunta_il=datetime.now(timezone.utc).isoformat(), ordine=1,
        ))
    if sources:
        _save(lesson_dir, sources)
    return sources


@lesson_locked
def add_source(lesson_dir: str, tipo: Literal["audio", "appunti", "materiale"],
               filename: str, content: bytes | None, ordine: int | None = None,
               source_path: str | None = None) -> Source:
    """Aggiunge una copia privata: nessuna operazione sovrascrive una fonte.
    source_path (file locale, per i caricamenti grandi) si copia senza leggerlo in memoria."""
    if tipo not in ("audio", "appunti", "materiale"):
        raise ValueError("Tipo di fonte non valido")
    sources = load_sources(lesson_dir)
    from rt.core.source_selection import selection
    previous_primary = selection(lesson_dir)["principale"]
    position = len(sources) + 1 if ordine is None else ordine
    if not 1 <= position <= len(sources) + 1:
        raise ValueError("Posizione della fonte non valida")
    name = os.path.basename(filename)
    if not name or name in (".", "..") or "\\" in name:
        raise ValueError("Nome della fonte non valido")
    sid = "src_" + uuid4().hex
    relative = os.path.join("sources", sid, name)
    path = os.path.join(lesson_dir, relative)
    fs.makedirs(os.path.dirname(path), exist_ok=True)
    if source_path is not None:
        fs.copyfile(source_path, path)
    else:
        with fs.open(path, "wb") as stream:
            stream.write(content)
    source = Source(id=sid, tipo=tipo, file=relative,
                    impronta=compute_file_sha256(path),
                    aggiunta_il=datetime.now(timezone.utc).isoformat(), ordine=position)
    sources.insert(position - 1, source)
    for index, item in enumerate(sources, 1):
        item.ordine = index
    _save(lesson_dir, sources)
    from rt.pipeline.source_update import _read_state, _write_state
    state = _read_state(lesson_dir)
    if (tipo == "audio" and not state.get("primary_explicit")
            and not any(s.tipo == "materiale" for s in sources)
            and not any(s.tipo == "audio" and s.id != source.id for s in sources)):
        state["principale"] = source.id
        _write_state(lesson_dir, state)
    elif "principale" not in state:
        state["principale"] = previous_primary or source.id
        _write_state(lesson_dir, state)
    return source


@lesson_locked
def remove_source(lesson_dir: str, source_id: str) -> None:
    """Segna la fonte come tolta; registro e file restano disponibili alle versioni."""
    sources = load_sources(lesson_dir, include_removed=True)
    source = next((s for s in sources if s.id == source_id and not s.rimossa_il), None)
    if source is None:
        raise KeyError(source_id)
    source.rimossa_il = datetime.now(timezone.utc).isoformat()
    for index, item in enumerate((s for s in sources if not s.rimossa_il), 1):
        item.ordine = index
    _save(lesson_dir, sources)
