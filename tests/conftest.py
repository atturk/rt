"""
tests/conftest.py
Fixture condivise per l'intera suite di test.
"""
import os
import pytest
from rt.llm.credentials import GLOBAL_CREDENTIALS, CredentialRef
from rt.core.config import RouteConfig, JobRoutingConfig
import rt.core.config

ORIGINAL_BUILD_DEFAULT_JOBS = rt.core.config._build_default_jobs


@pytest.fixture(autouse=True, scope="session")
def _register_standard_test_credentials():
    """Molti test esistenti costruiscono route con credential='openrouter'/'deepseek'/
    'google_1'/'google_2' assumendo che siano risolvibili, comportamento che prima di
    questo task era garantito da un default hardcoded in produzione (rt/llm/credentials.py).
    Quel default è stato rimosso deliberatamente (ogni provider richiede ora una
    dichiarazione esplicita 'credentials:' da parte dell'utente finale). Per non riscrivere
    decine di test che riguardano altro (retry, routing, telemetria) e non le credenziali,
    questa fixture ricrea la stessa disponibilità SOLO per la durata della suite di test,
    mai in codice di produzione."""
    for ref in [
        CredentialRef(name="openrouter", provider="openrouter", env_var="OPENROUTER_API_KEY"),
        CredentialRef(name="deepseek", provider="deepseek", env_var="DEEPSEEK_API_KEY"),
        CredentialRef(name="google_1", provider="google", env_var="GOOGLE_API_KEY_1"),
        CredentialRef(name="google_2", provider="google", env_var="GOOGLE_API_KEY_2"),
    ]:
        GLOBAL_CREDENTIALS.register(ref)


def _test_default_jobs():
    return {
        "outline": JobRoutingConfig(
            primary=RouteConfig(
                provider="deepseek",
                model="deepseek-v4-flash",
                base_url="https://api.deepseek.com",
                thinking=True,
                reasoning_effort="low",
                max_tokens=16384,
                timeout_seconds=240,
            )
        ),
        "rewrite": JobRoutingConfig(
            primary=RouteConfig(
                provider="deepseek",
                model="deepseek-v4-flash",
                base_url="https://api.deepseek.com",
                thinking=True,
                reasoning_effort="low",
                max_tokens=8192,
                timeout_seconds=180,
            )
        ),
        "review_asr": JobRoutingConfig(
            primary=RouteConfig(
                provider="deepseek",
                model="deepseek-v4-flash",
                base_url="https://api.deepseek.com",
                thinking=True,
                reasoning_effort="low",
                max_tokens=8192,
                timeout_seconds=120,
            )
        ),
        "review_science": JobRoutingConfig(
            primary=RouteConfig(
                provider="deepseek",
                model="deepseek-v4-flash",
                base_url="https://api.deepseek.com",
                thinking=True,
                reasoning_effort="low",
                max_tokens=8192,
                timeout_seconds=180,
            )
        ),
        "recall_quiz": JobRoutingConfig(
            primary=RouteConfig(
                provider="deepseek",
                model="deepseek-v4-flash",
                base_url="https://api.deepseek.com",
                thinking=True,
                reasoning_effort="low",
                max_tokens=8192,
                timeout_seconds=120,
            )
        ),
        "recall_mirata": JobRoutingConfig(
            primary=RouteConfig(
                provider="deepseek",
                model="deepseek-v4-flash",
                base_url="https://api.deepseek.com",
                thinking=True,
                reasoning_effort="low",
                max_tokens=8192,
                timeout_seconds=120,
            )
        ),
        "recall_vasta": JobRoutingConfig(
            primary=RouteConfig(
                provider="deepseek",
                model="deepseek-v4-flash",
                base_url="https://api.deepseek.com",
                thinking=True,
                reasoning_effort="low",
                max_tokens=8192,
                timeout_seconds=120,
            )
        ),
        "recall_eval_mirata": JobRoutingConfig(
            primary=RouteConfig(
                provider="deepseek",
                model="deepseek-v4-flash",
                base_url="https://api.deepseek.com",
                thinking=True,
                reasoning_effort="low",
                max_tokens=4096,
                timeout_seconds=120,
            )
        ),
        "recall_eval_vasta": JobRoutingConfig(
            primary=RouteConfig(
                provider="deepseek",
                model="deepseek-v4-flash",
                base_url="https://api.deepseek.com",
                thinking=True,
                reasoning_effort="low",
                max_tokens=4096,
                timeout_seconds=180,
            )
        ),
    }


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(autouse=True)
def _isolate_load_config_from_ambient_repo_config(monkeypatch):
    """Una vera cartella config/ nella working directory di sviluppo (creata per l'uso
    reale di RT, come consigliato dal README) non deve mai influenzare i test che non la
    richiedono esplicitamente: altrimenti chiunque esegua 'pytest' dalla root del repo dopo
    aver configurato RT per uso reale otterrebbe risultati diversi da un checkout pulito
    (es. CI, dove config/ non esiste essendo in .gitignore). Sostituisce load_config, in
    ciascun modulo che lo importa a livello di modulo, con una versione che ignora
    l'auto-discovery su disco quando invocata senza un config_path esplicito e quando la
    working directory è la root del repository (dove risiede la cartella config/ reale di sviluppo),
    restituendo invece job di test predefiniti e operativi. Se un test ha effettuato un chdir su
    una tmp_path con una propria config/ controllata, carica quella normalmente.

    I 3 moduli di rt/ che importano load_config a livello di modulo:
    - rt/llm/client.py
    - rt/pipeline/review_asr.py
    - rt/pipeline/smoke_test.py
    più rt.core.config stesso (per gli import locali dinamici in rt/cli.py)."""
    import rt.core.config
    import rt.llm.client
    import rt.pipeline.review_asr
    import rt.pipeline.smoke_test

    original_load_config = rt.core.config.load_config

    def patched_load_config(config_path=None):
        if config_path is not None:
            return original_load_config(config_path)
        if os.path.abspath(os.getcwd()) == REPO_ROOT:
            return rt.core.config.RTConfig(jobs=_test_default_jobs())
        return original_load_config(None)

    monkeypatch.setattr(rt.core.config, "load_config", patched_load_config)
    monkeypatch.setattr(rt.llm.client, "load_config", patched_load_config)
    monkeypatch.setattr(rt.pipeline.review_asr, "load_config", patched_load_config)
    monkeypatch.setattr(rt.pipeline.smoke_test, "load_config", patched_load_config)


