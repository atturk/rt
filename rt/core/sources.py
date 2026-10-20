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


class SourcePart(BaseModel):
    nome: str
    durata: str | None = None
    durata_s: float | None = None


def format_source_duration(seconds: float | None) -> str:
    if seconds is None:
        return ""
    m = round(seconds / 60)
    h = m // 60
    rem = m % 60
    if h > 0:
        return f"{h} h {rem} min" if rem > 0 else f"{h} h"
    return f"{m} min"


class Source(BaseModel):
    id: str
    tipo: Literal["audio", "appunti", "materiale"]
    file: str
    impronta: str
    aggiunta_il: str
    ordine: int = Field(ge=1)
    rimossa_il: str | None = None
    parti: list[SourcePart] | None = None
    pagine: list[int] | None = None
    estrai: Literal['testo', 'immagini'] | None = None
    uso: Literal['contesto', 'integra'] | None = None


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
               source_path: str | None = None,
               parti: list[SourcePart] | list[dict] | None = None,
               pagine=None, estrai=None, uso=None) -> Source:
    """Aggiunge una copia privata: nessuna operazione sovrascrive una fonte.
    source_path (file locale, per i caricamenti grandi) si copia senza leggerlo in memoria."""
    if tipo not in ("audio", "appunti", "materiale"):
        raise ValueError("Tipo di fonte non valido")
    from rt.core.source_options import parse_pages, default_extraction
    if estrai not in (None, 'testo', 'immagini') or uso not in (None, 'guida', 'contesto', 'integra'):
        raise ValueError('Opzioni della fonte non valide')
    if tipo == 'materiale':
        from rt.core.materials import page_count
        if pagine is not None:
            if source_path is not None:
                from rt.core.archive import find
                cached = find(compute_file_sha256(source_path))
                total = (cached or {}).get('pagine_totali') or page_count(source_path)
            else:
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=os.path.splitext(filename)[1]) as tmp:
                    tmp.write(content)
                    tmp.flush()
                    total = page_count(tmp.name)
            pagine = parse_pages(pagine, total)
        estrai = estrai or default_extraction(filename)
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
    from rt.core.archive import find, original_path, register_file, file_type
    upload_sha = compute_file_sha256(path)
    archived = find(upload_sha) if tipo == 'audio' else None
    if archived and fs.isfile(original_path(archived['impronta'])):
        relative = os.path.join('sources', sid, os.path.splitext(name)[0] + archived['estensione'])
        cached_path = os.path.join(lesson_dir, relative)
        if cached_path != path:
            fs.remove(path)
        fs.copyfile(original_path(archived['impronta']), cached_path)
        path = cached_path
    if tipo == "audio" and not archived:
        from rt.pipeline.setup import transcode_audio_for_storage, EFFICIENT_AUDIO_EXTENSIONS
        base_ext = os.path.splitext(name)[1].lower()
        if base_ext not in EFFICIENT_AUDIO_EXTENSIONS:
            converted_name = os.path.splitext(name)[0] + ".m4a"
            converted_relative = os.path.join("sources", sid, converted_name)
            converted_path = os.path.join(lesson_dir, converted_relative)
            transcode_ok = False
            with fs.materialize(path) as mat_in, fs.external_output(converted_path) as ext_out:
                if transcode_audio_for_storage(mat_in, ext_out):
                    transcode_ok = True
            if transcode_ok:
                fs.remove(path)
                relative = converted_relative
                path = converted_path
    parsed_parts = [SourcePart.model_validate(p) for p in parti] if parti else None
    source = Source(id=sid, tipo=tipo, file=relative,
                    impronta=compute_file_sha256(path),
                    aggiunta_il=datetime.now(timezone.utc).isoformat(), ordine=position,
                    parti=parsed_parts, pagine=pagine, estrai=estrai, uso='contesto' if uso == 'guida' else uso)
    if tipo != 'appunti':
        register_file(path, nome=name, tipo=file_type(path, tipo), sha=source.impronta, alias=[upload_sha])
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
    if uso == 'guida':
        from rt.core.source_selection import set_primary
        set_primary(lesson_dir, source.id)
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


@lesson_locked
def update_source(lesson_dir, source_id, **options):
    from rt.core.source_options import parse_pages
    sources = load_sources(lesson_dir)
    source = next((s for s in sources if s.id == source_id), None)
    if source is None:
        raise KeyError(source_id)
    if 'pagine' in options:
        from rt.core.materials import page_count
        source.pagine = parse_pages(options['pagine'], page_count(os.path.join(lesson_dir, source.file)))
    if 'estrai' in options:
        if options['estrai'] not in (None, 'testo', 'immagini'):
            raise ValueError('Estrai non valido')
        source.estrai = options['estrai']
    if 'uso' in options:
        if options['uso'] not in (None, 'guida', 'contesto', 'integra'):
            raise ValueError('Uso non valido')
        source.uso = 'contesto' if options['uso'] == 'guida' else options['uso']
    _save(lesson_dir, sources)
    from rt.pipeline.source_update import _read_state, _write_state
    state = _read_state(lesson_dir)
    state['used'] = [sid for sid in state.get('used', []) if sid != source_id]
    state.get('sources', {}).pop(source_id, None)
    _write_state(lesson_dir, state)
    if options.get('uso') == 'guida':
        from rt.core.source_selection import set_primary
        set_primary(lesson_dir, source_id)
    return source
