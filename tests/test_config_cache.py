"""V3a: cache dei YAML, sorgenti e copie difensive."""
from rt.core import config
from tests.api_support import isolated_workspace


def test_config_loaded_once_and_invalidated_by_yaml_changes(tmp_path, monkeypatch):
    isolated_workspace(tmp_path, monkeypatch)
    config._cached_config.cache_clear()
    calls = []
    original = config._load_config_dir
    def counted(path):
        calls.append(path)
        return original(path)
    monkeypatch.setattr(config, '_load_config_dir', counted)
    for _ in range(4):
        cfg = config.load_config()
        assert cfg.review.parallel_units == 4
        cfg.review.parallel_units = 1
    assert len(calls) == 1
    from pathlib import Path
    general = Path('config/general.yaml')
    general.write_text(general.read_text() + 'review:\n  parallel_units: 2\n')
    assert config.load_config().review.parallel_units == 2
    assert len(calls) == 2
    nested = Path('config/sub')
    nested.mkdir()
    job = nested / 'review.yaml'
    job.write_text('primary:\n  provider: deepseek\n  model: test-model\n')
    assert config.load_config().jobs['review'].primary.model == 'test-model'
    assert len(calls) == 3
    job.unlink()
    restored = config.load_config()
    assert restored.jobs.get('review') is None or restored.jobs['review'].primary.model != 'test-model'
    # La rimozione torna a un'impronta già letta: si può riusare la configurazione precedente.
    assert len(calls) == 3


def test_explicit_config_and_environment_changes(tmp_path, monkeypatch):
    isolated_workspace(tmp_path, monkeypatch)
    path = tmp_path / 'explicit.yaml'
    path.write_text('review:\n  parallel_units: 1\n')
    assert config.load_config(str(path)).review.parallel_units == 1
    path.write_text('review:\n  parallel_units: 8\n')
    assert config.load_config(str(path)).review.parallel_units == 8
    monkeypatch.setenv('RT_TELEGRAM_ENABLED', '0')
    assert config.load_config(str(path)).telegram.enabled is False
    monkeypatch.setenv('RT_TELEGRAM_ENABLED', '1')
    assert config.load_config(str(path)).telegram.enabled is True
