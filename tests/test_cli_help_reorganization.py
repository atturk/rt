"""
Test per Task 61 — Riorganizzazione rt -h in italiano, senza ridondanze, con esempi.
"""
import pytest
from rt.cli import main


def test_cli_help_main_commands_and_no_positional_arguments(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["-h"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out

    # Non deve più contenere "positional arguments"
    assert "positional arguments" not in out

    # Deve contenere "Comandi principali"
    assert "Comandi principali:" in out

    # Deve contenere "Workflow per Rielaborazione Trascritti e Active Recall"
    assert "Workflow per Rielaborazione Trascritti e Active Recall" in out
    assert "Academic Lecture Transcription" not in out

    # Ordine dei 6 comandi principali
    pos_config = out.find("config")
    pos_run = out.find("run")
    pos_review = out.find("review")
    pos_recall = out.find("recall")
    pos_status = out.find("status")
    pos_tgd = out.find("telegram-daemon")

    assert pos_config != -1
    assert pos_run != -1
    assert pos_review != -1
    assert pos_recall != -1
    assert pos_status != -1
    assert pos_tgd != -1

    assert pos_config < pos_run < pos_review < pos_recall < pos_status < pos_tgd


def test_cli_help_pipeline_phases_in_separate_section(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["-h"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out

    assert "Fasi della pipeline:" in out

    # Separa le sezioni
    main_section = out.split("Fasi della pipeline:")[0]
    pipeline_section = out.split("Fasi della pipeline:")[1]

    for phase in ["setup", "prepare", "outline", "rewrite", "build", "add-images"]:
        assert phase not in main_section
        assert phase in pipeline_section


def test_cli_help_no_uso_avanzato_and_clean_headers(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["-h"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out

    assert "(uso avanzato)" not in out
    assert "Comandi diagnostici:" in out
    assert "cost" in out
    assert "validate-outline" in out
    assert "validate-draft" in out


def test_cli_help_examples_section(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["-h"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out

    assert "Esempi:" in out
    examples_block = out.split("Esempi:")[1]
    example_lines = [l.strip() for l in examples_block.strip().split("\n") if l.strip().startswith("rt ")]
    assert len(example_lines) >= 3


def test_subcommand_help_still_works(capsys):
    for subcmd in ["setup", "prepare", "outline", "rewrite", "build", "add-images", "validate-outline", "validate-draft", "cost"]:
        with pytest.raises(SystemExit) as exc_info:
            main([subcmd, "-h"])
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert f"usage: rt {subcmd}" in out
