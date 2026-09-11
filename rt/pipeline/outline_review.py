"""
rt.pipeline.outline_review
Loop di conferma/revisione outline: blocca fino ad approvazione da terminale.
Nessuna conferma per singola unità di rewrite: una volta approvata l'outline,
il resto della pipeline procede automaticamente.
"""
import sys
from typing import Optional, Set
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.tree import Tree
from rich.text import Text

from rt.core.idempotency import check_phase_status, PhaseStatus
from rt.core.keyboard import read_single_key, raw_mode
from rt.core.models import Outline
from rt.pipeline.outline import load_outline, run_outline_revision
from rt.telegram import formatting as tg_fmt


def confirm_or_revise_outline(lesson_dir: str, force: bool = False, force_mock: bool = False) -> None:
    """Punto di ingresso unico, chiamato da cmd_run() tra OUTLINE e REWRITE.

    Regola di gating: si entra nel loop di conferma solo se la fase 'rewrite'
    NON è già VALID, oppure se force=True.
    """
    if not force:
        phase_status, _ = check_phase_status(lesson_dir, "rewrite")
        if phase_status == PhaseStatus.VALID:
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
                print("✔ Outline approvata.")
                return
            elif choice in ("m", "modifiche"):
                feedback = input("Descrivi le modifiche desiderate: ").strip()
                if not feedback:
                    print("Nessun feedback inserito, outline mantenuta invariata.")
                    continue
                print("⏳ Rigenerazione outline in corso...")
                previous_outline = load_outline(lesson_dir)
                run_outline_revision(lesson_dir, feedback=feedback, force_mock=force_mock)
                continue
            else:
                print("Scelta non valida.")

    # Modalità interattiva TTY con Rich Tree e keyboard navigation
    outline = load_outline(lesson_dir)
    selected_index = 0
    expanded_macros: Set[str] = set()

    if len(outline.macro_sections) <= 4:
        expanded_macros = {m.id for m in outline.macro_sections}

    console = Console()

    with raw_mode() as is_raw:
        while True:
            all_macros = [m.id for m in outline.macro_sections]
            if previous_outline:
                curr_map = {m.id: m for m in outline.macro_sections}
                for old_m in previous_outline.macro_sections:
                    if old_m.id not in curr_map:
                        all_macros.append(old_m.id)

            if not all_macros:
                selected_index = 0
            else:
                selected_index = max(0, min(selected_index, len(all_macros) - 1))

            tree = build_outline_tree(
                outline=outline,
                previous_outline=previous_outline,
                expanded_macros=expanded_macros,
                selected_macro_index=selected_index,
            )

            panel = Panel(
                tree,
                title="📋 OUTLINE REVIEW",
                subtitle="[A]pprova | [M]odifica | [↑↓] Naviga | [Invio/Spazio] Espandi-Collassa",
                border_style="cyan",
            )
            console.clear()
            console.print(panel)

            key = read_single_key(already_raw=is_raw)
            choice = key.strip().lower()

            if key == "UP" or choice in ("k", "w"):
                if selected_index > 0:
                    selected_index -= 1
            elif key == "DOWN" or choice in ("j", "s"):
                if selected_index < len(all_macros) - 1:
                    selected_index += 1
            elif key in ("", " ") or choice in ("enter", "\r", "\n"):
                if all_macros:
                    target_id = all_macros[selected_index]
                    if target_id in expanded_macros:
                        expanded_macros.remove(target_id)
                    else:
                        expanded_macros.add(target_id)
            elif choice in ("a", "approva"):
                print("✔ Outline approvata.")
                return
            elif choice in ("m", "modifiche"):
                feedback = ""
                try:
                    import questionary
                    feedback = questionary.text("Descrivi le modifiche desiderate:").ask()
                except Exception:
                    feedback = input("\nDescrivi le modifiche desiderate: ").strip()

                if not feedback:
                    print("Nessun feedback inserito, outline mantenuta invariata.")
                    continue

                print("⏳ Rigenerazione outline in corso...")
                previous_outline = load_outline(lesson_dir)
                run_outline_revision(lesson_dir, feedback=feedback, force_mock=force_mock)
                outline = load_outline(lesson_dir)
                selected_index = 0
                expanded_macros.update({m.id for m in outline.macro_sections})
