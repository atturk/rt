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


def _save(lesson_dir: str, sources: list[Source]) -> None:
    path = lesson_path(lesson_dir, "sources.json")
    with fs.open(path + ".tmp", "w", encoding="utf-8") as stream:
        json.dump([s.model_dump() for s in sources], stream, ensure_ascii=False, indent=2)
    fs.replace(path + ".tmp", path)


@lesson_locked
def load_sources(lesson_dir: str) -> list[Source]:
    """Crea soltanto il registro se assente; non modifica i file storici."""
    path = lesson_path(lesson_dir, "sources.json")
    if fs.isfile(path):
        with fs.open(path, encoding="utf-8") as stream:
            return [Source.model_validate(item) for item in json.load(stream)]
    info = read_info_yaml(lesson_path(lesson_dir, "info.yaml"))
    audio = info.get("file_audio")
    sources = []
    if audio:
        sources.append(Source(
            id="src_000001", tipo="audio", file=audio,
            impronta=compute_file_sha256(os.path.join(lesson_dir, audio)),
            aggiunta_il=datetime.now(timezone.utc).isoformat(), ordine=1,
        ))
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
    return source


@lesson_locked
def remove_source(lesson_dir: str, source_id: str) -> None:
    """Toglie dal registro; conserva la copia immutabile per l'annullamento."""
    sources = load_sources(lesson_dir)
    remaining = [s for s in sources if s.id != source_id]
    if len(remaining) == len(sources):
        raise KeyError(source_id)
    for index, item in enumerate(remaining, 1):
        item.ordine = index
    _save(lesson_dir, remaining)
