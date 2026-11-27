#!/usr/bin/env python3
"""
Crea l'archivio di esempio rt/assets/esempio/lezione-esempio.rt.

La lezione si costruisce con la pipeline vera in modalità mock, ma con risposte "scritte a
mano" al posto di quelle generiche del mock: così i file (scaletta, draft, verifica,
domande) hanno sempre lo schema attuale di RT. Se lo schema cambia basta rilanciare lo
script (il test tests/test_sample_lesson.py controlla che l'archivio incluso sia valido).
"""
import os
import shutil
import sys
import tempfile
from typing import Optional
from unittest import mock

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

DEFAULT_SCREENSHOT_DIR = os.path.join(ROOT_DIR, "rt", "assets", "esempio", "screenshot")

FOLDER_NAME = "[2026-10-01] ESEMPIO - Introduzione a RT"
LESSON_TITLE = "Introduzione a RT"

INFO_YAML = """data: '2026-10-01'
materia: ESEMPIO
titolo: Introduzione a RT
docente: Team RT
anno: 2026
esempio: true
"""

TRANSCRIPT_MD = """---
data: '2026-10-01'
materia: ESEMPIO
titolo: Introduzione a RT
---

*00:00*
Benvenuti in RT. Carichi la registrazione della lezione e i materiali del docente, e RT trascrive, divide in unità e rielabora tutto in un testo ordinato.

*00:25*
Quando leggi una lezione hai l'indice a sinistra, le unità con il loro timecode e puoi cliccare su un timecode per ascoltare l'audio da quel punto preciso.

*00:50*
Per creare una lezione carichi la registrazione audio insieme alle slide, ai PDF o alle foto della lavagna, che sono sempre facoltativi.

*01:15*
Mentre RT lavora segui la barra di avanzamento, puoi chiudere la finestra senza perdere nulla, vedi il costo stimato prima di partire e ricevi un avviso a fine lavoro.

*01:40*
Nella scheda Verifica trovi il confronto con le fonti del docente e gli avvisi da accettare o ignorare con un clic.

*02:05*
Puoi modificare il testo direttamente nella lezione, usare Annulla per tornare indietro oppure rigenerare una singola unità.

*02:30*
Con Mettimi alla prova ti eserciti con domande di ripasso a risposta multipla o aperta e leggi subito il commento sulle risposte.

*02:55*
Infine puoi segnare gli stati di studio di ogni unità, organizzare l'orario nel calendario delle lezioni e attivare Telegram in modo facoltativo.
"""

