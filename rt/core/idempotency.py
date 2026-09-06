"""
rt.core.idempotency
Modulo deterministico per la gestione dell'idempotenza, fingerprinting estensibile,
freschezza degli artefatti e invalidazione a cascata nel workflow RT 2.0.
"""

import os
import json
import hashlib
from enum import Enum
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, List

from rt.core.models import Manifest
from rt.core.manifest import load_manifest, save_manifest


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
    "review_asr": "review_asr_v1.0",
    "review_science": "review_science_v1.0",
    "build": "build_v1.0",
}

# Dependency Graph formale del workflow RT 2.0.
# Spiegazione architetturale delle dipendenze:
# - outline dipende da prepare (ha bisogno dei segmenti temporali).
# - rewrite dipende da prepare e outline (rielabora i segmenti seguendo la struttura didattica).
# - review_asr dipende SOLO da prepare: analizza le ambiguità fonetiche direttamente sui segmenti grezzi
#   della lezione (segments.json), indipendentemente dal draft. Può quindi rimanere valida anche se il draft viene riscritto.
# - review_science dipende da prepare e rewrite: agisce come critic avversario indipendente confrontando il
#   draft rielaborato con la fonte originale (draft.json + segments.json). Se il draft cambia, la critica deve essere rigenerata.
# - build dipende da tutte le fasi precedenti (prepare, outline, rewrite, review_asr, review_science).
UPSTREAM_DEPENDENCIES = {
    "prepare": [],
    "outline": ["prepare"],
    "rewrite": ["prepare", "outline"],
    "review_asr": ["prepare"],
    "review_science": ["prepare", "rewrite"],
    "build": ["prepare", "outline", "rewrite", "review_asr", "review_science"],
}


