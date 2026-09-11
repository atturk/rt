"""
rt.pipeline.outline_review
Loop di conferma/revisione outline: blocca fino ad approvazione da terminale.
Nessuna conferma per singola unità di rewrite: una volta approvata l'outline,
il resto della pipeline procede automaticamente.
"""
from rt.core.idempotency import check_phase_status, PhaseStatus
from rt.pipeline.outline import load_outline, run_outline_revision
from rt.telegram import formatting as tg_fmt


def confirm_or_revise_outline(lesson_dir: str, force: bool = False, force_mock: bool = False) -> None:
    """Punto di ingresso unico, chiamato da cmd_run() tra OUTLINE e REWRITE.

    Regola di gating (per evitare due bug distinti: ri-chiedere conferma ad ogni
    re-run idempotente quando il rewrite è già stato fatto, oppure saltarla dopo
    un Ctrl+C se l'outline risultava "già valida" al riavvio): si entra nel loop
    di conferma solo se la fase 'rewrite' NON è già VALID, oppure se force=True.
    """
    if not force:
        phase_status, _ = check_phase_status(lesson_dir, "rewrite")
        if phase_status == PhaseStatus.VALID:
            return

    _confirm_via_terminal(lesson_dir, force_mock)


def _confirm_via_terminal(lesson_dir: str, force_mock: bool) -> None:
    while True:
        outline = load_outline(lesson_dir)
        print("\n" + "=" * 60)
        print("📋 OUTLINE GENERATA — in attesa di conferma")
        print("=" * 60)
        print(tg_fmt.render_outline_summary_text(outline))

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
            run_outline_revision(lesson_dir, feedback=feedback, force_mock=force_mock)
            continue
        else:
            print("Scelta non valida.")

