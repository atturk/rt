"""
rt.storage.fs
Operazioni sui file delle lezioni con due backend scelti percorso per percorso.

- storage "folder" (layout storico, e sempre quando il DB è spento): ogni funzione delega
  a os/open/shutil, comportamento identico a prima.
- storage "db": la lezione non ha una cartella. Il suo path (Lesson.path) resta
  l'identificativo, ma i file sotto quel percorso sono righe di lesson_files: i testi e i
  metadati nel campo content, i media (audio, immagini, video, PDF) come file reali in
  <cartella dati>/media con il solo percorso nel DB, come fa Anki.

Le funzioni hanno la stessa firma e le stesse eccezioni delle omonime di os/os.path/shutil,
così i moduli della pipeline cambiano solo il prefisso (open -> fs.open, os.path.isfile ->
fs.isfile...). Un percorso appartiene a una lezione "db" se esso o un suo antenato è il path
di una Lesson con storage "db"; i nomi interni perdono il prefisso storico _state/.
"""
import hashlib
import io
import os
import shutil
import threading
import time
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional, Tuple

from contextlib import contextmanager

STORAGE_FOLDER = "folder"
STORAGE_DB = "db"
LEGACY_STATE_PREFIX = "_state/"
MEDIA_EXTENSIONS = {
    # audio
    ".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg", ".oga", ".opus", ".wma", ".aiff", ".aif",
    ".caf", ".amr", ".webm",
    # video
    ".mp4", ".mov", ".mkv", ".avi", ".m4v",
    # immagini e documenti sorgente
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".svg", ".heic", ".pdf",
}
# Profondità massima di un file dentro una lezione (es. assets/images/x.png = 3).
_MAX_DEPTH = 6

_lock = threading.RLock()
# url del DB -> {path della lezione -> id}: solo risultati positivi (una lezione "db" resta
# tale finché non viene cancellata da questo processo, che svuota la voce).
_known: Dict[str, Dict[str, int]] = {}


@dataclass(frozen=True)
class DbTarget:
    db: object
    lesson_id: int
    lesson_path: str
    rel: str  # "" = radice della lezione


# ---------------------------------------------------------------- risoluzione

def _norm(path: str) -> str:
    return os.path.realpath(os.path.abspath(os.path.expanduser(os.fspath(path))))


def _database():
    from rt.db.engine import get_database
    return get_database()


def _ancestors(p: str) -> List[str]:
    out = [p]
    for _ in range(_MAX_DEPTH):
        parent = os.path.dirname(out[-1])
        if parent == out[-1]:
            break
        out.append(parent)
    return out


def _rel(lesson_path: str, p: str) -> str:
    if p == lesson_path:
        return ""
    rel = os.path.relpath(p, lesson_path).replace(os.sep, "/")
    if rel.startswith(LEGACY_STATE_PREFIX):
        rel = rel[len(LEGACY_STATE_PREFIX):]
    elif rel == LEGACY_STATE_PREFIX.rstrip("/"):
        rel = ""
    return rel


def resolve(path) -> Optional[DbTarget]:
    """DbTarget se il percorso appartiene a una lezione con storage "db", altrimenti None."""
    db = _database()
    if db is None:
        return None
    p = _norm(path)
    candidates = _ancestors(p)
    with _lock:
        known = _known.setdefault(db.url, {})
        for c in candidates:
            if c in known:
                return DbTarget(db, known[c], c, _rel(c, p))
    from sqlalchemy import select
    from rt.db.models import Lesson
    from rt.db.session import read_scope
    with read_scope(db) as s:
        rows = s.execute(select(Lesson.id, Lesson.path).where(
            Lesson.storage == STORAGE_DB, Lesson.path.in_(candidates))).all()
    if not rows:
        return None
    lesson_id, lesson_path = max(rows, key=lambda r: len(r[1]))
    with _lock:
        _known.setdefault(db.url, {})[lesson_path] = lesson_id
    return DbTarget(db, lesson_id, lesson_path, _rel(lesson_path, p))


