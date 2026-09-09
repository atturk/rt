"""
tests/test_lesson_paths.py
Riorganizzazione della cartella di lezione: rt.core.lesson_paths.lesson_path()
(punto di verità unico per i percorsi interni), retrocompatibilità con le lezioni
già costruite (layout piatto), e la rinomina della cartella a fine build.

Copertura:
1. lesson_path() — comportamento base (radice esistente, nuova lezione, cartelle)
2. Lezione "vecchia" (layout piatto pre-esistente) — nessuna migrazione, nessuno
   stato misto, la pipeline intera continua a funzionare leggendo/scrivendo in radice
3. Lezione nuova — la pipeline intera mette lo stato interno in _state/, i soli
   deliverable restano in radice
4. check_phase_status — stesso verdetto su layout vecchio e nuovo
5. Rinomina della cartella a fine build (successo, no-op, collisione)
"""
import os
import json
import pytest

from rt.core.lesson_paths import lesson_path, STATE_SUBDIR
from rt.core.models import SegmentsData, Segment, Draft, DraftUnit, Outline, OutlineMacro, OutlineUnit
from rt.core.manifest import init_or_update_manifest
from rt.pipeline.prepare import run_prepare
from rt.pipeline.outline import run_outline
from rt.pipeline.rewrite import run_rewrite
from rt.pipeline.review_asr import run_review_asr
from rt.pipeline.review_science import run_review_science
from rt.pipeline.build import run_build
from rt.core.idempotency import PhaseStatus, check_phase_status


# ---------------------------------------------------------------------------
# 1. lesson_path()
# ---------------------------------------------------------------------------

class TestLessonPath:
    def test_deliverable_always_root(self, tmp_path):
        lesson_dir = str(tmp_path)
        assert lesson_path(lesson_dir, "Revisioni ASR.md") == os.path.join(lesson_dir, "Revisioni ASR.md")

    def test_new_lesson_state_file_goes_to_state_subdir(self, tmp_path):
        lesson_dir = str(tmp_path)
        p = lesson_path(lesson_dir, "draft.json")
        assert p == os.path.join(lesson_dir, STATE_SUBDIR, "draft.json")
        assert os.path.isdir(os.path.join(lesson_dir, STATE_SUBDIR))

    def test_existing_root_file_wins_over_state_subdir(self, tmp_path):
        lesson_dir = str(tmp_path)
        with open(os.path.join(lesson_dir, "draft.json"), "w") as f:
            f.write("{}")
        p = lesson_path(lesson_dir, "draft.json")
        assert p == os.path.join(lesson_dir, "draft.json")
        assert not os.path.isdir(os.path.join(lesson_dir, STATE_SUBDIR))

    def test_directory_entry_uses_exists_not_isfile(self, tmp_path):
        """recall_audio_clips è una sottocartella, non un file: una lezione con quella
        cartella già presente in radice (creata prima di questa riorganizzazione) deve
        continuare a risolvere lì, non in _state/."""
        lesson_dir = str(tmp_path)
        os.makedirs(os.path.join(lesson_dir, "recall_audio_clips"))
        p = lesson_path(lesson_dir, "recall_audio_clips")
        assert p == os.path.join(lesson_dir, "recall_audio_clips")

    def test_repeated_calls_consistently_resolve_to_state(self, tmp_path):
        """Una volta che un file non esiste in radice, ogni chiamata successiva deve
        continuare a risolvere nello stesso posto in _state/ (nessuna ambiguità)."""
        lesson_dir = str(tmp_path)
        p1 = lesson_path(lesson_dir, "segments.json")
        with open(p1, "w") as f:
            f.write("{}")
        p2 = lesson_path(lesson_dir, "segments.json")
        assert p1 == p2 == os.path.join(lesson_dir, STATE_SUBDIR, "segments.json")


# ---------------------------------------------------------------------------
# Fixture: lezione minimale pronta per l'intera pipeline (force_mock)
# ---------------------------------------------------------------------------

def _fmt(seconds):
    return f"{int(seconds) // 60:02d}:{int(seconds) % 60:02d}"


