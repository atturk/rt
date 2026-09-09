"""
tests/test_config_split.py
Suite di test per il caricamento modulare da cartella 'config/' e il pricing per-route.
"""

import os
import json
import pytest
from unittest.mock import patch, MagicMock
from pydantic import BaseModel

from rt.core.config import RouteConfig, JobRoutingConfig, RTConfig, load_config, find_job_yaml_paths, _load_config_dir
from rt.llm.pricing import ModelPricing, calculate_cost
from rt.llm.credentials import GLOBAL_CREDENTIALS, CredentialRef
from rt.llm.client import LLMClient
from rt.llm.telemetry import GLOBAL_TELEMETRY


class DummyResponseSchema(BaseModel):
    summary: str


def test_config_split_loads_identically_to_single_file(tmp_path, monkeypatch):
    """
    1. Verifica che una cartella config/ con general.yaml e file per-job produca
    un RTConfig equivalente a quello ottenuto da un unico rt.config.yaml.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    general_content = """version: "2.0.0"
pricing_staleness_warning_days: 3
mock_llm: false
streaming: true
show_monitor: true
retry:
  max_timeout_retries: 2
  timeout_backoff_seconds: 3.5
  idle_read_timeout_seconds: 50.0
thresholds:
  green: 0.96
  yellow: 0.80
"""
    (config_dir / "general.yaml").write_text(general_content, encoding="utf-8")

    outline_content = """max_attempts: 4
max_output_chars: 50000
primary:
  provider: "deepseek"
  model: "deepseek-v4-flash"
  thinking: true
  reasoning_effort: "low"
  timeout_seconds: 240
"""
    (config_dir / "outline.yaml").write_text(outline_content, encoding="utf-8")

    rewrite_content = """round_robin: false
max_attempts: 3
primary:
  provider: "google"
  credential: "google_1"
  model: "gemini-3.5-flash-lite"
  thinking: true
  reasoning_effort: "high"
  timeout_seconds: 180
"""
    (config_dir / "rewrite.yaml").write_text(rewrite_content, encoding="utf-8")

    # Single-file equivalent
    single_content = """version: "2.0.0"
pricing_staleness_warning_days: 3
mock_llm: false
streaming: true
show_monitor: true
retry:
  max_timeout_retries: 2
  timeout_backoff_seconds: 3.5
  idle_read_timeout_seconds: 50.0
thresholds:
  green: 0.96
  yellow: 0.80
jobs:
  outline:
    max_attempts: 4
    max_output_chars: 50000
    primary:
      provider: "deepseek"
      model: "deepseek-v4-flash"
      thinking: true
      reasoning_effort: "low"
      timeout_seconds: 240
  rewrite:
    round_robin: false
    max_attempts: 3
    primary:
      provider: "google"
      credential: "google_1"
      model: "gemini-3.5-flash-lite"
      thinking: true
      reasoning_effort: "high"
      timeout_seconds: 180
