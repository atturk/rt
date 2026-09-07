"""
rt.llm.monitor
Live terminal monitor per le chiamate LLM in streaming.
Mostra l'avanzamento dei 4 passaggi ([1/4] .. [4/4]), token (o stima live), latenza, costo stimato per blocco e cumulativo di sessione.
"""

import re
import shutil
import sys
import time
from typing import Optional, Dict, Any

from rt.llm.pricing import calculate_cost


class LiveTerminalMonitor:
    def __init__(
        self,
        job: str,
        provider: str,
        model: str,
        unit_id: Optional[str] = None,
        enabled: bool = True,
        pricing: Optional[Dict[str, Any]] = None,
        approx_input_tokens: Optional[int] = None,
        prev_session_cost: Optional[float] = None,
        attempt: int = 1,
        max_attempts: int = 1,
        timeout_seconds: Optional[int] = None,
        verbose: bool = False,
    ):
        self.job = job
        self.provider = provider
        self.model = model
        self.unit_id = unit_id
        self.enabled = enabled
        self.pricing = pricing
        self.approx_input_tokens = approx_input_tokens
        self.prev_session_cost = prev_session_cost or 0.0
        self.attempt = attempt
        self.max_attempts = max_attempts
        self.timeout_seconds = timeout_seconds
        self.verbose = verbose

        self._last_retry_reason: Optional[str] = None
        self.start_time = time.time()
        self.step_num = 1
        self.step_name = "Preparing request"
        self.status = "preparing"

        self.input_tokens: Optional[int] = None
        self.reasoning_tokens: Optional[int] = None
        self.output_tokens: Optional[int] = None
        self.total_tokens: Optional[int] = None

        self.estimated_cost: Optional[float] = None
        self.chunk_count = 0
        self.char_count = 0
        self.reasoning_char_count = 0

        # Metriche streaming
        self.stream_start_time: Optional[float] = None
        self.t_first_chunk: Optional[float] = None
        self.last_chunk_time: Optional[float] = None
        self.time_to_first_token: Optional[float] = None

        self.is_tty = sys.stdout.isatty() if hasattr(sys.stdout, "isatty") else False
        self._rendered_lines = 0
        self.resolved_model: Optional[str] = None

    def set_resolved_model(self, resolved_model: Optional[str]) -> None:
        """Imposta il modello risolto dal provider (se noto)."""
        self.resolved_model = resolved_model

    def set_retry_reason(self, reason: Optional[str]) -> None:
        """Imposta la causale dell'ultimo retry per visualizzazione nella riga compatta."""
        self._last_retry_reason = reason

    def set_step(self, step: int, name: str, status: Optional[str] = None) -> None:
        self.step_num = step
        self.step_name = name
        if status:
            self.status = status
        if not self.is_tty and self.enabled and self.verbose:
            unit_info = f" [{self.unit_id}]" if self.unit_id else ""
            print(f"[{self.step_num}/4]{unit_info} {self.step_name} ({self.status})")
            sys.stdout.flush()
        self.render()

    def on_chunk(self, content_delta: Optional[str], reasoning_delta: Optional[str]) -> None:
        now = time.time()
        if self.stream_start_time is None:
            self.stream_start_time = now
        if self.t_first_chunk is None and (content_delta or reasoning_delta):
            self.t_first_chunk = now
            self.time_to_first_token = round(now - self.start_time, 4)
        self.last_chunk_time = now

        self.chunk_count += 1
        if content_delta:
            self.char_count += len(content_delta)
        if reasoning_delta:
            self.reasoning_char_count += len(reasoning_delta)
        # Se siamo in fase streaming, rinfreschiamo periodicamente per feedback visivo immediato
        if self.step_num == 3 and (self.chunk_count % 3 == 0 or self.chunk_count == 1):
            self.render()

    def on_usage(self, usage: Optional[Dict[str, Any]], cost: Optional[float]) -> None:
        if usage:
            self.input_tokens = usage.get("prompt_tokens")
            self.output_tokens = usage.get("completion_tokens")
            self.total_tokens = usage.get("total_tokens")
            det = usage.get("completion_tokens_details") or {}
            self.reasoning_tokens = det.get("reasoning_tokens")
            if self.total_tokens is None and (self.input_tokens is not None or self.output_tokens is not None):
                self.total_tokens = (self.input_tokens or 0) + (self.output_tokens or 0)
        if cost is not None:
            self.estimated_cost = cost
        self.render()

    def render(self, final: bool = False) -> None:
        if not self.enabled:
            return

        elapsed = time.time() - self.start_time
        is_streaming_active = (self.step_num == 3 and not final)
        suffix = " (streaming)" if is_streaming_active else ""

        # Calcolo token dinamici durante lo streaming
        if self.input_tokens is not None:
            in_tok_str = str(self.input_tokens)
            in_est = self.input_tokens
        elif self.approx_input_tokens is not None:
            in_tok_str = f"~{self.approx_input_tokens}{suffix}"
            in_est = self.approx_input_tokens
        else:
            in_tok_str = "pending"
            in_est = 0

        if self.reasoning_tokens is not None:
            reas_tok_str = str(self.reasoning_tokens)
            reas_est = self.reasoning_tokens
        elif self.reasoning_char_count > 0:
            reas_est = max(1, self.reasoning_char_count // 4)
            reas_tok_str = f"~{reas_est}{suffix}"
        else:
            reas_tok_str = "0" if final else "pending"
            reas_est = 0

        if self.output_tokens is not None:
            out_tok_str = str(self.output_tokens)
            out_est = self.output_tokens
        elif self.char_count > 0:
            out_est = max(1, self.char_count // 4)
            out_tok_str = f"~{out_est}{suffix}"
        else:
            out_tok_str = "0" if final else "pending"
            out_est = 0

        if self.total_tokens is not None:
            tot_tok_str = str(self.total_tokens)
        elif reas_est > 0 or out_est > 0 or in_est > 0:
            tot_est = in_est + reas_est + out_est
            tot_tok_str = f"~{tot_est}{suffix}"
        else:
            tot_tok_str = "0" if final else "pending"

        # Calcolo costo: live dinamico durante lo streaming, o esatto finale se disponibile
        live_cost = None
        if self.estimated_cost is not None:
            cost_str = f"${self.estimated_cost:.6f}"
            current_cost = self.estimated_cost
        else:
            live_cost = calculate_cost(
                provider=self.provider,
                model=self.model,
                input_tokens=in_est,
                output_tokens=out_est,
                reasoning_tokens=reas_est,
                custom_pricing=self.pricing
            )
            if live_cost is not None and (in_est > 0 or out_est > 0 or reas_est > 0):
                cost_str = f"~${live_cost:.6f} (streaming)"
                current_cost = live_cost
            else:
                cost_str = "pending"
                current_cost = 0.0

        if self.status == "completed":
            step_badge = "[4/4] Completed"
        else:
            step_badge = f"[{self.step_num}/4] {self.step_name}"

        if not self.verbose:
            spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
            frame = spinner_frames[int(elapsed * 10) % len(spinner_frames)] if not final else ("✔" if self.status == "completed" else "✗")
            compact_unit_id = re.sub(r"\s*\([^)]*\)\s*$", "", self.unit_id).strip() if self.unit_id else None
            unit_part = f" · {compact_unit_id}" if compact_unit_id else f" · {self.attempt}/{self.max_attempts}"
            slow_tag = ""
            if self.timeout_seconds and not final:
                elapsed_now = time.time() - self.start_time
                if elapsed_now > 0.5 * self.timeout_seconds:
                    slow_tag = " ⚠lento"
            retry_tag = f" · retry:{self._last_retry_reason}" if getattr(self, "_last_retry_reason", None) and not final else ""
            compact_cost_str = cost_str.replace(" (streaming)", "")
            compact_line = (
                f"{frame} {self.job}{unit_part} · ↑{in_est} ↓{out_est} R{reas_est} "
                f"{compact_cost_str} · {self.provider}/{self.model}{retry_tag}{slow_tag} · {int(elapsed)}s"
            )
            if self.is_tty:
                term_width = shutil.get_terminal_size(fallback=(120, 24)).columns
                if len(compact_line) >= term_width:
                    compact_line = compact_line[:max(0, term_width - 2)] + "…"
                sys.stdout.write(f"\r\033[K{compact_line}")
                if final:
                    sys.stdout.write("\n")
                sys.stdout.flush()
            else:
                if final:
                    print(compact_line)
                    sys.stdout.flush()
            return

        lines = [
            "RT LLM",
            "────────────────────────────────────",
            f"Workflow: {step_badge}",
            f"Job:      {self.job}",
        ]

        if self.unit_id:
            clean_unit = " ".join(self.unit_id.split())
            if len(clean_unit) > 42:
                clean_unit = clean_unit[:39] + "..."
            lines.append(f"Block:    {clean_unit}")

        lines.extend([
            f"Provider: {self.provider}",
            f"Model:    {self.model}",
        ])
        if self.resolved_model and self.resolved_model != self.model:
            lines.append(f"Resolved: {self.resolved_model}")
        lines.append(f"Attempt:  {self.attempt}/{self.max_attempts}")
        if self.timeout_seconds:
            lines.append(f"Timeout:  {self.timeout_seconds}s")
        lines.extend([
            f"Status:   {self.status}",
            "",
            f"Input tokens:      {in_tok_str}",
            f"Reasoning tokens:  {reas_tok_str}",
            f"Output tokens:     {out_tok_str}",
            f"Total tokens:      {tot_tok_str}",
            "",
            f"Elapsed:           {elapsed:.2f}s",
        ])

        if self.prev_session_cost > 0.0:
            lines.append(f"Block cost:        {cost_str}")
            tot_sess = self.prev_session_cost + current_cost
            sess_suffix = "" if (final and self.estimated_cost is not None) else " (est.)"
            lines.append(f"Session cost:      ${tot_sess:.6f}{sess_suffix}")
        else:
            lines.append(f"Estimated cost:    {cost_str}")

        if self.step_num == 3 and not final:
            lines.append("")
            if self.char_count > 0:
                lines.append(f"Receiving content ({self.char_count} chars)...")
            elif self.reasoning_char_count > 0:
                lines.append(f"Thinking / reasoning ({self.reasoning_char_count} chars, ~{self.reasoning_char_count // 4} tokens)...")
            else:
                lines.append("Receiving...")

        lines.append("────────────────────────────────────")
        text_block = "\n".join(lines)
        num_lines = len(lines)

        if self.is_tty and not final:
            if self._rendered_lines > 0:
                sys.stdout.write(f"\033[{self._rendered_lines}F\033[J")
            sys.stdout.write(text_block + "\n")
            sys.stdout.flush()
            self._rendered_lines = num_lines
        elif final:
            if self.is_tty and self._rendered_lines > 0:
                sys.stdout.write(f"\033[{self._rendered_lines}F\033[J")
            print(text_block + "\n")
            sys.stdout.flush()
            self._rendered_lines = 0

    def log_timeout(self, elapsed: float, next_attempt: Optional[int] = None) -> None:
        """Emette log visibile di timeout e dell'eventuale retry."""
        if not self.verbose:
            return
        if self.is_tty and self._rendered_lines > 0:
            sys.stdout.write(f"\033[{self._rendered_lines}F\033[J")
            self._rendered_lines = 0
        timeout_str = f" after {elapsed:.1f}s"
        print(f"\nTIMEOUT{timeout_str}")
        if next_attempt is not None and next_attempt <= self.max_attempts:
            print(f"Retrying same provider (attempt {next_attempt}/{self.max_attempts})...\n")
        else:
            print(f"Max attempts ({self.max_attempts}) reached. Operation failed.\n")
        sys.stdout.flush()

    def log_retry(self, reason: str, elapsed: float, next_attempt: Optional[int] = None) -> None:
        """Emette log visibile per un retry non-timeout sulla stessa route (es. reasoning_required)."""
        if not self.verbose:
            return
        if self.is_tty and self._rendered_lines > 0:
            sys.stdout.write(f"\033[{self._rendered_lines}F\033[J")
            self._rendered_lines = 0
        print(f"\nRETRY ({reason}) after {elapsed:.1f}s")
        if next_attempt is not None and next_attempt <= self.max_attempts:
            print(f"Retrying same provider (attempt {next_attempt}/{self.max_attempts})...\n")
        else:
            print(f"Max attempts ({self.max_attempts}) reached. Operation failed.\n")
        sys.stdout.flush()

    def reset_for_attempt(self, attempt: int) -> None:
        """Reimposta lo stato per un nuovo tentativo."""
        self.attempt = attempt
        self.resolved_model = None
        self.start_time = time.time()
        self.step_num = 1
        self.step_name = "Preparing request"
        self.status = "preparing"
        self.chunk_count = 0
        self.char_count = 0
        self.reasoning_char_count = 0
        self.stream_start_time = None
        self.t_first_chunk = None
        self.last_chunk_time = None
        self.time_to_first_token = None
        self.estimated_cost = None
        self.input_tokens = None
        self.output_tokens = None
        self.reasoning_tokens = None
        self.total_tokens = None
        self._rendered_lines = 0

    def finish(self, success: bool = True, error_msg: Optional[str] = None) -> None:
        if success:
            self.status = "completed"
            self.step_num = 4
            self.step_name = "Completed"
        else:
            self.status = f"error: {error_msg}" if error_msg else "error"
        self.render(final=True)

