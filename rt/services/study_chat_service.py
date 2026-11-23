"""Chat dello Studio: cronologia per lezione, invio al modello con caching, immagini, note e STT."""
from __future__ import annotations

import base64
import os
import tempfile
import uuid
from typing import Any, Optional, Sequence

from sqlalchemy import delete, select

from rt.core.config import load_config
from rt.core.markdown_render import render_markdown
from rt.core.recall_stt import transcribe_voice_answer
from rt.db.engine import get_database
from rt.db.models import StudyChatMessage, StudyNote
from rt.db.session import read_scope, session_scope
from rt.llm.capabilities import supports_vision
from rt.llm.client import LLMClient
from rt.llm.errors import describe_llm_failure
from rt.llm.prompts import STUDY_CHAT_SYSTEM_PROMPT, PromptPrefix, StudyChatReply
from rt.llm.router import RoutingEngine
from rt.llm.telemetry import current_telemetry
from rt.pipeline.ledger import load_resolved_draft
from rt.services.errors import Invalid, NotFound
from rt.services.study_notes_service import add_study_note, decorate_study_note, delete_study_note
from rt.storage import fs

MAX_CHAT_IMAGES = 4
MAX_CHAT_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB
HISTORY_LIMIT = 30

ALLOWED_IMAGE_TYPES: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
ALLOWED_IMAGE_EXTS: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _image_url(lesson_id: int, rel_path: str) -> str:
    return f"/api/v1/lessons/{lesson_id}/chat/images/{os.path.basename(rel_path)}"


