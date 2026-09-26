"""Immagini integrate da 'rt add-images' (RT4-F6): elenco con le descrizioni e file serviti
per l'anteprima nel documento. Il caricamento (POST /lessons/{id}/images) è un job, in jobs.py."""
import mimetypes
import os
import re
from typing import List, Optional

from fastapi import APIRouter
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from rt.api.deps import Actor, LessonDir
from rt.api.errors import ApiError
from rt.storage import fs

router = APIRouter(tags=["immagini"])
# nomi scritti da add-images (hash breve + estensione): niente percorsi né file nascosti
_IMAGE_NAME = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9_.-]*\.(png|jpe?g|webp|gif|heic)$", re.IGNORECASE)


class LessonImage(BaseModel):
    name: str = Field(description="Nome del file in assets/images")
    url: str = Field(description="Percorso dell'API che serve il file")
    source: str = Field("", description="Origine: pdf:<file>#<pagina>, folder:<file>, websearch:<query>")
    slide_title: str = ""
    alt_text: str = ""
    in_document: bool = Field(description="True se il documento la richiama (finale se aggiornato, "
                                          "altrimenti l'anteprima dalla bozza)")


class LessonImages(BaseModel):
    images: List[LessonImage]


def _asset_url(lesson_id: int, name: str) -> str:
    return f"/api/v1/lessons/{lesson_id}/assets/images/{name}"


@router.get("/lessons/{lesson_id}/images", response_model=LessonImages,
            summary="Immagini della lezione con descrizione e presenza nel documento")
def list_images(lesson_id: int, lesson_dir: LessonDir, _actor: Actor):
    from rt.pipeline.add_images import load_image_descriptions
    from rt.services.lesson_service import load_markdown_preview
    # il documento mostrato dalla vista lezione: finale se aggiornato, altrimenti l'anteprima
    document = load_markdown_preview(lesson_dir)
    images = []
    for desc in load_image_descriptions(lesson_dir).values():
        rel = str(desc.get("filename") or "")
        name = os.path.basename(rel)
        if not _IMAGE_NAME.match(name):
            continue
        images.append(LessonImage(
            name=name, url=_asset_url(lesson_id, name), source=str(desc.get("source") or ""),
            slide_title=str(desc.get("slide_title") or ""), alt_text=str(desc.get("alt_text") or ""),
            in_document=bool(rel) and rel in document,
        ))
    images.sort(key=lambda img: (not img.in_document, img.source, img.name))
    return LessonImages(images=images)


@router.get("/lessons/{lesson_id}/assets/images/{name}", summary="File di un'immagine della lezione",
            response_class=Response, responses={200: {"content": {"image/*": {}}}})
def get_image(lesson_id: int, name: str, lesson_dir: LessonDir, _actor: Actor):
    from rt.pipeline.add_images import get_images_dir
    if not _IMAGE_NAME.match(name):
        raise ApiError(404, "image_not_found", "Immagine inesistente.")
    path = os.path.join(get_images_dir(lesson_dir), name)
    if not fs.isfile(path):
        raise ApiError(404, "image_not_found", "Immagine inesistente.")
    media_type: Optional[str] = mimetypes.guess_type(name)[0] or "application/octet-stream"
    headers = {"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"}
    real = fs.real_path(path)
    if real:
        return FileResponse(real, media_type=media_type, headers=headers)
    with fs.open(path, "rb") as f:
        return Response(content=f.read(), media_type=media_type, headers=headers)
