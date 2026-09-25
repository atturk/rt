"""
rt.tui.outline_review
UI da terminale per la conferma/revisione dell'outline (app Textual e fallback testuale
non-TTY). La logica (albero serializzabile, approvazione persistita, revisione con
feedback) sta in rt.services.outline_service: qui c'è solo la presentazione.
"""
import sys
from typing import Optional, Set, List
from rich.panel import Panel
from rich.tree import Tree
from rich.text import Text
from textual.app import App, ComposeResult, SuspendNotSupported
from textual.widgets import Static

from rt.core.models import Outline
from rt.pipeline.outline import load_outline
from rt.pipeline.outline_review import outline_needs_approval
from rt.services import outline_service
from rt.telegram import formatting as tg_fmt


def confirm_or_revise_outline(lesson_dir: str, force: bool = False, force_mock: bool = False) -> None:
    """Punto di ingresso unico, chiamato da cmd_run() tra OUTLINE e REWRITE.

    Regola di gating: si entra nel loop di conferma solo se la fase 'rewrite'
    NON è già VALID, oppure se force=True.
    """
    if not outline_needs_approval(lesson_dir, force):
        return

    _confirm_via_terminal(lesson_dir, force_mock)


def build_outline_tree(
    outline: Outline,
    previous_outline: Optional[Outline] = None,
    expanded_macros: Optional[Set[str]] = None,
    selected_macro_index: int = 0,
) -> Tree:
    """Costruisce l'albero Rich dell'outline con supporto a espansione/collasso e vista diff."""
    if expanded_macros is None:
        expanded_macros = set()

    root_label = Text(f"📋 {outline.lesson_title}", style="bold magenta")
    tree = Tree(root_label)

    prev_macros = {m.id: m for m in previous_outline.macro_sections} if previous_outline else {}
    curr_macros_map = {m.id: m for m in outline.macro_sections}

    all_macro_ids = [m.id for m in outline.macro_sections]
    if previous_outline:
        for old_m in previous_outline.macro_sections:
            if old_m.id not in curr_macros_map:
                all_macro_ids.append(old_m.id)

    for idx, m_id in enumerate(all_macro_ids):
        is_selected = (idx == selected_macro_index)
        pointer = "👉 " if is_selected else "   "

        if m_id in curr_macros_map and m_id not in prev_macros:
            macro = curr_macros_map[m_id]
            is_expanded = m_id in expanded_macros
            exp_symbol = "▼ " if is_expanded else "▶ "
            label_text = f"{pointer}+ [{macro.id}] {exp_symbol}{macro.title}"
            style = "bold green"
            if is_selected:
                style += " reverse"
            macro_node = tree.add(Text(label_text, style=style))

            if is_expanded:
                for unit in macro.units:
                    concepts = ", ".join(unit.key_concepts[:4])
                    suf = f" — {concepts}" if concepts else ""
                    macro_node.add(Text(f"  + {unit.id} {unit.title}{suf}", style="green"))

        elif m_id not in curr_macros_map and m_id in prev_macros:
            macro = prev_macros[m_id]
            is_expanded = m_id in expanded_macros
            exp_symbol = "▼ " if is_expanded else "▶ "
            label_text = f"{pointer}- [{macro.id}] {exp_symbol}{macro.title}"
            style = "bold red"
            if is_selected:
                style += " reverse"
            macro_node = tree.add(Text(label_text, style=style))

            if is_expanded:
                for unit in macro.units:
                    concepts = ", ".join(unit.key_concepts[:4])
                    suf = f" — {concepts}" if concepts else ""
                    macro_node.add(Text(f"  - {unit.id} {unit.title}{suf}", style="red"))

        else:
            macro = curr_macros_map[m_id]
            old_macro = prev_macros.get(m_id)
            is_expanded = m_id in expanded_macros
            exp_symbol = "▼ " if is_expanded else "▶ "

            if old_macro and old_macro.title != macro.title:
                label_text = f"{pointer}~ [{macro.id}] {exp_symbol}{macro.title} (era: {old_macro.title})"
                m_style = "bold yellow"
            elif previous_outline:
                label_text = f"{pointer}[{macro.id}] {exp_symbol}{macro.title}"
                m_style = "bold"
            else:
                label_text = f"{pointer}[{macro.id}] {exp_symbol}{macro.title}"
                m_style = "bold cyan"

            if is_selected:
                m_style += " reverse"
            macro_node = tree.add(Text(label_text, style=m_style))

            if is_expanded:
                prev_units = {u.id: u for u in old_macro.units} if old_macro else {}
                curr_units_map = {u.id: u for u in macro.units}
                all_unit_ids = [u.id for u in macro.units]
                if old_macro:
                    for ou in old_macro.units:
                        if ou.id not in curr_units_map:
                            all_unit_ids.append(ou.id)

                for u_id in all_unit_ids:
                    if u_id in curr_units_map and u_id not in prev_units:
                        u = curr_units_map[u_id]
                        concepts = ", ".join(u.key_concepts[:4])
                        suf = f" — {concepts}" if concepts else ""
                        macro_node.add(Text(f"  + {u.id} {u.title}{suf}", style="green"))
                    elif u_id not in curr_units_map and u_id in prev_units:
                        u = prev_units[u_id]
                        concepts = ", ".join(u.key_concepts[:4])
                        suf = f" — {concepts}" if concepts else ""
                        macro_node.add(Text(f"  - {u.id} {u.title}{suf}", style="red"))
                    else:
                        u = curr_units_map[u_id]
                        old_u = prev_units.get(u_id)
                        concepts = ", ".join(u.key_concepts[:4])
                        suf = f" — {concepts}" if concepts else ""
                        if old_u and (old_u.title != u.title or old_u.key_concepts != u.key_concepts):
                            macro_node.add(Text(f"  ~ {u.id} {u.title}{suf}", style="yellow"))
                        else:
                            macro_node.add(Text(f"  {u.id} {u.title}{suf}", style="dim" if previous_outline else "default"))

    return tree


