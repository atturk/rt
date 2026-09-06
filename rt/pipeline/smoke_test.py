"""
rt.pipeline.smoke_test
Modulo per il test di connettività e verifica formale con DeepSeek, OpenRouter o Google.
Esegue una singola chiamata minima con output strutturato, thinking (se supportato)
e validazione formale del payload.
"""

import sys
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field

from rt.core.config import load_config, get_api_key
from rt.llm.client import LLMClient, LLMError
from rt.llm.capabilities import get_capabilities
from rt.llm.telemetry import GLOBAL_TELEMETRY


class SmokeTestResponse(BaseModel):
    status: str = Field(description="Stato della risposta (es. 'OK')")
    message: str = Field(description="Breve messaggio di conferma")
    test_id: int = Field(description="Numero di test (es. 42)")


def run_smoke_test(
    config_path: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    credential: Optional[str] = None,
    stream: Optional[bool] = None,
    show_monitor: Optional[bool] = None,
    verbose: bool = True
) -> Dict[str, Any]:
    """
    Esegue uno smoke test minimale verso il provider configurato (DeepSeek, OpenRouter o Google)
    con output strutturato.
    Fallisce immediatamente se la chiave manca o se l'endpoint/modello è incompatibile.
    Non stampa MAI la API key.
    """
    cfg = load_config(config_path)
    job_cfg = cfg.llm.get("outline")
    if not job_cfg:
        raise LLMError("Configurazione job LLM non trovata in rt.config.yaml")

    target_provider = (provider or job_cfg.provider).lower().strip()
    if target_provider == "openrouter":
        target_model = model or (job_cfg.model if job_cfg.provider == "openrouter" else "~deepseek/deepseek-v4-flash-latest")
    elif target_provider == "google":
        target_model = model or (job_cfg.model if job_cfg.provider == "google" else "gemini-flash-latest")
    else:
        clean_cfg = job_cfg.model.lstrip("~")
        if clean_cfg.startswith("deepseek/"):
            clean_cfg = clean_cfg[len("deepseek/"):]
        target_model = model or (clean_cfg if job_cfg.provider == "deepseek" else "deepseek-v4-flash")

    target_credential = credential
    if not target_credential:
        if target_provider == "google":
            if get_api_key("google_1"):
                target_credential = "google_1"
            elif get_api_key("google_2"):
                target_credential = "google_2"
            else:
                target_credential = "google_1"
        else:
            target_credential = target_provider

    api_key = get_api_key(target_credential)
    if not api_key:
        if target_provider == "google":
            if target_credential == "google_2":
                env_var = "GOOGLE_API_KEY_2"
            else:
                env_var = "GOOGLE_API_KEY_1 (oppure GEMINI_API_KEY / GOOGLE_API_KEY)"
        elif target_provider == "openrouter":
            env_var = "OPENROUTER_API_KEY"
        else:
            env_var = "DEEPSEEK_API_KEY"

        err_msg = (
            f"❌ ERRORE: Variabile d'ambiente {env_var} non trovata!\n"
            f"   Per eseguire chiamate reali a {target_provider} (credenziale: {target_credential}), esporta la chiave:\n"
            f"     export {env_var}='tua_chiave'\n"
            f"   oppure inseriscila in un file .env locale (non versionato)."
        )
        if verbose:
            print(err_msg, file=sys.stderr)
        raise LLMError(f"{env_var} assente nell'ambiente.")

    system_prompt = (
        "Sei un assistente di verifica del sistema RT.\n"
        "Devi rispondere ESCLUSIVAMENTE in formato JSON valido.\n\n"
        "ESEMPIO JSON OUTPUT:\n"
        "{\n"
        '  "status": "OK",\n'
        '  "message": "LLM operational",\n'
        '  "test_id": 42\n'
        "}\n"
        "Non inserire testo, commenti o markdown prima o dopo il JSON."
    )
    prompt = (
        "Esegui il test di connessione per verificare la pipeline RT.\n"
        "Restituisci l'oggetto JSON con:\n"
        "- status: \"OK\"\n"
        "- message: \"LLM operational\"\n"
        "- test_id: 42"
    )

    client = LLMClient(config_path=config_path, force_mock=False)

    try:
        res: SmokeTestResponse = client.call_structured(
            prompt=prompt,
            system_prompt=system_prompt,
            response_model=SmokeTestResponse,
            job_name="outline",
            max_retries=2,
            override_provider=target_provider,
            override_model=target_model,
            override_credential=target_credential,
            stream=stream,
            show_monitor=show_monitor
        )
    except Exception as e:
        if verbose:
            print(f"❌ ERRORE durante la chiamata a {target_provider} ({target_credential}): {e}", file=sys.stderr)
        raise

    last_record = GLOBAL_TELEMETRY.get_last()

    cost_val = last_record.estimated_cost if last_record else None
    cost_str = f"${cost_val:.6f} (estimated)" if cost_val is not None else "pending"

    caps = get_capabilities(target_provider)
    if target_provider == "google":
        base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
    elif target_provider == "openrouter":
        base_url = "https://openrouter.ai/api/v1"
    else:
        base_url = job_cfg.base_url or "https://api.deepseek.com"

    output_info = {
        "connection": "OK",
        "provider": target_provider,
        "credential": target_credential,
        "model": target_model,
        "thinking": "enabled" if (caps.reasoning and job_cfg.thinking) else ("unsupported" if not caps.reasoning else "disabled"),
        "reasoning_effort": job_cfg.reasoning_effort if caps.reasoning else "n/a",
        "max_thinking_tokens": job_cfg.max_thinking_tokens if caps.reasoning else None,
        "base_url": base_url,
        "json_output": "OK",
        "final_content": "non-empty" if res.status else "empty",
        "schema_validation": "OK" if res.test_id == 42 else "FAILED",
        "response_status": res.status,
        "response_message": res.message,
        "test_id": res.test_id,
        "input_tokens": last_record.input_tokens if last_record else None,
        "reasoning_tokens": last_record.reasoning_tokens if last_record else None,
        "output_tokens": last_record.output_tokens if last_record else None,
        "total_tokens": last_record.total_tokens if last_record else None,
        "latency_ms": last_record.latency_ms if last_record else 0.0,
        "estimated_cost": cost_val,
    }

    if verbose:
        print(f"\nProvider:   {output_info['provider']}")
        if output_info.get('credential'):
            print(f"Credential: {output_info['credential']}")
        print(f"Model:      {output_info['model']}")
        print("Request:    OK\n")
        in_t = output_info['input_tokens'] if output_info['input_tokens'] is not None else "pending"
        reas_t = output_info['reasoning_tokens'] if output_info['reasoning_tokens'] is not None else "pending"
        out_t = output_info['output_tokens'] if output_info['output_tokens'] is not None else "pending"
        tot_t = output_info['total_tokens'] if output_info['total_tokens'] is not None else "pending"
        print(f"Input tokens:      {in_t}")
        print(f"Reasoning tokens:  {reas_t}")
        print(f"Output tokens:     {out_t}")
        print(f"Total tokens:      {tot_t}\n")
        print(f"Latency:           {output_info['latency_ms']:.1f}ms")
        print(f"Estimated cost:    {cost_str}\n")
        print("JSON: valid")

    return output_info

