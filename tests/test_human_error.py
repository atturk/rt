import pytest

from rt.services.human_error import human_error


def test_human_error_network_error():
    err1 = "…il modello openai/gpt-6-luna ha dato errore (network_error): ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))…"
    assert human_error(err1) == "Connessione al modello interrotta."

    err2 = "Connection aborted by peer"
    assert human_error(err2) == "Connessione al modello interrotta."

    err3 = "RemoteDisconnected('no response')"
    assert human_error(err3) == "Connessione al modello interrotta."


def test_human_error_macparakeet_failed():
    err = "SetupError: Trascrizione macparakeet-cli JSON fallita per 'finto-audio.mp3' (codice uscita: 1). Dettagli errore:"
    assert human_error(err) == "Non riesco a leggere l'audio «finto-audio.mp3»."


def test_human_error_timeout():
    err = "LLM request failed: timeout after 60s"
    assert human_error(err) == "Il modello non ha risposto in tempo."


def test_human_error_fallback_strips_class_prefix():
    err = "SetupError: Impossibile creare la cartella temporanea."
    assert human_error(err) == "Impossibile creare la cartella temporanea."

    err2 = "RuntimeError: Qualcosa è andato storto"
    assert human_error(err2) == "Qualcosa è andato storto"


def test_human_error_preserves_suffix():
    err = "SetupError: Trascrizione macparakeet-cli JSON fallita per 'lezione.m4a' (codice uscita: 1). Le unità completate sono salvate: Riprova rifà solo quelle mancanti."
    assert human_error(err) == "Non riesco a leggere l'audio «lezione.m4a». Le unità completate sono salvate: Riprova rifà solo quelle mancanti."

    err2 = "network_error: connection drop. Le unità completate sono salvate: Riprova rifà solo quelle mancanti."
    assert human_error(err2) == "Connessione al modello interrotta. Le unità completate sono salvate: Riprova rifà solo quelle mancanti."

    err3 = "RuntimeError: Errore generico. Le unità completate sono salvate: Riprova rifà solo quelle mancanti."
    assert human_error(err3) == "Errore generico. Le unità completate sono salvate: Riprova rifà solo quelle mancanti."


def test_human_error_empty():
    assert human_error(None) == ""
    assert human_error("") == ""


def test_human_error_missing_image_models():
    err_desc = "LLMError: La route per il job 'image_description' non è configurata (provider o model mancante)."
    assert human_error(err_desc) == (
        "Per leggere le immagini serve un modello di descrizione immagini. "
        "Sceglilo in Impostazioni › Modelli."
    )
    err_gen = "ValueError: Configura il modello Generazione immagini IA in Impostazioni → Modelli"
    assert human_error(err_gen) == (
        "Per generare le immagini serve un modello di generazione immagini. "
        "Sceglilo in Impostazioni › Modelli."
    )


def test_describe_images_without_model_raises_missing_phase_model(tmp_path, monkeypatch):
    from rt.core.image_extract import ExtractedImage
    from rt.pipeline.add_images import compute_image_hash, describe_new_images
    from rt.services.errors import MissingPhaseModel
    from tests.api_support import workspace_with_example_config

    workspace_with_example_config(tmp_path, monkeypatch)
    lesson_dir = tmp_path / "lezione"
    lesson_dir.mkdir()
    img = ExtractedImage(image_bytes=b"fake-png-bytes", source_label="folder:a.png")
    img_hash = compute_image_hash(img.image_bytes)
    with pytest.raises(MissingPhaseModel) as exc:
        describe_new_images(str(lesson_dir), [(img, img_hash)], lesson_context="Test", force_mock=False)
    assert exc.value.code == "missing_model"
    assert exc.value.message == (
        "Per leggere le immagini serve un modello di descrizione immagini. "
        "Sceglilo in Impostazioni › Modelli."
    )
    assert exc.value.details == {"phase": "image_description", "path": "/impostazioni/modelli"}


def test_worker_preserves_missing_model_result_code(tmp_path, monkeypatch, rt_db):
    from rt.services.jobs import DbJobQueue, JobState
    from rt.services.worker import Worker
    from tests.api_support import make_lesson, workspace_with_example_config

    root = workspace_with_example_config(tmp_path, monkeypatch)
    lesson_dir = make_lesson(str(root))
    img_dir = tmp_path / "work" / lesson_dir
    import os
    os.makedirs(os.path.join(lesson_dir, "assets", "images"), exist_ok=True)
    with open(os.path.join(lesson_dir, "assets", "images", "foto.png"), "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\nfake")

    queue = DbJobQueue(rt_db)
    job_id = queue.enqueue("describe_images", lesson_dir, {"names": ["foto.png"], "mock": False})
    worker = Worker(queue, worker_id="w-test", mock=False)
    info = worker.run_once()
    assert info is not None
    assert info.state == JobState.FAILED.value
    assert info.error == (
        "Per leggere le immagini serve un modello di descrizione immagini. "
        "Sceglilo in Impostazioni › Modelli."
    )
    assert info.result == {"code": "missing_model", "details": {"phase": "image_description", "path": "/impostazioni/modelli"}}


def test_enrichment_image_without_model_raises_missing_phase_model(tmp_path, monkeypatch):
    from rt.llm.enrichment_media import generate_image
    from rt.services.errors import MissingPhaseModel
    from tests.api_support import workspace_with_example_config

    workspace_with_example_config(tmp_path, monkeypatch)
    with pytest.raises(MissingPhaseModel) as exc:
        generate_image("schema cellula", str(tmp_path))
    assert exc.value.code == "missing_model"
    assert exc.value.details == {"phase": "enrichment_image", "path": "/impostazioni/modelli"}
