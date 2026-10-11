"""Etichette per sezione dei tipi personalizzati attivi sulla materia."""
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from rt.core.config import load_config, classifier_jev, classifier_job
from rt.core.filelock import file_lock
from rt.core.lesson_paths import lesson_path
from rt.storage import fs

LOG = logging.getLogger(__name__)

LABEL_VERSION = "section-labels-2"


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def _path(lesson_dir: str) -> str:
    return lesson_path(lesson_dir, "section_labels.json")


def _lock(lesson_dir: str):
    return file_lock(fs.lock_path(_path(lesson_dir) + ".lock"), retries=100, backoff=0.05)


def _load(lesson_dir: str) -> dict:
    path = _path(lesson_dir)
    if fs.isfile(path):
        try:
            with fs.open(path, "r", encoding="utf-8") as stream:
                data = json.load(stream)
            return data if isinstance(data, dict) else {}
        except (ValueError, OSError):
            LOG.warning("Etichette delle unità illeggibili: %s", lesson_dir, exc_info=True)
    return {}


def _save(lesson_dir: str, records: dict) -> None:
    path = _path(lesson_dir)
    temp = path + ".tmp"
    with fs.open(temp, "w", encoding="utf-8") as stream:
        json.dump(records, stream, ensure_ascii=False, indent=2)
    fs.replace(temp, path)


# ---------------------------------------------------------------- sezioni

def sections(lesson_dir: str, units: Optional[list] = None) -> List[dict]:
    """Le sezioni della scaletta con le loro unità selezionate per il recaller, in ordine:
    [{"id", "title", "units": [DraftUnit]}]. Le unità che la scaletta non elenca vanno nella
    sezione del loro prefisso (5.3 -> 5); le sezioni senza unità selezionate non compaiono."""
    from rt.services.recall_units import selected_units
    units = selected_units(lesson_dir) if units is None else units
    titles, owner = {}, {}
    try:
        from rt.pipeline.outline import load_outline
        outline = load_outline(lesson_dir)
        for macro in outline.macro_sections:
            titles[str(macro.id)] = macro.title
            for unit in macro.units:
                owner[unit.id] = str(macro.id)
    except (FileNotFoundError, ValueError):
        pass
    try:
        from rt.pipeline.document_edits import load_document_edits
        edits = load_document_edits(lesson_dir).get("macros", {})
        titles.update({k: v["title"] for k, v in edits.items() if isinstance(v, dict) and v.get("title")})
    except Exception:  # le modifiche al documento sono facoltative
        LOG.debug("Titoli modificati delle sezioni non disponibili", exc_info=True)
    out: Dict[str, dict] = {}
    for unit in units:
        sid = owner.get(unit.unit_id) or unit.unit_id.split(".")[0]
        out.setdefault(sid, {"id": sid, "title": titles.get(sid, f"Sezione {sid}"), "units": []})["units"].append(unit)
    return list(out.values())


def section_text(section: dict) -> str:
    return "\n\n".join(f"[{u.unit_id}] {u.title}\n{u.content}" for u in section["units"])


def _section_hash(lesson_dir: str, section: dict) -> str:
    from rt.services.recall_context import lesson_context
    return _hash([section["title"], [(u.unit_id, u.title, u.content) for u in section["units"]],
                  lesson_context(lesson_dir), LABEL_VERSION])


def _config_hash(cfg, types=None, threshold=None):
    from rt.services.custom_question_types import active_types
    types = load_config().recall.custom_types if types is None else types
    return _hash([cfg.relevance_model, cfg.credential, cfg.base_url, LABEL_VERSION,
                  [(t.id, t.nome, t.cerca, t.anche_adatti) for t in types],
                  load_config().recall.custom_type_threshold if threshold is None else threshold])


def configuration(lesson_dir, *, force_mock=False):
    from rt.services.custom_question_types import active_types
    cfg = load_config()
    return _hash([mode(force_mock), _config_hash(classifier_jev(cfg, "section_labels"),
                 active_types(lesson_dir=lesson_dir, cfg=cfg), cfg.recall.custom_type_threshold)])


def mode(force_mock=False):
    cfg = load_config()
    if force_mock or cfg.mock_llm:
        return "mock"
    model = classifier_jev(cfg, "section_labels")
    return "active" if model.relevance_model.strip() and model.relevance_mode != "disabled" else "disabled"


def _mock_labels(section, types):
    import re
    words = set(re.findall(r"\w+", section_text(section).casefold()))
    return {t.id: "presente" if any(w in words for w in re.findall(r"\w+", t.nome.casefold()))
            else "nessuno" for t in types}


def _classify(lesson_dir, section, cfg, types, *, persist_cost=True):
    from rt.llm import jev_client
    from rt.services.recall_context import context_block, lesson_context
    criteria = {t.id: t.cerca + (" Sono inclusi contenuti adatti senza un esempio esplicito." if t.anche_adatti
                                else " Richiede un esempio o procedimento esplicito nel testo.") for t in types}
    criteria['nessuno'] = "Nessuno dei tipi proposti è presente o adatto nella sezione."
    routing = classifier_jev(cfg, 'section_labels')
    response = jev_client.call_jev(
        state=context_block(lesson_context(lesson_dir)) + "\n\n" + section_text(section),
        questions={'tipo': jev_client.JevChoiceQuestion(
            instructions="Valuta quali tipi di domanda sono presenti o adatti nella sezione. Distribuisci la probabilità fra le etichette.",
            criteria=criteria)}, job_name='section_labels', unit_id=section['id'], lesson_dir=lesson_dir if persist_cost else None,
        model=routing.relevance_model, credential=routing.credential, base_url=routing.base_url,
        timeout_seconds=routing.timeout_seconds)
    answer = response.answers.get('tipo')
    if answer is None or answer.type != 'choice' or answer.choice not in criteria:
        raise ValueError("Etichette del classificatore non valide")
    probabilities = answer.probabilities or {key: answer.confidence if key == answer.choice else 0 for key in criteria}
    highest = max(probabilities.get(t.id, 0) for t in types)
    none_wins = probabilities.get('nessuno', 0) >= highest + cfg.recall.custom_type_threshold
    return {t.id: 'presente' if probabilities.get(t.id, 0) > cfg.recall.custom_type_threshold and not none_wins
            else 'nessuno' for t in types}, probabilities


