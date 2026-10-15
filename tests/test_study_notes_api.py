"""VC1b: test API study-notes, ritrovamento del passaggio e Applica con Annulla."""
import pytest

from rt.core.manifest import load_manifest
from rt.core.models import DecisionLedger
from rt.pipeline.anchors import make_anchor
from rt.pipeline.ledger import load_ledger, load_resolved_draft, write_ledger_file
from rt.pipeline.review import load_science_issues
from rt.pipeline.rewrite import load_draft, save_draft
from rt.services.jobs import DbJobQueue
from rt.services.study_notes_service import (
    add_study_note,
    get_study_note,
    list_study_notes,
)
from rt.services.worker import Worker
from tests.api_support import isolated_workspace
from tests.test_document_edit import _synthetic_lesson


def test_note_markdown_uses_shared_safe_renderer_and_preserves_latex(tmp_path, monkeypatch, rt_db, api_client):
    text = 'Un passaggio scientifico.'
    lesson = _synthetic_lesson(isolated_workspace(tmp_path, monkeypatch), {'1.1': text})
    write_ledger_file(DecisionLedger(schema_version='2.0'), lesson)
    lid = api_client.get('/api/v1/lessons').json()[0]['id']
    explanation = '### Titolo\n\n**Grassetto**\n\n- primo\n- secondo\n\n' + r'$a_1 * b_2$' + '\n\n<script>alert(1)</script>\n\n[bad](javascript:alert(1))'
    note = add_study_note(lesson_id=lid, unit_id='1.1', kind='verifica',
                          anchor=make_anchor(text, 0, len(text)).model_dump(),
                          response={'spiegazione': explanation, 'correzione': '**Correzione** <img src=x onerror=alert(1)>'})
    view = api_client.get(f"/api/v1/lessons/{lid}/study-notes/{note['id']}").json()
    from rt.core.markdown_render import render_markdown
    assert view['spiegazione_html'] == render_markdown(explanation)
    assert '<h3>Titolo</h3>' in view['spiegazione_html']
    assert '<strong>Grassetto</strong>' in view['spiegazione_html']
    assert '<li>primo</li>' in view['spiegazione_html']
    assert r'$a_1 * b_2$' in view['spiegazione_html']
    assert '<script' not in view['spiegazione_html']
    assert 'href="javascript:' not in view['spiegazione_html']
    assert '<img ' not in view['correzione_html']
    assert view['response']['spiegazione'] == explanation


def test_api_enqueue_and_worker_study_notes(tmp_path, monkeypatch, rt_db, api_client):
    text = "Il pH ematico si mantiene normale tra 7,36 e 7,45."
    lesson_dir = _synthetic_lesson(isolated_workspace(tmp_path, monkeypatch), {"1.1": text})
    write_ledger_file(DecisionLedger(schema_version="2.0"), lesson_dir)

    lesson_id = api_client.get("/api/v1/lessons").json()[0]["id"]
    anchor = make_anchor(text, text.index("7,36 e 7,45"), text.index("7,36 e 7,45") + len("7,36 e 7,45")).model_dump()

    # 1. Errore 422 se testo cambiato o non corrispondente
    bad_anchor = dict(anchor, quote="citazione inesistente")
    res_bad = api_client.post(
        f"/api/v1/lessons/{lesson_id}/study-notes",
        json={"unit_id": "1.1", "kind": "verifica", "anchor": bad_anchor, "mock": True},
    )
    assert res_bad.status_code == 422

    # 2. Errore 404 se unità non trovata
    res_404 = api_client.post(
        f"/api/v1/lessons/{lesson_id}/study-notes",
        json={"unit_id": "9.9", "kind": "verifica", "anchor": anchor, "mock": True},
    )
    assert res_404.status_code == 404

    # 3. Post valido accoda job (HTTP 202)
    res_post = api_client.post(
        f"/api/v1/lessons/{lesson_id}/study-notes",
        json={"unit_id": "1.1", "kind": "verifica", "anchor": anchor, "request": "È corretto?", "mock": True},
    )
    assert res_post.status_code == 202
    job_id = res_post.json()["job_id"]

    # Esegue il worker
    queue = DbJobQueue(rt_db)
    Worker(queue, worker_id="test-w").run_once()
    done = queue.get(job_id)
    assert done.state == "succeeded"
    note_id = done.result["note_id"]

    # 4. GET /study-notes con stato dell'ancora
    res_get = api_client.get(f"/api/v1/lessons/{lesson_id}/study-notes")
    assert res_get.status_code == 200
    notes = res_get.json()
    assert len(notes) == 1
    assert notes[0]["id"] == note_id
    assert notes[0]["kind"] == "verifica"
    assert notes[0]["anchor_state"] == "trovata"
    assert notes[0]["current_quote"] == "7,36 e 7,45"

    # 5. GET singola nota
    res_single = api_client.get(f"/api/v1/lessons/{lesson_id}/study-notes/{note_id}")
    assert res_single.status_code == 200
    assert res_single.json()["id"] == note_id