class OutlineReviewApp(App):
    """Schermata interattiva Textual per l'outline review."""
    BINDINGS = [
        ("up,k,w", "cursor_up", "Su"),
        ("down,j,s", "cursor_down", "Giù"),
        ("right", "expand", "Espandi"),
        ("left", "collapse", "Collassa"),
        ("enter,space", "toggle", "Espandi/Collassa"),
        ("a", "approve", "Approva"),
        ("m", "modify", "Modifica"),
    ]

    def __init__(self, lesson_dir: str, force_mock: bool = False):
        super().__init__()
        from rt.core.ui_theme import apply_saved_theme
        apply_saved_theme(self)
        self.lesson_dir = lesson_dir
        self.force_mock = force_mock
        self.outline: Outline = load_outline(lesson_dir)
        self.previous_outline: Optional[Outline] = None
        self.selected_index: int = 0
        self.expanded_macros: Set[str] = set()
        if len(self.outline.macro_sections) <= 4:
            self.expanded_macros = {m.id for m in self.outline.macro_sections}

    def compose(self) -> ComposeResult:
        yield Static(self._render_panel(), id="tree_view")

    def _get_all_macros(self) -> List[str]:
        all_macros = [m.id for m in self.outline.macro_sections]
        if self.previous_outline:
            curr_map = {m.id: m for m in self.outline.macro_sections}
            for old_m in self.previous_outline.macro_sections:
                if old_m.id not in curr_map:
                    all_macros.append(old_m.id)
        return all_macros

    def _render_panel(self) -> Panel:
        all_macros = self._get_all_macros()
        if not all_macros:
            self.selected_index = 0
        else:
            self.selected_index = max(0, min(self.selected_index, len(all_macros) - 1))

        tree = build_outline_tree(
            outline=self.outline,
            previous_outline=self.previous_outline,
            expanded_macros=self.expanded_macros,
            selected_macro_index=self.selected_index,
        )
        return Panel(
            tree,
            title="📋 OUTLINE REVIEW",
            subtitle="[A]pprova | [M]odifica | [↑↓/←→] Naviga | [Invio/Spazio] Espandi-Collassa",
            border_style="cyan",
        )

    def _update_display(self) -> None:
        try:
            widget = self.query_one("#tree_view", Static)
            widget.update(self._render_panel())
        except Exception:
            pass

    def action_cursor_up(self) -> None:
        if self.selected_index > 0:
            self.selected_index -= 1
            self._update_display()

    def action_cursor_down(self) -> None:
        all_macros = self._get_all_macros()
        if self.selected_index < len(all_macros) - 1:
            self.selected_index += 1
            self._update_display()

    def action_expand(self) -> None:
        all_macros = self._get_all_macros()
        if all_macros and 0 <= self.selected_index < len(all_macros):
            target_id = all_macros[self.selected_index]
            self.expanded_macros.add(target_id)
            self._update_display()

    def action_collapse(self) -> None:
        all_macros = self._get_all_macros()
        if all_macros and 0 <= self.selected_index < len(all_macros):
            target_id = all_macros[self.selected_index]
            self.expanded_macros.discard(target_id)
            self._update_display()

    def action_toggle(self) -> None:
        all_macros = self._get_all_macros()
        if all_macros and 0 <= self.selected_index < len(all_macros):
            target_id = all_macros[self.selected_index]
            if target_id in self.expanded_macros:
                self.expanded_macros.remove(target_id)
            else:
                self.expanded_macros.add(target_id)
            self._update_display()

    def action_approve(self) -> None:
        self.exit(True)

    def _do_modify_interaction(self) -> None:
        import concurrent.futures

        def _ask_feedback() -> str:
            try:
                import questionary
                res = questionary.text("Descrivi le modifiche desiderate:").ask()
                return (res or "").strip()
            except Exception:
                return input("\nDescrivi le modifiche desiderate: ").strip()

        # questionary/prompt_toolkit prova a creare un proprio event loop asyncio: eseguito nel
        # thread dell'event loop di Textual (anche sotto suspend()) fallisce silenziosamente e
        # cade sempre sul fallback input() — un thread dedicato senza loop già in esecuzione
        # evita il conflitto (stesso pattern di _run_in_thread in rt/pipeline/configure.py).
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            feedback = executor.submit(_ask_feedback).result()

        if not feedback:
            print("Nessun feedback inserito, outline mantenuta invariata.")
            return

        print("⏳ Rigenerazione outline in corso...")
        self.previous_outline = load_outline(self.lesson_dir)
        outline_service.request_outline_revision(self.lesson_dir, feedback, force_mock=self.force_mock)
        self.outline = load_outline(self.lesson_dir)
        self.selected_index = 0
        self.expanded_macros.update({m.id for m in self.outline.macro_sections})

    def action_modify(self) -> None:
        try:
            with self.suspend():
                self._do_modify_interaction()
        except SuspendNotSupported:
            self._do_modify_interaction()
        self._update_display()


