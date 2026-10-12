"""Classificazione (classificatore di rilevanza, es. Jev) post-rewrite, decisioni umane e filtro condiviso da review/Recall."""

import hashlib
import json
import logging
import math
from datetime import datetime, timezone
from typing import Optional

from rt.core.config import load_config, classifier_jev, classifier_job
from rt.core.filelock import file_lock
from rt.core.lesson_paths import lesson_path
from rt.pipeline.rewrite import load_draft
from rt.services import jev_mapping
from rt.services.jev_mapping import RELEVANCE_CRITERIA, RELEVANCE_INSTRUCTIONS
from rt.storage import fs
from rt.services.recall_context import lesson_context, POLICY_VERSION, RELEVANCE_DEFINITION

LOG = logging.getLogger(__name__)
CLASSES = ("didactic", "organizational", "no_content")
# Testi predefiniti della domanda: ora in jev_mapping (qui per compatibilità e per l'impronta).
CRITERIA = RELEVANCE_CRITERIA
INSTRUCTIONS = RELEVANCE_INSTRUCTIONS


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _unit_hash(unit, lesson_dir=None) -> str:
    return _hash(json.dumps([unit.title, unit.content, lesson_context(lesson_dir) if lesson_dir else {},
                             POLICY_VERSION, RELEVANCE_DEFINITION], sort_keys=True, ensure_ascii=False))


def _config_hash(cfg) -> str:
    return _hash(json.dumps([cfg.relevance_model, cfg.credential, cfg.base_url,
                             jev_mapping.effective_decision("relevance", cfg).model_dump()],
                            sort_keys=True, ensure_ascii=False))


def _path(lesson_dir: str, view="draft") -> str:
    if view not in ("draft", "resolved"):
        raise ValueError("Vista di rilevanza non valida")
    return lesson_path(lesson_dir, "unit_relevance.json" if view == "draft" else "unit_relevance_resolved.json")


def _load(lesson_dir: str, view="draft") -> dict:
    path = _path(lesson_dir, view)
    if fs.isfile(path):
        try:
            with fs.open(path, "r", encoding="utf-8") as stream:
                data = json.load(stream)
            return data if isinstance(data, dict) else {}
        except (ValueError, OSError):
            LOG.warning("Classificazioni del classificatore illeggibili: %s", lesson_dir, exc_info=True)
    return {}


def _save(lesson_dir: str, records: dict, view="draft") -> None:
    path = _path(lesson_dir, view)
    temp = path + ".tmp"
    with fs.open(temp, "w", encoding="utf-8") as stream:
        json.dump(records, stream, ensure_ascii=False, indent=2)
    fs.replace(temp, path)


def _lock(lesson_dir: str, view="draft"):
    return file_lock(fs.lock_path(_path(lesson_dir, view) + ".lock"), retries=100, backoff=0.05)


def mode() -> str:
    cfg = classifier_jev(load_config(), "relevance")
    return cfg.relevance_mode if cfg.relevance_model.strip() else "disabled"


def ensure_can_run() -> None:
    """Conflict se il classificatore di rilevanza è spento: il job non avrebbe niente da fare."""
    if mode() == "disabled":
        from rt.services.errors import Conflict
        raise Conflict("relevance_disabled", "Il classificatore di rilevanza è disattivato: scegli modello e comportamento in "
                       "Impostazioni > Modelli > Classificatore.")


