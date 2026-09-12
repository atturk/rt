"""
tests/test_audio_run.py
Test End-to-End per il flusso con sorgente audio:
audio -> rt setup/ingest -> prepare -> outline -> rewrite -> reviews -> human review -> build.
Esegue a costo zero e offline con fixture audio 'tests/fixtures/demo_lecture.wav' e mock deterministico.
"""

import os
import json
import pytest
from unittest.mock import patch

from rt.cli import cmd_run, cmd_setup
from rt.pipeline.setup import run_setup, SetupError
from rt.pipeline.prepare import run_prepare
from rt.core.state import get_current_state, WorkflowState
from rt.core.idempotency import PhaseStatus, check_phase_status
from rt.core.lesson_paths import lesson_path


FIXTURE_AUDIO = os.path.abspath("tests/fixtures/demo_lecture.wav")


def test_audio_run_e2e_mock(tmp_path, capsys):
    """
    Test E2E a costo zero partendo direttamente da file audio:
    - Input: fixture audio 'tests/fixtures/demo_lecture.wav'
    - Flag: --mock --auto-accept
    - Risultato atteso: creazione automatica della cartella lezione e arrivo fino al build finale.
    """
    assert os.path.isfile(FIXTURE_AUDIO), f"Audio fixture mancante in: {FIXTURE_AUDIO}"
    dest_dir = str(tmp_path)

    from types import SimpleNamespace
    args = SimpleNamespace(
        input=[FIXTURE_AUDIO],
        date="2026-09-05",
        materia="IMMUNOLOGIA",
        argomenti="Risposta Innata Demo",
        dest_dir=dest_dir,
        model=None,
        skip_transcribe=False,
        force=False,
        mock=True,
        with_review=True,
        auto_accept=True,
        auto_accept_asr=None,
        auto_accept_science=None,
        rename=False
    )

    with patch("builtins.input", return_value="A"):
        cmd_run(args)
    captured = capsys.readouterr().out

    expected_folder_name = "[2026-09-05] IMMUNOLOGIA - Risposta Innata Demo"
    lesson_dir = os.path.join(dest_dir, expected_folder_name)
    assert os.path.isdir(lesson_dir), f"Cartella lezione non creata: {lesson_dir}"

    # 1. File sorgente creati da setup
    assert os.path.isfile(os.path.join(lesson_dir, "info.yaml"))
    assert os.path.isfile(os.path.join(lesson_dir, "demo_lecture.wav"))
    assert os.path.isfile(os.path.join(lesson_dir, "trascritto grezzo.json"))
    assert os.path.isfile(os.path.join(lesson_dir, "trascritto grezzo.md"))

    # 2. Artefatti intermedi della pipeline
    assert os.path.isfile(lesson_path(lesson_dir, "segments.json"))
    assert os.path.isfile(lesson_path(lesson_dir, "outline.json"))
    assert os.path.isfile(lesson_path(lesson_dir, "draft.json"))
    assert os.path.isfile(lesson_path(lesson_dir, "asr_issues.json"))
    assert os.path.isfile(lesson_path(lesson_dir, "science_issues.json"))
    assert os.path.isfile(lesson_path(lesson_dir, "review_decisions.json"))

    # 3. Artefatti finali di build
    assert os.path.isfile(lesson_path(lesson_dir, "pre-elaborato.md"))
    assert os.path.isfile(lesson_path(lesson_dir, "rielaborato.md"))
    assert os.path.isfile(os.path.join(lesson_dir, "Revisioni ASR.md"))
    assert os.path.isfile(os.path.join(lesson_dir, "Errori concettuali.md"))
    assert os.path.isfile(os.path.join(lesson_dir, "Problemi scientifici.md"))

    # 4. Stato finale completato
    state = get_current_state(os.path.join(lesson_dir, "info.yaml"))
    assert state == WorkflowState.COMPLETED
    assert "PIPELINE COMPLETATA CON SUCCESSO" in captured


