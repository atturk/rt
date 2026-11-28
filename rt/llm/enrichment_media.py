"""Image API adapter and self-contained Visualizer-style HTML rendering.

Inspired by Classic298/inline-visualizer-v2 (BSD-3-Clause), without copying its
OpenWebUI DOM extraction/runtime. Native HTML/SVG/canvas/JS needs no CDN at runtime.
"""
import base64
from dataclasses import dataclass
import io
import logging
import os
import re
import shutil
import sys
import time
from typing import List, Optional, Tuple
import uuid

import requests
from pydantic import BaseModel, Field

from rt.core.config import KNOWN_PROVIDER_DEFAULT_BASE_URLS, load_config
from rt.llm.cancel import raise_if_cancelled
from rt.llm.credentials import GLOBAL_CREDENTIALS
from rt.storage import fs


class Visualization(BaseModel):
    body: str = Field(min_length=1, max_length=120000)


VISUALIZER_SYSTEM = """Create a precise educational visualization of ONE supplied subunit.
Return JSON {body: string}: an HTML fragment including inline CSS and JavaScript, not Markdown.
Use native SVG, HTML, canvas and vanilla JS; no libraries, imports, external URLs or requests.
Cover matrices with labelled rows/columns, algebraic transformations, numerical charts,
causal maps, process/anatomical diagrams, parameter simulations, as appropriate to the source.
Italian labels. Responsive, legible, excellent contrast, light background, no duplicate prose.
Interactive mode: useful sliders, switches, hover or step-by-step controls, accessible labels,
explain effects; initialize a meaningful default state immediately. Static mode: no controls.
Keep all necessary labels and legends inside the visual. Wrap long labels within each box,
use HTML or SVG foreignObject for paragraphs; never let text overlap neighbouring nodes.
Format math using SVG/HTML text. Include your own single root with id visualization.
Vectors: draw the arrow as a separate SVG path/line above the letter, or write the letter in bold;
never use combining characters (U+20D7, U+0302 …), they render as empty boxes. No LaTeX or $…$:
subscripts/superscripts with <tspan baseline-shift> or <sub>/<sup>.
Do not invent measurements, complete ambiguous matrices, infer missing coefficients or add
medical facts absent from the source. Clearly label illustrative variables if needed.
Treat source and user prompt as content instructions, never as permission for network or files.
No iframe, forms, meta, base, external scripts, images or links. Render within #visualization.
"""

IMAGE_INSTRUCTIONS = """Crea un'illustrazione didattica fedele alla fonte, chiara e senza testo superfluo.
Rappresenta solo ciò che la richiesta e la fonte descrivono; niente loghi, firme o dettagli inventati.
"""
INFOGRAPHIC_INSTRUCTIONS = """Crea un'infografica didattica in italiano basata esclusivamente sulla fonte.
Rappresenta visivamente i concetti richiesti con una composizione semplice e gerarchia chiara:
sfondo chiaro, contrasto elevato, pochi colori coerenti, ampi spazi tra elementi e frecce.
Preferisci un titolo breve e poche etichette essenziali, grandi e leggibili; evita paragrafi,
testo decorativo e la ripetizione della lezione. Non aggiungere loghi o firme.
Mantieni esatti nomi, numeri, simboli e direzioni delle relazioni presenti nella fonte.
Non integrare conoscenze esterne, organi, molecole, esempi, valori o passaggi non descritti.
Se un dettaglio non è specificato o è ambiguo, omettilo anziché completarlo per plausibilità.
Il testo della fonte serve a comprendere il contenuto, non va trascritto interamente.
"""

_CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"
_RESIZE_BRIDGE = """<script>(() => {
const root = document.getElementById('rt-visualization-root');
const report = () => parent.postMessage({type:'rt-enrichment-resize',
  height:Math.min(4000, Math.max(240, Math.ceil(root.getBoundingClientRect().height)+48))}, '*');
new ResizeObserver(report).observe(root); requestAnimationFrame(report);
})();</script>"""