# (macro, titolo macro, unità, titolo unità, testo rielaborato — 80-150 parole per unità)
UNITS = [
    (
        "1",
        "Cos'è RT",
        "1.1",
        "Dalla registrazione al testo",
        "RT trasforma le registrazioni delle tue lezioni universitarie in appunti ordinati, fedeli e pronti per lo studio. "
        "Quando crei una lezione, carichi il file audio e gli eventuali materiali usati dal docente durante la spiegazione. "
        "Da lì il programma lavora in più passaggi automatici: prima trascrive l'audio in testo, poi divide la spiegazione "
        "in sezioni e unità logiche con titoli chiari, infine riscrive ogni unità in modo leggibile senza perdere concetti, "
        "definizioni o formule. Alla fine confronta ciò che hai letto o registrato con le fonti fornite, segnalandoti "
        "eventuali imprecisioni. Così non devi riascoltare ore di audio per ricostruire un singolo passaggio: hai già un "
        "documento completo, organizzato per argomenti e collegato minuto per minuto alla voce del docente.",
    ),
    (
        "1",
        "Cos'è RT",
        "1.2",
        "Come leggere una lezione",
        "Quando apri una lezione trovi a sinistra l'indice delle sezioni e delle unità, utile per saltare subito al punto "
        "che ti interessa. Al centro scorre il testo rielaborato, diviso in blocchi ordinati con il relativo timecode all'inizio "
        "di ciascuna unità. Se un passaggio non ti è chiaro o vuoi risentire le parole esatte del docente, ti basta fare clic "
        "sul timecode per avviare la riproduzione dell'audio proprio da quel minuto, senza dover cercare a mano nella barra "
        "temporale. In alto trovi i pulsanti per aprire i pannelli laterali dedicati a verifica, domande, fonti e dettagli, "
        "mentre puoi scaricare in qualsiasi momento il testo completo in Markdown, in PDF oppure come archivio completo della lezione.",
    ),
    (
        "2",
        "Creare una lezione",
        "2.1",
        "Cosa caricare",
        "Per iniziare una nuova lezione fai clic su «Nuova lezione» nella schermata principale. L'unico elemento indispensabile "
        "è la registrazione audio della spiegazione oppure un trascritto già pronto, ma puoi aggiungere subito anche slide in PDF, "
        "dispense, appunti o foto della lavagna. Tutti i materiali aggiuntivi sono facoltativi: se li alleghi, RT li usa per "
        "arricchire i passaggi poco chiari della voce, inserire formule corrette, collocare le immagini nei punti giusti e "
        "controllare eventuali errori concettuali. Se invece non li hai al momento, puoi creare comunque la lezione e aggiungere "
        "fonti o foto in un secondo momento dalla scheda Fonti. Puoi anche collegare data, materia, docente e ora scegliendo dal calendario.",
    ),
    (
        "2",
        "Creare una lezione",
        "2.2",
        "Mentre RT lavora",
        "Prima di avviare l'elaborazione, RT ti mostra il costo stimato calcolato sui modelli configurati nelle impostazioni, "
        "così sai sempre quanto spenderai prima di partire. Dopo l'avvio compare una barra di avanzamento che indica la fase "
        "in corso tra preparazione, scaletta, rielaborazione, verifica e documento finale. Il lavoro prosegue in background "
        "sul servizio locale: puoi chiudere la finestra o cambiare scheda senza interrompere nulla. Quando la lezione è pronta "
        "o richiede una tua scelta, ricevi un avviso nell'app e, se lo hai attivato, anche una notifica su Telegram. Se usi "
        "la modalità di approvazione della scaletta, puoi controllare i titoli delle unità prima che RT inizi a riscrivere il testo.",
    ),
    (
        "3",
        "Verificare e correggere",
        "3.1",
        "La scheda Verifica",
        "La scheda Verifica confronta il testo riscritto con le slide, le dispense e i materiali del docente caricati nella "
        "lezione, oltre che con la trascrizione originale. Quando trova una possibile incongruenza, una formula incompleta o "
        "una frase poco chiara nell'audio, crea un avviso ordinato per unità e gravità. Ogni avviso mostra la citazione originale, "
        "la spiegazione del dubbio e una correzione proposta pronta da applicare. Puoi decidere con un clic se accettare il "
        "suggerimento, modificare a mano il testo proposto oppure ignorare la segnalazione se la tua formulazione va già bene. "
        "In alto vedi quante segnalazioni restano da decidere prima che la lezione risulti verificata e pronta per l'esportazione.",
    ),
    (
        "3",
        "Verificare e correggere",
        "3.2",
        "Modificare il testo",
        "Se vuoi rifinire un passaggio, correggere un titolo o aggiungere una precisazione personale, puoi aprire la modifica "
        "diretta direttamente dal documento della lezione. Modifichi il testo Markdown con anteprima immediata e puoi salvare "
        "la nuova versione della bozza senza dover rilanciare tutta la pipeline. Se cambi idea, il pulsante Annulla ti permette "
        "di tornare indietro, mentre nella cronologia delle versioni puoi confrontare e recuperare stati precedenti della lezione. "
        "Se invece un'intera unità non ti soddisfa per stile o completezza, puoi rigenerare solo quella unità chiedendo un nuovo "
        "passaggio mirato all'assistente, lasciando intatto tutto il resto del documento e risparmiando tempo e risorse.",
    ),
    (
        "4",
        "Studiare",
        "4.1",
        "Mettimi alla prova",
        "Nella scheda Domande puoi allenarti con il ripasso attivo basato sulle unità della lezione. RT genera un insieme di "
        "domande a scelta multipla, domande mirate su singoli concetti e domande vaste per collegare più parti della spiegazione. "
        "Quando rispondi a un quiz vedi subito se la risposta è corretta e leggi il commento che spiega perché; nelle domande "
        "aperte puoi scrivere la tua risposta oppure registrarla a voce e ricevere una valutazione dettagliata su correttezza e "
        "completezza. Se una domanda non ti convince, puoi votarla o scartarla indicando il motivo, così il sistema migliora nel "
        "tempo. Le risposte restano salvate nello storico e puoi ripassare anche un'intera materia alla volta.",
    ),
    (
        "4",
        "Studiare",
        "4.2",
        "Stati di studio e calendario",
        "Mentre leggi in modalità Studio puoi segnare lo stato di ogni unità: «Da imparare», «In apprendimento», «Appreso» "
        "oppure «Ignorata» per le parti organizzative che non servono all'esame. L'anello di avanzamento nella pagina Lezioni "
        "si aggiorna in tempo reale per mostrarti a colpo d'occhio quanto hai già studiato. Nella sezione Calendario puoi "
        "impostare l'orario settimanale delle tue materie: RT collega automaticamente le lezioni registrate agli slot del giorno "
        "e ti avvisa se mancano ore da recuperare. Infine, nelle impostazioni puoi collegare in modo facoltativo un bot Telegram "
        "personale per ricevere notifiche a fine elaborazione o fare ripasso rapido direttamente dal telefono.",
    ),
]

