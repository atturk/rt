"""
Unit e integration test per rt_setup.py e la corretta comparsa progressiva degli artefatti.
Verifica che rt_setup crei ESCLUSIVAMENTE i file sorgente e non artefatti di revisione/elaborazione.
"""

import os
import json
import subprocess
import pytest
from rt.pipeline.prepare import run_prepare
from rt.pipeline.outline import run_outline
from rt.pipeline.rewrite import run_rewrite
from rt.pipeline.review_asr import run_review_asr
from rt.pipeline.review_science import run_review_science
from rt.pipeline.build import run_build


def test_rt_setup_clean_initialization(tmp_path):
    dest_dir = str(tmp_path)
    
    # 1. Creiamo un file audio fittizio
    audio_file = os.path.join(dest_dir, "test_audio.m4a")
    with open(audio_file, "wb") as f:
        f.write(b"fake audio stream content")
        
    # 2. Eseguiamo rt_setup.py via subprocess con --skip-transcribe
    cmd = [
        "python3",
        "rt_setup.py",
        audio_file,
        "-d", "2026-09-05",
        "-m", "IMMUNOLOGIA",
        "-a", "Risposta innata e complemento",
        "-o", dest_dir,
        "--skip-transcribe"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"rt_setup.py fallito: {res.stderr}"
    
    folder_name = "[2026-09-05] IMMUNOLOGIA - Risposta innata e complemento"
    lecture_dir = os.path.join(dest_dir, folder_name)
    assert os.path.isdir(lecture_dir)
    
    # Per il test inseriamo anche trascritto grezzo.json (come prodotto da MacWhisper)
    json_path = os.path.join(lecture_dir, "trascritto grezzo.json")
    raw_mw_json = {
        "segments": [
            {"id": "s1", "start": 0, "end": 10000, "text": "Introduzione alla risposta innata."},
            {"id": "s2", "start": 10000, "end": 25000, "text": "Le vie di attivazione del complemento."}
        ]
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(raw_mw_json, f)
        
    # --- VERIFICA RIGOROSA DELLO STATO DOPO RT_SETUP ---
    # FILE CHE DEVONO ESSERE PRESENTI
    assert os.path.isfile(os.path.join(lecture_dir, "info.yaml")), "info.yaml deve essere presente"
    assert os.path.isfile(os.path.join(lecture_dir, "trascritto grezzo.md")), "trascritto grezzo.md deve essere presente"
    assert os.path.isfile(os.path.join(lecture_dir, "trascritto grezzo.json")), "trascritto grezzo.json deve essere presente"
    assert os.path.isfile(os.path.join(lecture_dir, "test_audio.m4a")), "L'audio deve essere presente nella cartella"
    
    # FILE CHE DEVONO ESSERE TASSATIVAMENTE ASSENTI DOPO SETUP
    forbidden_after_setup = [
        "Errori concettuali.md",
        "Revisioni ASR.md",
        "pre-elaborato.md",
        "rielaborato.md",
        "segments.json",
        "outline.json",
        "draft.json",
        "manifest.json",
        "asr_issues.json",
        "science_issues.json",
        "review_decisions.json"
    ]
    for filename in forbidden_after_setup:
        assert not os.path.exists(os.path.join(lecture_dir, filename)), f"{filename} NON deve essere presente dopo rt_setup!"
        
    # --- PASSO 2: RT PREPARE ---
    prep_res = run_prepare(lecture_dir)
    assert prep_res["status"] == "prepared"
    assert os.path.isfile(os.path.join(lecture_dir, "segments.json")), "segments.json deve essere creato solo da prepare"
    assert os.path.isfile(os.path.join(lecture_dir, "transcript_normalized.md"))
    assert os.path.isfile(os.path.join(lecture_dir, "manifest.json"))
    
    # Ancora assenti
    for filename in ["Errori concettuali.md", "Revisioni ASR.md", "pre-elaborato.md", "rielaborato.md", "outline.json", "draft.json"]:
        assert not os.path.exists(os.path.join(lecture_dir, filename)), f"{filename} non deve esistere dopo prepare!"
        
    # --- PASSO 3: RT OUTLINE ---
    out_res = run_outline(lecture_dir, force_mock=True)
    assert out_res["status"] == "outline_validated"
    assert os.path.isfile(os.path.join(lecture_dir, "outline.json")), "outline.json creato da outline"
    
    # Ancora assenti i file finali
    for filename in ["Errori concettuali.md", "Revisioni ASR.md", "pre-elaborato.md", "rielaborato.md", "draft.json"]:
        assert not os.path.exists(os.path.join(lecture_dir, filename)), f"{filename} non deve esistere dopo outline!"
        
    # --- PASSO 4: RT REWRITE ---
    rew_res = run_rewrite(lecture_dir, force_mock=True)
    assert rew_res["status"] == "draft_validated"
    assert os.path.isfile(os.path.join(lecture_dir, "draft.json")), "draft.json creato da rewrite"
    for filename in ["Errori concettuali.md", "Revisioni ASR.md", "pre-elaborato.md", "rielaborato.md"]:
        assert not os.path.exists(os.path.join(lecture_dir, filename)), f"{filename} non deve esistere dopo rewrite!"
        
    # --- PASSO 5 & 6: REVIEWS ---
    run_review_asr(lecture_dir, force_mock=True)
    assert os.path.isfile(os.path.join(lecture_dir, "asr_issues.json"))
    
    run_review_science(lecture_dir, force_mock=True)
    assert os.path.isfile(os.path.join(lecture_dir, "science_issues.json"))
    
    # I file Markdown finali sono ANCORA assenti prima del build
    for filename in ["Errori concettuali.md", "Revisioni ASR.md", "pre-elaborato.md", "rielaborato.md"]:
        assert not os.path.exists(os.path.join(lecture_dir, filename)), f"{filename} deve comparire SOLO con rt build!"
        
    # --- PASSO 7: RT BUILD ---
    bld_res = run_build(lecture_dir, rename_folder=False)
    assert bld_res["status"] == "completed"
    
    # ORA e solo ora i file Markdown finali devono esistere
    assert os.path.isfile(os.path.join(lecture_dir, "pre-elaborato.md"))
    assert os.path.isfile(os.path.join(lecture_dir, "rielaborato.md"))
    assert os.path.isfile(os.path.join(lecture_dir, "Revisioni ASR.md"))
    assert os.path.isfile(os.path.join(lecture_dir, "Errori concettuali.md"))
    assert os.path.isfile(os.path.join(lecture_dir, "Problemi scientifici.md"))


def test_macwhisper_failure_hard_fails(tmp_path):
    """
    Verifica che un fallimento irreversibile di MacWhisper provochi l'arresto immediato (hard-fail)
    sollevando SetupError, senza contrassegnare la lezione come completata o funzionante.
    """
    from unittest.mock import patch
    from rt.pipeline.setup import run_setup, SetupError

    dest_dir = str(tmp_path)
    audio_file = os.path.join(dest_dir, "test_audio.wav")
    with open(audio_file, "wb") as f:
        f.write(b"RIFF audio fake")

    # Mock per simulare fallimento MacWhisper CLI
    failed_proc = subprocess.CompletedProcess(
        args=["mw", "transcribe"],
        returncode=1,
        stdout="",
        stderr="Error: Model weights corrupted or MacWhisper crash"
    )

    with patch("shutil.which", return_value="/usr/local/bin/mw"):
        with patch("rt.pipeline.setup._run_mw_with_spinner", return_value=failed_proc):
            with pytest.raises(SetupError, match="Trascrizione MacWhisper JSON fallita"):
                run_setup(
                    audio=audio_file,
                    date="2026-09-05",
                    materia="PATOLOGIA",
                    argomenti="Infiammazione",
                    dest_dir=dest_dir,
                    interactive=False
                )


def test_run_setup_on_progress_callback(tmp_path):
    """
    Verifica che la callback on_progress riceva i messaggi corretti nell'ordine atteso
    sia con mock_asr che con trascrizione reale.
    """
    from unittest.mock import patch
    from rt.pipeline.setup import run_setup

    dest_dir = str(tmp_path)
    audio_file = os.path.join(dest_dir, "test_audio.wav")
    with open(audio_file, "wb") as f:
        f.write(b"RIFF audio fake")

    # 1. Con mock_asr=True: riceve SOLO la notifica di creazione cartella
    messages_mock = []
    run_setup(
        audio=audio_file,
        date="2026-09-05",
        materia="FARMACOLOGIA",
        argomenti="Farmacocinetica",
        dest_dir=dest_dir,
        mock_asr=True,
        interactive=False,
        on_progress=messages_mock.append
    )
    assert len(messages_mock) == 1
    assert "✔ Cartella lezione:" in messages_mock[0]
    assert "FARMACOLOGIA" in messages_mock[0]

    # 2. Con trascrizione reale (mockando _run_mw_with_spinner per simulare successo e scrittura file):
    messages_real = []

    def fake_mw_run(cmd, label):
        # Scrive il file di output fittizio atteso
        out_idx = cmd.index("-o") + 1
        out_file = cmd[out_idx]
        if out_file.endswith(".json"):
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump({"segments": [{"id": "s1", "start": 0, "end": 1000, "text": "Test"}], "text": "Test"}, f)
        elif out_file.endswith(".md"):
            with open(out_file, "w", encoding="utf-8") as f:
                f.write("Test markdown")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with patch("shutil.which", return_value="/usr/local/bin/mw"):
        with patch("rt.pipeline.setup._run_mw_with_spinner", side_effect=fake_mw_run):
            run_setup(
                audio=audio_file,
                date="2026-09-06",
                materia="ANATOMIA",
                argomenti="Apparato cardiovascolare",
                dest_dir=dest_dir,
                interactive=False,
                on_progress=messages_real.append
            )

    assert len(messages_real) == 2
    assert "✔ Cartella lezione:" in messages_real[0]
    assert "ANATOMIA" in messages_real[0]
    assert "[2/9] MACWHISPER TRANSCRIPTION" in messages_real[1]


def test_run_mw_with_spinner_polling():
    """
    Verifica che _run_mw_with_spinner esegua correttamente subprocess.Popen e ritorni CompletedProcess.
    """
    from unittest.mock import patch, MagicMock
    from rt.pipeline.setup import _run_mw_with_spinner

    mock_proc = MagicMock()
    # poll() restituisce None (running) la prima volta, poi 0 (terminato)
    mock_proc.poll.side_effect = [None, 0]
    mock_proc.communicate.return_value = ("fake stdout", "fake stderr")
    mock_proc.returncode = 0

    with patch("subprocess.Popen", return_value=mock_proc):
        with patch("time.sleep"):  # velocizza il test
            res = _run_mw_with_spinner(["echo", "hello"], "Test label")

    assert res.returncode == 0
    assert res.stdout == "fake stdout"
    assert res.stderr == "fake stderr"
    assert res.args == ["echo", "hello"]


def test_macwhisper_markdown_failure_is_soft(tmp_path, capsys):
    """
    Verifica che il fallimento dell'export Markdown di MacWhisper non sia bloccante (soft-fail)
    e stampi l'avviso chiaro con spiegazione che non ha impatto sulla pipeline.
    """
    from unittest.mock import patch
    from rt.pipeline.setup import run_setup

    dest_dir = str(tmp_path)
    audio_file = os.path.join(dest_dir, "test_soft.wav")
    with open(audio_file, "wb") as f:
        f.write(b"RIFF audio fake")

    def fake_mw_run(cmd, label):
        out_idx = cmd.index("-o") + 1
        out_file = cmd[out_idx]
        if out_file.endswith(".json"):
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump({"segments": [{"id": "s1", "start": 0, "end": 1000, "text": "Test"}], "text": "Test"}, f)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        elif out_file.endswith(".md"):
            # Fallimento dell'export markdown
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="Error exporting markdown")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with patch("shutil.which", return_value="/usr/local/bin/mw"):
        with patch("rt.pipeline.setup._run_mw_with_spinner", side_effect=fake_mw_run):
            res = run_setup(
                audio=audio_file,
                date="2026-09-07",
                materia="FISIOLOGIA",
                argomenti="Potenziale d'azione",
                dest_dir=dest_dir,
                interactive=False
            )

    assert res["status"] == "setup_completato"
    captured = capsys.readouterr()
    assert "Export Markdown di MacWhisper non riuscito (codice 1) — nessun impatto" in captured.out


def test_setup_optional_argomenti_empty(tmp_path):
    """Verifica che senza argomenti la cartella non abbia trattino finale e info.yaml abbia stringa vuota."""
    from rt.pipeline.setup import run_setup
    from rt.core.state import read_info_yaml

    dest_dir = str(tmp_path)
    audio_file = os.path.join(dest_dir, "test_empty_args.wav")
    with open(audio_file, "wb") as f:
        f.write(b"fake wav")

    res = run_setup(
        audio=audio_file,
        date="2026-09-07",
        materia="NEUROLOGIA",
        argomenti="",
        dest_dir=dest_dir,
        skip_transcribe=True,
        interactive=False
    )
    lesson_dir = res["lesson_dir"]
    folder_name = os.path.basename(lesson_dir)
    assert folder_name == "[2026-09-07] NEUROLOGIA"
    assert not folder_name.endswith(" - ")

    info = read_info_yaml(os.path.join(lesson_dir, "info.yaml"))
    assert info.get("argomenti") == ""
    assert info.get("materia") == "NEUROLOGIA"


def test_setup_argomenti_provided(tmp_path):
    """Verifica che con argomenti forniti la cartella mantenga il suffisso."""
    from rt.pipeline.setup import run_setup
    from rt.core.state import read_info_yaml

    dest_dir = str(tmp_path)
    audio_file = os.path.join(dest_dir, "test_provided_args.wav")
    with open(audio_file, "wb") as f:
        f.write(b"fake wav")

    res = run_setup(
        audio=audio_file,
        date="2026-09-07",
        materia="NEUROLOGIA",
        argomenti="Sinapsi chimiche",
        dest_dir=dest_dir,
        skip_transcribe=True,
        interactive=False
    )
    lesson_dir = res["lesson_dir"]
    folder_name = os.path.basename(lesson_dir)
    assert folder_name == "[2026-09-07] NEUROLOGIA - Sinapsi chimiche"

    info = read_info_yaml(os.path.join(lesson_dir, "info.yaml"))
    assert info.get("argomenti") == "Sinapsi chimiche"


def test_outline_prompt_and_manifest_with_empty_argomenti(tmp_path):
    """Verifica prompt LLM di outline e validazione manifest con topics=None."""
    from rt.llm.prompts import build_outline_user_prompt
    from rt.core.manifest import init_or_update_manifest
    from rt.core.models import Manifest

    # 1. Prompt con topics=None
    prompt_empty = build_outline_user_prompt("2026-09-07", "NEUROLOGIA", None, "[1] 00:00 - 01:00: Intro")
    first_line_empty = prompt_empty.strip().splitlines()[0]
    assert first_line_empty == "Lezione: [2026-09-07] NEUROLOGIA"
    assert " - " not in first_line_empty

    # 2. Prompt con topics stringa reale
    prompt_topics = build_outline_user_prompt("2026-09-07", "NEUROLOGIA", "Sinapsi", "[1] 00:00 - 01:00: Intro")
    first_line_topics = prompt_topics.strip().splitlines()[0]
    assert first_line_topics == "Lezione: [2026-09-07] NEUROLOGIA - Sinapsi"

    # 3. Manifest creation con topics=None non solleva ValidationError
    lesson_dir = str(tmp_path / "[2026-09-07] NEUROLOGIA")
    os.makedirs(lesson_dir, exist_ok=True)
    manifest = init_or_update_manifest(
        lesson_dir=lesson_dir,
        lesson_id="test_lesson",
        date="2026-09-07",
        subject="NEUROLOGIA",
        topics=None,
        current_state="preparato"
    )
    assert isinstance(manifest, Manifest)
    assert manifest.topics is None


def test_full_pipeline_with_empty_argomenti_e2e_mock(tmp_path):
    """Verifica che l'intera pipeline funzioni correttamente da capo a fondo senza argomenti."""
    from rt.pipeline.setup import run_setup
    from rt.pipeline.prepare import run_prepare
    from rt.pipeline.outline import run_outline
    from rt.pipeline.rewrite import run_rewrite
    from rt.pipeline.review_asr import run_review_asr
    from rt.pipeline.review_science import run_review_science
    from rt.pipeline.build import run_build

    dest_dir = str(tmp_path)
    audio_file = os.path.join(dest_dir, "test_e2e.wav")
    with open(audio_file, "wb") as f:
        f.write(b"fake wav e2e")

    setup_res = run_setup(
        audio=audio_file,
        date="2026-09-07",
        materia="FISIOLOGIA",
        argomenti="",
        dest_dir=dest_dir,
        mock_asr=True,
        interactive=False
    )
    lesson_dir = setup_res["lesson_dir"]
    assert os.path.basename(lesson_dir) == "[2026-09-07] FISIOLOGIA"

    # Prepare
    prep_res = run_prepare(lesson_dir)
    assert prep_res["status"] == "prepared"

    # Outline
    out_res = run_outline(lesson_dir, force_mock=True)
    assert out_res["status"] == "outline_validated"

    # Rewrite
    rew_res = run_rewrite(lesson_dir, force_mock=True)
    assert rew_res["status"] == "draft_validated"

    # Review ASR
    asr_res = run_review_asr(lesson_dir, force_mock=True)
    assert asr_res["status"] == "asr_review_completed"

    # Review Science
    sci_res = run_review_science(lesson_dir, force_mock=True)
    assert sci_res["status"] == "science_review_completed"

    # Build
    bld_res = run_build(lesson_dir)
    assert bld_res["status"] == "completed"
    assert os.path.isfile(os.path.join(lesson_dir, "rielaborato.md"))


