"""
rt.core.idempotency
Modulo deterministico per la gestione dell'idempotenza, fingerprinting estensibile,
freschezza degli artefatti e invalidazione a cascata nel workflow RT 2.0.
"""

import os
import hashlib
import json
from enum import Enum
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, List

from rt.core.manifest import load_manifest, save_manifest
from rt.core.lesson_paths import lesson_path
from rt.storage import fs


class PhaseStatus(str, Enum):
    VALID = "VALID"
    PARTIAL = "PARTIAL"
    STALE = "STALE"
    MISSING = "MISSING"
    INVALID = "INVALID"


# Versioni dei processori/trasformazioni per consentire invalidazioni future (requisito 4)
PROCESSOR_VERSIONS = {
    "prepare": "prepare_v1.0",
    "outline": "outline_v1.0",
    "rewrite": "rewrite_v1.0",
    "review": "review_v1.2",
    "build": "build_v1.0",
}

# Dependency Graph formale del workflow RT 2.0.
# Spiegazione architetturale delle dipendenze:
# - outline dipende da prepare (ha bisogno dei segmenti temporali).
# - rewrite dipende da prepare e outline (rielabora i segmenti seguendo la struttura didattica).
# - review dipende da prepare e rewrite: agisce come critic avversario indipendente,
#   valutando il draft rielaborato (non vede più la trascrizione grezza, solo il draft).
#   Se il draft cambia, la critica deve essere rigenerata.
# - build dipende da prepare, outline e rewrite: è la conferma dell'utente che l'anteprima
#   (bozza con le decisioni prese e le immagini) diventa il documento finale. La review non
#   blocca: se è STALE, PARTIAL o ha issue pendenti o orfane il build si fa lo stesso e questi
#   problemi diventano avvisi (build_warnings). Il documento resta aggiornato finché non
#   cambiano bozza, scaletta, segmenti, decisioni prese o immagini (vedi BUILD_INPUT_FILES).
UPSTREAM_DEPENDENCIES = {
    "prepare": [],
    "outline": ["prepare"],
    "rewrite": ["prepare", "outline"],
    "review": ["prepare", "rewrite"],
    "build": ["prepare", "outline", "rewrite"],
}

# Posizionamento delle immagini nel documento (scritto da 'rt add-images', letto dal build).
IMAGE_PLACEMENT_FILE = "assets/images/placement.json"

# Input del documento finale: quello che cambia il testo dell'anteprima. science_issues.json
# non c'è: una nuova review non cambia il documento finché non si decide sulle sue issue.
BUILD_INPUT_FILES = ["segments.json", "outline.json", "draft.json", "review_decisions.json", IMAGE_PLACEMENT_FILE]
# Impronta del build fino a RT 4.0 (con science_issues.json e senza immagini): ancora
# accettata per i documenti creati prima, finché la lezione non ha immagini posizionate.
_LEGACY_BUILD_INPUT_FILES = ["segments.json", "outline.json", "draft.json", "science_issues.json", "review_decisions.json"]

# File di input per fase registrati con l'impronta (input_hashes), per dire nel motivo di uno
# stato STALE quale file è cambiato.
PHASE_INPUT_FILES = {
    "rewrite": ["segments.json", "outline.json"],
    "review": ["draft.json", "segments.json"],
    "build": BUILD_INPUT_FILES,
}

INPUT_LABELS = {
    "segments.json": "segmenti (segments.json)",
    "outline.json": "scaletta (outline.json)",
    "draft.json": "bozza (draft.json)",
    "review_decisions.json": "decisioni della revisione",
    IMAGE_PLACEMENT_FILE: "immagini",
}