def forget(lesson_path: str) -> None:
    """Svuota la cache per una lezione (cancellata o riportata a cartella)."""
    p = _norm(lesson_path)
    with _lock:
        for known in _known.values():
            known.pop(p, None)


def reset_cache() -> None:
    with _lock:
        _known.clear()


def is_db_lesson(lesson_dir) -> bool:
    t = resolve(lesson_dir)
    return t is not None and t.rel == ""


def is_db_path(path) -> bool:
    return resolve(path) is not None


def is_media_name(name: str) -> bool:
    return os.path.splitext(name)[1].lower() in MEDIA_EXTENSIONS


# ---------------------------------------------------------------- cartelle dati

def data_dir(db=None) -> str:
    """Cartella dati di RT: quella del file SQLite, altrimenti ~/.rt."""
    from rt.db.engine import sqlite_file
    db = db or _database()
    path = sqlite_file(db.url) if db is not None else None
    if path:
        return os.path.dirname(os.path.abspath(path))
    return os.path.join(os.path.expanduser("~"), ".rt")


def media_dir(db=None) -> str:
    return os.path.join(data_dir(db), "media")


def lock_path(path) -> str:
    """Percorso reale per un file di lock: invariato per le cartelle, in <dati>/locks per
    le lezioni "db" (che non hanno una cartella dove crearlo)."""
    t = resolve(path)
    if t is None:
        return os.fspath(path)
    digest = hashlib.sha1(f"{t.lesson_path}/{t.rel}".encode("utf-8")).hexdigest()[:20]
    base = os.path.basename(os.fspath(path)).lstrip(".") or "lock"
    target = os.path.join(data_dir(t.db), "locks", f"{digest}-{base}")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    return target


# ---------------------------------------------------------------- righe lesson_files

def _session(t: DbTarget):
    """Sessione per scrivere: si unisce alla transazione già aperta nel thread, se c'è."""
    from rt.db.session import joined_scope
    return joined_scope(t.db)


def _reader(t: DbTarget):
    from rt.db.session import read_scope
    return read_scope(t.db)


def _row(s, t: DbTarget, name: Optional[str] = None):
    from sqlalchemy import select
    from rt.db.models import LessonFile
    return s.scalar(select(LessonFile).where(LessonFile.lesson_id == t.lesson_id,
                                             LessonFile.name == (t.rel if name is None else name)))


def _names(t: DbTarget) -> List[str]:
    from sqlalchemy import select
    from rt.db.models import LessonFile
    with _reader(t) as s:
        return list(s.scalars(select(LessonFile.name).where(LessonFile.lesson_id == t.lesson_id)))


def _has_prefix(t: DbTarget, prefix: str) -> bool:
    from sqlalchemy import select
    from rt.db.models import LessonFile
    with _reader(t) as s:
        return s.scalar(select(LessonFile.id).where(
            LessonFile.lesson_id == t.lesson_id,
            LessonFile.name.startswith(prefix + "/", autoescape=True)).limit(1)) is not None


def _media_abspath(t: DbTarget, media_path: str) -> str:
    return os.path.join(media_dir(t.db), media_path)


def _new_media_name(s, t: DbTarget, rel: str) -> str:
    from sqlalchemy import select
    from rt.db.models import LessonFile
    base = os.path.basename(rel) or "file"
    stem, ext = os.path.splitext(base)
    taken = set(s.scalars(select(LessonFile.media_path).where(LessonFile.lesson_id == t.lesson_id,
                                                              LessonFile.media_path.is_not(None))))
    candidate, n = f"L{t.lesson_id}_{base}", 2
    while candidate in taken or os.path.exists(_media_abspath(t, candidate)):
        candidate, n = f"L{t.lesson_id}_{stem}_{n}{ext}", n + 1
    return candidate