def refresh(lesson_dir: str, *, force_mock: bool = False, ctx=None, force: bool = False, view: str = "draft", responses=None, unit_ids=None) -> dict:
    """Classifica le unità cambiate (force: tutte). Un errore lascia passare l'unità e resta
    visibile; le correzioni dell'utente su un testo invariato restano."""
    cfg = classifier_jev(load_config(), "relevance")
    if not cfg.relevance_model.strip() or cfg.relevance_mode == "disabled":
        return _load(lesson_dir, view)
    from rt.llm import jev_client

    decision = jev_mapping.effective_decision("relevance", cfg)
    previous = _load(lesson_dir, view)
    result = {}
    configuration = _config_hash(cfg)
    from rt.pipeline.ledger import load_resolved_draft
    units = (load_resolved_draft(lesson_dir) if view == "resolved" else load_draft(lesson_dir)).units
    context = lesson_context(lesson_dir)
    other = _load(lesson_dir, "draft" if view == "resolved" else "resolved")
    errors = 0
    for unit in units:
        digest = _unit_hash(unit, lesson_dir)
        old = previous.get(unit.unit_id, {})
        if unit_ids is not None and unit.unit_id not in unit_ids:
            if old:
                result[unit.unit_id] = old
            continue
        shared = other.get(unit.unit_id, {})
        if shared.get("text_hash") == digest and shared.get("config_hash") == configuration:
            if old.get("text_hash") != digest or old.get("config_hash") != configuration or old.get("prediction") not in CLASSES:
                old = dict(shared)
            if (shared.get("override_changed_at") or "") > (old.get("override_changed_at") or ""):
                old = {**old, **{k: shared.get(k) for k in ("override", "override_changed_at", "corrected_at", "corrected_by")}}
        if not force and old.get("text_hash") == digest and old.get("config_hash") == configuration \
                and old.get("prediction") in CLASSES:
            old = dict(old)
            old["view"] = view
            old["last_run_mode"] = cfg.relevance_mode
            result[unit.unit_id] = old
            continue
        override = old.get("override") if old.get("text_hash") == digest else None
        prior_override = old.get("override") if old.get("text_hash") != digest else old.get("prior_override")
        mapped, error = None, None
        now = datetime.now(timezone.utc).isoformat()
        try:
            if force_mock:
                mapped = jev_mapping.DecisionResult(label=decision.fallback_label, outcome="didactic", rule=None,
                                                    answer={"type": "mock"})
            else:
                answer = (responses[unit.unit_id] if responses is not None and unit.unit_id in responses else jev_client.call_jev(
                    state=jev_mapping.state_for("relevance", unit.title, unit.content, context),
                    questions={jev_mapping.QUESTION_NAMES["relevance"]: jev_mapping.build_question(decision)},
                    job_name="relevance", unit_id=unit.unit_id, lesson_dir=lesson_dir,
                    model=cfg.relevance_model, credential=cfg.credential, base_url=cfg.base_url,
                    timeout_seconds=cfg.timeout_seconds,
                )).answers[jev_mapping.QUESTION_NAMES["relevance"]]
                if answer.type != decision.type:
                    raise ValueError("Risposta del classificatore di tipo inatteso")
                mapped = jev_mapping.evaluate("relevance", decision, answer)
        except Exception as exc:
            error = str(exc)
            errors += 1
            LOG.warning("Classificatore rilevanza %s: %s", unit.unit_id, exc)
        answer_data = mapped.answer if mapped else None
        result[unit.unit_id] = {"text_hash": digest, "config_hash": configuration, "view": view,
                                # prediction è già l'esito della mappatura (soglie comprese).
                                "prediction": mapped.outcome if mapped else None,
                                "confidence": _confidence(answer_data),
                                "label": mapped.label if mapped else None,
                                "rule": mapped.rule if mapped else None,
                                "answer": answer_data, "mapped": True,
                                "override": override, "error": error,
                                "prior_override": prior_override if prior_override in CLASSES else None,
                                "last_run_mode": cfg.relevance_mode, "model": cfg.relevance_model,
                                "classified_at": now, "updated_at": now,
                                "override_changed_at": old.get("override_changed_at"),
                                "corrected_at": old.get("corrected_at") if override else None,
                                "corrected_by": old.get("corrected_by") if override else None}
        if ctx is not None and mapped is not None and not force_mock:
            from rt.services.events import Notice
            ctx.emit(Notice(message=f"Classificatore rilevanza {unit.unit_id}: {jev_mapping.describe(mapped)}"))
    try:
        with _lock(lesson_dir, view):
            latest = _load(lesson_dir, view)
            for unit_id, row in result.items():
                current = latest.get(unit_id, {})
                if current.get("text_hash") == row["text_hash"] and (current.get("override_changed_at") or "") > (row.get("override_changed_at") or ""):
                    for key in ("override", "override_changed_at", "corrected_at", "corrected_by"):
                        row[key] = current.get(key)
            if result != latest:
                _save(lesson_dir, result, view)
    except (OSError, TimeoutError):
        LOG.exception("Impossibile salvare le classificazioni; tutte le unità passeranno")
    if ctx is not None:
        from rt.services.events import Notice
        excluded = sum(1 for row in result.values() if _effective(row, cfg) != "didactic")
        ctx.emit(Notice(message=f"Classificatore ({cfg.relevance_mode}): {len(units)} unità valutate, {excluded} non didattiche, {errors} errori."))
    return result


