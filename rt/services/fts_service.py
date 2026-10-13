"""
rt.services.fts_service
Indice di ricerca full-text SQLite FTS5 per le lezioni di RT (AP1).
Dato derivato creato all'avvio con CREATE VIRTUAL TABLE IF NOT EXISTS e riallineato a ogni
ricerca: una lezione si reindicizza quando cambia la sua impronta (bozza, decisioni, metadati) e
si toglie quando viene eliminata.
"""
from typing import Any, Dict, List, Optional
from sqlalchemy import text

from rt.db.engine import get_database


def _get_db(db=None):
    if db is not None:
        return db
    return get_database()


def init_fts_table(db=None) -> None:
    """Crea la tabella virtuale FTS5 se non esiste."""
    database = _get_db(db)
    if database is None:
        return
    with database.engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS lessons_fts USING fts5(
                    lesson_id UNINDEXED,
                    unit_id UNINDEXED,
                    subject,
                    date,
                    title,
                    content,
                    tokenize='unicode61'
                )
                """
            )
        )


def index_lesson_units(lesson_id: int, path: str, subject: str, date: str, title: str, db=None) -> int:
    """Indicizza le unità di una singola lezione caricando la bozza risolta."""
    from rt.pipeline.ledger import load_resolved_draft

    database = _get_db(db)
    if database is None:
        return 0

    try:
        draft = load_resolved_draft(path)
        units = draft.units
    except Exception:
        units = []

    with database.engine.begin() as conn:
        conn.execute(
            text("DELETE FROM lessons_fts WHERE lesson_id = :lesson_id"),
            {"lesson_id": lesson_id},
        )
        count = 0
        for u in units:
            content = u.content or ""
            if not content.strip():
                continue
            conn.execute(
                text(
                    """
                    INSERT INTO lessons_fts (lesson_id, unit_id, subject, date, title, content)
                    VALUES (:lesson_id, :unit_id, :subject, :date, :title, :content)
                    """
                ),
                {
                    "lesson_id": lesson_id,
                    "unit_id": u.unit_id,
                    "subject": subject or "",
                    "date": date or "",
                    "title": u.title or title or "",
                    "content": content,
                },
            )
            count += 1
    return count


def reindex_all_lessons(db=None) -> int:
    """Ricostruisce l'indice FTS5 per tutte le lezioni nel DB."""
    from rt.db.models import Lesson
    from rt.db.session import read_scope
    from sqlalchemy import select

    database = _get_db(db)
    if database is None:
        return 0

    init_fts_table(database)

    with read_scope(database) as session:
        lessons = session.scalars(select(Lesson)).all()
        lesson_data = [
            (l.id, l.path, l.materia, l.data, l.titolo) for l in lessons
        ]

    total = 0
    for lid, lpath, lmat, ldat, ltit in lesson_data:
        total += index_lesson_units(lid, lpath, lmat, ldat, ltit, db=database)
    return total


def _init_state_table(database) -> None:
    """Impronta per lezione dell'ultimo indice: dato derivato come lessons_fts, niente migrazione."""
    with database.engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS lessons_fts_state "
                          "(lesson_id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL)"))


def _lesson_fingerprint(path: str, subject, date, title) -> str:
    """Stessa chiave della cache del testo risolto (bozza, verifiche, modifiche, decisioni)
    più i metadati indicizzati: cambia quando pipeline, aggiornamento o ripristino riscrivono la bozza."""
    import hashlib
    from rt.pipeline.ledger import _resolved_key
    try:
        key = repr(_resolved_key(path))
    except Exception:
        key = "missing"
    return hashlib.sha256(f"{key}|{subject}|{date}|{title}".encode("utf-8")).hexdigest()