def test_audio_skip_transcribe_creates_metadata_only(tmp_path):
    """
    Test del flag --skip-transcribe:
    - Crea la cartella e info.yaml in stato METADATA_ONLY.
    - Se si tenta di eseguire prepare senza ASR, prepare si arresta con errore diagnostico chiaro.
    """
    dest_dir = str(tmp_path)
    res = run_setup(
        audio=FIXTURE_AUDIO,
        date="2026-09-05",
        materia="VIROLOGIA",
        argomenti="Coronavirus",
        dest_dir=dest_dir,
        skip_transcribe=True,
        interactive=False
    )
    lesson_dir = res["lesson_dir"]
    assert res["status"] == "metadata_only"

    state = get_current_state(os.path.join(lesson_dir, "info.yaml"))
    assert state == WorkflowState.METADATA_ONLY

    # Prepare deve rifiutarsi di procedere senza trascritto ASR
    with pytest.raises(ValueError, match="Trascrizione non disponibile|METADATA_ONLY"):
        run_prepare(lesson_dir)


def test_existing_folder_protection_and_force(tmp_path):
    """
    Verifica che il setup rifiuti la sovrascrittura di una cartella già esistente
    senza il flag --force, e che con --force non distrugga review_decisions.json.
    """
    dest_dir = str(tmp_path)
    # Prima esecuzione setup
    res1 = run_setup(
        audio=FIXTURE_AUDIO,
        date="2026-09-05",
        materia="FARMACOLOGIA",
        argomenti="Farmacocinetica",
        dest_dir=dest_dir,
        mock_asr=True,
        interactive=False
    )
    lesson_dir = res1["lesson_dir"]

    # Simuliamo la presenza di review_decisions.json protetto
    decisions_path = os.path.join(lesson_dir, "review_decisions.json")
    with open(decisions_path, "w", encoding="utf-8") as f:
        json.dump({"decisions": [{"issue_id": "test_id", "action": "accetta"}]}, f)

    # Seconda esecuzione SENZA --force deve sollevare SetupError
    with pytest.raises(SetupError, match="esiste già"):
        run_setup(
            audio=FIXTURE_AUDIO,
            date="2026-09-05",
            materia="FARMACOLOGIA",
            argomenti="Farmacocinetica",
            dest_dir=dest_dir,
            mock_asr=True,
            force=False,
            interactive=False
        )

    # Con --force, l'esecuzione procede ma NON cancella review_decisions.json
    res_forced = run_setup(
        audio=FIXTURE_AUDIO,
        date="2026-09-05",
        materia="FARMACOLOGIA",
        argomenti="Farmacocinetica",
        dest_dir=dest_dir,
        mock_asr=True,
        force=True,
        interactive=False
    )
    assert res_forced["lesson_dir"] == lesson_dir
    assert os.path.isfile(decisions_path), "review_decisions.json protetto NON deve essere distrutto!"
    with open(decisions_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data["decisions"]) == 1
    assert data["decisions"][0]["issue_id"] == "test_id"


def test_audio_format_recognition(tmp_path):
    """
    Verifica che il sistema riconosca correttamente i principali formati audio (.wav, .m4a, .mp3)
    tramite is_audio_file e permetta l'inizializzazione del setup.
    """
    from rt.pipeline.setup import is_audio_file

    formats = [".wav", ".m4a", ".mp3"]
    for ext in formats:
        test_file = str(tmp_path / f"audio_sample{ext}")
        with open(test_file, "wb") as f:
            f.write(b"RIFF dummy audio content")
        assert is_audio_file(test_file), f"Formato {ext} non riconosciuto come file audio valido!"


