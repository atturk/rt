"""
rt.services.section_labels
Etichette nascoste delle unità per casi clinici ed esercizi.

Terminologia: qui "sezione" è la macro-sezione della scaletta (5), che l'utente chiama unità;
le sue "unità" del draft (5.1, 5.2) sono le subunità. Il classificatore (Jev, lo stesso modello
della rilevanza) legge l'intera sezione con una sola chiamata e due domande:

- esercizio, criterio stretto: un esercizio viene svolto o viene spiegato come si risolve una
  tipologia di esercizi ("continua" se prosegue quello della sezione precedente);
- caso clinico, criterio largo: il docente presenta uno o più pazienti, oppure il contenuto si
  presta a essere formulato come caso clinico.

Le etichette restano nella cache section_labels.json (impronta del testo e della configurazione,
come unit_relevance.json); una correzione dell'utente vale finché il testo non cambia. Nessuna
etichetta compare nello studio: servono solo al recaller dei casi e degli esercizi
(rt.pipeline.recall_special).
"""

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

LABEL_VERSION = "section-labels-1"
KINDS = ("esercizio", "caso")
ESERCIZIO_CRITERIA = {
    "nessuno": "Nessun esercizio svolto e nessuna spiegazione di come si risolve un tipo di esercizio: "
               "solo teoria, esempi citati di sfuggita o esercizi soltanto annunciati o assegnati.",
    "svolto": "Il docente svolge un esercizio (dati, passaggi, risultato) oppure spiega passo per passo "
              "come si risolve una tipologia di esercizi.",
    "continua": "La sezione prosegue un esercizio iniziato nella sezione precedente (passaggi successivi, "
                "conclusione o verifica dello stesso esercizio).",
}
ESERCIZIO_INSTRUCTIONS = (
    "Valuta un'intera sezione di una lezione universitaria riscritta: decidi se contiene un esercizio "
    "effettivamente svolto o la spiegazione del procedimento di una tipologia di esercizi. Il criterio è "
    "stretto: una formula o un esempio teorico non bastano, servono passaggi risolutivi."
)
CASO_CRITERIA = {
    "nessuno": "Il contenuto non riguarda pazienti, quadri clinici, diagnosi, fisiopatologia applicabile "
               "o terapie, e non si presta a diventare un caso clinico.",
    "esplicito": "Il docente presenta uno o più pazienti o situazioni cliniche concrete (ad esempio "
                 "'arriva in pronto soccorso un paziente con questi parametri').",
    "adattabile": "Nessun paziente esplicito, ma il contenuto (fisiopatologia, quadro diagnostico, "
                  "parametri, terapia) si presta bene a essere formulato come caso clinico.",
}
CASO_INSTRUCTIONS = (
    "Valuta un'intera sezione di una lezione universitaria riscritta: decidi se il docente presenta casi "
    "clinici o se il contenuto si presta a essere formulato come caso clinico per verificarne la "
    "comprensione. Il criterio è largo: in caso di dubbio tra nessuno e adattabile, scegli adattabile "
    "quando ci sono contenuti clinici applicabili a un paziente."
)
POSITIVE = {"esercizio": ("svolto", "continua"), "caso": ("esplicito", "adattabile")}
QUESTION_NAMES = {"esercizio": "esercizio", "caso": "caso_clinico"}


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


def _config_hash(cfg) -> str:
    return _hash([cfg.relevance_model, cfg.credential, cfg.base_url, ESERCIZIO_CRITERIA, CASO_CRITERIA,
                  ESERCIZIO_INSTRUCTIONS, CASO_INSTRUCTIONS])


def mode(force_mock: bool = False) -> str:
    """mock, active (il classificatore è configurato) o disabled: senza classificatore niente
    casi né esercizi (generarli su ogni sezione alla cieca costerebbe troppo)."""
    cfg = load_config()
    if force_mock or cfg.mock_llm:
        return "mock"
    return "active" if classifier_jev(cfg, "section_labels").relevance_model.strip() and classifier_jev(cfg, "section_labels").relevance_mode != "disabled" else "disabled"


def _mock_labels(section: dict) -> dict:
    """Etichette deterministiche per mock e test: parole chiave nel testo della sezione."""
    text = section_text(section).casefold()
    return {"esercizio": "svolto" if "esercizi" in text else "nessuno",
            "caso": "esplicito" if "paziente" in text else "nessuno"}


def _classify(lesson_dir: str, section: dict, cfg) -> dict:
    from rt.llm import jev_client
    from rt.services.recall_context import context_block, lesson_context
    state = (context_block(lesson_context(lesson_dir)) + "\n\n" + f"Sezione {section['id']}: {section['title']}\n\n"
             + section_text(section))
    response = jev_client.call_jev(
        state=state,
        questions={QUESTION_NAMES["esercizio"]: jev_client.JevChoiceQuestion(instructions=ESERCIZIO_INSTRUCTIONS,
                                                                               criteria=ESERCIZIO_CRITERIA),
                   QUESTION_NAMES["caso"]: jev_client.JevChoiceQuestion(instructions=CASO_INSTRUCTIONS,
                                                                          criteria=CASO_CRITERIA)},
        job_name="section_labels", unit_id=section["id"], lesson_dir=lesson_dir,
        model=classifier_jev(cfg, "section_labels").relevance_model, credential=classifier_jev(cfg, "section_labels").credential, base_url=classifier_jev(cfg, "section_labels").base_url,
        timeout_seconds=classifier_jev(cfg, "section_labels").timeout_seconds)
    out = {}
    for kind, criteria in (("esercizio", ESERCIZIO_CRITERIA), ("caso", CASO_CRITERIA)):
        answer = response.answers.get(QUESTION_NAMES[kind])
        if answer is None or answer.type != "choice" or answer.choice not in criteria:
            raise ValueError(f"Risposta del classificatore non valida per {kind}")
        out[kind] = answer.choice
        out[kind + "_confidence"] = answer.confidence
    return out