def refresh(lesson_dir, *, force_mock=False, force=False, progress=None, unit_ids=None, explicit=False):
    from rt.services.custom_question_types import active_types
    cfg = load_config()
    types = active_types(lesson_dir=lesson_dir, cfg=cfg)
    if not types:
        return {}
    if classifier_job(cfg, 'section_labels').mode == 'manual' and not explicit or mode(force_mock) == 'disabled':
        return _load(lesson_dir)
    fingerprint = configuration(lesson_dir, force_mock=force_mock)
    previous, result = _load(lesson_dir), {}
    for section in sections(lesson_dir):
        digest = _section_hash(lesson_dir, section)
        old = previous.get(section['id'], {})
        if unit_ids is not None and section['id'] not in unit_ids and not any(u.unit_id in unit_ids for u in section['units']):
            if old:
                result[section['id']] = old
            continue
        overrides = old.get('overrides', {}) if old.get('text_hash') == digest else {}
        if not force and old.get('text_hash') == digest and old.get('config_hash') == fingerprint and not old.get('error'):
            result[section['id']] = old
            continue
        row = {'text_hash': digest, 'config_hash': fingerprint, 'title': section['title'],
               'unit_ids': [u.unit_id for u in section['units']], 'overrides': overrides,
               'classified_at': datetime.now(timezone.utc).isoformat(), 'error': None}
        try:
            if mode(force_mock) == 'mock':
                values = _mock_labels(section, types)
                probabilities = {key: float(value == 'presente') for key, value in values.items()}
            else:
                values, probabilities = _classify(lesson_dir, section, cfg, types)
            row.update(labels=values, probabilities=probabilities)
        except Exception as exc:
            row.update(labels={}, probabilities={}, error=str(exc))
            LOG.warning("Classificatore della sezione %s: %s", section['id'], exc)
        result[section['id']] = row
        if progress:
            progress(f"Unità {section['id']}: etichette personalizzate aggiornate")
    with _lock(lesson_dir):
        latest = _load(lesson_dir)
        for sid, row in result.items():
            other = latest.get(sid, {})
            if other.get('text_hash') == row['text_hash']:
                row['overrides'] = {**row.get('overrides', {}), **other.get('overrides', {})}
        if result != latest:
            _save(lesson_dir, result)
    return result


def effective(row, kind):
    override = row.get('overrides', {}).get(kind)
    return override if override is not None else row.get('labels', {}).get(kind)


def labels(lesson_dir, sections=None):
    from rt.services.custom_question_types import active_types
    types = active_types(lesson_dir=lesson_dir)
    records, out = _load(lesson_dir), {}
    configuration_hash = configuration(lesson_dir)
    # Le etichette mock sono valide anche quando il mock era un'opzione del singolo job.
    mock_hash = configuration(lesson_dir, force_mock=True)
    for section in (globals()['sections'](lesson_dir) if sections is None else sections):
        row = records.get(section['id'], {})
        if row.get('text_hash') != _section_hash(lesson_dir, section):
            continue
        fresh = row.get('config_hash') in (configuration_hash, mock_hash)
        out[section['id']] = {t.id: effective(row, t.id) for t in types
                              if fresh or row.get('overrides', {}).get(t.id) is not None}
    return out


def view(lesson_dir, sections=None):
    from rt.services.custom_question_types import active_types
    records, rows = _load(lesson_dir), []
    for section in (globals()['sections'](lesson_dir) if sections is None else sections):
        row = records.get(section['id'], {})
        fresh = row.get('text_hash') == _section_hash(lesson_dir, section)
        rows.append({'section_id': section['id'], 'title': section['title'],
                     'unit_ids': [u.unit_id for u in section['units']], 'fresh': fresh,
                     'labels': row.get('labels', {}) if fresh else {},
                     'overrides': row.get('overrides', {}) if fresh else {},
                     'error': row.get('error') if fresh else None})
    return {'mode': mode(), 'sections': rows,
            'options': {t.id: ['presente', 'nessuno'] for t in active_types(lesson_dir=lesson_dir)}}


def set_override(lesson_dir, section_id, kind, value):
    from rt.services.custom_question_types import active_types
    if kind not in {t.id for t in active_types(lesson_dir=lesson_dir)} or value not in (None, 'presente', 'nessuno'):
        raise ValueError("Etichetta o valore non valido")
    section = next((s for s in sections(lesson_dir) if s['id'] == section_id), None)
    if section is None:
        raise KeyError(section_id)
    digest = _section_hash(lesson_dir, section)
    with _lock(lesson_dir):
        records = _load(lesson_dir)
        row = records.get(section_id, {})
        if row.get('text_hash') != digest:
            row = {'text_hash': digest, 'config_hash': None, 'labels': {}, 'error': None, 'overrides': {}}
        row.setdefault('overrides', {})[kind] = value
        records[section_id] = row
        _save(lesson_dir, records)
    return view(lesson_dir)