def _row(msg: StudyChatMessage, lesson_id: Optional[int] = None) -> dict[str, Any]:
    lid = lesson_id if lesson_id is not None else msg.lesson_id
    images = list(msg.images or [])
    return {
        "id": msg.id,
        "lesson_id": msg.lesson_id,
        "role": msg.role,
        "content": msg.content,
        "content_html": render_markdown(msg.content) if msg.content else "",
        "images": images,
        "image_urls": [_image_url(lid, rel) for rel in images],
        "unit_id": msg.unit_id,
        "model": msg.model,
        "cost": msg.cost,
        "error": msg.error,
        "saved_note_id": msg.saved_note_id,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


def list_messages(lesson_id: int) -> list[dict[str, Any]]:
    with read_scope(get_database()) as session:
        rows = session.scalars(
            select(StudyChatMessage)
            .where(StudyChatMessage.lesson_id == lesson_id)
            .order_by(StudyChatMessage.id.asc())
        )
        return [_row(m, lesson_id) for m in rows]


def _resolve_image_spec(data: bytes, content_type: Optional[str], filename: Optional[str]) -> tuple[str, str]:
    """Restituisce (ext, mime_type) validati oppure solleva Invalid."""
    mime = (content_type or "").split(";")[0].strip().lower()
    ext = ALLOWED_IMAGE_TYPES.get(mime)
    if ext is None and filename:
        f_ext = os.path.splitext(filename)[1].lower()
        if f_ext in ALLOWED_IMAGE_EXTS:
            mime = ALLOWED_IMAGE_EXTS[f_ext]
            ext = ".jpg" if f_ext == ".jpeg" else f_ext
    if ext is None:
        raise Invalid("unsupported_media_type", "Formato immagine non supportato. Usa PNG, JPEG, WebP o GIF.")
    if not data:
        raise Invalid("empty_file", "L'immagine allegata è vuota.")
    if len(data) > MAX_CHAT_IMAGE_BYTES:
        raise Invalid("payload_too_large", "Ogni immagine può pesare al massimo 10 MB.")
    if mime == "image/jpg":
        mime = "image/jpeg"
    return ext, mime


def _build_lesson_context(lesson_dir: str, unit_id: str) -> tuple[Optional[PromptPrefix], str]:
    draft = load_resolved_draft(lesson_dir)
    units_blocks = [f"### {u.unit_id} {u.title}\n\n{u.content}" for u in draft.units]
    lesson_text = "\n\n".join(units_blocks).strip()
    prefix = PromptPrefix(["TESTO INTEGRALE DELLA LEZIONE:\n\n" + lesson_text]) if lesson_text else None
    current_unit = next((u for u in draft.units if u.unit_id == unit_id), None)
    if current_unit:
        unit_label = f"{current_unit.unit_id} {current_unit.title}".strip()
    else:
        unit_label = unit_id.strip()
    return prefix, unit_label


def _is_image_input_error(exc: BaseException) -> bool:
    msg = f"{getattr(exc, 'message', '')} {exc}".lower()
    has_image_term = any(t in msg for t in ("image", "vision", "multimodal", "image_url"))
    if not has_image_term:
        return False
    return any(
        k in msg
        for k in (
            "not support",
            "doesn't support",
            "does not support",
            "unsupported",
            "cannot read",
            "unable to",
            "invalid content",
            "invalid_request",
            "cannot process",
            "no vision",
            "does not accept",
            "image_url",
        )
    )


def _vision_error_text(model_name: Optional[str]) -> str:
    label = model_name or "selezionato"
    return (
        f"Il modello {label} non legge le immagini. "
        "Scegline uno con visione in Impostazioni → Modelli → Chat dello Studio, oppure invia solo il testo."
    )


def _recent_history(lesson_id: int) -> list[dict[str, str]]:
    with read_scope(get_database()) as session:
        rows = list(
            session.scalars(
                select(StudyChatMessage)
                .where(
                    StudyChatMessage.lesson_id == lesson_id,
                    StudyChatMessage.error.is_(None),
                    StudyChatMessage.content != "",
                )
                .order_by(StudyChatMessage.id.desc())
                .limit(HISTORY_LIMIT)
            )
        )
        rows.reverse()
        return [{"role": m.role, "content": m.content} for m in rows]


def send_message(
    lesson_dir: str,
    lesson_id: int,
    text: str,
    unit_id: str = "",
    images: Sequence[tuple[bytes, Optional[str], Optional[str]]] = (),
    force_mock: bool = False,
) -> dict[str, Any]:
    clean_text = (text or "").strip()
    if not clean_text and not images:
        raise Invalid("empty_message", "Scrivi un messaggio o allega almeno un'immagine.")
    if len(images) > MAX_CHAT_IMAGES:
        raise Invalid("too_many_images", f"Puoi allegare al massimo {MAX_CHAT_IMAGES} immagini per messaggio.")

    validated_images: list[tuple[bytes, str, str]] = []
    for data, mime, filename in images:
        ext, resolved_mime = _resolve_image_spec(data, mime, filename)
        validated_images.append((data, ext, resolved_mime))

    lesson_prefix, unit_label = _build_lesson_context(lesson_dir, unit_id)
    history = _recent_history(lesson_id)

    saved_rel_paths: list[str] = []
    image_data_urls: list[str] = []
    if validated_images:
        chat_dir = os.path.join(lesson_dir, "chat")
        fs.makedirs(chat_dir, exist_ok=True)
        for data, ext, mime in validated_images:
            rel_path = f"chat/{uuid.uuid4().hex}{ext}"
            abs_path = os.path.join(lesson_dir, rel_path)
            with fs.open(abs_path, "wb") as stream:
                stream.write(data)
            saved_rel_paths.append(rel_path)
            b64 = base64.b64encode(data).decode("ascii")
            image_data_urls.append(f"data:{mime};base64,{b64}")

    with session_scope(get_database()) as session:
        user_row = StudyChatMessage(
            lesson_id=lesson_id,
            role="user",
            content=clean_text,
            images=saved_rel_paths,
            unit_id=unit_id or "",
        )
        session.add(user_row)
        session.flush()
        user_dict = _row(user_row, lesson_id)

    prompt_parts = []
    if unit_label:
        prompt_parts.append(f"L'utente sta leggendo l'unità {unit_label}.")
    prompt_parts.append(clean_text if clean_text else "(L'utente ha allegato delle immagini.)")
    user_prompt = "\n\n".join(prompt_parts)

    client = LLMClient(force_mock=force_mock)
    resolved_route_provider: Optional[str] = None
    resolved_route_model: Optional[str] = None
    if not client.force_mock:
        try:
            exec_route = RoutingEngine(client.config).select_initial_route("study_chat")
            resolved_route_provider = exec_route.provider
            resolved_route_model = exec_route.model
        except Exception:
            pass

    if image_data_urls and not client.force_mock and resolved_route_provider and not supports_vision(
        resolved_route_provider, resolved_route_model
    ):
        with session_scope(get_database()) as session:
            assistant_row = StudyChatMessage(
                lesson_id=lesson_id,
                role="assistant",
                content="",
                images=[],
                unit_id=unit_id or "",
                model=resolved_route_model,
                error=_vision_error_text(resolved_route_model),
            )
            session.add(assistant_row)
            session.flush()
            return {"user_message": user_dict, "assistant_message": _row(assistant_row, lesson_id)}

    try:
        reply = client.call_structured(
            prompt=user_prompt,
            system_prompt=STUDY_CHAT_SYSTEM_PROMPT,
            response_model=StudyChatReply,
            job_name="study_chat",
            unit_id=unit_id or None,
            lesson_dir=lesson_dir,
            history=history or None,
            image_data_url=image_data_urls or None,
            constrained_schema=True,
            prompt_prefix=lesson_prefix,
        )
        last_t = current_telemetry().get_last()
        model_name = (last_t.resolved_model or last_t.model) if last_t else resolved_route_model
        cost_usd = last_t.estimated_cost if last_t else 0.0
        with session_scope(get_database()) as session:
            assistant_row = StudyChatMessage(
                lesson_id=lesson_id,
                role="assistant",
                content=reply.text,
                images=[],
                unit_id=unit_id or "",
                model=model_name,
                cost=cost_usd,
            )
            session.add(assistant_row)
            session.flush()
            assistant_dict = _row(assistant_row, lesson_id)
    except Exception as exc:
        failed_model = getattr(exc, "model", None) or resolved_route_model
        error_msg = (
            _vision_error_text(failed_model)
            if image_data_urls and _is_image_input_error(exc)
            else describe_llm_failure(exc)
        )
        with session_scope(get_database()) as session:
            assistant_row = StudyChatMessage(
                lesson_id=lesson_id,
                role="assistant",
                content="",
                images=[],
                unit_id=unit_id or "",
                model=failed_model,
                error=error_msg,
            )
            session.add(assistant_row)
            session.flush()
            assistant_dict = _row(assistant_row, lesson_id)

    return {"user_message": user_dict, "assistant_message": assistant_dict}


def clear(lesson_dir: str, lesson_id: int) -> None:
    with session_scope(get_database()) as session:
        rows = list(session.scalars(select(StudyChatMessage).where(StudyChatMessage.lesson_id == lesson_id)))
        image_paths = [rel for m in rows for rel in (m.images or []) if isinstance(rel, str)]
        session.execute(delete(StudyChatMessage).where(StudyChatMessage.lesson_id == lesson_id))
    for rel in image_paths:
        target = os.path.join(lesson_dir, rel)
        try:
            if fs.isfile(target):
                fs.remove(target)
        except OSError:
            pass
    chat_dir = os.path.join(lesson_dir, "chat")
    if fs.isdir(chat_dir):
        try:
            fs.rmtree(chat_dir, ignore_errors=True)
        except OSError:
            pass


def save_as_note(lesson_dir: str, lesson_id: int, message_id: int) -> dict[str, Any]:
    with session_scope(get_database()) as session:
        msg = session.get(StudyChatMessage, message_id)
        if msg is None or msg.lesson_id != lesson_id:
            raise NotFound("chat_message_not_found", "Messaggio della chat non trovato.")
        if msg.role != "assistant" or not msg.content or msg.error:
            raise Invalid("invalid_chat_message", "Puoi salvare come nota solo una risposta valida dell'assistente.")
        if msg.saved_note_id:
            existing = session.get(StudyNote, msg.saved_note_id)
            if existing is not None and existing.lesson_id == lesson_id:
                from rt.services.study_notes_service import get_study_note
                note_view = decorate_study_note(get_study_note(lesson_id, existing.id), lesson_dir, lesson_id)
                return {"message": _row(msg, lesson_id), "note": note_view}
        prev_user = session.scalar(
            select(StudyChatMessage)
            .where(
                StudyChatMessage.lesson_id == lesson_id,
                StudyChatMessage.id < msg.id,
                StudyChatMessage.role == "user",
            )
            .order_by(StudyChatMessage.id.desc())
            .limit(1)
        )
        question_text = prev_user.content if prev_user else ""
        unit_id = msg.unit_id or (prev_user.unit_id if prev_user else "") or ""
        content = msg.content
        model = msg.model
        cost = msg.cost

    saved_note = add_study_note(
        lesson_id=lesson_id,
        unit_id=unit_id,
        kind="chat",
        anchor={},
        unit_fingerprint="",
        request=question_text,
        response={"text": content},
        model=model,
        cost=cost,
    )
    with session_scope(get_database()) as session:
        msg = session.get(StudyChatMessage, message_id)
        if msg is not None:
            msg.saved_note_id = saved_note["id"]
            session.flush()
            msg_view = _row(msg, lesson_id)
    decorated = decorate_study_note(saved_note, lesson_dir, lesson_id)
    return {"message": msg_view, "note": decorated}


def unsave_as_note(lesson_id: int, message_id: int) -> dict[str, Any]:
    note_to_delete: Optional[int] = None
    with session_scope(get_database()) as session:
        msg = session.get(StudyChatMessage, message_id)
        if msg is None or msg.lesson_id != lesson_id:
            raise NotFound("chat_message_not_found", "Messaggio della chat non trovato.")
        note_to_delete = msg.saved_note_id
        msg.saved_note_id = None
        session.flush()
        msg_view = _row(msg, lesson_id)
    if note_to_delete is not None:
        try:
            delete_study_note(lesson_id, note_to_delete)
        except NotFound:
            pass
    return msg_view


def transcribe_audio(audio_bytes: bytes, filename: Optional[str] = None) -> str:
    if not audio_bytes:
        raise Invalid("empty_file", "File audio vuoto.")
    ext = os.path.splitext(filename or "")[1].lower()
    if not ext or len(ext) > 10:
        ext = ".webm"
    fd, tmp_path = tempfile.mkstemp(prefix="study_chat_stt_", suffix=ext)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(audio_bytes)
        stt_engine = load_config().telegram.recall.stt_engine
        return transcribe_voice_answer(tmp_path, stt_engine=stt_engine)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