def refresh(lesson_dir: str, *, force_mock: bool = False, force: bool = False, progress=None) -> dict:
    """Classifica le sezioni cambiate (force: tutte). Un errore lascia la sezione senza etichette
    (nessun caso né esercizio) e si riprova alla generazione successiva."""
    current = mode(force_mock)
    if current == "disabled":
        return _load(lesson_dir)
    cfg = load_config()
    configuration = "mock" if current == "mock" else _config_hash(classifier_jev(cfg, "section_labels"))
    previous = _load(lesson_dir)
    result = {}
    for section in sections(lesson_dir):
        digest = _section_hash(lesson_dir, section)
        old = previous.get(section["id"], {})
        overrides = {k: old.get(k) for k in ("override_esercizio", "override_caso")} if old.get("text_hash") == digest else {}
        if not force and old.get("text_hash") == digest and old.get("config_hash") == configuration and not old.get("error"):
            result[section["id"]] = old
            continue
        now = datetime.now(timezone.utc).isoformat()
        row = {"text_hash": digest, "config_hash": configuration, "title": section["title"],
               "unit_ids": [u.unit_id for u in section["units"]], "error": None, "classified_at": now, **overrides}
        try:
            row.update(_mock_labels(section) if current == "mock" else _classify(lesson_dir, section, cfg))
        except Exception as exc:
            row.update({"esercizio": None, "caso": None, "error": str(exc)})
            LOG.warning("Classificatore delle unità %s: %s", section["id"], exc)
        if progress is not None:
            progress(f"Unità {section['id']}: esercizio {row.get('esercizio') or '?'}, caso {row.get('caso') or '?'}")
        result[section["id"]] = row
    try:
        with _lock(lesson_dir):
            latest = _load(lesson_dir)
            for sid, row in result.items():
                other = latest.get(sid, {})
                if other.get("text_hash") == row["text_hash"]:
                    for key in ("override_esercizio", "override_caso"):
                        if key in other:
                            row[key] = other[key]
            if result != latest:
                _save(lesson_dir, result)
    except (OSError, TimeoutError):
        LOG.exception("Impossibile salvare le etichette delle unità")
    return result


def effective(row: dict, kind: str) -> Optional[str]:
    override = row.get("override_" + kind)
    if override is not None:
        return override
    return row.get(kind)


def labels(lesson_dir: str, sections=None) -> Dict[str, dict]:
    """Etichette in vigore per le sezioni attuali (correzioni comprese); le sezioni il cui testo
    è cambiato dopo la classificazione restano senza etichette fino al prossimo refresh."""
    records = _load(lesson_dir)
    out = {}
    for section in (globals()["sections"](lesson_dir) if sections is None else sections):
        row = records.get(section["id"], {})
        if row.get("text_hash") != _section_hash(lesson_dir, section):
            continue
        out[section["id"]] = {kind: effective(row, kind) for kind in KINDS}
    return out


def view(lesson_dir: str, sections=None) -> dict:
    """Per la pagina Classificatore: sezioni con etichette previste, correzioni ed errori."""
    records = _load(lesson_dir)
    rows = []
    for section in (globals()["sections"](lesson_dir) if sections is None else sections):
        row = records.get(section["id"], {})
        fresh = row.get("text_hash") == _section_hash(lesson_dir, section)
        rows.append({"section_id": section["id"], "title": section["title"],
                     "unit_ids": [u.unit_id for u in section["units"]], "fresh": fresh,
                     "esercizio": row.get("esercizio") if fresh else None,
                     "caso": row.get("caso") if fresh else None,
                     "override_esercizio": row.get("override_esercizio") if fresh else None,
                     "override_caso": row.get("override_caso") if fresh else None,
                     "error": row.get("error") if fresh else None})
    return {"mode": mode(), "sections": rows,
            "options": {"esercizio": list(ESERCIZIO_CRITERIA), "caso": list(CASO_CRITERIA)}}


def set_override(lesson_dir: str, section_id: str, kind: str, value: Optional[str]) -> dict:
    """Corregge l'etichetta di una sezione (None: torna a quella del classificatore)."""
    if kind not in KINDS:
        raise ValueError("Etichetta non valida")
    criteria = ESERCIZIO_CRITERIA if kind == "esercizio" else CASO_CRITERIA
    if value is not None and value not in criteria:
        raise ValueError("Valore non valido")
    section = next((s for s in sections(lesson_dir) if s["id"] == section_id), None)
    if section is None:
        raise KeyError(section_id)
    digest = _section_hash(lesson_dir, section)
    with _lock(lesson_dir):
        records = _load(lesson_dir)
        row = records.get(section_id, {})
        if row.get("text_hash") != digest:
            row = {"text_hash": digest, "config_hash": None, "title": section["title"],
                   "unit_ids": [u.unit_id for u in section["units"]], "esercizio": None, "caso": None, "error": None}
        row["override_" + kind] = value
        records[section_id] = row
        _save(lesson_dir, records)
    return view(lesson_dir)