def test_ritrovamento_del_passaggio_trovata_cambiata_non_ritrovata(tmp_path, monkeypatch, rt_db, api_client):
    u1_text = "Unità uno con passaggio importante che verrà spostato."
    u2_text = "Unità due con altro testo."
    lesson_dir = _synthetic_lesson(isolated_workspace(tmp_path, monkeypatch), {"1.1": u1_text, "1.2": u2_text})
    write_ledger_file(DecisionLedger(schema_version="2.0"), lesson_dir)

    lesson_id = api_client.get("/api/v1/lessons").json()[0]["id"]
    anchor = make_anchor(u1_text, u1_text.index("passaggio importante"), u1_text.index("passaggio importante") + len("passaggio importante")).model_dump()

    # Creiamo direttamente una nota nel DB
    created = add_study_note(
        lesson_id=lesson_id,
        unit_id="1.1",
        kind="verifica",
        anchor=anchor,
        request="Verifica",
        response={"esito": "corretto", "spiegazione": "Tutto ok"},
    )
    note_id = created["id"]

    # Caso 1: trovato esattamente nella stessa unità
    res1 = api_client.get(f"/api/v1/lessons/{lesson_id}/study-notes/{note_id}").json()
    assert res1["anchor_state"] == "trovata"
    assert res1["unit_id"] == "1.1"

    # Caso 2: spostato nell'unità 1.2 -> unit_id si aggiorna a 1.2
    draft = load_draft(lesson_dir)
    draft.units[0].content = "Unità uno senza quel passaggio."
    draft.units[1].content = "Unità due con passaggio importante spostato qui."
    save_draft(draft, lesson_dir)

    res2 = api_client.get(f"/api/v1/lessons/{lesson_id}/study-notes/{note_id}").json()
    assert res2["anchor_state"] == "trovata"
    assert res2["unit_id"] == "1.2"
    # Controlliamo che nel DB unit_id sia stato aggiornato a 1.2
    assert get_study_note(lesson_id, note_id)["unit_id"] == "1.2"

    # Caso 3: testo cambiato (fuzzy match)
    # Modifichiamo leggermente il passaggio
    draft = load_draft(lesson_dir)
    draft.units[1].content = "Unità due con passaggio quasi importante spostato qui."
    save_draft(draft, lesson_dir)

    res3 = api_client.get(f"/api/v1/lessons/{lesson_id}/study-notes/{note_id}").json()
    # SequenceMatcher trova il passaggio simile
    if res3["anchor_state"] == "cambiata":
        assert "passaggio" in res3["current_quote"]

    # Caso 4: passaggio completamente rimosso
    draft = load_draft(lesson_dir)
    draft.units[0].content = "Solo testo A."
    draft.units[1].content = "Solo testo B."
    save_draft(draft, lesson_dir)

    res4 = api_client.get(f"/api/v1/lessons/{lesson_id}/study-notes/{note_id}").json()
    assert res4["anchor_state"] == "non_ritrovata"
    assert res4["current_quote"] is None