def _write_new_lesson(lesson_dir, num_units=2):
    os.makedirs(lesson_dir, exist_ok=True)
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write(
            "data: '2026-09-09'\nmateria: TEST\nargomenti: Prova\n"
            "fase_corrente: setup_completato\nstato: setup_completato\n"
        )
    with open(os.path.join(lesson_dir, "trascritto grezzo.json"), "w", encoding="utf-8") as f:
        json.dump({"segments": [
            {"id": f"s{i}", "start": i * 1000, "end": i * 1000 + 900, "text": f"Segmento {i}."}
            for i in range(1, num_units + 1)
        ]}, f)


# ---------------------------------------------------------------------------
# 2. Lezione "vecchia" (layout piatto pre-esistente): tutto già in radice,
#    la pipeline deve continuare a leggere/scrivere lì senza mai spostare nulla.
# ---------------------------------------------------------------------------

def _flatten_state_dir(lesson_dir):
    """Sposta ogni file da <lesson_dir>/_state/ alla radice e rimuove la sottocartella,
    per simulare una lezione realmente 'vecchia': completamente costruita dal codice
    pre-riorganizzazione, quindi con OGNI file di stato già in radice (non solo alcuni,
    come sarebbe se li si pre-creasse a mano uno per uno prima di eseguire la pipeline —
    lesson_path() decide per singolo file, quindi la simulazione realistica di 'lezione
    vecchia' è costruirla per intero e poi appiattirla, non pre-piazzare a mano 1-2 file)."""
    import shutil
    state_dir = os.path.join(lesson_dir, STATE_SUBDIR)
    if not os.path.isdir(state_dir):
        return
    for name in os.listdir(state_dir):
        shutil.move(os.path.join(state_dir, name), os.path.join(lesson_dir, name))
    os.rmdir(state_dir)


class TestOldFlatLayoutStaysFlat:
    def test_resumed_pipeline_on_flattened_lesson_stays_flat(self, tmp_path):
        lesson_dir = str(tmp_path / "old_lesson")
        _write_new_lesson(lesson_dir)

        # 1. Costruisce la lezione per intero (finisce in _state/, come una lezione nuova).
        run_prepare(lesson_dir)
        run_outline(lesson_dir, force_mock=True)
        run_rewrite(lesson_dir, force_mock=True)
        run_review_asr(lesson_dir, force_mock=True)
        run_review_science(lesson_dir, force_mock=True)
        run_build(lesson_dir, rename_folder=False)
        assert os.path.isdir(os.path.join(lesson_dir, STATE_SUBDIR))

        # 2. Appiattisce tutto in radice: ora è indistinguibile da una lezione vecchia.
        _flatten_state_dir(lesson_dir)
        assert not os.path.isdir(os.path.join(lesson_dir, STATE_SUBDIR))
        assert os.path.isfile(os.path.join(lesson_dir, "segments.json"))
        assert os.path.isfile(os.path.join(lesson_dir, "draft.json"))
        assert os.path.isfile(os.path.join(lesson_dir, "rielaborato.md"))

        # 3. Ripetendo l'intera pipeline con --force, ogni fase deve continuare a
        # leggere/scrivere in radice: nessun FILE di stato deve finire in _state/, nessuno
        # stato misto. Nota: lesson_path() può creare la sottocartella _state/ vuota come
        # effetto collaterale di una semplice risoluzione di percorso per un file opzionale
        # mai esistito (es. review_decisions.json prima di qualunque decisione umana, letto
        # da load_ledger anche solo per un controllo) — una cartella vuota è innocua, quello
        # che conta davvero è che nessun file finisca lì per una lezione già tutta in radice.
        run_prepare(lesson_dir, force=True)
        run_outline(lesson_dir, force_mock=True)
        run_rewrite(lesson_dir, force_mock=True)
        run_review_asr(lesson_dir, force_mock=True)
        run_review_science(lesson_dir, force_mock=True)
        bld_res = run_build(lesson_dir, force=True, rename_folder=False)
        assert bld_res["status"] == "completed"

        state_dir = os.path.join(lesson_dir, STATE_SUBDIR)
        if os.path.isdir(state_dir):
            assert os.listdir(state_dir) == [], "nessun file di stato deve finire in _state/ per una lezione già tutta in radice"
        assert os.path.isfile(os.path.join(lesson_dir, "rielaborato.md"))
        assert os.path.isfile(os.path.join(lesson_dir, "pre-elaborato.md"))

    def test_check_phase_status_reads_flattened_lesson_correctly(self, tmp_path):
        lesson_dir = str(tmp_path / "old_lesson2")
        _write_new_lesson(lesson_dir)
        run_prepare(lesson_dir)
        run_outline(lesson_dir, force_mock=True)
        run_rewrite(lesson_dir, force_mock=True)
        run_review_asr(lesson_dir, force_mock=True)
        run_review_science(lesson_dir, force_mock=True)
        run_build(lesson_dir, rename_folder=False)
        _flatten_state_dir(lesson_dir)

        for phase in ("prepare", "outline", "rewrite", "review_asr", "review_science", "build"):
            status, reason = check_phase_status(lesson_dir, phase)
            assert status == PhaseStatus.VALID, f"{phase}: {reason}"


