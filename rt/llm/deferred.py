"""
rt.llm.deferred
Cache persistente per richieste LLM in modalità batch differita (tabella llm_deferred)
e contesto di esecuzione corrente (job_id, batch_fallback).
"""
from __future__ import annotations

import contextlib
import contextvars
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Sequence, TypeVar

from sqlalchemy import delete as sa_delete, or_, select, update

from rt.db.engine import Database, get_database
from rt.db.models import Job, LlmDeferred, utcnow
from rt.db.repositories import normalize_lesson_path
from rt.db.session import read_scope, session_scope
from rt.llm.cancel import RunCancelled
from rt.llm.errors import DeferredCall, DeferredPhase

TItem = TypeVar("TItem")
TResult = TypeVar("TResult")

_CURRENT_JOB_ID: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("rt_deferred_job_id", default=None)
_BATCH_FALLBACK: contextvars.ContextVar[bool] = contextvars.ContextVar("rt_batch_fallback", default=False)


def current_job_id() -> Optional[str]:
    return _CURRENT_JOB_ID.get()


@contextlib.contextmanager
def use_job_id(job_id: Optional[str]) -> Iterator[None]:
    token = _CURRENT_JOB_ID.set(job_id)
    try:
        yield
    finally:
        _CURRENT_JOB_ID.reset(token)


def is_batch_fallback() -> bool:
    return bool(_BATCH_FALLBACK.get())


@contextlib.contextmanager
def use_batch_fallback(enabled: bool) -> Iterator[None]:
    token = _BATCH_FALLBACK.set(bool(enabled))
    try:
        yield
    finally:
        _BATCH_FALLBACK.reset(token)


