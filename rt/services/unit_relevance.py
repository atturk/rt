"""Classificazione JEV post-rewrite, decisioni umane e filtro condiviso da review/Recall."""

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from rt.core.config import load_config
from rt.core.filelock import file_lock
from rt.core.lesson_paths import lesson_path
from rt.pipeline.rewrite import load_draft
from rt.services import jev_mapping
from rt.services.jev_mapping import RELEVANCE_CRITERIA, RELEVANCE_INSTRUCTIONS
from rt.storage import fs

LOG = logging.getLogger(__name__)
CLASSES = ("didactic", "organizational", "no_content")
# Testi predefiniti della domanda: ora in jev_mapping (qui per compatibilità e per l'impronta).
CRITERIA = RELEVANCE_CRITERIA
INSTRUCTIONS = RELEVANCE_INSTRUCTIONS


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _unit_hash(unit) -> str:
    return _hash(json.dumps([unit.title, unit.content], ensure_ascii=False))


def _config_hash(cfg) -> str:
    if cfg.relevance_decision is None:
        # Decisione predefinita: stessa impronta di prima del playground, così le
        # classificazioni già salvate restano valide dopo l'aggiornamento.
        return _hash(json.dumps([cfg.relevance_model, cfg.credential, cfg.base_url, cfg.relevance_prompt,
                                 cfg.relevance_threshold, INSTRUCTIONS, CRITERIA], sort_keys=True, ensure_ascii=False))
    return _hash(json.dumps([cfg.relevance_model, cfg.credential, cfg.base_url,
                             cfg.relevance_decision.model_dump()], sort_keys=True, ensure_ascii=False))


def _path(lesson_dir: str) -> str:
    return lesson_path(lesson_dir, "unit_relevance.json")


def _load(lesson_dir: str) -> dict:
    path = _path(lesson_dir)
    if fs.isfile(path):
        try:
            with fs.open(path, "r", encoding="utf-8") as stream:
                data = json.load(stream)
            return data if isinstance(data, dict) else {}
        except (ValueError, OSError):
            LOG.warning("Classificazioni JEV illeggibili: %s", lesson_dir, exc_info=True)
    return {}


def _save(lesson_dir: str, records: dict) -> None:
    path = _path(lesson_dir)
    temp = path + ".tmp"
    with fs.open(temp, "w", encoding="utf-8") as stream:
        json.dump(records, stream, ensure_ascii=False, indent=2)
    fs.replace(temp, path)


def _lock(lesson_dir: str):
    return file_lock(fs.lock_path(_path(lesson_dir) + ".lock"), retries=100, backoff=0.05)


def mode() -> str:
    cfg = load_config().jev
    return cfg.relevance_mode if cfg.relevance_model.strip() else "disabled"


def refresh(lesson_dir: str, *, force_mock: bool = False, ctx=None) -> dict:
    """Classifica le unità cambiate. Un errore lascia passare l'unità e resta visibile."""
    cfg = load_config().jev
    if not cfg.relevance_model.strip() or cfg.relevance_mode == "disabled":
        return _load(lesson_dir)
    from rt.llm import jev_client

    decision = jev_mapping.effective_decision("relevance", cfg)
    previous = _load(lesson_dir)
    result = {}
    configuration = _config_hash(cfg)
    units = load_draft(lesson_dir).units
    errors = 0
    for unit in units:
        digest = _unit_hash(unit)
        old = previous.get(unit.unit_id, {})
        if old.get("text_hash") == digest and old.get("config_hash") == configuration and old.get("prediction") in CLASSES:
            old["last_run_mode"] = cfg.relevance_mode
            result[unit.unit_id] = old
            continue
        override = old.get("override") if old.get("text_hash") == digest else None
        prior_override = old.get("override") if old.get("text_hash") != digest else old.get("prior_override")
        mapped, error = None, None
        try:
            if force_mock:
                mapped = jev_mapping.DecisionResult(label=decision.fallback_label, outcome="didactic", rule=None,
                                                    answer={"type": "mock"})
            else:
                answer = jev_client.call_jev(
                    state=jev_mapping.state_for("relevance", unit.title, unit.content),
                    questions={jev_mapping.QUESTION_NAMES["relevance"]: jev_mapping.build_question(decision)},
                    job_name="relevance", unit_id=unit.unit_id, lesson_dir=lesson_dir,
                    model=cfg.relevance_model, credential=cfg.credential, base_url=cfg.base_url,
                    timeout_seconds=cfg.timeout_seconds,
                ).answers[jev_mapping.QUESTION_NAMES["relevance"]]
                if answer.type != decision.type:
                    raise ValueError("Risposta JEV di tipo inatteso")
                mapped = jev_mapping.evaluate("relevance", decision, answer)
        except Exception as exc:
            error = str(exc)
            errors += 1
            LOG.warning("JEV rilevanza %s: %s", unit.unit_id, exc)
        answer_data = mapped.answer if mapped else None
        result[unit.unit_id] = {"text_hash": digest, "config_hash": configuration,
                                # prediction è già l'esito della mappatura (soglie comprese).
                                "prediction": mapped.outcome if mapped else None,
                                "confidence": _confidence(answer_data),
                                "label": mapped.label if mapped else None,
                                "rule": mapped.rule if mapped else None,
                                "answer": answer_data, "mapped": True,
                                "override": override, "error": error,
                                "prior_override": prior_override if prior_override in CLASSES else None,
                                "last_run_mode": cfg.relevance_mode,
                                "updated_at": datetime.now(timezone.utc).isoformat()}
        if ctx is not None and mapped is not None and not force_mock:
            from rt.services.events import Notice
            ctx.emit(Notice(message=f"JEV rilevanza {unit.unit_id}: {jev_mapping.describe(mapped)}"))
    try:
        with _lock(lesson_dir):
            latest = _load(lesson_dir)
            for unit_id, row in result.items():
                current = latest.get(unit_id, {})
                if current.get("text_hash") == row["text_hash"] and current.get("override") in CLASSES:
                    row["override"] = current["override"]
                    row["corrected_at"] = current.get("corrected_at")
                    row["corrected_by"] = current.get("corrected_by")
            if result != latest:
                _save(lesson_dir, result)
    except (OSError, TimeoutError):
        LOG.exception("Impossibile salvare le classificazioni JEV; tutte le unità passeranno")
    if ctx is not None:
        from rt.services.events import Notice
        excluded = sum(1 for row in result.values() if _effective(row, cfg) != "didactic")
        ctx.emit(Notice(message=f"JEV {cfg.relevance_mode}: {len(units)} unità valutate, {excluded} non didattiche, {errors} errori."))
    return result