def compute_file_sha256(path: str) -> str:
    """Calcola l'hash SHA256 di un file su disco in modo efficiente."""
    if not os.path.isfile(path):
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_string_sha256(text: str) -> str:
    """Calcola l'hash SHA256 di una stringa UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def find_raw_transcript_source(lesson_dir: str) -> Optional[str]:
    """Individua il file sorgente della trascrizione grezza."""
    candidates = [
        os.path.join(lesson_dir, "trascritto grezzo.json"),
        os.path.join(lesson_dir, "segments_raw.json"),
        os.path.join(lesson_dir, "transcript.json"),
        os.path.join(lesson_dir, "trascritto grezzo.md"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


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

    if phase_name == "prepare":
        raw_source = find_raw_transcript_source(lesson_dir)
        source_hash = compute_file_sha256(raw_source) if raw_source else "no_source"
        from rt.core.state import read_info_yaml
        yaml_path = os.path.join(lesson_dir, "info.yaml")
        info_str = ""
        if os.path.isfile(yaml_path):
            try:
                info = read_info_yaml(yaml_path)
                info_str = f"{info.get('data', '')}:{info.get('materia', '')}:{info.get('argomenti', '')}"
            except Exception:
                pass
        return compute_string_sha256(f"{source_hash}|{info_str}|{proc_ver}")

    elif phase_name == "outline":
        seg_path = os.path.join(lesson_dir, "segments.json")
        seg_hash = compute_file_sha256(seg_path)
        from rt.core.state import read_info_yaml
        yaml_path = os.path.join(lesson_dir, "info.yaml")
        info_str = ""
        if os.path.isfile(yaml_path):
            try:
                info = read_info_yaml(yaml_path)
                info_str = f"{info.get('data', '')}:{info.get('materia', '')}:{info.get('argomenti', '')}"
            except Exception:
                pass
        return compute_string_sha256(f"{seg_hash}|{info_str}|{proc_ver}")

    elif phase_name == "rewrite":
        seg_path = os.path.join(lesson_dir, "segments.json")
        out_path = os.path.join(lesson_dir, "outline.json")
        seg_hash = compute_file_sha256(seg_path)
        out_hash = compute_file_sha256(out_path)

        if target_unit_id:
            # Fingerprint mirato per la specifica unità didattica
            return compute_string_sha256(f"{seg_hash}|{out_hash}|unit:{target_unit_id}|{proc_ver}")
        return compute_string_sha256(f"{seg_hash}|{out_hash}|{proc_ver}")

    elif phase_name == "review_asr":
        seg_path = os.path.join(lesson_dir, "segments.json")
        seg_hash = compute_file_sha256(seg_path)
        from rt.core.config import load_config
        try:
            cfg = load_config()
            cfg_str = f"{cfg.thresholds.green}:{cfg.thresholds.yellow}"
        except Exception:
            cfg_str = "0.95:0.75"
        return compute_string_sha256(f"{seg_hash}|{cfg_str}|{proc_ver}")

    elif phase_name == "review_science":
        draft_path = os.path.join(lesson_dir, "draft.json")
        seg_path = os.path.join(lesson_dir, "segments.json")
        draft_hash = compute_file_sha256(draft_path)
        seg_hash = compute_file_sha256(seg_path)
        return compute_string_sha256(f"{draft_hash}|{seg_hash}|{proc_ver}")

    elif phase_name == "build":
        in_hashes = []
        for fn in ["segments.json", "outline.json", "draft.json", "asr_issues.json", "science_issues.json", "review_decisions.json"]:
            p = os.path.join(lesson_dir, fn)
            in_hashes.append(compute_file_sha256(p))
        return compute_string_sha256("|".join(in_hashes) + f"|{proc_ver}")

    return compute_string_sha256(f"unknown_{phase_name}|{proc_ver}")


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
        "review_asr": ["asr_issues.json"],
        "review_science": ["science_issues.json"],
        "build": [
            "pre-elaborato.md",
            "rielaborato.md",
            "Revisioni ASR.md",
            "Errori concettuali.md",
            "Problemi scientifici.md"
        ]
    }

    primary_files = phase_primary_artifacts.get(phase_name, [])
    for pf in primary_files:
        p = os.path.join(lesson_dir, pf)
        if not os.path.isfile(p):
            return PhaseStatus.MISSING, f"{pf} non trovato"

    # 2. Se l'artefatto esiste su disco, verifica ricorsivamente la dependency graph a monte:
    # se una fase a monte è non-VALID (STALE, INVALID, MISSING), l'artefatto esistente diventa STALE.
    if _visited is None:
        _visited = set()
    _visited.add(phase_name)

    upstream_deps = UPSTREAM_DEPENDENCIES.get(phase_name, [])
    for dep in upstream_deps:
        if dep in _visited:
            continue
        dep_status, dep_reason = check_phase_status(lesson_dir, dep, _visited=set(_visited))
        if dep_status != PhaseStatus.VALID:
            return PhaseStatus.STALE, f"Dipendenza a monte '{dep}' non valida ({dep_status.value}: {dep_reason})"

    if phase_name == "prepare":
        seg_path = os.path.join(lesson_dir, "segments.json")
        md_norm = os.path.join(lesson_dir, "transcript_normalized.md")
        if not os.path.isfile(seg_path) or not os.path.isfile(md_norm):
            return PhaseStatus.MISSING, "File segments.json o transcript_normalized.md mancante"
        try:
            from rt.core.segments import load_segments_json
            data = load_segments_json(seg_path)
            if not data.segments:
                return PhaseStatus.INVALID, "segments.json non contiene segmenti"
        except Exception as e:
            return PhaseStatus.INVALID, f"segments.json non valido o corrotto: {e}"

        current_fp = compute_source_fingerprint(lesson_dir, "prepare")
        recorded_fp = current_rec.get("source_fingerprint")
        if recorded_fp and recorded_fp != current_fp:
            return PhaseStatus.STALE, "Trascritto grezzo o metadati info.yaml modificati"
        return PhaseStatus.VALID, "segments.json valido e aggiornato"

    elif phase_name == "outline":
        out_path = os.path.join(lesson_dir, "outline.json")
        if not os.path.isfile(out_path):
            return PhaseStatus.MISSING, "outline.json non trovato"

        # Verifica se i segmenti sono validi
        seg_path = os.path.join(lesson_dir, "segments.json")
        if not os.path.isfile(seg_path):
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

        current_fp = compute_source_fingerprint(lesson_dir, "outline")
        recorded_fp = current_rec.get("source_fingerprint")
        if recorded_fp and recorded_fp != current_fp:
            return PhaseStatus.STALE, "segments.json o metadati modificati dopo la generazione dell'outline"
        return PhaseStatus.VALID, "outline.json valido e conforme ai segmenti"

    elif phase_name == "rewrite":
        draft_path = os.path.join(lesson_dir, "draft.json")
        if not os.path.isfile(draft_path):
            return PhaseStatus.MISSING, "draft.json non trovato"

        out_path = os.path.join(lesson_dir, "outline.json")
        seg_path = os.path.join(lesson_dir, "segments.json")
        if not os.path.isfile(out_path) or not os.path.isfile(seg_path):
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
            return PhaseStatus.STALE, "outline.json o segments.json modificati dopo la generazione del draft"

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

    elif phase_name == "review_asr":
        asr_path = os.path.join(lesson_dir, "asr_issues.json")
        if not os.path.isfile(asr_path):
            return PhaseStatus.MISSING, "asr_issues.json non trovato"

        try:
            from rt.pipeline.review_asr import load_asr_issues
            issues = load_asr_issues(lesson_dir)
        except Exception as e:
            return PhaseStatus.INVALID, f"asr_issues.json non valido: {e}"

        current_fp = compute_source_fingerprint(lesson_dir, "review_asr")
        recorded_fp = current_rec.get("source_fingerprint")
        if recorded_fp and recorded_fp != current_fp:
            return PhaseStatus.STALE, "segments.json o soglie configurazione modificate"

        # Controllo hash artefatto se parziale
        if current_rec.get("status") == PhaseStatus.PARTIAL.value:
            art_fps = current_rec.get("artifact_fingerprints", {})
            if "asr_issues.json" in art_fps:
                actual_h = compute_file_sha256(asr_path)
                if actual_h != art_fps["asr_issues.json"]:
                    return PhaseStatus.INVALID, "asr_issues.json modificato esternamente rispetto al checkpoint"

        if current_rec.get("status") == PhaseStatus.PARTIAL.value:
            completed_batches = current_rec.get("completed_items", [])
            return PhaseStatus.PARTIAL, f"asr_issues.json parziale ({len(completed_batches)} batch completati)"

        if current_rec.get("status") != PhaseStatus.VALID.value:
            return PhaseStatus.PARTIAL, f"asr_issues.json parziale ({len(issues)} issue registrate)"

        return PhaseStatus.VALID, f"asr_issues.json valido ({len(issues)} issue registrate)"

    elif phase_name == "review_science":
        sci_path = os.path.join(lesson_dir, "science_issues.json")
        if not os.path.isfile(sci_path):
            return PhaseStatus.MISSING, "science_issues.json non trovato"

        try:
            from rt.pipeline.review_science import load_science_issues
            issues = load_science_issues(lesson_dir)
        except Exception as e:
            return PhaseStatus.INVALID, f"science_issues.json non valido: {e}"

        current_fp = compute_source_fingerprint(lesson_dir, "review_science")
        recorded_fp = current_rec.get("source_fingerprint")
        if recorded_fp and recorded_fp != current_fp:
            return PhaseStatus.STALE, "draft.json o segments.json modificati dopo la revisione scientifica"

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
            "Revisioni ASR.md",
            "Errori concettuali.md",
            "Problemi scientifici.md"
        ]
        for rf in required_files:
            p = os.path.join(lesson_dir, rf)
            if not os.path.isfile(p) or os.path.getsize(p) == 0:
                return PhaseStatus.MISSING, f"Artefatto build mancante o vuoto: {rf}"

        current_fp = compute_source_fingerprint(lesson_dir, "build")
        recorded_fp = current_rec.get("source_fingerprint")
        if recorded_fp and recorded_fp != current_fp:
            return PhaseStatus.STALE, "Uno o più input della build (draft, outline, review, ledger) sono stati modificati"
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
            out_path = os.path.join(lesson_dir, "outline.json")
            draft_path = os.path.join(lesson_dir, "draft.json")
            if os.path.isfile(out_path) and os.path.isfile(draft_path):
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

    if artifact_fingerprints:
        rec_art = record.get("artifact_fingerprints", {})
        rec_art.update(artifact_fingerprints)
        record["artifact_fingerprints"] = rec_art

    if metadata:
        record.update(metadata)

    phase_records[phase_name] = record
    manifest.phase_records = phase_records
    save_manifest(manifest)


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
    save_manifest(manifest)


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

    current_fp = compute_source_fingerprint(lesson_dir, phase_name)
    recorded_fp = record.get("source_fingerprint")
    if not recorded_fp or recorded_fp != current_fp:
        return record, PhaseStatus.STALE, "Input a monte o configurazione modificati rispetto al checkpoint"

    art_fps = record.get("artifact_fingerprints", {})
    for fname, expected_hash in art_fps.items():
        fpath = os.path.join(lesson_dir, fname)
        if not os.path.isfile(fpath):
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
        "prepare": ["outline", "rewrite", "review_asr", "review_science", "build"],
        "outline": ["rewrite", "review_science", "build"],
        "rewrite": ["review_science", "build"],
        "review_asr": ["build"],
        "review_science": ["build"],
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
        rec["status"] = PhaseStatus.STALE.value
        rec["stale_reason"] = reason_text
        phase_records[ph] = rec
        invalidated.append(ph)

    manifest.phase_records = phase_records
    save_manifest(manifest)
    return invalidated