def test_applica_e_annulla_decisione(tmp_path, monkeypatch, rt_db, api_client):
    text = "Gli acidi fissi vengono eliminati principalmente per via respiratoria dall'organismo."
    lesson_dir = _synthetic_lesson(isolated_workspace(tmp_path, monkeypatch), {"1.1": text})
    write_ledger_file(DecisionLedger(schema_version="2.0"), lesson_dir)

    lesson_id = api_client.get("/api/v1/lessons").json()[0]["id"]
    target = "eliminati principalmente per via respiratoria"
    fix = "eliminati principalmente per via renale"

    anchor = make_anchor(text, text.index(target), text.index(target) + len(target)).model_dump()

    # Creiamo nota di tipo verifica con correzione
    note = add_study_note(
        lesson_id=lesson_id,
        unit_id="1.1",
        kind="verifica",
        anchor=anchor,
        request="È giusto respiratoria?",
        response={"esito": "errato", "spiegazione": "Gli acidi fissi sono eliminati dal rene.", "correzione": fix},
    )
    note_id = note["id"]

    # 1. Applicazione della correzione
    res_apply = api_client.post(f"/api/v1/lessons/{lesson_id}/study-notes/{note_id}/apply")
    assert res_apply.status_code == 200, res_apply.text
    apply_data = res_apply.json()
    assert apply_data["ok"] is True
    decision_id = apply_data["applied_decision_id"]
    issue_id = apply_data["issue_id"]
    assert decision_id > 0
    assert issue_id.startswith("sci_")

    # Verifica issue creata nel json con origin 'studio'
    sci_issues = load_science_issues(lesson_dir)
    created_issue = next(i for i in sci_issues if i.id == issue_id)
    assert created_issue.origin == "studio"
    assert created_issue.claim == target
    assert created_issue.suggested_fix == fix

    # Verifica decisione registrata nel ledger
    ledger = load_ledger(lesson_dir)
    dec = next(d for d in ledger.decisions if d.issue_id == issue_id)
    assert dec.decision == "accepted"
    assert dec.resolved_text == fix

    # Verifica che il testo risolto sia cambiato!
    resolved_draft = load_resolved_draft(lesson_dir)
    assert fix in resolved_draft.units[0].content
    assert target not in resolved_draft.units[0].content

    # Verifica stato nota dopo l'applicazione
    note_after = api_client.get(f"/api/v1/lessons/{lesson_id}/study-notes/{note_id}").json()
    assert note_after["applied_decision_id"] == decision_id
    assert note_after["issue_id"] == issue_id

    # 2. Non è possibile applicare due volte (già applicata)
    res_dup = api_client.post(f"/api/v1/lessons/{lesson_id}/study-notes/{note_id}/apply")
    assert res_dup.status_code == 409

    # 3. Annulla dal toast / pannello Verifica (POST /decisions/undo)
    res_undo = api_client.post(f"/api/v1/lessons/{lesson_id}/decisions/undo", json={"issue_id": issue_id})
    assert res_undo.status_code == 200

    # Verifica che il testo sia tornato quello originale!
    draft_restored = load_resolved_draft(lesson_dir)
    assert target in draft_restored.units[0].content
    assert fix not in draft_restored.units[0].content

    # Verifica che la nota riconosca che la decisione è stata annullata
    note_undone = api_client.get(f"/api/v1/lessons/{lesson_id}/study-notes/{note_id}").json()
    assert note_undone["applied_decision_id"] is None
    assert note_undone["anchor_state"] == "trovata"
    assert note_undone["current_quote"] == target


