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
    "caso": "Il contenuto riguarda pazienti, quadri clinici, diagnosi, parametri o terapie: si verifica bene presentando un caso clinico da interpretare.",
    "esercizio": "Il contenuto contiene calcoli, formule da applicare o procedimenti risolutivi: si verifica bene con un esercizio da svolgere.",
}


def enabled() -> bool:
    cfg = classifier_jev(load_config(), "question_types")
    return bool(cfg.relevance_model.strip()) and cfg.relevance_mode != "disabled"


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _text_hash(unit, lesson_dir):
    from rt.services.recall_context import lesson_context
    return _hash([unit.title, unit.content, lesson_context(lesson_dir)])


def _config_hash(cfg):
    return _hash([cfg.relevance_model, cfg.credential, cfg.base_url, cfg.relevance_mode, QT_VERSION, INSTRUCTIONS, CRITERIA])


def _path(lesson_dir):
    return lesson_path(lesson_dir, "unit_question_types.json")


def _load(lesson_dir):
    try:
        with fs.open(_path(lesson_dir), encoding="utf-8") as stream:
            data = json.load(stream)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _compatible(row, section, labels):
    from rt.services.section_labels import POSITIVE
    kind = row.get("candidate", row.get("type"))
    if kind in POSITIVE and labels.get(section, {}).get(kind) not in POSITIVE[kind]:
        probabilities = row.get("probabilities") or {}
        return max(("quiz", "mirata"), key=lambda k: probabilities.get(k, 0))
    return kind if kind in CRITERIA else None


def _sections(lesson_dir, units):
    from rt.services import section_labels
    sections = section_labels.sections(lesson_dir, units)
    owner = {u.unit_id: s["id"] for s in sections for u in s["units"]}
    return owner, section_labels.labels(lesson_dir, sections=sections)


def _mock(unit):
    text = unit.content.casefold()
    kind = "esercizio" if "$" in text or "calcol" in text or "esercizio" in text else "caso" if any(w in text for w in ("paziente", "diagnosi", "terapia")) else ("quiz" if int(hashlib.sha256(unit.unit_id.encode()).hexdigest(), 16) % 2 else "mirata")
    return {"candidate": kind, "confidence": .9,
            "probabilities": {k: .85 if k == kind else .05 for k in CRITERIA}}


def refresh(lesson_dir, *, force_mock=False, unit_ids=None, ctx=None, responses=None):
    from rt.pipeline.rewrite import load_draft
    from rt.services import section_labels
    from rt.services.events import Notice
    from rt.services.recall_context import context_block, lesson_context
    from rt.llm import jev_client
    cfg = load_config()
    if not enabled():
        return {}
    units = load_draft(lesson_dir).units
    mock = force_mock or cfg.mock_llm
    section_labels.refresh(lesson_dir, force_mock=mock)
    owner, labels = _sections(lesson_dir, units)
    from rt.services.unit_relevance import included_ids
    allowed = included_ids(lesson_dir, units)
    wanted = set(unit_ids) if unit_ids is not None else {u.unit_id for u in units}
    previous = _load(lesson_dir)
    result = {}
    configuration = _config_hash(classifier_jev(cfg, "question_types"))
    for unit in units:
        old = previous.get(unit.unit_id, {})
        digest = _text_hash(unit, lesson_dir)
        if unit.unit_id not in allowed:
            continue
        if unit.unit_id not in wanted:
            if old:
                result[unit.unit_id] = old
            continue
        if old.get("text_hash") == digest and old.get("config_hash") == configuration and old.get("mock") == mock and old.get("candidate") in CRITERIA:
            row = dict(old)
        else:
            row = {"text_hash": digest, "config_hash": configuration, "at": datetime.now(timezone.utc).isoformat(),
                   "type": None, "candidate": None, "confidence": None, "probabilities": {}, "mock": mock}
            try:
                if mock:
                    row.update(_mock(unit))
                else:
                    response = (responses[unit.unit_id] if responses is not None and unit.unit_id in responses else jev_client.call_jev(
                        state=context_block(lesson_context(lesson_dir)) + f"\n\n[{unit.unit_id}] {unit.title}\n{unit.content}",
                        questions={"tipo_consigliato": jev_client.JevChoiceQuestion(instructions=INSTRUCTIONS, criteria=CRITERIA)},
                        job_name="question_types", unit_id=unit.unit_id, lesson_dir=lesson_dir,
                        model=classifier_jev(cfg, "question_types").relevance_model, credential=classifier_jev(cfg, "question_types").credential, base_url=classifier_jev(cfg, "question_types").base_url,
                        timeout_seconds=classifier_jev(cfg, "question_types").timeout_seconds))
                    answer = response.answers.get("tipo_consigliato")
                    if answer is None or answer.type != "choice" or answer.choice not in CRITERIA:
                        raise ValueError("Tipo consigliato non valido")
                    row.update(candidate=answer.choice, confidence=answer.confidence, probabilities=answer.probabilities)
            except Exception as exc:
                LOG.warning("Tipo consigliato %s: %s", unit.unit_id, exc)
                if ctx is not None:
                    ctx.emit(Notice(level="warning", message=f"Avviso: tipo consigliato non disponibile per l’unità {unit.unit_id}."))
        row["type"] = _compatible(row, owner.get(unit.unit_id), labels)
        result[unit.unit_id] = row
    try:
        with file_lock(fs.lock_path(_path(lesson_dir) + ".lock"), retries=100, backoff=.05):
            latest = _load(lesson_dir)
            # Una generazione su una parte conserva eventuali consigli aggiornati fuori da essa.
            for uid in set(result) - wanted:
                if uid in latest:
                    result[uid] = latest[uid]
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
    from rt.pipeline.rewrite import load_draft
    try:
        units = load_draft(lesson_dir).units
    except (OSError, ValueError):
        return {}
    owner, labels = _sections(lesson_dir, units)
    records, cfg_hash = _load(lesson_dir), _config_hash(classifier_jev(load_config(), "question_types"))
    return {u.unit_id: _compatible(records[u.unit_id], owner.get(u.unit_id), labels) for u in units
            if u.unit_id in records and records[u.unit_id].get("text_hash") == _text_hash(u, lesson_dir)
            and records[u.unit_id].get("config_hash") == cfg_hash}


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