# ---------------------------------------------------------------------------
# 3. Lezione nuova: lo stato interno finisce in _state/, i deliverable in radice
# ---------------------------------------------------------------------------

class TestNewLessonUsesStateSubdir:
    def test_full_pipeline_places_internal_state_in_subdir(self, tmp_path):
        lesson_dir = str(tmp_path / "new_lesson")
        _write_new_lesson(lesson_dir)

        run_prepare(lesson_dir)
        state_dir = os.path.join(lesson_dir, STATE_SUBDIR)
        assert os.path.isfile(os.path.join(state_dir, "segments.json"))
        assert os.path.isfile(os.path.join(state_dir, "transcript_normalized.md"))
        assert not os.path.exists(os.path.join(lesson_dir, "segments.json"))

        run_outline(lesson_dir, force_mock=True)
        assert os.path.isfile(os.path.join(state_dir, "outline.json"))
        assert not os.path.exists(os.path.join(lesson_dir, "outline.json"))

        run_rewrite(lesson_dir, force_mock=True)
        assert os.path.isfile(os.path.join(state_dir, "draft.json"))

        run_review_asr(lesson_dir, force_mock=True)
        assert os.path.isfile(os.path.join(state_dir, "asr_issues.json"))

        run_review_science(lesson_dir, force_mock=True)
        assert os.path.isfile(os.path.join(state_dir, "science_issues.json"))

        bld_res = run_build(lesson_dir, rename_folder=False)
        assert bld_res["status"] == "completed"

        # Deliverable: SOLO in radice.
        assert os.path.isfile(os.path.join(lesson_dir, "Revisioni ASR.md"))
        assert os.path.isfile(os.path.join(lesson_dir, "Errori concettuali.md"))
        assert os.path.isfile(os.path.join(lesson_dir, "Problemi scientifici.md"))
        # Il file col titolo formale (il deliverable finale) è in radice...
        md_deliverables = [f for f in os.listdir(lesson_dir) if f.endswith(".md")]
        assert any(f not in ("Revisioni ASR.md", "Errori concettuali.md", "Problemi scientifici.md") for f in md_deliverables)
        # ...mentre rielaborato.md e pre-elaborato.md (intermedi) sono SOLO in _state/,
        # non duplicati anche in radice (era la ridondanza segnalata dall'utente).
        assert "rielaborato.md" not in md_deliverables
        assert "pre-elaborato.md" not in md_deliverables
        assert os.path.isfile(os.path.join(state_dir, "rielaborato.md"))
        assert os.path.isfile(os.path.join(state_dir, "pre-elaborato.md"))


# ---------------------------------------------------------------------------
# 4. check_phase_status: stesso verdetto su layout vecchio e nuovo
# ---------------------------------------------------------------------------