def _confidence(answer: Optional[dict]) -> Optional[float]:
    """Confidenza mostrata accanto alla classificazione: quella del classificatore, o la probabilità noul."""
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


def included_ids(lesson_dir: str, units, *, view="draft", records=None, cfg=None) -> set:
    """Carica configurazione e classificazioni una volta per l'intera vista."""
    cfg = cfg if cfg is not None else classifier_jev(load_config(), "relevance")
    if not cfg.relevance_model.strip() or cfg.relevance_mode != "active":
        return {u.unit_id for u in units}
    records = _load(lesson_dir, view) if records is None else records
    configuration = _config_hash(cfg)
    return {u.unit_id for u in units
            if (records.get(u.unit_id, {}).get("text_hash") != _unit_hash(u, lesson_dir)
                or records.get(u.unit_id, {}).get("config_hash") != configuration
                or _effective(records[u.unit_id], cfg) == "didactic")}


def included(lesson_dir: str, unit, *, view="draft") -> bool:
    return unit.unit_id in included_ids(lesson_dir, [unit], view=view)


def list_units(lesson_dir: str, *, view="draft") -> dict:
    cfg = classifier_jev(load_config(), "relevance")
    records = _load(lesson_dir, view)
    try:
        from rt.pipeline.ledger import load_resolved_draft
        units = (load_resolved_draft(lesson_dir) if view == "resolved" else load_draft(lesson_dir)).units
    except FileNotFoundError:
        units = []
    resolved_records = _load(lesson_dir, "resolved") if view != "resolved" else records
    allowed = included_ids(lesson_dir, units, view=view, records=records, cfg=cfg)
    configuration = _config_hash(cfg)
    rows = []
    from rt.pipeline.ledger import load_resolved_draft
    try:
        resolved = {u.unit_id: u for u in load_resolved_draft(lesson_dir).units}
    except (FileNotFoundError, ValueError):
        resolved = {}
    for unit in units:
        row = records.get(unit.unit_id, {})
        fresh = row.get("text_hash") == _unit_hash(unit, lesson_dir) and row.get("config_hash") == configuration
        effective = _effective(row, cfg) if fresh else "didactic"
        rows.append({"unit_id": unit.unit_id, "title": unit.title, "content": unit.content,
                     "prediction": row.get("prediction") if fresh else None,
                     "confidence": row.get("confidence") if fresh else None,
                     "label": row.get("label") if fresh else None,
                     "answer": row.get("answer") if fresh else None,
                     "override": row.get("override") if fresh else None,
                     "review_included": unit.unit_id in allowed,
                     "effective": effective, "error": row.get("error") if fresh else None,
                     "stale": bool(row) and not fresh,
                     "corrected_at": row.get("corrected_at") if fresh else None,
                     "corrected_by": row.get("corrected_by") if fresh else None,
                     "prior_override": row.get("prior_override") if fresh else row.get("override"),
                     "recall_assessment": recall_assessment(lesson_dir, resolved[unit.unit_id], records=resolved_records, cfg=cfg) if unit.unit_id in resolved else {"state": "unavailable", "level": None}})
    return {"mode": mode(), "view": view, "units": rows, "summary": _summary(rows, records, units)}


