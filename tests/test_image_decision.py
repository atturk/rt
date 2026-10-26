"""Lettura "decision": il modello decisionale guarda l'immagine invece della descrizione."""
import base64
import io
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from rt.llm import jev_client as jev
from rt.llm.decision_images import image_part, normalize_image
from rt.llm.telemetry import TelemetryStore, use_telemetry
from rt.pipeline import image_decision
from rt.pipeline.add_images import compute_image_hash, load_image_descriptions, run_add_images
from rt.pipeline.image_placement import load_image_placement
from rt.pipeline.add_images import _mock_png
from tests.test_add_images_mapping import lesson  # noqa: F401  (fixture)

pytestmark = pytest.mark.decision_reader


def _png(size, mode="RGB", color="red", fmt="PNG", exif_rotate=False):
    out = io.BytesIO()
    image = Image.new(mode, size, color)
    if exif_rotate:
        exif = Image.Exif()
        exif[0x0112] = 6  # ruotata di 90°
        image.save(out, "JPEG", exif=exif)
    else:
        image.save(out, fmt)
    return out.getvalue()


def _decoded(part):
    url = part["image_url"]["url"]
    mime, data = url[5:].split(";base64,")
    return mime, Image.open(io.BytesIO(base64.b64decode(data)))


def test_image_part_respects_jev_limits():
    mime, big = _decoded(image_part(_png((4000, 3000))))
    assert mime == "image/png" and max(big.size) == 1568
    _, small = _decoded(image_part(_png((100, 50))))
    assert min(small.size) >= 280 and small.size == (280, 280)
    _, flat = _decoded(image_part(_png((300, 300), mode="RGBA", color=(0, 0, 0, 0))))
    assert flat.mode == "RGB" and flat.getpixel((10, 10)) == (255, 255, 255)
    data, mime = normalize_image(_png((600, 300), fmt="JPEG", exif_rotate=True))
    assert mime == "image/jpeg" and Image.open(io.BytesIO(data)).size == (300, 600)