def compute_file_sha256(path: str) -> str:
    """Calcola l'hash SHA256 di un file su disco in modo efficiente."""
    if not fs.isfile(path):
        return ""
    h = hashlib.sha256()
    with fs.open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_string_sha256(text: str) -> str:
    """Calcola l'hash SHA256 di una stringa UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def find_raw_transcript_source(lesson_dir: str) -> Optional[str]:
    """Individua il file sorgente della trascrizione grezza."""
    candidates = [
        lesson_path(lesson_dir, "trascritto grezzo.json"),
        lesson_path(lesson_dir, "segments_raw.json"),
        lesson_path(lesson_dir, "transcript.json"),
        lesson_path(lesson_dir, "trascritto grezzo.md"),
    ]
    for c in candidates:
        if fs.isfile(c):
            return c
    return None


def _info_fingerprint_strs(lesson_dir: str) -> List[str]:
    """Metadati di info.yaml che entrano nell'impronta di prepare e outline.

    Gli argomenti generati dall'outline (lezione nata senza argomenti) vengono scritti in
    info.yaml dal build: sono un prodotto della pipeline, non un input dell'utente, quindi
    finché coincidono con outline.generated_topics contano come argomenti vuoti. Vuoto può
    essere stato registrato come null o come '' a seconda di chi ha scritto info.yaml, per
    cui in quel caso si restituiscono entrambe le varianti."""
    from rt.core.state import read_info_yaml
    yaml_path = lesson_path(lesson_dir, "info.yaml")
    if not fs.isfile(yaml_path):
        return [""]
    try:
        info = read_info_yaml(yaml_path)
    except Exception:
        return [""]
    prefix = f"{info.get('data', '')}:{info.get('materia', '')}:"
    topics = info.get("argomenti", "")
    if topics and str(topics).strip():
        try:
            with fs.open(lesson_path(lesson_dir, "outline.json"), "r", encoding="utf-8") as f:
                generated = json.load(f).get("generated_topics") or []
        except (OSError, ValueError, AttributeError):
            generated = []
        if generated and str(topics).strip() == ", ".join(generated):
            return [prefix + "None", prefix]
    return [f"{prefix}{topics}"]


def _metadata_fingerprints(lesson_dir: str, phase_name: str) -> List[str]:
    """Impronte accettabili per prepare e outline, una per variante dei metadati."""
    proc_ver = PROCESSOR_VERSIONS.get(phase_name, "v1.0")
    if phase_name == "prepare":
        raw_source = find_raw_transcript_source(lesson_dir)
        source_hash = compute_file_sha256(raw_source) if raw_source else "no_source"
    else:
        source_hash = compute_file_sha256(lesson_path(lesson_dir, "segments.json"))
    return [
        compute_string_sha256(f"{source_hash}|{info_str}|{proc_ver}")
        for info_str in _info_fingerprint_strs(lesson_dir)
    ]


def compute_source_fingerprint(
    lesson_dir: str,
    phase_name: str,
    target_unit_id: Optional[str] = None
) -> str:
    """
    Calcola un'impronta deterministica ed estensibile per la fase specificata.
    Combina:
    1. SHA256 degli input upstream
    2. Versioning della trasformazione/prompt (PROCESSOR_VERSIONS)
    3. Parametri rilevanti di configurazione
    """
    proc_ver = PROCESSOR_VERSIONS.get(phase_name, "v1.0")

    if phase_name in ("prepare", "outline"):
        return _metadata_fingerprints(lesson_dir, phase_name)[0]

    if phase_name == "rewrite":
        seg_path = lesson_path(lesson_dir, "segments.json")
        out_path = lesson_path(lesson_dir, "outline.json")
        seg_hash = compute_file_sha256(seg_path)
        out_hash = compute_file_sha256(out_path)

        if target_unit_id:
            # Fingerprint mirato per la specifica unità didattica
            return compute_string_sha256(f"{seg_hash}|{out_hash}|unit:{target_unit_id}|{proc_ver}")
        return compute_string_sha256(f"{seg_hash}|{out_hash}|{proc_ver}")

    elif phase_name == "review":
        draft_path = lesson_path(lesson_dir, "draft.json")
        seg_path = lesson_path(lesson_dir, "segments.json")
        draft_hash = compute_file_sha256(draft_path)
        seg_hash = compute_file_sha256(seg_path)
        return compute_string_sha256(f"{draft_hash}|{seg_hash}|{proc_ver}")

    elif phase_name == "build":
        in_hashes = [compute_file_sha256(lesson_path(lesson_dir, fn)) for fn in BUILD_INPUT_FILES]
        return compute_string_sha256("|".join(in_hashes) + f"|inputs_v2|{proc_ver}")

    return compute_string_sha256(f"unknown_{phase_name}|{proc_ver}")


def _legacy_build_fingerprint(lesson_dir: str) -> Optional[str]:
    """Impronta del build nel formato precedente, valida solo senza immagini posizionate."""
    if fs.isfile(lesson_path(lesson_dir, IMAGE_PLACEMENT_FILE)):
        return None
    in_hashes = [compute_file_sha256(lesson_path(lesson_dir, fn)) for fn in _LEGACY_BUILD_INPUT_FILES]
    return compute_string_sha256("|".join(in_hashes) + f"|{PROCESSOR_VERSIONS['build']}")


def accepted_fingerprints(lesson_dir: str, phase_name: str) -> List[str]:
    """Impronte che rendono aggiornata la fase con i file attuali."""
    if phase_name in ("prepare", "outline"):
        return _metadata_fingerprints(lesson_dir, phase_name)
    accepted = [compute_source_fingerprint(lesson_dir, phase_name)]
    if phase_name == "build":
        legacy = _legacy_build_fingerprint(lesson_dir)
        if legacy:
            accepted.append(legacy)
    return accepted


def phase_input_hashes(lesson_dir: str, phase_name: str) -> Dict[str, str]:
    return {fn: compute_file_sha256(lesson_path(lesson_dir, fn)) for fn in PHASE_INPUT_FILES.get(phase_name, [])}


def stale_reason(lesson_dir: str, phase_name: str, record: Dict[str, Any], generic: str) -> str:
    """Motivo di un'impronta superata: versione del processore cambiata, oppure quali input
    sono cambiati (se registrati), altrimenti il motivo generico della fase."""
    recorded_ver = record.get("processor_version")
    current_ver = PROCESSOR_VERSIONS.get(phase_name)
    if recorded_ver and current_ver and recorded_ver != current_ver:
        return (f"Eseguita con una versione precedente di RT ({recorded_ver}, ora {current_ver}): "
                "va rifatta per aggiornarla")
    recorded = record.get("input_hashes")
    if isinstance(recorded, dict) and recorded:
        current = phase_input_hashes(lesson_dir, phase_name)
        changed = [fn for fn in PHASE_INPUT_FILES.get(phase_name, []) if recorded.get(fn, "") != current.get(fn, "")]
        if changed:
            return "Modificati dopo l'ultima esecuzione: " + ", ".join(INPUT_LABELS.get(fn, fn) for fn in changed)
    return generic


def check_phase_status(
    lesson_dir: str,
    phase_name: str,
    target_unit_id: Optional[str] = None,
    _visited: Optional[set] = None
) -> Tuple[PhaseStatus, str]:
    """
    Ispezione dinamica live dello stato di freschezza dell'artefatto.
    Verifica ricorsivamente la dependency graph a monte: se una fase a monte
    è non-VALID (STALE, INVALID, MISSING), la fase corrente risulterà STALE.
    Restituisce (PhaseStatus, motivo).
    """
    manifest = load_manifest(lesson_dir)
    phase_records = getattr(manifest, "phase_records", {}) if manifest else {}
    current_rec = phase_records.get(phase_name, {})

    # Se marcato esplicitamente STALE nel manifest da un'invalidazione precedente
    if current_rec.get("status") == PhaseStatus.STALE.value and not target_unit_id:
        reason = current_rec.get("stale_reason") or "Marcato esplicitamente STALE da modifica a monte"
        return PhaseStatus.STALE, reason

    # 1. Controllo preliminare di esistenza artefatto primario:
    # Se il file della fase non esiste affatto su disco, lo stato è tassativamente MISSING (non ancora generato).
    phase_primary_artifacts = {
        "prepare": ["segments.json", "transcript_normalized.md"],
        "outline": ["outline.json"],
        "rewrite": ["draft.json"],
        "review": ["science_issues.json"],
        "build": [
            "pre-elaborato.md",
            "rielaborato.md",
            "Errori concettuali.md"
        ]
    }

    primary_files = phase_primary_artifacts.get(phase_name, [])
    for pf in primary_files:
        p = lesson_path(lesson_dir, pf)
        if not fs.isfile(p):
            return PhaseStatus.MISSING, f"{pf} non trovato"

    # 2. Se l'artefatto esiste su disco, verifica ricorsivamente la dependency graph a monte:
    # se una fase a monte è non-VALID (STALE, INVALID, MISSING), l'artefatto esistente diventa STALE.
    if _visited is None:
        _visited = set()
    _visited.add(phase_name)

    # review è una fase opzionale (disaccoppiata dalla run di default):
    # se non è mai stata eseguita (MISSING), questo NON deve invalidare i discendenti
    # (es. build) — solo se era stata generata e poi diventata STALE/INVALID per
    # una modifica a monte deve continuare a propagarsi normalmente.
    OPTIONAL_UPSTREAM_DEPS = {"review"}

    upstream_deps = UPSTREAM_DEPENDENCIES.get(phase_name, [])
    for dep in upstream_deps:
        if dep in _visited:
            continue
        dep_status, dep_reason = check_phase_status(lesson_dir, dep, _visited=set(_visited))
        if dep_status == PhaseStatus.MISSING and dep in OPTIONAL_UPSTREAM_DEPS:
            continue
        if dep_status != PhaseStatus.VALID:
            return PhaseStatus.STALE, f"Dipendenza a monte '{dep}' non valida ({dep_status.value}: {dep_reason})"

    if phase_name == "prepare":
        seg_path = lesson_path(lesson_dir, "segments.json")
        md_norm = lesson_path(lesson_dir, "transcript_normalized.md")
        if not fs.isfile(seg_path) or not fs.isfile(md_norm):
            return PhaseStatus.MISSING, "File segments.json o transcript_normalized.md mancante"
        try:
            from rt.core.segments import load_segments_json
            data = load_segments_json(seg_path)
            if not data.segments:
                return PhaseStatus.INVALID, "segments.json non contiene segmenti"
        except Exception as e:
            return PhaseStatus.INVALID, f"segments.json non valido o corrotto: {e}"

        recorded_fp = current_rec.get("source_fingerprint")
        if recorded_fp and recorded_fp not in _metadata_fingerprints(lesson_dir, "prepare"):
            return PhaseStatus.STALE, "Trascritto grezzo o metadati info.yaml modificati"
        return PhaseStatus.VALID, "segments.json valido e aggiornato"

    elif phase_name == "outline":
        out_path = lesson_path(lesson_dir, "outline.json")
        if not fs.isfile(out_path):
            return PhaseStatus.MISSING, "outline.json non trovato"

        # Verifica se i segmenti sono validi
        seg_path = lesson_path(lesson_dir, "segments.json")
        if not fs.isfile(seg_path):
            return PhaseStatus.STALE, "segments.json mancante"

        try:
            from rt.pipeline.outline import load_outline
            from rt.core.segments import load_segments_json
            from rt.pipeline.validator import validate_outline
            outline = load_outline(lesson_dir)
            seg_data = load_segments_json(seg_path)
            validate_outline(outline, seg_data)
        except Exception as e:
            return PhaseStatus.INVALID, f"outline.json non valido rispetto ai segmenti: {e}"

        recorded_fp = current_rec.get("source_fingerprint")
        if recorded_fp and recorded_fp not in _metadata_fingerprints(lesson_dir, "outline"):
            return PhaseStatus.STALE, "segments.json o metadati modificati dopo la generazione dell'outline"
        return PhaseStatus.VALID, "outline.json valido e conforme ai segmenti"

    elif phase_name == "rewrite":
        draft_path = lesson_path(lesson_dir, "draft.json")
        if not fs.isfile(draft_path):
            return PhaseStatus.MISSING, "draft.json non trovato"

        out_path = lesson_path(lesson_dir, "outline.json")
        seg_path = lesson_path(lesson_dir, "segments.json")
        if not fs.isfile(out_path) or not fs.isfile(seg_path):
            return PhaseStatus.STALE, "outline.json o segments.json mancante"

        try:
            from rt.pipeline.rewrite import load_draft
            from rt.pipeline.outline import load_outline
            from rt.core.segments import load_segments_json
            from rt.pipeline.validator import validate_draft
            draft = load_draft(lesson_dir)
            outline = load_outline(lesson_dir)
            seg_data = load_segments_json(seg_path)
            val_report = validate_draft(draft, outline, seg_data)
        except Exception as e:
            return PhaseStatus.INVALID, f"draft.json non valido: {e}"

        current_fp = compute_source_fingerprint(lesson_dir, "rewrite")
        recorded_fp = current_rec.get("source_fingerprint")
        if recorded_fp and recorded_fp != current_fp:
            return PhaseStatus.STALE, stale_reason(
                lesson_dir, "rewrite", current_rec, "outline.json o segments.json modificati dopo la generazione del draft")

        # Se richiesta specifica unità
        if target_unit_id:
            unit_in_draft = next((u for u in draft.units if u.unit_id == target_unit_id), None)
            if not unit_in_draft:
                return PhaseStatus.MISSING, f"Unità {target_unit_id} non trovata nel draft"
            unit_fps = current_rec.get("unit_fingerprints", {})
            current_u_fp = compute_source_fingerprint(lesson_dir, "rewrite", target_unit_id=target_unit_id)
            recorded_u_fp = unit_fps.get(target_unit_id)
            if recorded_u_fp and recorded_u_fp != current_u_fp:
                return PhaseStatus.STALE, f"Segmenti o contesto per unità {target_unit_id} modificati"
            return PhaseStatus.VALID, f"Unità {target_unit_id} nel draft valida e aggiornata"

        # Controllo completezza globale
        all_units_count = val_report.get("expected_units_count", len(outline.macro_sections))
        draft_units_count = val_report.get("draft_units_count", len(draft.units))
        is_complete = val_report.get("all_units_covered", False)

        # Verifica coerenza hash se registrato come parziale
        if current_rec.get("status") == PhaseStatus.PARTIAL.value:
            art_fps = current_rec.get("artifact_fingerprints", {})
            if "draft.json" in art_fps:
                actual_h = compute_file_sha256(draft_path)
                if actual_h != art_fps["draft.json"]:
                    return PhaseStatus.INVALID, "draft.json modificato esternamente rispetto al checkpoint registrato"

        if not is_complete or current_rec.get("status") != PhaseStatus.VALID.value:
            if draft_units_count > 0:
                return PhaseStatus.PARTIAL, f"draft.json parziale ({draft_units_count}/{all_units_count} unità completate)"
            return PhaseStatus.MISSING, "draft.json non contiene unità valide"

        return PhaseStatus.VALID, f"draft.json valido ({draft_units_count} unità verificate)"

    elif phase_name == "review":
        sci_path = lesson_path(lesson_dir, "science_issues.json")
        if not fs.isfile(sci_path):
            return PhaseStatus.MISSING, "science_issues.json non trovato"

        try:
            from rt.pipeline.review import load_science_issues
            issues = load_science_issues(lesson_dir)
        except Exception as e:
            return PhaseStatus.INVALID, f"science_issues.json non valido: {e}"

        current_fp = compute_source_fingerprint(lesson_dir, "review")
        recorded_fp = current_rec.get("source_fingerprint")
        if recorded_fp and recorded_fp != current_fp:
            return PhaseStatus.STALE, stale_reason(
                lesson_dir, "review", current_rec, "draft.json o segments.json modificati dopo la revisione scientifica")

        # Controllo hash artefatto se parziale
        if current_rec.get("status") == PhaseStatus.PARTIAL.value:
            art_fps = current_rec.get("artifact_fingerprints", {})
            if "science_issues.json" in art_fps:
                actual_h = compute_file_sha256(sci_path)
                if actual_h != art_fps["science_issues.json"]:
                    return PhaseStatus.INVALID, "science_issues.json modificato esternamente rispetto al checkpoint"

        # Controllo completezza rispetto a draft.json
        try:
            from rt.pipeline.rewrite import load_draft
            draft = load_draft(lesson_dir)
            total_draft_units = len(draft.units)
        except Exception:
            total_draft_units = 0

        reviewed_units = current_rec.get("completed_items", [])
        if current_rec.get("status") == PhaseStatus.PARTIAL.value or len(reviewed_units) < total_draft_units or current_rec.get("status") != PhaseStatus.VALID.value:
            return PhaseStatus.PARTIAL, f"science_issues.json parziale ({len(reviewed_units)}/{total_draft_units} unità verificate)"

        return PhaseStatus.VALID, f"science_issues.json valido ({len(issues)} issue registrate)"

    elif phase_name == "build":
        required_files = [
            "pre-elaborato.md",
            "rielaborato.md",
            "Errori concettuali.md"
        ]
        for rf in required_files:
            p = lesson_path(lesson_dir, rf)
            if not fs.isfile(p) or fs.getsize(p) == 0:
                return PhaseStatus.MISSING, f"Artefatto build mancante o vuoto: {rf}"

        recorded_fp = current_rec.get("source_fingerprint")
        if recorded_fp and recorded_fp not in accepted_fingerprints(lesson_dir, "build"):
            return PhaseStatus.STALE, stale_reason(
                lesson_dir, "build", current_rec,
                "Uno o più input del documento (bozza, scaletta, decisioni, immagini) sono stati modificati")
        return PhaseStatus.VALID, "Documenti Markdown finali completi e aggiornati"

    return PhaseStatus.MISSING, f"Fase sconosciuta: {phase_name}"


def record_phase_fingerprint(
    lesson_dir: str,
    phase_name: str,
    source_fingerprint: str,
    artifact_fingerprints: Optional[Dict[str, str]] = None,
    unit_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> None:
    """
    Registra in modo atomico nel manifest.json l'impronta e lo stato VALID per la fase (o aggiorna una singola unità).
    """
    manifest = load_manifest(lesson_dir)
    if not manifest:
        return

    phase_records = getattr(manifest, "phase_records", {}) or {}
    record = phase_records.get(phase_name, {})

    record["stale_reason"] = None
    if unit_id:
        unit_fps = record.get("unit_fingerprints", {})
        unit_fps[unit_id] = source_fingerprint
        record["unit_fingerprints"] = unit_fps
        # Se viene aggiornata una singola unità, calcola l'impronta globale
        global_fp = compute_source_fingerprint(lesson_dir, phase_name)
        record["source_fingerprint"] = global_fp

        completed = record.get("completed_items") or []
        if unit_id not in completed:
            completed.append(unit_id)
        record["completed_items"] = completed

        # Non impostare ciecamente VALID se mancano altre unità
        is_fully_complete = False
        if phase_name == "rewrite":
            out_path = lesson_path(lesson_dir, "outline.json")
            draft_path = lesson_path(lesson_dir, "draft.json")
            if fs.isfile(out_path) and fs.isfile(draft_path):
                try:
                    from rt.pipeline.outline import load_outline
                    from rt.pipeline.rewrite import load_draft
                    out = load_outline(lesson_dir)
                    d = load_draft(lesson_dir)
                    all_out_units = [u.id for m in out.macro_sections for u in m.units]
                    draft_unit_ids = {u.unit_id for u in d.units}
                    is_fully_complete = all(uid in draft_unit_ids for uid in all_out_units)
                except Exception:
                    is_fully_complete = False

        if is_fully_complete:
            record["status"] = PhaseStatus.VALID.value
        else:
            record["status"] = PhaseStatus.PARTIAL.value
    else:
        record["status"] = PhaseStatus.VALID.value
        record["source_fingerprint"] = source_fingerprint

    record["processor_version"] = PROCESSOR_VERSIONS.get(phase_name, "v1.0")
    record["updated_at"] = datetime.now().isoformat()
    if phase_name in PHASE_INPUT_FILES:
        record["input_hashes"] = phase_input_hashes(lesson_dir, phase_name)

    if artifact_fingerprints:
        rec_art = record.get("artifact_fingerprints", {})
        rec_art.update(artifact_fingerprints)
        record["artifact_fingerprints"] = rec_art

    if metadata:
        record.update(metadata)

    phase_records[phase_name] = record
    manifest.phase_records = phase_records
    save_manifest(manifest, lesson_dir)


def record_phase_checkpoint(
    lesson_dir: str,
    phase_name: str,
    source_fingerprint: str,
    artifact_fingerprints: Optional[Dict[str, str]] = None,
    completed_items: Optional[List[Any]] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> None:
    """
    Registra in modo atomico nel manifest.json un checkpoint parziale (PARTIAL)
    per una fase iterativa (rewrite, review_science, review_asr).
    """
    manifest = load_manifest(lesson_dir)
    if not manifest:
        return

    phase_records = getattr(manifest, "phase_records", {}) or {}
    record = phase_records.get(phase_name, {})

    record["status"] = PhaseStatus.PARTIAL.value
    record["stale_reason"] = None
    record["source_fingerprint"] = source_fingerprint
    record["processor_version"] = PROCESSOR_VERSIONS.get(phase_name, "v1.0")
    record["updated_at"] = datetime.now().isoformat()
    if phase_name in PHASE_INPUT_FILES:
        record["input_hashes"] = phase_input_hashes(lesson_dir, phase_name)

    if artifact_fingerprints:
        rec_art = record.get("artifact_fingerprints", {})
        rec_art.update(artifact_fingerprints)
        record["artifact_fingerprints"] = rec_art

    if completed_items is not None:
        record["completed_items"] = completed_items

    if metadata:
        record.update(metadata)

    phase_records[phase_name] = record
    manifest.phase_records = phase_records
    save_manifest(manifest, lesson_dir)


def get_phase_checkpoint(
    lesson_dir: str,
    phase_name: str
) -> Tuple[Optional[Dict[str, Any]], Optional[PhaseStatus], str]:
    """
    Recupera e valida la coerenza del checkpoint per la fase specificata.
    Ritorna (checkpoint_dict, status, reason).
    """
    manifest = load_manifest(lesson_dir)
    if not manifest:
        return None, PhaseStatus.MISSING, "manifest.json non trovato"

    phase_records = getattr(manifest, "phase_records", {}) or {}
    record = phase_records.get(phase_name)
    if not record:
        return None, PhaseStatus.MISSING, f"Nessun checkpoint per fase {phase_name}"

    recorded_fp = record.get("source_fingerprint")
    accepted = accepted_fingerprints(lesson_dir, phase_name)
    if not recorded_fp or recorded_fp not in accepted:
        return record, PhaseStatus.STALE, "Input a monte o configurazione modificati rispetto al checkpoint"

    art_fps = record.get("artifact_fingerprints", {})
    for fname, expected_hash in art_fps.items():
        fpath = lesson_path(lesson_dir, fname)
        if not fs.isfile(fpath):
            return record, PhaseStatus.MISSING, f"Artefatto {fname} del checkpoint non trovato su disco"
        actual_hash = compute_file_sha256(fpath)
        if actual_hash != expected_hash:
            return record, PhaseStatus.INVALID, f"Hash di {fname} ({actual_hash[:8]}...) difforme dal checkpoint ({expected_hash[:8]}...)"

    status_str = record.get("status", PhaseStatus.PARTIAL.value)
    try:
        p_status = PhaseStatus(status_str)
    except ValueError:
        p_status = PhaseStatus.PARTIAL

    return record, p_status, "Checkpoint valido"


def mark_downstream_stale(
    lesson_dir: str,
    from_phase: str,
    target_unit_id: Optional[str] = None
) -> List[str]:
    """
    Invalida e marca STALE in modo mirato solo gli artefatti downstream che dipendono da from_phase.
    Ritorna la lista dei nomi delle fasi invalidate.
    """
    downstream_map = {
        "prepare": ["outline", "rewrite", "review", "build"],
        "outline": ["rewrite", "review", "build"],
        "rewrite": ["review", "build"],
        # la review non invalida il documento: il build non ne dipende (vedi UPSTREAM_DEPENDENCIES)
        "review": [],
        "build": []
    }

    affected_phases = downstream_map.get(from_phase, [])
    if not affected_phases:
        return []

    manifest = load_manifest(lesson_dir)
    if not manifest:
        return []

    phase_records = getattr(manifest, "phase_records", {}) or {}

    reason_text = f"Input a monte '{from_phase}' modificato o rigenerato"
    if target_unit_id:
        reason_text = f"Unità {target_unit_id} in draft.json rigenerata"

    invalidated: List[str] = []
    for ph in affected_phases:
        rec = phase_records.get(ph, {})
        if not rec:
            # Mai eseguita: non c'è nulla da invalidare. Marcarla STALE comunque la
            # farebbe sembrare "generata ma superata" per sempre a chi legge lo stato
            # (es. compute_effective_workflow_state), anche se in realtà non è mai
            # stata generata affatto — rilevante ora che review_asr/review_science
            # sono fasi opzionali che possono non essere mai eseguite. check_phase_status
            # la valuterà comunque correttamente come MISSING finché non esiste il file.
            continue
        rec["status"] = PhaseStatus.STALE.value
        rec["stale_reason"] = reason_text
        phase_records[ph] = rec
        invalidated.append(ph)

    manifest.phase_records = phase_records
    save_manifest(manifest, lesson_dir)
    return invalidated