def _store(t: DbTarget, data: bytes) -> None:
    """Scrive (crea o sostituisce) il file t.rel con il contenuto dato."""
    from rt.db.models import LessonFile
    sha = hashlib.sha256(data).hexdigest()
    now = time.time()
    with _session(t) as s:
        row = _row(s, t)
        if row is None:
            row = LessonFile(lesson_id=t.lesson_id, name=t.rel)
            s.add(row)
        if is_media_name(t.rel):
            if not row.media_path:
                row.media_path = _new_media_name(s, t, t.rel)
            target = _media_abspath(t, row.media_path)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            tmp = target + ".tmp"
            with io.open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, target)
            row.content = None
        else:
            row.media_path = None
            row.content = data
        row.size, row.sha256, row.mtime = len(data), sha, now


def _register_media_file(t: DbTarget, real_file: str, move: bool) -> None:
    """Porta un file reale (anche grande) nella cartella media senza caricarlo in memoria."""
    from rt.db.models import LessonFile
    h = hashlib.sha256()
    with io.open(real_file, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    size = os.path.getsize(real_file)
    with _session(t) as s:
        row = _row(s, t)
        if row is None:
            row = LessonFile(lesson_id=t.lesson_id, name=t.rel)
            s.add(row)
        if not row.media_path:
            row.media_path = _new_media_name(s, t, t.rel)
        target = _media_abspath(t, row.media_path)
        if os.path.abspath(real_file) != os.path.abspath(target):
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if move:
                shutil.move(real_file, target)
            else:
                shutil.copy2(real_file, target)
        row.content = None
        row.size, row.sha256, row.mtime = size, h.hexdigest(), time.time()


def _load(t: DbTarget) -> bytes:
    with _reader(t) as s:
        row = _row(s, t)
        if row is None:
            raise FileNotFoundError(2, "No such file or directory", os.path.join(t.lesson_path, t.rel))
        if row.media_path:
            media = _media_abspath(t, row.media_path)
        else:
            return bytes(row.content or b"")
    with io.open(media, "rb") as f:
        return f.read()


class _DbWriter(io.BytesIO):
    """Buffer che al close() salva il contenuto nel DB (o nella cartella media)."""

    def __init__(self, target: DbTarget, initial: bytes = b"", append: bool = False):
        super().__init__(initial)
        self._target = target
        self.name = os.path.join(target.lesson_path, target.rel)
        if append:
            self.seek(0, io.SEEK_END)

    def close(self):
        if not self.closed:
            try:
                _store(self._target, self.getvalue())
            finally:
                super().close()


# ---------------------------------------------------------------- API compatibile con os

def open(path, mode: str = "r", buffering: int = -1, encoding: Optional[str] = None,
         errors: Optional[str] = None, newline: Optional[str] = None):
    t = resolve(path)
    if t is None:
        return io.open(path, mode, buffering, encoding, errors, newline)
    if t.rel == "" or (not _is_file(t) and _has_prefix(t, t.rel)):
        raise IsADirectoryError(21, "Is a directory", os.fspath(path))
    binary = "b" in mode
    kind = mode.replace("b", "").replace("t", "")
    if kind == "r":
        data = _load(t)
        if binary:
            return _named(io.BytesIO(data), t)
        text = data.decode(encoding or "utf-8", errors or "strict")
        if newline is None:
            text = text.replace("\r\n", "\n").replace("\r", "\n")
        return _named(io.StringIO(text), t)
    if kind in ("w", "a", "x", "r+", "w+", "a+"):
        if kind == "x" and _is_file(t):
            raise FileExistsError(17, "File exists", os.fspath(path))
        initial = b""
        if kind in ("a", "a+", "r+"):
            try:
                initial = _load(t)
            except FileNotFoundError:
                if kind == "r+":
                    raise
        writer = _DbWriter(t, initial, append=kind.startswith("a"))
        if binary:
            return writer
        return io.TextIOWrapper(writer, encoding=encoding or "utf-8", errors=errors,
                                newline=newline, write_through=True)
    raise ValueError(f"modo non supportato per una lezione nel database: {mode!r}")


def _named(buf, t: DbTarget):
    buf.name = os.path.join(t.lesson_path, t.rel)
    return buf


def _is_file(t: DbTarget) -> bool:
    if t.rel == "":
        return False
    with _reader(t) as s:
        return _row(s, t) is not None


def exists(path) -> bool:
    t = resolve(path)
    if t is None:
        return os.path.exists(path)
    return t.rel == "" or _is_file(t) or _has_prefix(t, t.rel)


def isfile(path) -> bool:
    t = resolve(path)
    if t is None:
        return os.path.isfile(path)
    return _is_file(t)


def isdir(path) -> bool:
    t = resolve(path)
    if t is None:
        return os.path.isdir(path)
    return t.rel == "" or (not _is_file(t) and _has_prefix(t, t.rel))


def listdir(path) -> List[str]:
    """Come os.listdir. Su una cartella reale aggiunge le lezioni "db" che hanno lì il loro
    percorso, così chi scandisce lessons_root le vede come sottocartelle."""
    t = resolve(path)
    if t is None:
        entries = os.listdir(path)
        extra = [os.path.basename(p) for p in db_lessons_under(path)]
        return entries + [e for e in extra if e not in entries]
    if not isdir(path):
        raise NotADirectoryError(20, "Not a directory", os.fspath(path))
    prefix = t.rel + "/" if t.rel else ""
    children = set()
    for name in _names(t):
        if prefix and not name.startswith(prefix):
            continue
        children.add(name[len(prefix):].split("/", 1)[0])
    return sorted(children)


def makedirs(path, mode: int = 0o777, exist_ok: bool = False) -> None:
    if resolve(path) is None:
        os.makedirs(path, mode=mode, exist_ok=exist_ok)
    # Lezione "db": le cartelle sono implicite nei nomi dei file.


def remove(path) -> None:
    t = resolve(path)
    if t is None:
        os.remove(path)
        return
    media = None
    with _session(t) as s:
        row = _row(s, t)
        if row is None:
            raise FileNotFoundError(2, "No such file or directory", os.fspath(path))
        media = row.media_path
        s.delete(row)
    if media:
        try:
            os.remove(_media_abspath(t, media))
        except FileNotFoundError:
            pass


unlink = remove


def replace(src, dst) -> None:
    ts, td = resolve(src), resolve(dst)
    if ts is None and td is None:
        os.replace(src, dst)
        return
    if ts is not None and ts.rel == "":
        _rename_lesson(ts, dst)
        return
    if ts is not None and td is not None and ts.lesson_id == td.lesson_id \
            and is_media_name(ts.rel) == is_media_name(td.rel):
        _rename_row(ts, td, src)
        return
    copyfile(src, dst)
    remove(src)


rename = replace


def _rename_lesson(ts: DbTarget, dst) -> None:
    """Rinomina o sposta una lezione "db": cambia solo il suo percorso nel DB."""
    from rt.db.models import Lesson
    new_path = _norm(dst)
    if exists(dst):
        raise FileExistsError(17, "File exists", os.fspath(dst))
    with _session(ts) as s:
        lesson = s.get(Lesson, ts.lesson_id)
        lesson.path = new_path
        lesson.folder_name = os.path.basename(new_path)
    forget(ts.lesson_path)
    with _lock:
        _known.setdefault(ts.db.url, {})[new_path] = ts.lesson_id


def _rename_row(ts: DbTarget, td: DbTarget, src) -> None:
    old_media = None
    with _session(ts) as s:
        row = _row(s, ts)
        if row is None:
            raise FileNotFoundError(2, "No such file or directory", os.fspath(src))
        dst_row = _row(s, td)
        if dst_row is not None and dst_row.id != row.id:
            old_media = dst_row.media_path
            s.delete(dst_row)
            s.flush()
        row.name = td.rel
        row.mtime = time.time()
    if old_media:
        try:
            os.remove(_media_abspath(ts, old_media))
        except FileNotFoundError:
            pass


def getmtime(path) -> float:
    t = resolve(path)
    if t is None:
        return os.path.getmtime(path)
    with _reader(t) as s:
        row = _row(s, t)
        if row is None:
            if isdir(path):
                return time.time()
            raise FileNotFoundError(2, "No such file or directory", os.fspath(path))
        return float(row.mtime or 0.0)


def getsize(path) -> int:
    t = resolve(path)
    if t is None:
        return os.path.getsize(path)
    with _reader(t) as s:
        row = _row(s, t)
        if row is None:
            raise FileNotFoundError(2, "No such file or directory", os.fspath(path))
        return int(row.size or 0)


def sha256(path) -> str:
    """sha256 del contenuto, "" se il file non c'è."""
    t = resolve(path)
    if t is None:
        if not os.path.isfile(path):
            return ""
        h = hashlib.sha256()
        with io.open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    with _reader(t) as s:
        row = _row(s, t)
        return row.sha256 if row is not None else ""


def rmtree(path, ignore_errors: bool = False) -> None:
    t = resolve(path)
    if t is None:
        shutil.rmtree(path, ignore_errors=ignore_errors)
        return
    from sqlalchemy import select
    from rt.db.models import LessonFile
    media: List[str] = []
    with _session(t) as s:
        stmt = select(LessonFile).where(LessonFile.lesson_id == t.lesson_id)
        if t.rel:
            stmt = stmt.where(LessonFile.name.startswith(t.rel + "/", autoescape=True))
        rows = list(s.scalars(stmt))
        if not rows and t.rel and not ignore_errors:
            raise FileNotFoundError(2, "No such file or directory", os.fspath(path))
        for row in rows:
            if row.media_path:
                media.append(row.media_path)
            s.delete(row)
    for m in media:
        try:
            os.remove(_media_abspath(t, m))
        except FileNotFoundError:
            pass


def copyfile(src, dst) -> None:
    """Copia src in dst; ognuno dei due può essere reale o nel DB."""
    ts, td = resolve(src), resolve(dst)
    if ts is None and td is None:
        shutil.copyfile(src, dst)
        return
    if td is not None and ts is None and is_media_name(td.rel):
        _register_media_file(td, os.fspath(src), move=False)
        return
    if td is None:
        real = real_path(src)
        if real is not None:
            shutil.copyfile(real, dst)
            return
        with io.open(dst, "wb") as f:
            f.write(_load(ts))
        return
    if ts is not None and is_media_name(ts.rel):
        real = real_path(src)
        if real is not None and is_media_name(td.rel):
            _register_media_file(td, real, move=False)
            return
    _store(td, _load(ts) if ts is not None else _read_real(src))


copy = copy2 = copyfile


def _read_real(path) -> bytes:
    with io.open(path, "rb") as f:
        return f.read()


def move(src, dst) -> None:
    ts, td = resolve(src), resolve(dst)
    if ts is None and td is None:
        shutil.move(src, dst)
        return
    if ts is None and td is not None and is_media_name(td.rel):
        _register_media_file(td, os.fspath(src), move=True)
        return
    replace(src, dst)


def walk(top) -> Iterator[Tuple[str, List[str], List[str]]]:
    t = resolve(top)
    if t is None:
        yield from os.walk(top)
        return
    dirs, files = [], []
    for name in listdir(top):
        (dirs if isdir(os.path.join(top, name)) else files).append(name)
    yield os.fspath(top), dirs, files
    for d in dirs:
        yield from walk(os.path.join(top, d))


def real_path(path) -> Optional[str]:
    """Percorso di un file reale leggibile da programmi esterni (ffmpeg, player, ASR): il
    percorso stesso per le cartelle, il file nella cartella media per i media "db". None per
    un testo "db" (usa materialize) o se il file non c'è."""
    t = resolve(path)
    if t is None:
        return os.fspath(path) if os.path.exists(path) else None
    with _reader(t) as s:
        row = _row(s, t)
        if row is None or not row.media_path:
            return None
        return _media_abspath(t, row.media_path)


@contextmanager
def materialize(path) -> Iterator[str]:
    """Percorso reale temporaneo con il contenuto di path, per chi ha bisogno di un file."""
    real = real_path(path)
    if real is not None:
        yield real
        return
    import tempfile
    t = resolve(path)
    if t is None:
        raise FileNotFoundError(2, "No such file or directory", os.fspath(path))
    suffix = os.path.splitext(t.rel)[1]
    fd, tmp = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(_load(t))
        yield tmp
    finally:
        try:
            os.remove(tmp)
        except FileNotFoundError:
            pass


@contextmanager
def external_output(path) -> Iterator[str]:
    """Percorso reale dove un programma esterno può scrivere il file path; all'uscita senza
    errori il file entra nella lezione (cartella media per le lezioni "db")."""
    t = resolve(path)
    if t is None:
        yield os.fspath(path)
        return
    import tempfile
    tmp_dir = tempfile.mkdtemp(prefix="rt-out-")
    tmp = os.path.join(tmp_dir, os.path.basename(t.rel) or "out")
    try:
        yield tmp
        if os.path.isfile(tmp):
            if is_media_name(t.rel):
                _register_media_file(t, tmp, move=True)
            else:
                _store(t, _read_real(tmp))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------- lezioni

def db_lessons_under(root) -> List[str]:
    """Percorsi delle lezioni "db" figlie dirette di root."""
    db = _database()
    if db is None or not root:
        return []
    from sqlalchemy import select
    from rt.db.models import Lesson
    from rt.db.session import read_scope
    r = _norm(root)
    with read_scope(db) as s:
        paths = list(s.scalars(select(Lesson.path).where(Lesson.storage == STORAGE_DB,
                                                         Lesson.path.startswith(r + os.sep, autoescape=True))))
    return sorted(p for p in paths if os.path.dirname(p) == r)


def lesson_files(lesson_dir) -> List[Dict[str, object]]:
    """Elenco dei file di una lezione "db" (nome, dimensione, sha, media)."""
    t = resolve(lesson_dir)
    if t is None:
        return []
    from sqlalchemy import select
    from rt.db.models import LessonFile
    with _reader(t) as s:
        rows = s.scalars(select(LessonFile).where(LessonFile.lesson_id == t.lesson_id).order_by(LessonFile.name))
        return [{"name": r.name, "size": r.size, "sha256": r.sha256, "media_path": r.media_path,
                 "mtime": r.mtime} for r in rows]


def create_db_lesson(lesson_dir) -> str:
    """Registra una nuova lezione con storage "db" (nessuna cartella creata); restituisce il
    suo percorso normalizzato. Se esiste già una Lesson con quel percorso la converte."""
    db = _database()
    if db is None:
        raise RuntimeError("Il database è spento: una lezione nel database richiede il DB.")
    from rt.db.repositories import LessonRepository
    from rt.db.session import session_scope
    with session_scope(db) as s:
        lesson = LessonRepository(s).get_or_create(os.fspath(lesson_dir))
        lesson.storage = STORAGE_DB
        path, lesson_id = lesson.path, lesson.id
    with _lock:
        _known.setdefault(db.url, {})[path] = lesson_id
    return path


def new_lessons_use_db() -> bool:
    """Le nuove lezioni nascono nel DB quando il DB è attivo, salvo impostazione
    storage.new_lessons = "folder" (tabella settings)."""
    db = _database()
    if db is None:
        return False
    from rt.db.repositories import SettingRepository
    from rt.db.session import session_scope
    with session_scope(db) as s:
        value = SettingRepository(s).get("storage.new_lessons")
    return str(value or STORAGE_DB) != STORAGE_FOLDER