def test_audio_run_with_custom_dest_dir(tmp_path, capsys):
    """
    Verifica che il flag -o/--dest-dir venga correttamente propagato da `rt run <audio>`:
    - Dest-dir personalizzata e non preesistente (es. sottocartella nidificata)
    - La cartella della lezione viene creata dentro dest-dir
    - L'intera pipeline prosegue usando esattamente quella cartella
    - Tutti gli artefatti obbligatori sono presenti su disco
    - Lo stato finale è COMPLETED e tutte le fasi sono VALID
    """
    assert os.path.isfile(FIXTURE_AUDIO), f"Audio fixture mancante in: {FIXTURE_AUDIO}"
    custom_dest = os.path.join(str(tmp_path), "nested", "custom_pipeline_output")
    assert not os.path.exists(custom_dest), "La cartella dest_dir non deve esistere a priori"

    from types import SimpleNamespace
    args = SimpleNamespace(
        input=[FIXTURE_AUDIO],
        date="2026-09-06",
        materia="BIOINFORMATICA",
        argomenti="Test Pipeline Custom Dest",
        dest_dir=custom_dest,
        model=None,
        skip_transcribe=False,
        force=False,
        mock=True,
        with_review=True,
        auto_accept=True,
        auto_accept_asr=None,
        auto_accept_science=None,
        rename=False
    )

    with patch("builtins.input", return_value="A"):
        cmd_run(args)
    captured = capsys.readouterr().out
    assert "PIPELINE COMPLETATA CON SUCCESSO" in captured

    expected_folder_name = "[2026-09-06] BIOINFORMATICA - Test Pipeline Custom Dest"
    expected_lesson_dir = os.path.join(custom_dest, expected_folder_name)
    assert os.path.isdir(expected_lesson_dir), f"La cartella deve essere creata sotto {custom_dest}"

    # Controllo tassativo di tutti gli 11 artefatti richiesti
    required_artifacts = [
        "info.yaml",
        "trascritto grezzo.json",
        "trascritto grezzo.md",
        "segments.json",
        "outline.json",
        "draft.json",
        "asr_issues.json",
        "science_issues.json",
        "review_decisions.json",
        "pre-elaborato.md",
        "rielaborato.md"
    ]
    for art in required_artifacts:
        art_path = lesson_path(expected_lesson_dir, art)
        assert os.path.isfile(art_path), f"Artefatto atteso mancante: {art} in {expected_lesson_dir}"

    # Controllo stato finale COMPLETED
    state = get_current_state(os.path.join(expected_lesson_dir, "info.yaml"))
    assert state == WorkflowState.COMPLETED

    # Controllo validità delle fasi
    for phase in ["prepare", "outline", "rewrite", "review", "build"]:
        p_stat, reason = check_phase_status(expected_lesson_dir, phase)
        assert p_stat == PhaseStatus.VALID, f"Fase {phase} non è VALID: {reason}"


def test_audio_setup_with_custom_dest_dir(tmp_path):
    """
    Verifica che il flag -o/--dest-dir venga rispettato anche da `rt setup <audio>`
    con una directory base di destinazione non ancora esistente.
    """
    custom_dest = os.path.join(str(tmp_path), "setup_only_output")
    assert not os.path.exists(custom_dest)

    from types import SimpleNamespace
    args = SimpleNamespace(
        audio=[FIXTURE_AUDIO],
        date="2026-09-06",
        materia="GENETICA",
        argomenti="Sequenziamento",
        dest_dir=custom_dest,
        model=None,
        skip_transcribe=False,
        force=False,
        mock=True
    )
    cmd_setup(args)

    expected_folder_name = "[2026-09-06] GENETICA - Sequenziamento"
    expected_lesson_dir = os.path.join(custom_dest, expected_folder_name)
    assert os.path.isdir(expected_lesson_dir), f"Cartella non creata sotto {custom_dest}"
    assert os.path.isfile(os.path.join(expected_lesson_dir, "info.yaml"))
    assert os.path.isfile(os.path.join(expected_lesson_dir, "trascritto grezzo.json"))