def _confirm_via_terminal(lesson_dir: str, force_mock: bool) -> None:
    previous_outline: Optional[Outline] = None

    if not sys.stdin.isatty():
        # Fallback non-interattivo per script e test
        while True:
            outline = load_outline(lesson_dir)
            print("\n" + "=" * 60)
            print("📋 OUTLINE GENERATA — in attesa di conferma")
            print("=" * 60)
            print(tg_fmt.render_outline_summary_text(outline, for_telegram=False))

            choice = input("\nAzione [A=Approva / M=Richiedi modifiche]: ").strip().lower()
            if choice in ("a", "approva", ""):
                outline_service.approve_outline(lesson_dir, actor="user", channel="cli")
                print("✔ Outline approvata.")
                return
            elif choice in ("m", "modifiche"):
                feedback = input("Descrivi le modifiche desiderate: ").strip()
                if not feedback:
                    print("Nessun feedback inserito, outline mantenuta invariata.")
                    continue
                print("⏳ Rigenerazione outline in corso...")
                previous_outline = load_outline(lesson_dir)
                outline_service.request_outline_revision(lesson_dir, feedback, force_mock=force_mock)
                continue
            else:
                print("Scelta non valida.")

    # Modalità interattiva TTY con Textual App
    app = OutlineReviewApp(lesson_dir=lesson_dir, force_mock=force_mock)
    approved = app.run()
    if not approved:
        # L'utente ha chiuso la app senza approvare (es. Ctrl+Q, binding di default
        # di Textual): tratta come un'interruzione volontaria, non come un'approvazione
        # silenziosa — riusa il gestore KeyboardInterrupt già presente in cli.py::main().
        raise KeyboardInterrupt()
    outline_service.approve_outline(lesson_dir, actor="user", channel="cli")
    print("✔ Outline approvata.")