"""
    single_file = tmp_path / "rt.config.yaml"
    single_file.write_text(single_content, encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    # 1. Carica da config/ (senza path)
    cfg_split = load_config()

    # 2. Carica da singolo file con path esplicito
    cfg_single = load_config(str(single_file))

    assert cfg_split.version == cfg_single.version
    assert cfg_split.pricing_staleness_warning_days == 3
    assert cfg_split.retry.max_timeout_retries == 2
    assert cfg_split.retry.timeout_backoff_seconds == 3.5
    assert cfg_split.thresholds.green == 0.96
    assert cfg_split.thresholds.yellow == 0.80
    assert "outline" in cfg_split.jobs
    assert "rewrite" in cfg_split.jobs
    assert cfg_split.jobs["outline"].primary.model == "deepseek-v4-flash"
    assert cfg_split.jobs["rewrite"].primary.model == "gemini-3.5-flash-lite"
    assert cfg_split.model_dump() == cfg_single.model_dump()


def test_config_split_precedence_over_single_file(tmp_path, monkeypatch):
    """
    2. Verifica la precedenza: se sia config/ che rt.config.yaml esistono
    nella stessa working directory, la cartella config/ vince.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "general.yaml").write_text("pricing_staleness_warning_days: 42\n", encoding="utf-8")

    single_file = tmp_path / "rt.config.yaml"
    single_file.write_text("pricing_staleness_warning_days: 10\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    cfg = load_config()

    assert cfg.pricing_staleness_warning_days == 42


def test_explicit_config_path_ignores_config_dir(tmp_path, monkeypatch):
    """
    3. Verifica che con config_path esplicito, il comportamento sia invariato
    e carichi il singolo file indicato, anche se config/ esiste.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "general.yaml").write_text("pricing_staleness_warning_days: 99\n", encoding="utf-8")

    explicit_file = tmp_path / "custom_config.yaml"
    explicit_file.write_text("pricing_staleness_warning_days: 5\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    cfg = load_config(str(explicit_file))

    assert cfg.pricing_staleness_warning_days == 5


def test_credentials_registered_from_split_general_yaml(tmp_path, monkeypatch):
    """
    4. Verifica che credentials: in config/general.yaml vengano registrate
    correttamente in GLOBAL_CREDENTIALS prima della validazione delle RouteConfig.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    general_yaml = """
credentials:
  - name: "split_cred_test"
    provider: "openai_compatible"
    env_var: "SPLIT_CRED_KEY"
"""
    (config_dir / "general.yaml").write_text(general_yaml, encoding="utf-8")

    outline_yaml = """
primary:
  provider: "openai_compatible"
  credential: "split_cred_test"
  model: "test-model"
  base_url: "https://api.split-test.com/v1"
  timeout_seconds: 120
"""
    (config_dir / "outline.yaml").write_text(outline_yaml, encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    cfg = load_config()

    assert "outline" in cfg.jobs
    route = cfg.jobs["outline"].primary
    assert route.provider == "openai_compatible"
    assert route.credential == "split_cred_test"
    assert GLOBAL_CREDENTIALS.validate_credential("openai_compatible", "split_cred_test") is True
    assert GLOBAL_CREDENTIALS.get_env_var_name("split_cred_test") == "SPLIT_CRED_KEY"


def test_route_config_pricing_field():
    """
    5. Test per il campo pricing su RouteConfig (compresa validazione sub-model).
    """
    route = RouteConfig(
        provider="google",
        model="gemini-3.5-flash-lite",
        pricing={"input_per_million": 0.0, "output_per_million": 0.0}
    )
    assert route.pricing is not None
    assert isinstance(route.pricing, ModelPricing)
    assert route.pricing.input_per_million == 0.0
    assert route.pricing.output_per_million == 0.0
    assert route.pricing.reasoning_per_million is None


def test_llm_client_resolve_custom_pricing():
    """
    6. Test per LLMClient._resolve_custom_pricing: con una route che ha pricing impostato,
    il dizionario risultante deve contenere l'override per (provider, model) preservando
    le altre voci di config.pricing.
    """
    client = LLMClient(force_mock=True)
    client.config.pricing = {
        "google": {
            "gemini-pro-latest": {"input_per_million": 2.0, "output_per_million": 8.0}
        },
        "deepseek": {
            "deepseek-v4-flash": {"input_per_million": 0.14, "output_per_million": 0.28}
        }
    }

    # Route con pricing dedicato
    route_with_pricing = RouteConfig(
        provider="google",
        model="gemini-3.5-flash-lite",
        pricing=ModelPricing(input_per_million=0.01, output_per_million=0.02)
    )

    resolved = client._resolve_custom_pricing(route_with_pricing, "google", "gemini-3.5-flash-lite")
    assert resolved is not None
    assert "google" in resolved
    assert "gemini-3.5-flash-lite" in resolved["google"]
    assert resolved["google"]["gemini-3.5-flash-lite"]["input_per_million"] == 0.01
    assert resolved["google"]["gemini-3.5-flash-lite"]["output_per_million"] == 0.02
    # Preserva la voce preesistente di google
    assert resolved["google"]["gemini-pro-latest"]["input_per_million"] == 2.0
    # Preserva deepseek
    assert "deepseek" in resolved

    # Route senza pricing dedicato -> restituisce config.pricing immutato
    route_no_pricing = RouteConfig(
        provider="google",
        model="gemini-3.5-flash-lite"
    )
    resolved_none = client._resolve_custom_pricing(route_no_pricing, "google", "gemini-3.5-flash-lite")
    assert resolved_none == client.config.pricing


def test_end_to_end_route_pricing_telemetry(monkeypatch, tmp_path):
    """
    7. Test end-to-end: un job con route.pricing impostato a un valore volutamente
    diverso sia da DEFAULT_PRICING sia da cfg.pricing globale produce nella telemetria
    il costo stimato calcolato dal prezzo della route.
    """
    config_file = tmp_path / "rt.config.yaml"
    config_yaml = """
version: "2.0.0"
mock_llm: false
pricing:
  deepseek:
    deepseek-v4-flash:
      input_per_million: 99.0
      output_per_million: 99.0
jobs:
  outline:
    primary:
      provider: "deepseek"
      model: "deepseek-v4-flash"
      pricing:
        input_per_million: 10.0
        output_per_million: 20.0
      timeout_seconds: 60
"""
    config_file.write_text(config_yaml, encoding="utf-8")

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-test-key")

    client = LLMClient(config_path=str(config_file))

    mock_resp_json = {
        "id": "chatcmpl-test-pricing",
        "object": "chat.completion",
        "created": 123456789,
        "model": "deepseek-v4-flash",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"summary": "Test completato con successo."}),
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 1_000_000,
            "completion_tokens": 1_000_000,
            "total_tokens": 2_000_000,
        },
    }

    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.json.return_value = mock_resp_json
    mock_post_resp.text = json.dumps(mock_resp_json)

    with patch("requests.post", return_value=mock_post_resp):
        res = client.call_structured(
            job_name="outline",
            system_prompt="Sei un assistente.",
            prompt="Genera riassunto.",
            response_model=DummyResponseSchema,
            stream=False,
        )

        assert isinstance(res, DummyResponseSchema)
        assert res.summary == "Test completato con successo."

        # Verifica telemetria: il record più recente deve avere estimated_cost = 10.0 + 20.0 = 30.0
        last_rec = GLOBAL_TELEMETRY.get_last()
        assert last_rec is not None
        assert last_rec.job == "outline"
        assert last_rec.provider == "deepseek"
        assert last_rec.model == "deepseek-v4-flash"
        # 1M in * 10.0/M + 1M out * 20.0/M = 30.0 (non 0.42 di default, non 198.0 del globale)
        assert last_rec.estimated_cost == 30.0


