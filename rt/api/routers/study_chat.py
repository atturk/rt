"""Router API per la Chat dello Studio."""
import mimetypes
import os
import re
from typing import List

from fastapi import APIRouter, File, Form, Response, UploadFile
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from rt.api import schemas
from rt.api.deps import Actor, LessonDir
from rt.api.errors import ApiError
from rt.services.study_chat_service import MAX_CHAT_IMAGE_BYTES, MAX_CHAT_IMAGES
from rt.storage import fs

router = APIRouter(tags=["studio"])

_CHAT_IMAGE_NAME = re.compile(r"^[A-Za-z0-9_-]+\.(png|jpe?g|webp|gif)$", re.IGNORECASE)


@router.get(
    "/lessons/{lesson_id}/chat",
    response_model=List[schemas.StudyChatMessageView],
    summary="Cronologia della chat dello Studio per la lezione",
)
def list_chat_messages(lesson_id: int, _lesson_dir: LessonDir, _actor: Actor):
    from rt.services.study_chat_service import list_messages

    return list_messages(lesson_id)


@router.post(
    "/lessons/{lesson_id}/chat",
    response_model=schemas.StudyChatSendResponse,
    summary="Invia un messaggio (e fino a 4 immagini) alla chat dello Studio",
)
async def post_chat_message(
    lesson_id: int,
    lesson_dir: LessonDir,
    _actor: Actor,
    text: str = Form(""),
    unit_id: str = Form(""),
    images: List[UploadFile] = File([]),
    mock: bool = Form(False),
):
    from rt.services.errors import Invalid
    from rt.services.study_chat_service import _resolve_image_spec, send_message

    if len(images) > MAX_CHAT_IMAGES:
        raise ApiError(422, "too_many_images", f"Puoi allegare al massimo {MAX_CHAT_IMAGES} immagini.")

    image_payloads = []
    for upload in images:
        try:
            raw = await upload.read(MAX_CHAT_IMAGE_BYTES + 1)
            if len(raw) > MAX_CHAT_IMAGE_BYTES:
                raise ApiError(413, "payload_too_large", "Ogni immagine può pesare al massimo 10 MB.")
            try:
                _resolve_image_spec(raw, upload.content_type, upload.filename)
            except Invalid as exc:
                if exc.code == "unsupported_media_type":
                    raise ApiError(415, exc.code, exc.message) from None
                raise
            image_payloads.append((raw, upload.content_type, upload.filename))
        finally:
            await upload.close()

    return await run_in_threadpool(
        send_message,
        lesson_dir,
        lesson_id,
        text,
        unit_id,
        image_payloads,
        mock,
    )


@router.delete(
    "/lessons/{lesson_id}/chat",
    status_code=204,
    summary="Cancella la cronologia e le immagini della chat dello Studio per la lezione",
)
def delete_chat_history(lesson_id: int, lesson_dir: LessonDir, _actor: Actor):
    from rt.services.study_chat_service import clear

    clear(lesson_dir, lesson_id)
    return Response(status_code=204)


@router.post(
    "/lessons/{lesson_id}/chat/{message_id}/save",
    response_model=schemas.StudyChatSaveResponse,
    summary="Salva una risposta della chat in Verifiche e domande (idempotente)",
)
def save_chat_message(lesson_id: int, message_id: int, lesson_dir: LessonDir, _actor: Actor):
    from rt.services.study_chat_service import save_as_note

    return save_as_note(lesson_dir, lesson_id, message_id)


@router.delete(
    "/lessons/{lesson_id}/chat/{message_id}/save",
    response_model=schemas.StudyChatMessageView,
    summary="Rimuove da Verifiche e domande una risposta della chat salvata",
)
def unsave_chat_message(lesson_id: int, message_id: int, _lesson_dir: LessonDir, _actor: Actor):
    from rt.services.study_chat_service import unsave_as_note

    return unsave_as_note(lesson_id, message_id)


@router.post(
    "/lessons/{lesson_id}/chat/transcribe",
    response_model=schemas.StudyChatTranscribeResponse,
    summary="Trascrive un breve audio vocale per la chat dello Studio",
)
async def transcribe_chat_audio(
    lesson_id: int,
    _lesson_dir: LessonDir,
    _actor: Actor,
    audio: UploadFile = File(...),
):
    from rt.services.study_chat_service import transcribe_audio

    max_audio_bytes = 50 * 1024 * 1024
    try:
        raw = await audio.read(max_audio_bytes + 1)
        if len(raw) > max_audio_bytes:
            raise ApiError(413, "payload_too_large", "File audio troppo grande.")
        text = await run_in_threadpool(transcribe_audio, raw, audio.filename)
        return {"text": text}
    finally:
        await audio.close()


@router.get(
    "/lessons/{lesson_id}/chat/images/{filename}",
    summary="Serve un'immagine allegata nella chat dello Studio",
)
def get_chat_image(lesson_id: int, filename: str, lesson_dir: LessonDir, _actor: Actor):
    if not _CHAT_IMAGE_NAME.match(filename):
        raise ApiError(404, "not_found", "Immagine non trovata.")
    rel = os.path.join("chat", filename)
    path = os.path.join(lesson_dir, rel)
    if not fs.isfile(path):
        raise ApiError(404, "not_found", "Immagine non trovata.")
    mime, _ = mimetypes.guess_type(filename)
    media_type = mime or "application/octet-stream"
    real = fs.real_path(path)
    if real is not None and os.path.isfile(real):
        return FileResponse(real, media_type=media_type)
    return Response(content=fs.read_bytes(path), media_type=media_type)