TOPICS = [
    "Da audio a testo",
    "Lettura e timecode",
    "Creazione lezione",
    "Verifica e modifica",
    "Ripasso attivo e calendario",
]

ISSUE = {
    "unit": "3.1",
    "citazione": "con le slide, le dispense e i materiali del docente",
    "sostituzione": "con le slide, le dispense, gli appunti e i materiali del docente",
    "motivazione": "Esempio di avviso in Verifica: RT confronta il testo rielaborato anche con eventuali appunti aggiunti alle fonti.",
}

QUESTIONS = {
    "1.2": (
        "Cosa succede quando fai clic sul timecode all'inizio di un'unità?",
        [
            "Si apre il pannello per modificare il titolo",
            "Parte la riproduzione dell'audio da quel minuto preciso",
            "Viene esportato il documento in PDF",
            "L'unità viene segnata come ignorata",
        ],
        1,
    ),
    "2.1": (
        "Quale file è indispensabile per creare una nuova lezione in RT?",
        [
            "Una registrazione audio oppure un trascritto già pronto",
            "Le slide PDF della lezione",
            "L'orario settimanale del calendario",
            "Una foto della lavagna",
        ],
        0,
    ),
    "2.2": (
        "Cosa puoi fare mentre la barra di avanzamento mostra che RT sta elaborando la lezione?",
        [
            "Devi lasciare la pagina aperta fino alla fine",
            "Devi riavviare la pipeline a ogni fase",
            "Puoi chiudere la finestra senza interrompere il lavoro in background",
            "Non puoi vedere il costo stimato finché non finisce",
        ],
        2,
    ),
    "3.1": (
        "A cosa serve la scheda Verifica dentro una lezione?",
        [
            "A cambiare la materia della lezione",
            "A confrontare il testo con le fonti e applicare o ignorare gli avvisi",
            "A registrare una risposta vocale di ripasso",
            "A impostare le lezioni settimanali nel calendario",
        ],
        1,
    ),
    "4.1": (
        "Come valuta «Mettimi alla prova» le risposte alle domande aperte?",
        [
            "Assegna un punteggio casuale se superi dieci parole",
            "Confronta soltanto l'esattezza ortografica",
            "Le lascia sempre senza commento",
            "Valuta correttezza e completezza della risposta scritta o registrata a voce",
        ],
        3,
    ),
}