def test_empty_config_dir_fallback(tmp_path, monkeypatch):
    """
    8. Verifica che una cartella config/ vuota o senza general.yaml
    non sollevi eccezioni e restituisca un RTConfig valido con default.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    monkeypatch.chdir(tmp_path)
    cfg = load_config()

    assert cfg.version == "2.0.0"
    assert "outline" in cfg.jobs


def test_load_config_no_fallback_without_config_dir(tmp_path, monkeypatch):
    """
    9. Verificare che load_config() (senza path, con monkeypatch.chdir su una tmp_path
    che contiene rt.config.yaml con un valore distintivo ma NESSUNA cartella config/)
    restituisca i default di RTConfig(), NON i valori di quel file (fallback rimosso).
    """
    single_file = tmp_path / "rt.config.yaml"
    single_file.write_text("pricing_staleness_warning_days: 99\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    with patch("rt.core.config._default_project_root", return_value=str(tmp_path)):
        cfg = load_config()

    # Deve restituire il default (7) e non 99
    assert cfg.pricing_staleness_warning_days == 7


def test_load_config_explicit_path_still_works(tmp_path):
    """
    10. Verificare che load_config(path_esplicito) continui a funzionare esattamente
    come prima anche se punta a un file chiamato rt.config.yaml.
    """
    single_file = tmp_path / "rt.config.yaml"
    single_file.write_text("pricing_staleness_warning_days: 99\n", encoding="utf-8")

    cfg = load_config(str(single_file))
    assert cfg.pricing_staleness_warning_days == 99


def test_cli_commands_exit_when_no_config_dir_and_not_mock(tmp_path, monkeypatch, capsys):
    """
    11. Per ciascuno dei 5 comandi CLI (cmd_outline, cmd_rewrite, cmd_review_asr,
    cmd_review_science, cmd_run): verificare SystemExit(1) e messaggio su stderr se config/ manca.
    """
    import argparse
    from rt.cli import cmd_outline, cmd_rewrite, cmd_review_asr, cmd_review_science, cmd_run

    monkeypatch.chdir(tmp_path)

    cli_commands = [
        (cmd_outline, argparse.Namespace(lesson_dir=str(tmp_path), force=False, mock=False)),
        (cmd_rewrite, argparse.Namespace(lesson_dir=str(tmp_path), unit=None, force=False, mock=False)),
        (cmd_review_asr, argparse.Namespace(lesson_dir=str(tmp_path), force=False, mock=False)),
        (cmd_review_science, argparse.Namespace(lesson_dir=str(tmp_path), force=False, mock=False)),
        (cmd_run, argparse.Namespace(input=str(tmp_path), force=False, mock=False, date=None, materia=None, argomenti=None, dest_dir=None, model=None, skip_transcribe=False)),
    ]

    with patch("rt.cli._default_project_root", return_value=str(tmp_path)):
        for cmd_func, args in cli_commands:
            with pytest.raises(SystemExit) as exc_info:
                cmd_func(args)
            assert exc_info.value.code == 1

            captured = capsys.readouterr()
            assert "❌ Nessuna configurazione trovata (cartella 'config/' mancante)." in captured.err
            assert "cp -r config.example config" in captured.err


def test_cli_commands_proceed_when_mock_without_config_dir(tmp_path, monkeypatch):
    """
    12. Verificare che con --mock i 5 comandi procedano oltre il controllo di config mancante.
    """
    import argparse
    from rt.cli import cmd_outline, cmd_rewrite, cmd_review_asr, cmd_review_science, cmd_run

    monkeypatch.chdir(tmp_path)

    dummy_res = {
        "action": "RUN",
        "reason": "test",
        "segment_count": 1,
        "duration_seconds": 1.0,
        "validation_report": {"units_count": 1, "coverage_percentage": 100},
        "total_units": 1,
        "processed_units": 1,
        "total_issues": 0,
        "green_auto_applied": 0,
        "yellow_review_queue": 0,
        "red_human_required": 0,
        "findings_count": 0,
        "critical_issues": 0,
        "pedagogical_notes": 0,
        "total_science_issues": 0,
        "docente_issues": 0,
        "reconstruction_issues": 0,
        "science_checks": 0,
    }

    with patch("rt.cli.run_prepare", return_value=dummy_res), \
         patch("rt.cli.run_outline", return_value=dummy_res), \
         patch("rt.cli.confirm_or_revise_outline", return_value=None), \
         patch("rt.cli.run_rewrite", return_value=dummy_res), \
         patch("rt.cli.run_review_asr", return_value=dummy_res), \
         patch("rt.cli.run_review_science", return_value=dummy_res), \
         patch("rt.pipeline.setup.run_setup", return_value={"lesson_dir": str(tmp_path)}), \
         patch("rt.pipeline.setup.is_audio_file", return_value=False), \
         patch("rt.cli.run_build", return_value={"status": "OK", "skipped": True}), \
         patch("rt.cli.run_interactive_review", return_value=True):

        # None of these should raise SystemExit(1) due to missing config
        cmd_outline(argparse.Namespace(lesson_dir=str(tmp_path), force=False, mock=True))
        cmd_rewrite(argparse.Namespace(lesson_dir=str(tmp_path), unit=None, force=False, mock=True))
        cmd_review_asr(argparse.Namespace(lesson_dir=str(tmp_path), force=False, mock=True))
        cmd_review_science(argparse.Namespace(lesson_dir=str(tmp_path), force=False, mock=True))
        cmd_run(argparse.Namespace(
            input=str(tmp_path), force=False, mock=True, with_review=True, auto_accept=True, rename=False,
            date=None, materia=None, argomenti=None, dest_dir=None, model=None, skip_transcribe=False
        ))



def test_fallback_to_project_root_when_not_in_cwd(tmp_path, monkeypatch):
    """
    E.1: Con monkeypatch.chdir(tmp_path) (cwd temporanea SENZA .env/config/),
    verificare che load_env_file() e load_config() risolvano comunque correttamente
    rispetto alla project root reale del repository sotto test.
    """
    from rt.core.config import _default_project_root, load_env_file

    real_root = _default_project_root()
    monkeypatch.chdir(tmp_path)

    # 1. load_config() risolve la config reale del progetto
    cfg = load_config()
    assert cfg.version is not None
    assert "outline" in cfg.jobs
    # state_dir è risolto rispetto alla project root reale
    assert os.path.isabs(cfg.telegram.state_dir)
    assert cfg.telegram.state_dir == os.path.join(real_root, ".rt_telegram")

    # 2. load_env_file() prova a caricare dalla project root reale
    fake_project_root = tmp_path / "fake_project"
    fake_project_root.mkdir()
    (fake_project_root / ".env").write_text("FALLBACK_ENV_TEST_VAR=root_value\n", encoding="utf-8")

    empty_cwd = tmp_path / "empty_cwd"
    empty_cwd.mkdir()
    monkeypatch.chdir(empty_cwd)

    with patch("rt.core.config._default_project_root", return_value=str(fake_project_root)):
        monkeypatch.delenv("FALLBACK_ENV_TEST_VAR", raising=False)
        load_env_file()
        assert os.environ.get("FALLBACK_ENV_TEST_VAR") == "root_value"


def test_cwd_takes_precedence_over_project_root(tmp_path, monkeypatch):
    """
    E.2: Lanciando da una cwd con un proprio .env/config/ locale,
    quello viene preferito rispetto alla project root (retrocompatibilità).
    """
    from rt.core.config import load_env_file

    # Fake project root con determinati valori
    fake_project_root = tmp_path / "fake_project"
    fake_project_root.mkdir()
    fake_root_config = fake_project_root / "config"
    fake_root_config.mkdir()
    (fake_root_config / "general.yaml").write_text("pricing_staleness_warning_days: 10\n", encoding="utf-8")
    (fake_project_root / ".env").write_text("TEST_PRECEDENCE_VAR=from_project_root\n", encoding="utf-8")

    # Fake cwd con valori differenti
    fake_cwd = tmp_path / "fake_cwd"
    fake_cwd.mkdir()
    fake_cwd_config = fake_cwd / "config"
    fake_cwd_config.mkdir()
    (fake_cwd_config / "general.yaml").write_text("pricing_staleness_warning_days: 99\n", encoding="utf-8")
    (fake_cwd / ".env").write_text("TEST_PRECEDENCE_VAR=from_cwd\n", encoding="utf-8")

    monkeypatch.chdir(fake_cwd)
    with patch("rt.core.config._default_project_root", return_value=str(fake_project_root)):
        # Config carica da cwd
        cfg = load_config()
        assert cfg.pricing_staleness_warning_days == 99
        assert cfg.telegram.state_dir == os.path.join(str(fake_cwd), ".rt_telegram")

        # Env carica da cwd
        monkeypatch.delenv("TEST_PRECEDENCE_VAR", raising=False)
        load_env_file()
        assert os.environ.get("TEST_PRECEDENCE_VAR") == "from_cwd"


def test_resolve_telegram_state_dir_branches(tmp_path, monkeypatch):
    """
    E.3: Test per _resolve_telegram_state_dir(): con state_dir relativo nella config caricata,
    verificare che diventi assoluto e ancorato correttamente sia nel branch cwd, sia nel branch project-root,
    sia nel branch default, sia con config_path esplicito.
    """
    from rt.core.config import _resolve_telegram_state_dir

    # 1. Branch esplicito: ancorato alla directory del file
    explicit_dir = tmp_path / "explicit"
    explicit_dir.mkdir()
    explicit_file = explicit_dir / "custom.yaml"
    explicit_file.write_text("telegram:\n  state_dir: '.custom_tg'\n", encoding="utf-8")
    cfg_explicit = load_config(str(explicit_file))
    assert cfg_explicit.telegram.state_dir == os.path.join(str(explicit_dir), ".custom_tg")

    # 2. Branch cwd: ancorato a cwd
    cwd_dir = tmp_path / "cwd_test"
    cwd_dir.mkdir()
    (cwd_dir / "config").mkdir()
    (cwd_dir / "config" / "general.yaml").write_text("telegram:\n  state_dir: '.cwd_tg'\n", encoding="utf-8")
    monkeypatch.chdir(cwd_dir)
    cfg_cwd = load_config()
    assert cfg_cwd.telegram.state_dir == os.path.join(str(cwd_dir), ".cwd_tg")

    # 3. Branch project root: ancorato a project_root quando cwd non ha config
    empty_cwd = tmp_path / "empty"
    empty_cwd.mkdir()
    monkeypatch.chdir(empty_cwd)
    fake_project_root = tmp_path / "project_root_test"
    fake_project_root.mkdir()
    (fake_project_root / "config").mkdir()
    (fake_project_root / "config" / "general.yaml").write_text("telegram:\n  state_dir: '.root_tg'\n", encoding="utf-8")
    with patch("rt.core.config._default_project_root", return_value=str(fake_project_root)):
        cfg_root = load_config()
        assert cfg_root.telegram.state_dir == os.path.join(str(fake_project_root), ".root_tg")

    # 4. Già assoluto: non viene modificato
    cfg_abs = RTConfig()
    cfg_abs.telegram.state_dir = "/absolute/path/to/state"
    resolved = _resolve_telegram_state_dir(cfg_abs, "/some/other/anchor")
    assert resolved.telegram.state_dir == "/absolute/path/to/state"





def test_find_job_yaml_paths_excludes_recall_lessons_yaml(tmp_path):
    """recall_lessons.yaml (config/telegram/) non è un job di routing LLM: se venisse
    trattato come tale, _load_config_dir fallirebbe la validazione pydantic (JobRoutingConfig
    richiede almeno 'primary', che recall_lessons.yaml non ha)."""
    config_dir = tmp_path / "config"
    (config_dir / "telegram").mkdir(parents=True)
    (config_dir / "general.yaml").write_text("telegram:\n  state_dir: '.tg'\n", encoding="utf-8")
    (config_dir / "telegram" / "recall_quiz.yaml").write_text(
        "primary:\n  provider: null\n  model: null\n", encoding="utf-8"
    )
    (config_dir / "telegram" / "recall_lessons.yaml").write_text(
        "BIOCHIMICA: \"/tmp/qualche/lezione\"\n", encoding="utf-8"
    )

    paths = find_job_yaml_paths(str(config_dir))
    assert "recall_quiz" in paths
    assert "recall_lessons" not in paths

    # Non deve far fallire il caricamento della config (recall_lessons.yaml non ha la
    # forma di un JobRoutingConfig e romperebbe model_validate se non fosse escluso).
    cfg = _load_config_dir(str(config_dir))
    assert "recall_quiz" in cfg.jobs