def classification_status(lesson_dir: str) -> dict:
    """In breve, se il classificatore è passato sulla lezione (per elenchi come la pagina del
    recall): state = done | partial | stale | never | disabled | unavailable (senza bozza),
    con le stesse regole del riepilogo della pagina Classificatore."""
    if mode() == "disabled":
        return {"state": "disabled", "classified": 0, "total": 0}
    try:
        units = load_draft(lesson_dir).units
    except (FileNotFoundError, ValueError):
        return {"state": "unavailable", "classified": 0, "total": 0}
    cfg = classifier_jev(load_config(), "relevance")
    config_hash = _config_hash(cfg)
    records = _load(lesson_dir)
    classified = errors = stale = 0
    for unit in units:
        row = records.get(unit.unit_id)
        if not row:
            continue
        if row.get("text_hash") != _unit_hash(unit, lesson_dir) or row.get("config_hash") != config_hash:
            stale += 1
        elif row.get("prediction") in CLASSES:
            classified += 1
        elif row.get("error"):
            errors += 1
    total = len(units)
    if total and classified == total:
        state = "done"
    elif classified == 0 and errors == 0:
        state = "stale" if stale else "never"
    else:
        state = "partial"
    return {"state": state, "classified": classified, "total": total}


def _summary(rows: list, records: dict, units: list) -> dict:
    """Riepilogo per capire a colpo d'occhio se il classificatore è passato sulla lezione e con che esito."""
    current = {unit.unit_id for unit in units}
    classified = [r for r in rows if r["prediction"] in CLASSES]
    by_outcome = {name: sum(1 for r in classified if r["prediction"] == name) for name in CLASSES}
    by_label: dict = {}
    for row in classified:
        key = row["label"] or row["prediction"]
        by_label[key] = by_label.get(key, 0) + 1
    fresh = {r["unit_id"] for r in rows if r["prediction"] in CLASSES or r["error"]}
    # Righe salvate prima di classified_at: vale l'ultimo aggiornamento della riga.
    runs = [records[uid] for uid in current & fresh]
    stamps = [r.get("classified_at") or r.get("updated_at") for r in runs]
    stamps = [s for s in stamps if s]
    latest = max(runs, key=lambda r: r.get("classified_at") or r.get("updated_at") or "", default={})
    return {"total": len(rows), "classified": len(classified),
            "errors": sum(1 for r in rows if r["error"]),
            "stale": sum(1 for r in rows if r["stale"]),
            "missing": sum(1 for r in rows if not r["stale"] and r["prediction"] not in CLASSES and not r["error"]),
            "corrected": sum(1 for r in rows if r["override"] in CLASSES),
            "excluded": sum(1 for r in rows if r["effective"] != "didactic"),
            "by_outcome": by_outcome, "by_label": dict(sorted(by_label.items(), key=lambda kv: (-kv[1], kv[0]))),
            "last_run_at": max(stamps) if stamps else None,
            "model": latest.get("model"), "last_run_mode": latest.get("last_run_mode")}


