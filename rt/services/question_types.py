"""Tipo di domanda consigliato per ciascuna unità della bozza, con cache e fail-open."""
import hashlib
import json
import logging
from datetime import datetime, timezone

from rt.core.config import load_config, classifier_jev, classifier_job
from rt.core.filelock import file_lock
from rt.core.lesson_paths import lesson_path
from rt.storage import fs

LOG = logging.getLogger(__name__)
INSTRUCTIONS = "Valuta un'unità di una lezione universitaria riscritta e scegli il tipo di domanda più adatto per verificare se lo studente l'ha capita."
QT_VERSION = 2
CRITERIA = {
    "quiz": "Il contenuto è fatto soprattutto di fatti, definizioni, valori o classificazioni da riconoscere: si verifica bene con domande a risposta multipla.",
    "mirata": "Il contenuto spiega un meccanismo, un perché o un collegamento fra concetti: si verifica bene con una domanda aperta precisa, a cui rispondere in poche righe.",
}


def enabled() -> bool:
    cfg = classifier_jev(load_config(), "question_types")
    return bool(cfg.relevance_model.strip()) and cfg.relevance_mode != "disabled"


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _text_hash(unit, lesson_dir):
    from rt.services.recall_context import lesson_context
    return _hash([unit.title, unit.content, lesson_context(lesson_dir)])


def _config_hash(cfg, criteria=None):
    return _hash([cfg.relevance_model, cfg.credential, cfg.base_url, cfg.relevance_mode, QT_VERSION, INSTRUCTIONS, CRITERIA if criteria is None else criteria])


def _path(lesson_dir):
    return lesson_path(lesson_dir, "unit_question_types.json")


def _load(lesson_dir):
    try:
        with fs.open(_path(lesson_dir), encoding="utf-8") as stream:
            data = json.load(stream)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def offered(lesson_dir, section, labels, *, cfg=None):
    from rt.services.custom_question_types import active_types
    return {**CRITERIA, **{t.id: t.cerca for t in active_types(lesson_dir=lesson_dir, cfg=cfg)
                          if labels.get(section, {}).get(t.id) == "presente"}}


def current_choice(row, criteria):
    value = row.get("override") if row.get("override") in criteria else row.get("candidate", row.get("type"))
    return value if value in criteria else None


def _sections(lesson_dir, units):
    from rt.services import section_labels
    sections = section_labels.sections(lesson_dir, units)
    owner = {u.unit_id: s["id"] for s in sections for u in s["units"]}
    return owner, section_labels.labels(lesson_dir, sections=sections)


def _mock(unit, criteria):
    custom = [kind for kind in criteria if kind not in CRITERIA]
    kind = custom[0] if custom else "quiz"
    return {"candidate": kind, "confidence": .9,
            "probabilities": {k: .85 if k == kind else .05 for k in criteria}}


def refresh(lesson_dir, *, force_mock=False, unit_ids=None, ctx=None, responses=None, force=False, view="draft", refresh_sections=True):
    from rt.pipeline.rewrite import load_draft
    from rt.services import section_labels
    from rt.services.events import Notice
    from rt.services.recall_context import lesson_context
    from rt.services import jev_mapping
    from rt.llm import jev_client
    cfg = load_config()
    if not enabled():
        return {}
    from rt.pipeline.ledger import load_resolved_draft
    units = (load_resolved_draft(lesson_dir) if view == "resolved" else load_draft(lesson_dir)).units
    mock = force_mock or cfg.mock_llm
    if refresh_sections:
        section_labels.refresh(lesson_dir, force_mock=mock)
    owner, labels = _sections(lesson_dir, units)
    from rt.services.unit_relevance import included_ids
    from rt.pipeline.ledger import load_resolved_draft
    allowed = included_ids(lesson_dir, load_resolved_draft(lesson_dir).units if view == "resolved" else units, view=view)
    wanted = set(unit_ids) if unit_ids is not None else {u.unit_id for u in units}
    previous = _load(lesson_dir)
    result = {}
    for unit in units:
        old = previous.get(unit.unit_id, {})
        digest = _text_hash(unit, lesson_dir)
        criteria = offered(lesson_dir, owner.get(unit.unit_id), labels, cfg=cfg)
        configuration = _config_hash(classifier_jev(cfg, "question_types"), criteria)
        if unit.unit_id not in allowed:
            if old:
                result[unit.unit_id] = old
            continue
        if unit.unit_id not in wanted:
            if old:
                result[unit.unit_id] = old
            continue
        if not force and old.get("text_hash") == digest and old.get("config_hash") == configuration and old.get("mock") == mock and old.get("candidate") in criteria:
            row = dict(old)
        else:
            row = {"text_hash": digest, "config_hash": configuration, "at": datetime.now(timezone.utc).isoformat(),
                   "type": None, "candidate": None, "confidence": None, "probabilities": {}, "mock": mock}
            try:
                if mock:
                    row.update(_mock(unit, criteria))
                else:
                    response = (responses[unit.unit_id] if responses is not None and unit.unit_id in responses else jev_client.call_jev(
                        state=jev_mapping.state_for("relevance", unit.title, unit.content, lesson_context(lesson_dir)),
                        questions={"tipo_consigliato": jev_client.JevChoiceQuestion(instructions=INSTRUCTIONS, criteria=criteria)},
                        job_name="question_types", unit_id=unit.unit_id, lesson_dir=lesson_dir,
                        model=classifier_jev(cfg, "question_types").relevance_model, credential=classifier_jev(cfg, "question_types").credential, base_url=classifier_jev(cfg, "question_types").base_url,
                        timeout_seconds=classifier_jev(cfg, "question_types").timeout_seconds))
                    answer = response.answers.get("tipo_consigliato")
                    if answer is None or answer.type != "choice" or answer.choice not in criteria:
                        raise ValueError("Tipo consigliato non valido")
                    row.update(candidate=answer.choice, confidence=answer.confidence, probabilities=answer.probabilities)
            except Exception as exc:
                LOG.warning("Tipo consigliato %s: %s", unit.unit_id, exc)
                if ctx is not None:
                    ctx.emit(Notice(level="warning", message=f"Avviso: tipo consigliato non disponibile per l’unità {unit.unit_id}."))
        if old.get("text_hash") == digest and "override" in old:
            row.update({k: old.get(k) for k in ("override", "corrected_at")})
        row["type"] = current_choice(row, criteria)
        result[unit.unit_id] = row
    try:
        with file_lock(fs.lock_path(_path(lesson_dir) + ".lock"), retries=100, backoff=.05):
            latest = _load(lesson_dir)
            # Una generazione su una parte conserva eventuali consigli aggiornati fuori da essa.
            for uid in set(result) - wanted:
                if uid in latest:
                    result[uid] = latest[uid]
            for uid, row in result.items():
                current = latest.get(uid, {})
                if current.get("text_hash") == row.get("text_hash") and (current.get("corrected_at") or "") > (row.get("corrected_at") or ""):
                    row.update(override=current.get("override"), corrected_at=current.get("corrected_at"))
            if result != latest:
                temp = _path(lesson_dir) + ".tmp"
                with fs.open(temp, "w", encoding="utf-8") as stream:
                    json.dump(result, stream, ensure_ascii=False, indent=2)
                fs.replace(temp, _path(lesson_dir))
    except (OSError, TimeoutError):
        LOG.exception("Impossibile salvare i tipi consigliati")
    return result