class TestIdempotencyParityAcrossLayouts:
    def test_build_phase_valid_on_both_layouts(self, tmp_path):
        # Nuova lezione (layout _state/)
        new_dir = str(tmp_path / "new")
        _write_new_lesson(new_dir)
        run_prepare(new_dir)
        run_outline(new_dir, force_mock=True)
        run_rewrite(new_dir, force_mock=True)
        run_review_asr(new_dir, force_mock=True)
        run_review_science(new_dir, force_mock=True)
        run_build(new_dir, rename_folder=False)
        status_new, _ = check_phase_status(new_dir, "build")
        assert status_new == PhaseStatus.VALID

        # Vecchia lezione (layout piatto) — stesso risultato finale
        old_dir = str(tmp_path / "old")
        _write_new_lesson(old_dir)
        segs = [
            Segment(id=f"seg_{i:06d}", index=i, start_seconds=float(i), end_seconds=float(i) + 0.9,
                    start_formatted=_fmt(i), end_formatted=_fmt(i + 0.9), text_raw=f"Segmento {i}.")
            for i in range(1, 3)
        ]
        seg_data = SegmentsData(schema_version="1.0", audio_file="a.mp3", audio_duration_seconds=10.0, segments=segs)
        with open(os.path.join(old_dir, "segments.json"), "w", encoding="utf-8") as f:
            json.dump(seg_data.model_dump(mode="json"), f)
        with open(os.path.join(old_dir, "transcript_normalized.md"), "w", encoding="utf-8") as f:
            f.write("# trascritto\n")
        run_prepare(old_dir, force=True)
        run_outline(old_dir, force_mock=True)
        run_rewrite(old_dir, force_mock=True)
        run_review_asr(old_dir, force_mock=True)
        run_review_science(old_dir, force_mock=True)
        run_build(old_dir, rename_folder=False)
        status_old, _ = check_phase_status(old_dir, "build")
        assert status_old == PhaseStatus.VALID


# ---------------------------------------------------------------------------
# 5. Rinomina della cartella a fine build
# ---------------------------------------------------------------------------

class TestBuildFolderRename:
    def _build_ready_lesson(self, lesson_dir):
        _write_new_lesson(lesson_dir)
        run_prepare(lesson_dir)
        run_outline(lesson_dir, force_mock=True)
        run_rewrite(lesson_dir, force_mock=True)
        run_review_asr(lesson_dir, force_mock=True)
        run_review_science(lesson_dir, force_mock=True)

    def test_renames_to_target_and_result_reflects_new_dir(self, tmp_path):
        lesson_dir = str(tmp_path / "provvisorio")
        self._build_ready_lesson(lesson_dir)

        res = run_build(lesson_dir, rename_folder=True)
        assert res["status"] == "completed"
        assert res["lesson_dir"] != lesson_dir
        assert os.path.isdir(res["lesson_dir"])
        assert not os.path.isdir(lesson_dir)
        assert os.path.basename(res["lesson_dir"]).startswith("[2026-09-09] TEST")

    def test_noop_when_already_correctly_named(self, tmp_path, capsys):
        # Costruisce prima con rename per ottenere il nome finale, poi rilancia
        # con force sulla stessa cartella già correttamente nominata.
        lesson_dir = str(tmp_path / "provvisorio2")
        self._build_ready_lesson(lesson_dir)
        first = run_build(lesson_dir, rename_folder=True)
        final_dir = first["lesson_dir"]

        second = run_build(final_dir, force=True, rename_folder=True)
        assert second["lesson_dir"] == final_dir
        assert os.path.isdir(final_dir)

    def test_collision_does_not_overwrite_or_crash(self, tmp_path):
        lesson_dir = str(tmp_path / "provvisorio3")
        self._build_ready_lesson(lesson_dir)

        # Copia della stessa lezione (stessa data/materia/titolo -> stesso nome target),
        # buildata per prima, per scoprire il nome target e farlo esistere già.
        import shutil
        probe_dir = str(tmp_path / "provvisorio3_probe")
        shutil.copytree(lesson_dir, probe_dir)
        probe_res = run_build(probe_dir, rename_folder=True)
        target_dir = probe_res["lesson_dir"]
        assert os.path.isdir(target_dir)

        # Ora la cartella target esiste già: build sulla cartella originale deve
        # rilevare la collisione, non sovrascrivere, e non crashare.
        res = run_build(lesson_dir, rename_folder=True)
        assert res["status"] == "completed"
        assert res["lesson_dir"] == lesson_dir  # non rinominata, collisione rilevata
        assert os.path.isdir(lesson_dir)
        assert os.path.isdir(target_dir)  # la cartella target preesistente resta intatta
