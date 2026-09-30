"""Unità da cui il recaller genera il pool di domande di una lezione.

Di predefinito sono selezionate le unità rilevanti: quelle che il classificatore non ha
giudicato organizzative o senza contenuto e a cui non ha dato livello 0 (nessuna domanda).
Senza classificazione valgono tutte. La scelta dell'utente sta nel bank del recall
(`unit_selection`) insieme alle unità che esistevano quando l'ha fatta, così un'unità nuova
(bozza rielaborata) parte dalla selezione predefinita invece di restare esclusa.
"""
from typing import Dict, Iterable, List, Optional

from rt.pipeline.ledger import load_resolved_draft


def _units(lesson_dir: str) -> list:
    try:
        return list(load_resolved_draft(lesson_dir).units)
    except (FileNotFoundError, ValueError):
        return []


def suggested(signal: dict) -> bool:
    """Unità rilevante per il recall secondo il classificatore (nessun giudizio: sì)."""
    if signal.get("category") not in (None, "didactic"):
        return False
    return signal.get("level") != 0


def unit_rows(lesson_dir: str, units: Optional[list] = None) -> List[Dict]:
    """Per ogni unità: titolo, giudizio del classificatore, se è suggerita e se è selezionata."""
    from rt.pipeline.recall import load_recall_bank
    from rt.services.unit_relevance import _load, recall_signal
    units = _units(lesson_dir) if units is None else units
    records = _load(lesson_dir, "resolved")
    stored = load_recall_bank(lesson_dir).unit_selection or {}
    chosen, known = set(stored.get("selected") or []), set(stored.get("known") or [])
    rows = []
    for unit in units:
        signal = recall_signal(lesson_dir, unit, records)
        default = suggested(signal)
        custom = bool(stored) and unit.unit_id in known
        rows.append({"unit_id": unit.unit_id, "title": unit.title, **signal, "suggested": default,
                     "selected": unit.unit_id in chosen if custom else default})
    return rows


def selected_units(lesson_dir: str, units: Optional[list] = None) -> list:
    """Le unità selezionate, nell'ordine della lezione."""
    units = _units(lesson_dir) if units is None else units
    picked = {row["unit_id"] for row in unit_rows(lesson_dir, units) if row["selected"]}
    return [u for u in units if u.unit_id in picked]


def selected_unit_ids(lesson_dir: str) -> Optional[set]:
    """ID delle unità selezionate; None se la bozza non si legge (nessun filtro)."""
    units = _units(lesson_dir)
    if not units:
        return None
    return {u.unit_id for u in selected_units(lesson_dir, units)}


def set_selection(lesson_dir: str, unit_ids: Optional[Iterable[str]]) -> List[Dict]:
    """Salva la selezione (None: torna a quella predefinita). Ignora gli ID che non esistono."""
    from rt.pipeline.recall import load_recall_bank, recall_bank_lock, save_recall_bank
    units = _units(lesson_dir)
    current = [u.unit_id for u in units]
    with recall_bank_lock(lesson_dir):
        bank = load_recall_bank(lesson_dir)
        if unit_ids is None:
            bank.unit_selection = None
        else:
            wanted = set(unit_ids)
            bank.unit_selection = {"selected": [uid for uid in current if uid in wanted], "known": current}
        save_recall_bank(bank, lesson_dir)
    return unit_rows(lesson_dir, units)


def selection_view(lesson_dir: str) -> Dict:
    from rt.pipeline.recall import load_recall_bank
    from rt.services.unit_relevance import mode
    rows = unit_rows(lesson_dir)
    return {"units": rows, "custom": load_recall_bank(lesson_dir).unit_selection is not None,
            "classifier": mode(), "selected": sum(r["selected"] for r in rows)}