@dataclass
class DeferredEntry:
    key: str
    job_id: Optional[str]
    lesson_path: Optional[str]
    batch_id: Optional[str]
    provider: str
    model: str
    credential_ref: Optional[str]
    base_url: Optional[str]
    request: Dict[str, Any]
    state: str
    response: Optional[Dict[str, Any]]
    error: Optional[str]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: LlmDeferred) -> "DeferredEntry":
        return cls(
            key=row.key,
            job_id=row.job_id,
            lesson_path=row.lesson_path,
            batch_id=row.batch_id,
            provider=row.provider,
            model=row.model,
            credential_ref=row.credential_ref,
            base_url=row.base_url,
            request=dict(row.request or {}),
            state=row.state,
            response=dict(row.response) if row.response is not None else None,
            error=row.error,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


def _resolve_db(db: Optional[Database]) -> Database:
    target = db if db is not None else get_database()
    if target is None:
        raise RuntimeError("Database non disponibile per la cache batch.")
    return target


def request_key(
    provider: str,
    model: str,
    messages: Any,
    schema: Any = None,
    params: Optional[Dict[str, Any]] = None,
) -> str:
    """Calcola la chiave sha256 deterministica della richiesta."""
    canonical = {
        "provider": (provider or "").lower().strip(),
        "model": (model or "").strip(),
        "messages": messages,
        "schema": schema,
        "params": params or {},
    }
    encoded = json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _normalize_messages_for_match(messages: Any) -> Any:
    """Normalizza i messaggi ignorando i blocchi cache_control aggiunti per specifici provider."""
    if not isinstance(messages, list):
        return messages
    normalized = []
    for msg in messages:
        if not isinstance(msg, dict):
            normalized.append(msg)
            continue
        content = msg.get("content")
        if isinstance(content, list) and all(isinstance(b, dict) and b.get("type") == "text" for b in content):
            norm_content: Any = "".join(str(b.get("text") or "") for b in content)
        else:
            norm_content = content
        normalized.append({"role": msg.get("role"), "content": norm_content})
    return normalized


def find_for_job(
    job_id: Optional[str],
    messages: Any,
    *,
    states: Sequence[str] = ("done", "submitted", "error"),
    db: Optional[Database] = None,
) -> Optional[DeferredEntry]:
    """Trova una chiamata differita già inviata/completata per questo job e stessi messaggi,
    indipendentemente dal modello o provider attualmente configurati per la fase."""
    if not job_id:
        return None
    target = _resolve_db(db)
    wanted = _normalize_messages_for_match(messages)
    priority = {"done": 0, "submitted": 1, "error": 2}
    with read_scope(target) as s:
        rows = list(
            s.scalars(
                select(LlmDeferred)
                .where(LlmDeferred.job_id == job_id, LlmDeferred.state.in_(list(states)))
                .order_by(LlmDeferred.updated_at.desc(), LlmDeferred.created_at.desc())
            )
        )
        matches = [
            row for row in rows
            if _normalize_messages_for_match((row.request or {}).get("messages")) == wanted
        ]
        if not matches:
            return None
        matches.sort(key=lambda r: priority.get(r.state, 99))
        return DeferredEntry.from_row(matches[0])


def get(key: str, *, db: Optional[Database] = None) -> Optional[DeferredEntry]:
    target = _resolve_db(db)
    with read_scope(target) as s:
        row = s.get(LlmDeferred, key)
        return DeferredEntry.from_row(row) if row is not None else None


def put_pending(
    key: str,
    *,
    job_id: Optional[str],
    lesson_path: Optional[str],
    provider: str,
    model: str,
    request: Dict[str, Any],
    credential_ref: Optional[str] = None,
    base_url: Optional[str] = None,
    db: Optional[Database] = None,
) -> DeferredEntry:
    """Registra una richiesta in stato 'pending' (o riusa/aggiorna la riga esistente)."""
    target = _resolve_db(db)
    norm_path = normalize_lesson_path(lesson_path) if lesson_path else None
    now = utcnow()
    with session_scope(target) as s:
        row = s.get(LlmDeferred, key)
        if row is None:
            row = LlmDeferred(
                key=key,
                job_id=job_id,
                lesson_path=norm_path,
                batch_id=None,
                provider=provider,
                model=model,
                credential_ref=credential_ref,
                base_url=base_url,
                request=request,
                state="pending",
                response=None,
                error=None,
                created_at=now,
                updated_at=now,
            )
            s.add(row)
        else:
            if row.state == "submitted" and row.batch_id:
                # Già inviata a un lotto aperto: mantieni batch_id e stato submitted, aggiorna il job se mancava.
                if job_id and not row.job_id:
                    row.job_id = job_id
                row.updated_at = now
            else:
                row.job_id = job_id if job_id is not None else row.job_id
                row.lesson_path = norm_path if norm_path is not None else row.lesson_path
                row.batch_id = None
                row.provider = provider
                row.model = model
                row.credential_ref = credential_ref
                row.base_url = base_url
                row.request = request
                row.state = "pending"
                row.response = None
                row.error = None
                row.updated_at = now
        s.flush()
        return DeferredEntry.from_row(row)


def mark_submitted(keys: Sequence[str], batch_id: str, *, db: Optional[Database] = None) -> int:
    """Segna le richieste indicate come 'submitted' associate a batch_id."""
    if not keys:
        return 0
    target = _resolve_db(db)
    now = utcnow()
    with session_scope(target) as s:
        res = s.execute(
            update(LlmDeferred)
            .where(LlmDeferred.key.in_(list(keys)))
            .values(state="submitted", batch_id=batch_id, updated_at=now)
        )
        return int(res.rowcount or 0)


def _extract_result_payload(item: Any) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Traduce un item di risultato (NormalizedResponse, BatchResultItem o dict) in (response_dict, error_str)."""
    if hasattr(item, "model_dump") and hasattr(item, "custom_id"):
        # BatchResultItem
        if getattr(item, "error", None):
            return None, str(item.error)
        resp = getattr(item, "response", None)
        if resp is not None:
            return (resp.model_dump(mode="json") if hasattr(resp, "model_dump") else dict(resp)), None
        return None, "Risposta vuota nel lotto batch"
    if hasattr(item, "model_dump") and hasattr(item, "content"):
        # NormalizedResponse
        return item.model_dump(mode="json"), None
    if isinstance(item, Mapping):
        if item.get("error"):
            return None, str(item["error"])
        if "response" in item and item["response"] is not None:
            resp = item["response"]
            return (resp.model_dump(mode="json") if hasattr(resp, "model_dump") else dict(resp)), None
        return dict(item), None
    return None, str(item) if item is not None else "Risposta batch mancante"


def store_results(
    batch_id: str,
    results: Mapping[str, Any] | Sequence[Any],
    *,
    db: Optional[Database] = None,
) -> List[str]:
    """Salva i risultati di un lotto completato. Restituisce i job_id toccati (ordinati)."""
    target = _resolve_db(db)
    if isinstance(results, Mapping):
        by_key = dict(results)
    else:
        by_key = {str(getattr(item, "custom_id", "") or item["custom_id"]): item for item in results}

    now = utcnow()
    job_ids: set[str] = set()
    with session_scope(target) as s:
        rows = list(s.scalars(select(LlmDeferred).where(LlmDeferred.batch_id == batch_id)))
        for row in rows:
            if row.job_id:
                job_ids.add(row.job_id)
            if row.key in by_key:
                resp_dict, err_str = _extract_result_payload(by_key[row.key])
                if err_str is not None:
                    row.state = "error"
                    row.error = err_str
                    row.response = None
                else:
                    row.state = "done"
                    row.response = resp_dict
                    row.error = None
                row.updated_at = now
            elif row.state == "submitted":
                row.state = "error"
                row.error = f"Risposta mancante nel lotto {batch_id} per la chiave {row.key}"
                row.response = None
                row.updated_at = now
    return sorted(job_ids)


def consume_error(key: str, *, db: Optional[Database] = None) -> None:
    """Azzera una chiave in stato 'error' così i retry successivi possono ripartire da zero."""
    target = _resolve_db(db)
    with session_scope(target) as s:
        s.execute(sa_delete(LlmDeferred).where(LlmDeferred.key == key, LlmDeferred.state == "error"))


def delete_key(key: str, *, db: Optional[Database] = None) -> bool:
    target = _resolve_db(db)
    with session_scope(target) as s:
        res = s.execute(sa_delete(LlmDeferred).where(LlmDeferred.key == key))
        return bool(res.rowcount)


def pending_for_job(job_id: str, *, db: Optional[Database] = None) -> List[DeferredEntry]:
    target = _resolve_db(db)
    with read_scope(target) as s:
        rows = s.scalars(
            select(LlmDeferred)
            .where(LlmDeferred.job_id == job_id, LlmDeferred.state == "pending")
            .order_by(LlmDeferred.created_at, LlmDeferred.key)
        )
        return [DeferredEntry.from_row(r) for r in rows]


def job_has_waiting_items(job_id: str, *, db: Optional[Database] = None) -> bool:
    target = _resolve_db(db)
    with read_scope(target) as s:
        row = s.scalar(
            select(LlmDeferred.key)
            .where(LlmDeferred.job_id == job_id, LlmDeferred.state.in_(["pending", "submitted"]))
            .limit(1)
        )
        return row is not None


def open_batches(*, db: Optional[Database] = None) -> List[Dict[str, Any]]:
    """Elenco dei batch_id aperti (almeno una riga 'submitted'), con provider e credenziale."""
    target = _resolve_db(db)
    with read_scope(target) as s:
        rows = s.scalars(
            select(LlmDeferred)
            .where(LlmDeferred.state == "submitted", LlmDeferred.batch_id.is_not(None))
            .order_by(LlmDeferred.created_at)
        )
        grouped: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            bid = row.batch_id
            if not bid:
                continue
            info = grouped.setdefault(
                bid,
                {
                    "batch_id": bid,
                    "provider": row.provider,
                    "model": row.model,
                    "credential_ref": row.credential_ref,
                    "base_url": row.base_url,
                    "job_ids": [],
                    "keys": [],
                },
            )
            if row.job_id and row.job_id not in info["job_ids"]:
                info["job_ids"].append(row.job_id)
            info["keys"].append(row.key)
        return list(grouped.values())


def delete_for_job(
    job_id: str,
    *,
    states: Sequence[str] = ("pending", "submitted"),
    db: Optional[Database] = None,
) -> List[DeferredEntry]:
    """Rimuove le righe di un job negli stati indicati (es. su annullamento). Restituisce le righe rimosse."""
    target = _resolve_db(db)
    with session_scope(target) as s:
        rows = list(
            s.scalars(
                select(LlmDeferred).where(LlmDeferred.job_id == job_id, LlmDeferred.state.in_(list(states)))
            )
        )
        entries = [DeferredEntry.from_row(r) for r in rows]
        if rows:
            s.execute(
                sa_delete(LlmDeferred).where(LlmDeferred.job_id == job_id, LlmDeferred.state.in_(list(states)))
            )
        return entries


def batch_still_used_by_other_job(batch_id: str, exclude_job_id: Optional[str] = None, *, db: Optional[Database] = None) -> bool:
    target = _resolve_db(db)
    with read_scope(target) as s:
        stmt = select(LlmDeferred.key).where(LlmDeferred.batch_id == batch_id, LlmDeferred.state == "submitted")
        if exclude_job_id is not None:
            stmt = stmt.where(LlmDeferred.job_id != exclude_job_id)
        return s.scalar(stmt.limit(1)) is not None


def mark_batch_fallback(batch_id: str, error: Optional[str] = None, *, db: Optional[Database] = None) -> List[str]:
    """Rimuove le righe 'submitted' di un lotto fallito/scaduto per permettere il fallback sincrono."""
    target = _resolve_db(db)
    with session_scope(target) as s:
        rows = list(
            s.scalars(
                select(LlmDeferred).where(LlmDeferred.batch_id == batch_id, LlmDeferred.state == "submitted")
            )
        )
        job_ids = sorted({r.job_id for r in rows if r.job_id})
        if rows:
            s.execute(
                sa_delete(LlmDeferred).where(LlmDeferred.batch_id == batch_id, LlmDeferred.state == "submitted")
            )
        return job_ids


def cleanup(
    max_age_days: int = 7,
    *,
    db: Optional[Database] = None,
    now: Optional[datetime] = None,
) -> int:
    """Pulisce le righe 'done' più vecchie di max_age_days e le righe pendenti/errore dei job terminati."""
    target = _resolve_db(db)
    ref_now = now or utcnow()
    cutoff = ref_now - timedelta(days=max_age_days)
    terminal_states = ("succeeded", "failed", "cancelled")
    with session_scope(target) as s:
        terminal_job_ids = select(Job.id).where(Job.state.in_(terminal_states))
        cancelled_job_ids = select(Job.id).where(Job.state == "cancelled")
        res = s.execute(
            sa_delete(LlmDeferred).where(
                or_(
                    (LlmDeferred.state == "done") & (LlmDeferred.updated_at < cutoff),
                    (LlmDeferred.state != "done") & LlmDeferred.job_id.in_(terminal_job_ids),
                    LlmDeferred.job_id.in_(cancelled_job_ids),
                )
            )
        )
        return int(res.rowcount or 0)


def collect_deferred_keys(calls: Sequence[BaseException]) -> List[str]:
    """Estrae tutte le chiavi differite da DeferredCall e DeferredPhase senza duplicati."""
    keys: List[str] = []
    seen: set[str] = set()
    for exc in calls:
        if isinstance(exc, DeferredCall):
            if exc.key and exc.key not in seen:
                seen.add(exc.key)
                keys.append(exc.key)
        elif isinstance(exc, DeferredPhase):
            for k in exc.keys:
                if k and k not in seen:
                    seen.add(k)
                    keys.append(k)
    return keys


def raise_deferred_phase(
    calls: Sequence[BaseException],
    *,
    job_id: Optional[str] = None,
    phase: Optional[str] = None,
) -> None:
    """Solleva un singolo DeferredPhase con tutte le chiavi raccolte."""
    keys = collect_deferred_keys(calls)
    resolved_job_id = job_id or current_job_id()
    if resolved_job_id is None:
        for exc in calls:
            if getattr(exc, "job_id", None):
                resolved_job_id = exc.job_id
                break
    raise DeferredPhase(job_id=resolved_job_id, keys=keys, phase=phase)


def run_collecting(
    items: Sequence[TItem],
    fn: Callable[[TItem], TResult],
    *,
    max_workers: int = 1,
    job_id: Optional[str] = None,
    phase: Optional[str] = None,
) -> List[TResult]:
    """Esegue fn su tutti gli items raccogliendo eventuali DeferredCall.
    Restituisce i risultati se nessuna chiamata è stata differita, altrimenti solleva un solo DeferredPhase."""
    seq = list(items)
    if not seq:
        return []

    deferred_calls: List[BaseException] = []
    results: Dict[int, TResult] = {}

    if max_workers <= 1 or len(seq) <= 1:
        for idx, item in enumerate(seq):
            try:
                results[idx] = fn(item)
            except (DeferredCall, DeferredPhase) as dc:
                deferred_calls.append(dc)
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from contextvars import copy_context

        workers = max(1, min(max_workers, len(seq)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(copy_context().run, fn, item): idx for idx, item in enumerate(seq)}
            try:
                for fut in as_completed(futures):
                    idx = futures[fut]
                    try:
                        results[idx] = fut.result()
                    except (DeferredCall, DeferredPhase) as dc:
                        deferred_calls.append(dc)
            except BaseException:
                for f in futures:
                    f.cancel()
                raise

    if deferred_calls:
        raise_deferred_phase(deferred_calls, job_id=job_id, phase=phase)

    return [results[i] for i in range(len(seq))]