def suggestions(lesson_dir):
    """Solo consigli attuali, coerenti anche con correzioni alle etichette delle sezioni."""
    if not enabled():
        return {}
    from rt.pipeline.ledger import load_resolved_draft
    try:
        units = load_resolved_draft(lesson_dir).units
    except (OSError, ValueError):
        return {}
    owner, labels = _sections(lesson_dir, units)
    records, cfg = _load(lesson_dir), load_config()
    out = {}
    for unit in units:
        row = records.get(unit.unit_id, {})
        criteria = offered(lesson_dir, owner.get(unit.unit_id), labels, cfg=cfg)
        if row.get("text_hash") == _text_hash(unit, lesson_dir) and (
                row.get("override") in criteria or row.get("config_hash") == _config_hash(classifier_jev(cfg, "question_types"), criteria)):
            out[unit.unit_id] = current_choice(row, criteria)
    return out


def set_override(lesson_dir, unit_id, value):
    from rt.pipeline.ledger import load_resolved_draft
    unit = next((u for u in load_resolved_draft(lesson_dir).units if u.unit_id == unit_id), None)
    if unit is None:
        raise KeyError(unit_id)
    owner, labels = _sections(lesson_dir, load_resolved_draft(lesson_dir).units)
    criteria = offered(lesson_dir, owner.get(unit_id), labels)
    if value is not None and value not in criteria:
        raise ValueError("Tipo di domanda non disponibile nell’unità")
    with file_lock(fs.lock_path(_path(lesson_dir) + ".lock"), retries=100, backoff=.05):
        records = _load(lesson_dir)
        row = records.get(unit_id, {})
        text_hash = _text_hash(unit, lesson_dir)
        if row.get("text_hash") != text_hash:
            row = {"text_hash": text_hash, "candidate": None, "type": None}
        row.update(override=value, corrected_at=datetime.now(timezone.utc).isoformat(),
                   config_hash=_config_hash(classifier_jev(load_config(), "question_types"), criteria))
        records[unit_id] = row
        with fs.open(_path(lesson_dir) + ".tmp", "w", encoding="utf-8") as stream:
            json.dump(records, stream, ensure_ascii=False, indent=2)
        fs.replace(_path(lesson_dir) + ".tmp", _path(lesson_dir))


def allocate(groups, count):
    """Quota proporzionale, almeno una per gruppo visitato; con pochi posti precedono i gruppi più grandi."""
    if not groups or count <= 0:
        return {}
    selected = sorted(groups, key=lambda k: -len(groups[k]))[:count]
    total = sum(len(groups[k]) for k in selected)
    remaining = count - len(selected)
    shares = {k: remaining * len(groups[k]) / total for k in selected}
    quotas = {k: 1 + int(shares[k]) for k in selected}
    for k in sorted(selected, key=lambda k: -(shares[k] % 1))[:count - sum(quotas.values())]:
        quotas[k] += 1
    return quotas