def _scripted_response(original):
    """Risposte del mock sostituite con il contenuto della lezione di esempio."""
    import re
    from rt.core.models import DraftUnit, LessonTopics, Outline, OutlineMacro, OutlineUnit, RecallQuestion

    def unit_segments(prompt):
        return list(dict.fromkeys(re.findall(r"seg_\d{6,}", prompt)))

    def fake(self, job_name, prompt, response_model):
        name = response_model.__name__
        if name == "Outline":
            segs = unit_segments(prompt) or [f"seg_{i + 1:06d}" for i in range(len(UNITS))]
            while len(segs) < len(UNITS):
                segs.append(segs[-1])
            groups = {}
            for i, (mid, mtitle, uid, utitle, _text) in enumerate(UNITS):
                groups.setdefault((mid, mtitle), []).append(OutlineUnit(
                    id=uid, title=utitle, start_segment_id=segs[i], end_segment_id=segs[i], key_concepts=[utitle]))
            macros = [OutlineMacro(id=mid, title=mtitle, units=units) for (mid, mtitle), units in groups.items()]
            return Outline(lesson_title=LESSON_TITLE, macro_sections=macros)
        if name == "LessonTopics":
            return LessonTopics(argomenti=TOPICS)
        if name == "DraftUnit":
            match = re.search(r"ID:\s*([0-9.]+)", prompt)
            uid = match.group(1) if match else UNITS[0][2]
            unit = next(u for u in UNITS if u[2] == uid)
            segs = unit_segments(prompt) or ["seg_000001"]
            return DraftUnit(unit_id=uid, title=unit[3], start_segment_id=segs[0], end_segment_id=segs[-1],
                             source_segment_ids=segs, content=unit[4])
        if name == "ReviewFindingList":
            match = re.search(r"UNITÀ:\s*([0-9.]+)", prompt)
            if match and match.group(1) == ISSUE["unit"] and ISSUE["citazione"] in prompt:
                return response_model(issues=[{"tipo": "concettuale", "gravita": "bassa",
                                               "citazione": ISSUE["citazione"],
                                               "motivazione": ISSUE["motivazione"],
                                               "sostituzione": ISSUE["sostituzione"]}])
            return response_model(issues=[])
        if name == "RecallQuestion":
            match = re.search(r"UNIT[ÀA]:\s*([\w.]+)", prompt)
            uid = match.group(1) if match else ""
            if uid in QUESTIONS:
                text, options, correct = QUESTIONS[uid]
                return RecallQuestion(id="recall_mock", type="quiz", unit_ids=[uid], question_text=text,
                                      options=options, correct_index=correct)
        return original(self, job_name, prompt, response_model)
    return fake


def _rewrite_questions(path: str) -> None:
    """Il mock del recall scrive domande generiche: tiene una domanda per le unità di QUESTIONS
    e le dà testo e opzioni veri."""
    import json
    with open(path, encoding="utf-8") as f:
        bank = json.load(f)
    kept, seen = [], set()
    for question in bank.get("questions", []):
        uid = (question.get("unit_ids") or [""])[0]
        if uid in QUESTIONS and uid not in seen:
            seen.add(uid)
            text, options, correct = QUESTIONS[uid]
            question.update(question_text=text, options=options, correct_index=correct,
                            pregenerated_material=f"La risposta corretta è «{options[correct]}».")
            kept.append(question)
    bank["questions"] = kept
    with open(path, "w", encoding="utf-8") as f:
        json.dump(bank, f, ensure_ascii=False, indent=2)