def _confidence(answer: Optional[dict]) -> Optional[float]:
    """Confidenza mostrata accanto alla classificazione: quella di Jev, o la probabilità noul."""
    if not answer:
        return None
    value = answer.get("confidence", answer.get("noul"))
    return value if isinstance(value, (int, float)) else None


def _effective(row: dict, cfg) -> str:
    if row.get("override") in CLASSES:
        return row["override"]
    if row.get("mapped"):
        return row["prediction"] if row.get("prediction") in CLASSES else "didactic"
    # Righe salvate prima del playground: la scelta grezza di Jev con la soglia di allora
    # (sono fresche solo con la decisione predefinita, che applica la stessa regola).
    if row.get("prediction") in CLASSES and (row.get("confidence") or 0) >= cfg.relevance_threshold:
        return row["prediction"]
    return "didactic"


def included(lesson_dir: str, unit) -> bool:
    cfg = load_config().jev
    if not cfg.relevance_model.strip() or cfg.relevance_mode != "active":
        return True
    row = _load(lesson_dir).get(unit.unit_id, {})
    if row.get("text_hash") != _unit_hash(unit) or row.get("config_hash") != _config_hash(cfg):
        return True  # classificazione mancante/stale: fail-open
    return _effective(row, cfg) == "didactic"


def list_units(lesson_dir: str) -> dict:
    cfg = load_config().jev
    records = _load(lesson_dir)
    try:
        units = load_draft(lesson_dir).units
    except FileNotFoundError:
        units = []
    rows = []
    for unit in units:
        row = records.get(unit.unit_id, {})
        fresh = row.get("text_hash") == _unit_hash(unit) and row.get("config_hash") == _config_hash(cfg)
        effective = _effective(row, cfg) if fresh else "didactic"
        rows.append({"unit_id": unit.unit_id, "title": unit.title, "content": unit.content,
                     "prediction": row.get("prediction") if fresh else None,
                     "confidence": row.get("confidence") if fresh else None,
                     "label": row.get("label") if fresh else None,
                     "answer": row.get("answer") if fresh else None,
                     "override": row.get("override") if fresh else None,
                     "effective": effective, "error": row.get("error") if fresh else None,
                     "stale": bool(row) and not fresh,
                     "corrected_at": row.get("corrected_at") if fresh else None,
                     "corrected_by": row.get("corrected_by") if fresh else None,
                     "prior_override": row.get("prior_override") if fresh else row.get("override")})
    return {"mode": mode(), "units": rows}


def set_override(lesson_dir: str, unit_id: str, category: Optional[str], actor: str = "utente") -> dict:
    if category is not None and category not in CLASSES:
        raise ValueError("Categoria non valida")
    unit = next((u for u in load_draft(lesson_dir).units if u.unit_id == unit_id), None)
    if unit is None:
        raise KeyError(unit_id)
    cfg = load_config().jev
    with _lock(lesson_dir):
        records = _load(lesson_dir)
        row = records.get(unit_id, {})
        if row.get("text_hash") != _unit_hash(unit):
            row = {"text_hash": _unit_hash(unit), "config_hash": _config_hash(cfg),
                   "prediction": None, "confidence": None, "error": None}
        row["config_hash"] = _config_hash(cfg)
        row["override"] = category
        row["prior_override"] = None
        row["corrected_at"] = datetime.now(timezone.utc).isoformat() if category else None
        row["corrected_by"] = actor if category else None
        row["updated_at"] = datetime.now(timezone.utc).isoformat()
        records[unit_id] = row
        _save(lesson_dir, records)
    return list_units(lesson_dir)