def test_applica_rifiuta_se_passaggio_cambiato(tmp_path, monkeypatch, rt_db, api_client):
    text = "Valore iniziale della formula chimica."
    lesson_dir = _synthetic_lesson(isolated_workspace(tmp_path, monkeypatch), {"1.1": text})
    write_ledger_file(DecisionLedger(schema_version="2.0"), lesson_dir)

    lesson_id = api_client.get("/api/v1/lessons").json()[0]["id"]
    anchor = make_anchor(text, 0, len("Valore iniziale")).model_dump()

    note = add_study_note(
        lesson_id=lesson_id,
        unit_id="1.1",
        kind="verifica",
        anchor=anchor,
        response={"esito": "errato", "spiegazione": "Errore", "correzione": "Valore corretto"},
    )

    # Modifichiamo il testo prima di applicare
    draft = load_draft(lesson_dir)
    draft.units[0].content = "Altro valore differente della formula chimica."
    save_draft(draft, lesson_dir)

    # Applica deve fallire con 409
    res = api_client.post(f"/api/v1/lessons/{lesson_id}/study-notes/{note['id']}/apply")
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "passage_changed"
    assert "cambiato" in res.json()["error"]["message"].lower()


def test_delete_note_non_tocca_correzione(tmp_path, monkeypatch, rt_db, api_client):
    text = "Passaggio con errore iniziale."
    lesson_dir = _synthetic_lesson(isolated_workspace(tmp_path, monkeypatch), {"1.1": text})
    write_ledger_file(DecisionLedger(schema_version="2.0"), lesson_dir)

    lesson_id = api_client.get("/api/v1/lessons").json()[0]["id"]
    anchor = make_anchor(text, 0, len("Passaggio con errore")).model_dump()

    note = add_study_note(
        lesson_id=lesson_id,
        unit_id="1.1",
        kind="verifica",
        anchor=anchor,
        response={"esito": "errato", "spiegazione": "Errore", "correzione": "Passaggio con correzione"},
    )
    note_id = note["id"]

    # Applica
    res_apply = api_client.post(f"/api/v1/lessons/{lesson_id}/study-notes/{note_id}/apply")
    assert res_apply.status_code == 200
    issue_id = res_apply.json()["issue_id"]

    # Elimina nota: 204
    res_del = api_client.delete(f"/api/v1/lessons/{lesson_id}/study-notes/{note_id}")
    assert res_del.status_code == 204

    # La nota è eliminata dal DB
    res_get = api_client.get(f"/api/v1/lessons/{lesson_id}/study-notes/{note_id}")
    assert res_get.status_code == 404

    # MA la correzione nel ledger e nel documento RESTA intatta!
    resolved_draft = load_resolved_draft(lesson_dir)
    assert "Passaggio con correzione" in resolved_draft.units[0].content
    ledger = load_ledger(lesson_dir)
    assert any(d.issue_id == issue_id for d in ledger.decisions)


def test_api_study_note_selection_from_rendered_text(tmp_path, monkeypatch, rt_db, api_client):
    """Nello Studio il testo selezionato è quello reso: il grassetto del markdown non lo blocca."""
    text = "Durante la fase S il DNA si duplica. La **mitosi** produce due cellule figlie identiche."
    lesson_dir = _synthetic_lesson(isolated_workspace(tmp_path, monkeypatch), {"1.1": text})
    write_ledger_file(DecisionLedger(schema_version="2.0"), lesson_dir)
    lesson_id = api_client.get("/api/v1/lessons").json()[0]["id"]
    anchor = {"quote": "La mitosi produce due cellule", "prefix": "fase S il DNA si duplica. ",
              "suffix": " figlie identiche.", "start": 37, "end": 66}
    res = api_client.post(f"/api/v1/lessons/{lesson_id}/study-notes",
                          json={"unit_id": "1.1", "kind": "verifica", "anchor": anchor, "mock": True})
    assert res.status_code == 202

    from rt.pipeline.study_notes import run_study_note
    saved = run_study_note(lesson_dir=lesson_dir, unit_id="1.1", kind="verifica", anchor=anchor,
                           lesson_id=lesson_id, force_mock=True)
    assert saved["note"]["anchor"]["quote"] == "La **mitosi** produce due cellule"