def _attach_screenshots(lesson_dir: str, screenshot_dir: Optional[str]) -> None:
    """Allega alle unità gli screenshot WebP trovati in <screenshot_dir>/<unit_id>.webp.
    Se i file mancano non fa nulla e non solleva errori."""
    if not screenshot_dir or not os.path.isdir(screenshot_dir):
        return
    from rt.pipeline.add_images import (
        compute_image_hash,
        load_image_descriptions,
        save_image_descriptions,
        save_raw_image,
    )
    from rt.pipeline.build import run_build
    from rt.pipeline.image_placement import save_image_placement

    descriptions = load_image_descriptions(lesson_dir)
    placement_units = {}
    for _mid, _mtitle, uid, utitle, _text in UNITS:
        shot_path = os.path.join(screenshot_dir, f"{uid}.webp")
        if not os.path.isfile(shot_path):
            continue
        with open(shot_path, "rb") as f:
            raw_bytes = f.read()
        img_hash = compute_image_hash(raw_bytes)
        rel_path = save_raw_image(lesson_dir, raw_bytes, img_hash, ext=".webp")
        descriptions[img_hash] = {
            "filename": rel_path,
            "source": f"sample:{uid}",
            "slide_title": utitle,
            "alt_text": f"Schermata di RT: {utitle}",
            "summary_keywords": [utitle],
        }
        placement_units[uid] = [img_hash]

    if not placement_units:
        return
    save_image_descriptions(lesson_dir, descriptions)
    save_image_placement(lesson_dir, macros={}, carousel=False, units=placement_units)
    run_build(lesson_dir, force=True, rename_folder=False)


def build_sample_lesson(output_path: str, screenshot_dir: Optional[str] = DEFAULT_SCREENSHOT_DIR) -> str:
    from rt.llm.client import LLMClient
    from rt.llm.jev_client import JevError
    from rt.services.context import RunContext
    from rt.services.pipeline_service import PipelineOptions, run_pipeline
    from rt.storage.export import export_zip

    temp_root = tempfile.mkdtemp(prefix="rt-sample-lesson-")
    lesson_dir = os.path.join(temp_root, FOLDER_NAME)
    os.makedirs(lesson_dir)
    try:
        with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
            f.write(INFO_YAML)
        with open(os.path.join(lesson_dir, "trascritto grezzo.md"), "w", encoding="utf-8") as f:
            f.write(TRANSCRIPT_MD)
        original = LLMClient._generate_mock_response
        secrets_env = {} if os.environ.get("RT_SECRETS_FILE") else {
            "RT_SECRETS_FILE": os.path.join(temp_root, "absent-secrets.enc"),
        }
        with (
            mock.patch.dict(os.environ, secrets_env),
            mock.patch.object(LLMClient, "_generate_mock_response", _scripted_response(original)),
            mock.patch("rt.llm.jev_client.call_jev", side_effect=JevError("disabilitato nella generazione esempio")),
            mock.patch("rt.security.secrets.keyring_get_master_key", return_value=None),
        ):
            options = PipelineOptions(mock=True, with_review=True, auto_accept=True, rename=False)
            result = run_pipeline([lesson_dir], options, RunContext())
            if result.error:
                raise RuntimeError(f"Pipeline della lezione di esempio fallita: {result.error}")
            try:
                from rt.services.recall_service import generate_pool
                generate_pool(lesson_dir, force_mock=True, qtypes=["quiz"])
                _rewrite_questions(os.path.join(lesson_dir, "_state", "recall_questions.json"))
            except Exception as exc:  # noqa: BLE001 - le domande sono un di più
                print(f"⚠️  Domande di esempio non generate: {exc}")

        _attach_screenshots(lesson_dir, screenshot_dir)

        for noise in ("llm_debug.log", "telemetry_summary.json"):
            path = os.path.join(lesson_dir, "_state", noise)
            if os.path.exists(path):
                os.remove(path)
        archive_bytes = export_zip(lesson_dir, scope="all")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(archive_bytes)
        size_kb = os.path.getsize(output_path) / 1024
        print(f"✅ Lezione di esempio creata in {output_path} ({size_kb:.1f} KB)")
        if size_kb > 3072:
            raise ValueError(f"L'archivio supera 3 MB: {size_kb:.1f} KB")
        return output_path
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    os.environ.setdefault("RT_DATABASE_URL", "off")
    os.environ.setdefault("RT_SECRETS_FILE", os.path.join(tempfile.gettempdir(), "rt-sample-absent-secrets.enc"))
    build_sample_lesson(os.path.join(ROOT_DIR, "rt", "assets", "esempio", "lezione-esempio.rt"))