def test_state_with_image_is_sent_as_list_and_never_logged(tmp_path):
    part = image_part(_png((300, 300)))
    body = {"model": "typesafe/jev-1.14", "answers": {"role": {"type": "choice", "choice": "contenuto",
            "confidence": 0.9, "probabilities": {"contenuto": 0.9, "introduttiva": 0.05, "irrilevante": 0.05}}}}
    post = MagicMock(return_value=MagicMock(status_code=200, json=MagicMock(return_value=body)))
    questions = {"role": jev.JevChoiceQuestion(instructions="r", criteria=dict(image_decision.ROLES))}
    with patch.object(jev.GLOBAL_CREDENTIALS, "get_api_key", return_value="sk-test"), \
            patch.object(jev.requests, "post", post), use_telemetry(TelemetryStore()):
        jev.call_jev(["IMMAGINE", part], questions, job_name="image_unit_judge", lesson_dir=str(tmp_path),
                     timeout_seconds=15)
    sent = post.call_args.kwargs
    assert sent["json"]["state"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert sent["timeout"] == 60
    log = "\n".join(p.read_text() for p in tmp_path.rglob("*.log"))
    assert '"images": 1' in log and "base64" not in log


def test_rejected_image_error_hides_base64():
    part = image_part(_png((300, 300)))
    error = {"error": {"message": f"bad image {part['image_url']['url']}"}}
    post = MagicMock(return_value=MagicMock(status_code=422, json=MagicMock(return_value=error)))
    with patch.object(jev.GLOBAL_CREDENTIALS, "get_api_key", return_value="sk-test"), \
            patch.object(jev.requests, "post", post), use_telemetry(TelemetryStore()):
        with pytest.raises(jev.JevError) as caught:
            jev.call_jev(["x", part], {"q": jev.JevNoulQuestion(instructions="q")}, job_name="t")
    assert caught.value.http_status == 422 and "base64" not in str(caught.value)


OUTLINE = SimpleNamespace(macro_sections=[
    SimpleNamespace(id="1", title="Organelli", units=[
        SimpleNamespace(id="1.1", title="Mitocondri", key_concepts=["ATP"]),
        SimpleNamespace(id="1.2", title="Cloroplasti", key_concepts=[])]),
])
UNITS = [{"id": "1.1", "macro_id": "1", "title": "Mitocondri", "content": "Respirazione"},
         {"id": "1.2", "macro_id": "1", "title": "Cloroplasti", "content": "Fotosintesi"}]


def _answers(role, place, probability=0.9):
    labels = ["macro_0", "unit_0", "unit_1", "none"]
    return SimpleNamespace(answers={
        "role": jev.JevChoiceAnswer(choice=role, confidence=0.9,
                                    probabilities={r: (0.9 if r == role else 0.05) for r in image_decision.ROLES}),
        "place": jev.JevChoiceAnswer(choice=place, confidence=probability,
                                     probabilities={k: (probability if k == place else 0.0) for k in labels}),
    })


@pytest.fixture
def real_decision(monkeypatch):
    import rt.llm.client
    import rt.services.enrichment_service as enrichment
    monkeypatch.setattr(rt.llm.client, "LLMClient", lambda force_mock=False: SimpleNamespace(force_mock=False))
    calls = []

    def install(*answers):
        queue = list(answers)

        def decision(state, questions, **kwargs):
            calls.append((state, questions))
            return queue.pop(0)
        monkeypatch.setattr(enrichment, "decision", decision)
        return calls
    return install


@pytest.mark.parametrize("role,place,probability,expected", [
    ("introduttiva", "unit_0", 0.9, ([], [])),
    ("contenuto", "macro_0", 0.9, ([], ["1"])),
    ("contenuto", "unit_1", 0.9, (["1.2"], [])),
    ("contenuto", "unit_1", 0.5, ([], [])),
])
def test_decide_image_places_only_content_above_threshold(tmp_path, real_decision, role, place, probability, expected):
    calls = real_decision(_answers(role, place, probability))
    cached = {}
    units, macros, got_role = image_decision.decide_image(
        str(tmp_path), OUTLINE, "h" * 64, _png((300, 300)), "testo della slide", cached, lesson_units=UNITS)
    assert (units, macros) == expected and got_role == role
    state, questions = calls[0]
    assert state[0] == "IMMAGINE DA COLLOCARE" and state[1]["type"] == "image_url"
    assert state[2].startswith("TESTO ESTRATTO DALLA PAGINA\ntesto della slide")
    assert "[unit_0] 1.1 Mitocondri" in state[3] and "Concetti: ATP" in state[3]
    assert set(questions) == {"role", "place"} and "none" in questions["place"].criteria


def test_decide_image_uses_the_cache(tmp_path, real_decision):
    calls = real_decision(_answers("contenuto", "unit_0"))
    cached = {}
    args = (str(tmp_path), OUTLINE, "h" * 64, _png((300, 300)), "", cached)
    first = image_decision.decide_image(*args, lesson_units=UNITS)
    second = image_decision.decide_image(*args, lesson_units=UNITS)
    assert first == second == (["1.1"], [], "contenuto") and len(calls) == 1
    assert json.loads((tmp_path / "assets/images/decisions.json").read_text())["h" * 64]["place"] == "unit_0"


def test_decision_reader_never_describes(lesson, tmp_path, monkeypatch):  # noqa: F811
    import rt.pipeline.add_images as add_images
    monkeypatch.delenv("RT_IMAGES_READER", raising=False)
    monkeypatch.setattr(add_images, "describe_new_images", lambda *a, **k: pytest.fail("niente descrittore"))
    photo = tmp_path / "foto.png"
    photo.write_bytes(_mock_png("foto"))
    run_add_images(lesson, input_path=str(photo), force_mock=True)
    run_add_images(lesson, selected_images=[compute_image_hash(_mock_png("foto"))], force_mock=True)
    entry = load_image_descriptions(lesson)[compute_image_hash(_mock_png("foto"))]
    assert entry["ruolo"] == "contenuto" and "visual_elements" not in entry
    assert load_image_placement(lesson)["units"]["1.1"] == [compute_image_hash(_mock_png("foto"))]


def test_rejected_image_falls_back_to_the_descriptor(lesson, monkeypatch):  # noqa: F811
    import rt.pipeline.add_images as add_images
    monkeypatch.delenv("RT_IMAGES_READER", raising=False)

    def reject(*args, **kwargs):
        raise jev.JevError("formato", http_status=422)
    monkeypatch.setattr(image_decision, "decide_image", reject)
    described, placed = [], []
    monkeypatch.setattr(add_images, "describe_new_images", lambda d, images, **k: described.extend(h for _, h in images))

    def by_text(lesson_dir, outline, images, **kwargs):
        assert kwargs.get("by_text")
        placed.extend(i.file_fingerprint for i in images)
        return {"1.2": list(placed)}, {}
    real_place = add_images.place_uploaded_images
    monkeypatch.setattr(add_images, "place_uploaded_images",
                        lambda *a, **k: by_text(*a, **k) if k.get("by_text") else real_place(*a, **k))
    data = _mock_png("rifiutata")
    image_hash = compute_image_hash(data)
    descriptions = {image_hash: {"filename": add_images.save_raw_image(lesson, data, image_hash), "source": "folder:x.png"}}
    add_images.save_image_descriptions(lesson, descriptions)
    units, _macros = add_images.decide_images(lesson, OUTLINE, [(image_hash, data, "")])
    assert described == [image_hash] and units == {"1.2": [image_hash]}