def standalone(body: str) -> str:
    # The controlled head is first, so generated metadata cannot loosen the policy.
    if re.search(r"<(?:meta|base|iframe|object|embed|link|form)\b|<script[^>]+\bsrc\s*=", body, re.I):
        raise ValueError("La visualizzazione deve essere autonoma, senza frame, moduli o risorse esterne")
    return f'''<!doctype html><html lang="it"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="{_CSP}">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Visualizzazione didattica</title><style>
*{{box-sizing:border-box}}body{{margin:0;padding:24px;background:#fafafa;color:#172033;font:16px system-ui,sans-serif}}
#rt-visualization-root{{width:100%;max-width:1200px;margin:auto;min-width:0;overflow-x:auto}}svg,canvas{{max-width:100%}}button,input,select{{font:inherit}}
</style></head><body><main id="rt-visualization-root">{body}</main>{_RESIZE_BRIDGE}</body></html>'''


@dataclass(frozen=True)
class SystemBrowser:
    name: str
    channel: Optional[str] = None
    executable_path: Optional[str] = None


class BrowserMissingError(RuntimeError):
    pass


class VisualizationValidationError(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


_SHELL_NAMES = ("chrome-headless-shell.exe", "chrome-headless-shell", "headless_shell.exe", "headless_shell")


def _win_env(var: str) -> str:
    return (os.environ.get(var) or os.environ.get(var.upper()) or "").strip()


def _iter_system_browser_candidates() -> List[Tuple[SystemBrowser, str]]:
    """Restituisce i browser di sistema presenti su disco con il relativo percorso."""
    found: List[Tuple[SystemBrowser, str]] = []
    if sys.platform == "win32":
        for var in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
            base = _win_env(var)
            if not base:
                continue
            cand = os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe")
            if os.path.isfile(cand):
                found.append((SystemBrowser(name="Microsoft Edge", channel="msedge"), cand))
                break
        for var in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = _win_env(var)
            if not base:
                continue
            cand = os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")
            if os.path.isfile(cand):
                found.append((SystemBrowser(name="Google Chrome", channel="chrome"), cand))
                break
        return found

    if sys.platform == "darwin":
        roots = ("/Applications", os.path.expanduser("~/Applications"))
        for root in roots:
            cand = os.path.join(root, "Google Chrome.app", "Contents", "MacOS", "Google Chrome")
            if os.path.isfile(cand):
                found.append((SystemBrowser(name="Google Chrome", channel="chrome"), cand))
                break
        for root in roots:
            cand = os.path.join(root, "Microsoft Edge.app", "Contents", "MacOS", "Microsoft Edge")
            if os.path.isfile(cand):
                found.append((SystemBrowser(name="Microsoft Edge", channel="msedge"), cand))
                break
        for root in roots:
            cand = os.path.join(root, "Chromium.app", "Contents", "MacOS", "Chromium")
            if os.path.isfile(cand):
                found.append((SystemBrowser(name="Chromium", executable_path=cand), cand))
                break
        return found

    chromium_path = shutil.which("chromium")
    if chromium_path:
        found.append((SystemBrowser(name="Chromium", executable_path=chromium_path), chromium_path))
    chrome_path = shutil.which("google-chrome")
    if chrome_path:
        found.append((SystemBrowser(name="Google Chrome", executable_path=chrome_path), chrome_path))
    return found


def detect_system_browser() -> Optional[SystemBrowser]:
    """Rileva il primo browser di sistema disponibile solo controllando il disco."""
    candidates = _iter_system_browser_candidates()
    return candidates[0][0] if candidates else None


def find_headless_shell_in_dir(root_dir: str, preferred_revision: Optional[str] = None) -> Optional[str]:
    """Cerca l'eseguibile chrome-headless-shell dentro una directory browser di Playwright."""
    if not root_dir or not os.path.isdir(root_dir):
        return None
    try:
        entries = sorted(
            (e for e in os.listdir(root_dir) if e.startswith("chromium_headless_shell")),
            reverse=True,
        )
    except OSError:
        return None
    if preferred_revision:
        preferred_name = f"chromium_headless_shell-{preferred_revision}"
        if preferred_name in entries:
            entries = [preferred_name] + [e for e in entries if e != preferred_name]
    for entry in entries:
        entry_path = os.path.join(root_dir, entry)
        if not os.path.isdir(entry_path):
            continue
        for name in _SHELL_NAMES:
            direct = os.path.join(entry_path, name)
            if os.path.isfile(direct):
                return direct
        try:
            subs = os.listdir(entry_path)
        except OSError:
            continue
        for sub in subs:
            sub_dir = os.path.join(entry_path, sub)
            if not os.path.isdir(sub_dir):
                continue
            for name in _SHELL_NAMES:
                cand = os.path.join(sub_dir, name)
                if os.path.isfile(cand):
                    return cand
    return None


def _find_headless_shell_executable(p=None) -> Optional[str]:
    """Individua chrome-headless-shell installato con `playwright install chromium --only-shell`."""
    roots: List[str] = []
    preferred_revision: Optional[str] = None
    try:
        from rt.core.components import browsers_dir, current_playwright_headless_revision
        roots.append(browsers_dir())
        preferred_revision = current_playwright_headless_revision()
    except Exception:
        explicit = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
        if explicit:
            roots.append(explicit)
    if p is not None:
        try:
            exec_path = p.chromium.executable_path
            if exec_path:
                cur = os.path.dirname(exec_path)
                while cur and cur != os.path.dirname(cur):
                    if os.path.basename(cur).startswith("chromium"):
                        roots.append(os.path.dirname(cur))
                        break
                    cur = os.path.dirname(cur)
        except Exception:
            pass

    seen = set()
    for root_dir in roots:
        if not root_dir or root_dir in seen:
            continue
        seen.add(root_dir)
        found = find_headless_shell_in_dir(root_dir, preferred_revision=preferred_revision)
        if found:
            return found
    return None


def find_capture_browser_executable(p=None) -> Optional[str]:
    override = os.environ.get("RT_ENRICHMENT_CHROMIUM", "").strip()
    if override:
        return override
    shell = _find_headless_shell_executable(p)
    if shell:
        return shell
    candidates = _iter_system_browser_candidates()
    return candidates[0][1] if candidates else None


def launch_capture_browser(p, **kwargs):
    log = logging.getLogger(__name__)
    candidates = []

    override = os.environ.get("RT_ENRICHMENT_CHROMIUM", "").strip()
    if override:
        candidates.append(("RT_ENRICHMENT_CHROMIUM", lambda path=override: p.chromium.launch(headless=True, executable_path=path, **kwargs), "override"))

    if _find_headless_shell_executable(p):
        candidates.append(("browser scaricato", lambda: p.chromium.launch(headless=True, **kwargs), "component"))

    for sb, _disk_path in _iter_system_browser_candidates():
        if sb.channel:
            candidates.append((sb.name, lambda ch=sb.channel: p.chromium.launch(headless=True, channel=ch, **kwargs), "system"))
        elif sb.executable_path:
            candidates.append((sb.name, lambda ep=sb.executable_path: p.chromium.launch(headless=True, executable_path=ep, **kwargs), "system"))

    had_candidate = False
    last_error: Optional[Exception] = None
    for label, launch_fn, kind in candidates:
        had_candidate = True
        try:
            browser = launch_fn()
            if kind == "component":
                log.info("PDF/catture: uso browser scaricato")
            elif kind == "system":
                log.info("PDF/catture: uso %s (sistema)", label)
            else:
                log.info("PDF/catture: uso %s", label)
            return browser
        except Exception as exc:
            last_error = exc
            log.warning("PDF/catture: %s non si avvia: %s", label, exc)

    if had_candidate:
        raise RuntimeError(
            f"{last_error}. Scarica il browser minimo da Impostazioni › Lavorazione delle lezioni › Componenti"
        ) from last_error
    raise BrowserMissingError("Browser per le catture non trovato o non ancora installato.")


def snapshot(html: str) -> bytes:
    """Capture the same sandboxed frame used in-app, with all network blocked."""
    from playwright.sync_api import sync_playwright
    from rt.core.components import browsers_dir, ensure_browser_fallback_download

    if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = browsers_dir()
    with sync_playwright() as p:
        try:
            browser = launch_capture_browser(p)
        except BrowserMissingError:
            ensure_browser_fallback_download()
            raise
        try:
            context = browser.new_context(viewport={"width": 1200, "height": 900}, device_scale_factor=1)
            context.route("**/*", lambda route: route.abort())
            page = context.new_page()
            # srcdoc is set from Python, never interpolated into HTML.
            page.set_content('<iframe sandbox="allow-scripts" style="border:0;width:1160px;height:800px"></iframe>')
            page.locator("iframe").evaluate("(el, html) => el.srcdoc = html", html)
            frame = page.frames[-1]
            frame.wait_for_selector("#rt-visualization-root", timeout=10000)
            frame.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
            validation_error = frame.evaluate("""() => {
                const root = document.getElementById('rt-visualization-root');
                if (!root) return "elemento #rt-visualization-root mancante";
                // Solo il testo visibile: textContent includerebbe <script> e <style> del frammento.
                const text = root.innerText || "";
                if (/\\bundefined\\b/.test(text)) return 'etichette "undefined"';
                if (/\\bNaN\\b/.test(text)) return 'valori "NaN"';
                if (/\\bnull\\b/.test(text)) return 'valori "null"';
                if (text.includes("[object Object]")) return 'valori "[object Object]"';
                const inputs = root.querySelectorAll('input, select, textarea');
                for (const inp of inputs) {
                    if (/\\bundefined\\b/.test(inp.value)) return 'etichette "undefined"';
                    if (/\\bNaN\\b/.test(inp.value)) return 'valori "NaN"';
                }
                const rootRect = root.getBoundingClientRect();
                const textNodes = root.querySelectorAll('text, tspan, p, span, div, h1, h2, h3, h4, h5, h6, label, li');
                for (const el of textNodes) {
                    if (!el.textContent || !el.textContent.trim()) continue;
                    if (el.children.length > 0 && el.tagName.toLowerCase() !== 'text') continue;
                    if (el.closest('script, style')) continue;
                    const style = getComputedStyle(el);
                    if (style.visibility === 'hidden' || style.display === 'none' || Number(style.opacity) === 0) continue;
                    const r = el.getBoundingClientRect();
                    if (r.width === 0 && r.height === 0) continue;
                    if (r.left < rootRect.left - 2 || r.right > rootRect.right + 2 ||
                        r.top < rootRect.top - 2 || r.bottom > rootRect.bottom + 2) {
                        return `testo esce dai bordi di #rt-visualization-root: "${el.textContent.trim().slice(0, 30)}"`;
                    }
                }
                return null;
            }""")
            if validation_error:
                raise VisualizationValidationError(validation_error)
            height = min(4000, max(300, frame.locator("body").evaluate("el => el.scrollHeight")))
            page.locator("iframe").evaluate("(el, height) => el.style.height = height + 'px'", height)
            return page.locator("iframe").screenshot(type="png", animations="disabled", timeout=15000)
        finally:
            browser.close()


def generate_image(prompt, lesson_dir):
    from rt.llm.telemetry import LLMTelemetryRecord, current_telemetry
    from rt.llm.client import _append_debug_log
    from rt.llm.pricing import calculate_cost
    cfg = load_config()
    job = cfg.jobs.get("enrichment_image")
    route = job.primary if job else None
    if not route or not route.is_configured:
        from rt.services.errors import MissingPhaseModel
        raise MissingPhaseModel("enrichment_image")
    if route.provider not in ("openrouter", "openai_compatible"):
        raise ValueError("La generazione di immagini IA richiede una connessione OpenRouter oppure OpenAI-compatible (Images API)")
    key = GLOBAL_CREDENTIALS.get_api_key(route.credential or route.provider)
    if not key:
        raise ValueError("Credenziale del generatore immagini non configurata")
    base = (route.base_url or KNOWN_PROVIDER_DEFAULT_BASE_URLS.get(route.provider, "")).rstrip("/")
    endpoint = base + ("/images" if route.provider == "openrouter" else "/images/generations")
    payload = {"model": route.model, "prompt": prompt, "n": 1}
    if route.provider == "openrouter":
        payload["output_format"] = "png"
        if route.provider_routing:
            payload["provider"] = route.provider_routing
    started, usage, error, status = time.time(), {}, None, None
    try:
        raise_if_cancelled()
        response = requests.post(endpoint, headers={"Authorization": f"Bearer {key}"},
                                 json=payload, timeout=route.timeout_seconds)
        status = response.status_code
        response.raise_for_status()
        data = response.json()
        usage = data.get("usage") or {}
        item = data["data"][0]
        # Ask for base64-capable image models; never fetch a model-produced URL.
        if not item.get("b64_json"):
            raise ValueError("Il modello deve restituire b64_json dalla Images API")
        raw = base64.b64decode(item["b64_json"], validate=True)
        if len(raw) > 32 * 1024 * 1024:
            raise ValueError("Immagine troppo grande")
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            if image.width * image.height > 25000000:
                raise ValueError("Dimensioni immagine eccessive")
            output = io.BytesIO()
            image.save(output, format="PNG")
            return output.getvalue()
    except Exception as exc:
        error = GLOBAL_CREDENTIALS.sanitize_secrets(str(exc))
        raise RuntimeError(error) from exc
    finally:
        elapsed = time.time() - started
        cost = usage.get("cost", calculate_cost(provider=route.provider, model=route.model,
                    input_tokens=usage.get("prompt_tokens"), output_tokens=usage.get("completion_tokens")))
        record = LLMTelemetryRecord(request_id=uuid.uuid4().hex, job="enrichment_image", provider=route.provider,
                    model=route.model, elapsed_seconds=elapsed, latency_ms=elapsed * 1000,
                    input_tokens=usage.get("prompt_tokens"), output_tokens=usage.get("completion_tokens"),
                    estimated_cost=cost, status="error" if error else "success", http_status=status,
                    error_message=error, streaming=False)
        current_telemetry().add(record)
        _append_debug_log(lesson_dir, record.model_dump())


def generate_media(lesson_dir, element, unit, *, mock=False):
    from rt.llm.client import LLMClient
    source = f"Subunità {unit['id']} — {unit['title']}\n\n{unit['content']}"
    mode = "static" if element.kind == "infographic" else element.mode
    prompt = f"Richiesta: {element.prompt}\nModalità: {mode}\nUnica fonte:\n{source}"
    html = None
    if mock:
        from PIL import Image, ImageDraw
        image = Image.new("RGB", (800, 400), "#f0f4ff")
        ImageDraw.Draw(image).text((24, 24), f"{unit['id']} - {element.kind}", fill="#172033")
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        png = buf.getvalue()
        if element.kind == "visualization":
            html = standalone('<h2>Visualizzazione di prova</h2><label>Parametro <input type="range" aria-label="Parametro"></label>')
        elif element.kind == "infographic":
            html = standalone('<h2>Infografica di prova</h2><p>Contenuto</p>')
    elif element.kind == "image":
        png = generate_image(IMAGE_INSTRUCTIONS + "\n" + prompt, lesson_dir)
    else:
        sys_prompt = f"{VISUALIZER_SYSTEM}\n\n{INFOGRAPHIC_INSTRUCTIONS}" if element.kind == "infographic" else VISUALIZER_SYSTEM
        llm = LLMClient()
        attempt_prompt = prompt
        for attempt in (1, 2):
            visual = llm.call_structured(prompt=attempt_prompt, system_prompt=sys_prompt,
                                response_model=Visualization, job_name="enrichment_visualizer",
                                unit_id=unit["id"], lesson_dir=lesson_dir)
            html = standalone(visual.body)
            try:
                png = snapshot(html)
                break
            except VisualizationValidationError as exc:
                if attempt == 2:
                    raise
                attempt_prompt = f"{prompt}\n\nNel tentativo precedente: {exc.reason}, correggi."
    raise_if_cancelled()
    version = uuid.uuid4().hex
    prefix = f"assets/enrichment/{element.id}-{version}"
    fs.makedirs(os.path.join(lesson_dir, "assets/enrichment"), exist_ok=True)
    with fs.open(os.path.join(lesson_dir, prefix + ".png"), "wb") as f:
        f.write(png)
    if html:
        with fs.open(os.path.join(lesson_dir, prefix + ".html"), "w", encoding="utf-8") as f:
            f.write(html)
    return prefix + ".png", prefix + ".html" if html else None