def sync_fts_index(db=None) -> int:
    """Allinea l'indice alle lezioni: reindicizza quelle la cui impronta è cambiata e
    toglie quelle eliminate. Restituisce il numero di lezioni reindicizzate."""
    from rt.db.models import Lesson
    from rt.db.session import read_scope
    from sqlalchemy import select

    database = _get_db(db)
    if database is None:
        return 0
    init_fts_table(database)
    _init_state_table(database)
    with read_scope(database) as session:
        lessons = [(l.id, l.path, l.materia, l.data, l.titolo) for l in session.scalars(select(Lesson)).all()]
    with database.engine.begin() as conn:
        known = dict(conn.execute(text("SELECT lesson_id, fingerprint FROM lessons_fts_state")).fetchall())
        indexed = {int(r[0]) for r in conn.execute(text("SELECT DISTINCT lesson_id FROM lessons_fts")).fetchall()}
    current = {lid for lid, *_ in lessons}
    with database.engine.begin() as conn:
        for lid in (set(known) | indexed) - current:
            conn.execute(text("DELETE FROM lessons_fts WHERE lesson_id = :id"), {"id": lid})
            conn.execute(text("DELETE FROM lessons_fts_state WHERE lesson_id = :id"), {"id": lid})
    changed = 0
    for lid, lpath, lmat, ldat, ltit in lessons:
        fingerprint = _lesson_fingerprint(lpath, lmat, ldat, ltit)
        if known.get(lid) == fingerprint:
            continue
        index_lesson_units(lid, lpath, lmat, ldat, ltit, db=database)
        with database.engine.begin() as conn:
            conn.execute(text("INSERT OR REPLACE INTO lessons_fts_state (lesson_id, fingerprint) "
                              "VALUES (:id, :fp)"), {"id": lid, "fp": fingerprint})
        changed += 1
    return changed


def remove_lesson_from_index(lesson_id: int, db=None) -> None:
    database = _get_db(db)
    if database is None:
        return
    init_fts_table(database)
    _init_state_table(database)
    with database.engine.begin() as conn:
        conn.execute(text("DELETE FROM lessons_fts WHERE lesson_id = :id"), {"id": lesson_id})
        conn.execute(text("DELETE FROM lessons_fts_state WHERE lesson_id = :id"), {"id": lesson_id})


def ensure_fts_index(db=None) -> None:
    """Verifica e inizializza l'indice FTS5 e lo tiene allineato alle lezioni (impronta per lezione)."""
    database = _get_db(db)
    if database is None:
        return
    try:
        sync_fts_index(database)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Aggiornamento dell'indice di ricerca non riuscito")


def sanitize_fts5_query(query: str) -> str:
    """Pulisce la query per evitare errori di sintassi in SQLite FTS5."""
    cleaned = "".join(c if c.isalnum() or c.isspace() else " " for c in query)
    tokens = [t.strip() for t in cleaned.split() if t.strip()]
    if not tokens:
        return '""'
    return " ".join(f'"{t}"' for t in tokens)


def search_lessons_fts(
    query: str,
    subject: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 10,
    db=None,
) -> List[Dict[str, Any]]:
    """Cerca nel testo delle lezioni tramite SQLite FTS5 con filtri opzionali su materia e date."""
    database = _get_db(db)
    if database is None:
        return []

    ensure_fts_index(database)

    fts_query = sanitize_fts5_query(query)
    conditions = ["lessons_fts MATCH :fts_query"]
    params: Dict[str, Any] = {"fts_query": fts_query, "limit": max(1, min(limit, 50))}

    if subject and subject.strip():
        conditions.append("subject = :subject")
        params["subject"] = subject.strip().upper()

    if date_from and date_from.strip():
        conditions.append("date >= :date_from")
        params["date_from"] = date_from.strip()

    if date_to and date_to.strip():
        conditions.append("date <= :date_to")
        params["date_to"] = date_to.strip()

    where_clause = " AND ".join(conditions)

    sql = f"""
        SELECT
            lesson_id,
            unit_id,
            subject,
            date,
            title,
            snippet(lessons_fts, 5, '<b>', '</b>', '...', 24) AS snippet
        FROM lessons_fts
        WHERE {where_clause}
        LIMIT :limit
    """

    with database.engine.begin() as conn:
        rows = conn.execute(text(sql), params).fetchall()

    results = []
    for r in rows:
        results.append({
            "lesson_id": int(r[0]),
            "unit_id": str(r[1]),
            "subject": str(r[2] or ""),
            "date": str(r[3] or ""),
            "title": str(r[4] or ""),
            "snippet": str(r[5] or ""),
        })
    return results