def set_override(lesson_dir: str, unit_id: str, category: Optional[str], actor: str = "utente", *, view="draft") -> dict:
    if category is not None and category not in CLASSES:
        raise ValueError("Categoria non valida")
    from rt.pipeline.ledger import load_resolved_draft
    unit = next((u for u in (load_resolved_draft(lesson_dir) if view == "resolved" else load_draft(lesson_dir)).units if u.unit_id == unit_id), None)
    if unit is None:
        raise KeyError(unit_id)
    cfg = classifier_jev(load_config(), "relevance")
    with _lock(lesson_dir, view):
        records = _load(lesson_dir, view)
        row = records.get(unit_id, {})
        if row.get("text_hash") != _unit_hash(unit, lesson_dir):
            row = {"text_hash": _unit_hash(unit, lesson_dir), "config_hash": _config_hash(cfg),
                   "prediction": None, "confidence": None, "error": None}
        row["config_hash"] = _config_hash(cfg)
        row["override"] = category
        row["prior_override"] = None
        row["corrected_at"] = datetime.now(timezone.utc).isoformat() if category else None
        row["corrected_by"] = actor if category else None
        row["updated_at"] = datetime.now(timezone.utc).isoformat()
        row["override_changed_at"] = row["updated_at"]
        records[unit_id] = row
        _save(lesson_dir, records, view)
    other_view = "draft" if view == "resolved" else "resolved"
    with _lock(lesson_dir, other_view):
        resolved = _load(lesson_dir, other_view)
        other = resolved.get(unit_id, {})
        if other.get("text_hash") == row["text_hash"]:
            for key in ("override", "override_changed_at", "prior_override", "corrected_at", "corrected_by"):
                other[key] = row.get(key)
            _save(lesson_dir, resolved, other_view)
    return list_units(lesson_dir, view=view)


def recall_assessment(lesson_dir: str, unit, *, records=None, cfg=None) -> dict:
    """Score indicativo, mai una quota; shadow, errori e scale estranee restano neutri."""
    cfg = classifier_jev(load_config(), "relevance") if cfg is None else cfg
    decision = jev_mapping.effective_decision("relevance", cfg)
    row = (records if records is not None else _load(lesson_dir, "resolved")).get(unit.unit_id, {})
    neutral = {"state": "unavailable", "level": None}
    if not cfg.relevance_model.strip() or cfg.relevance_mode != "active" or not decision.recall_richness:
        return neutral
    if row.get("text_hash") != _unit_hash(unit, lesson_dir) or row.get("config_hash") != _config_hash(cfg) or row.get("error"):
        return neutral
    return _score_level(row, cfg)


def recall_signal(lesson_dir: str, unit, records: Optional[dict] = None) -> dict:
    """Quello che il classificatore dice di un'unità della bozza risolta, anche col gate in
    ombra: categoria, score e livello (0/1/2) per il selettore delle unità del recall."""
    cfg = classifier_jev(load_config(), "relevance")
    empty = {"category": None, "score": None, "level": None, "confidence": None, "error": None}
    if not cfg.relevance_model.strip() or cfg.relevance_mode == "disabled":
        return empty
    row = (records if records is not None else _load(lesson_dir, "resolved")).get(unit.unit_id, {})
    if not row or row.get("text_hash") != _unit_hash(unit, lesson_dir) or row.get("config_hash") != _config_hash(cfg):
        return empty
    if row.get("error"):
        return {**empty, "error": row["error"]}
    assessed = _score_level(row, cfg)
    return {"category": _effective(row, cfg), "score": assessed.get("score"), "level": assessed.get("level"),
            "confidence": _confidence(row.get("answer")) if row.get("answer") else row.get("confidence"), "error": None}


def _score_level(row: dict, cfg) -> dict:
    answer = row.get("answer") or {}
    score, confidence = answer.get("score"), answer.get("confidence")

    def valid(value, low, high):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and low <= value <= high

    result = {"state": "uncertain", "level": None, "score": score,
              "confidence": confidence, "probabilities": answer.get("probabilities") or {}}
    if answer.get("type") != "score" or not valid(score, 0, 2) or not valid(confidence, cfg.relevance_threshold, 1):
        return result
    probabilities = result["probabilities"]
    if probabilities:
        if not isinstance(probabilities, dict) or set(probabilities) != {"0", "1", "2"} or not all(valid(v, 0, 1) for v in probabilities.values()):
            return result
        if not math.isclose(sum(probabilities.values()), 1, abs_tol=.02):
            return result
        top = max(probabilities.values())
        winners = [k for k, v in probabilities.items() if math.isclose(v, top, abs_tol=1e-9)]
        if len(winners) != 1 or top < cfg.relevance_threshold:
            return result
        level = int(winners[0])
    else:
        level = 0 if score < .5 else 1 if score < 1.5 else 2
    return {**result, "state": "assessed", "level": level}
