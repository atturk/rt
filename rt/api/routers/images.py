"""Immagini integrate da 'rt add-images' (RT4-F6): elenco con le descrizioni e file serviti
per l'anteprima nel documento. Il caricamento (POST /lessons/{id}/images) è un job, in jobs.py."""
import mimetypes
import os
import re
from typing import List, Optional

from fastapi import APIRouter, File, Form, UploadFile
from starlette.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from rt.api.deps import Actor, LessonDir
from rt.api.errors import ApiError
from rt.storage import fs

router = APIRouter(tags=["immagini"])
# nomi scritti da add-images (hash breve + estensione): niente percorsi né file nascosti
_IMAGE_NAME = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9_.-]*\.(png|jpe?g|webp|gif|heic)$", re.IGNORECASE)


class LessonImage(BaseModel):
    macro_ids: List[str] = Field(default_factory=list, description="Macro unità a cui è assegnata")
    name: str = Field(description="Nome del file in assets/images o identificativo")
    url: str = Field(description="Percorso dell'API che serve il file")
    source: str = Field("", description="Origine: pdf:<file>#<pagina>, folder:<file>, websearch:<query>, material:...")
    source_name: str = Field("", description="Nome leggibile della fonte: nome del file, Dal web, Dall'editor")
    page: Optional[int] = Field(None, description="Numero di pagina per documenti multipagina")
    in_assets: bool = Field(True, description="True se il file è già presente in assets/images")
    units: List[str] = Field(default_factory=list, description="Unità in cui compare nel documento")
    slide_title: str = ""
    alt_text: str = ""
    in_document: bool = Field(description="True se il documento la richiama (finale se aggiornato, "
                                          "altrimenti l'anteprima dalla bozza)")
    crop_of: Optional[str] = Field(None, description="Hash o identificativo dell'immagine originale se ritaglio")
    crop_index: Optional[int] = Field(None, description="Indice progressivo del ritaglio per la pagina")


class LessonImages(BaseModel):
    images: List[LessonImage]


class EditorImage(BaseModel):
    path: str = Field(description="Riferimento relativo da inserire nel Markdown: assets/images/…")
    name: str
    url: str
    alt_text: str


class MaterialPageRequest(BaseModel):
    source_id: str
    page: int
    lease_token: Optional[str] = None


@router.post("/lessons/{lesson_id}/media/images", response_model=EditorImage, status_code=201,
             summary="Carica un'immagine PNG, JPEG o GIF dall'editor nei media della lezione")
async def upload_editor_image(lesson_id: int, lesson_dir: LessonDir, _actor: Actor,
                              file: UploadFile = File(...), lease_token: Optional[str] = Form(None)):
    from rt.services.editor_media_service import MAX_IMAGE_BYTES, upload_image
    try:
        content = await file.read(MAX_IMAGE_BYTES + 1)
        return await run_in_threadpool(upload_image, lesson_id, lesson_dir, content, file.filename or '', lease_token)
    finally:
        await file.close()


@router.post("/lessons/{lesson_id}/media/material-page", response_model=EditorImage, status_code=201,
             summary="Copia una pagina dei materiali in assets/images")
def copy_material_page(lesson_id: int, lesson_dir: LessonDir, _actor: Actor, req: MaterialPageRequest):
    from rt.services.editor_media_service import copy_material_page_to_assets
    return copy_material_page_to_assets(
        lesson_id=lesson_id,
        lesson_dir=lesson_dir,
        source_id=req.source_id,
        page_number=req.page,
        lease_token=req.lease_token,
    )


def _asset_url(lesson_id: int, name: str) -> str:
    return f"/api/v1/lessons/{lesson_id}/assets/images/{name}"


@router.get("/lessons/{lesson_id}/images", response_model=LessonImages,
            summary="Immagini della lezione con descrizione e presenza nel documento")
def list_images(lesson_id: int, lesson_dir: LessonDir, _actor: Actor):
    from rt.pipeline.add_images import load_image_descriptions
    from rt.services.lesson_service import load_markdown_preview
    from rt.pipeline.image_placement import load_image_placement
    from rt.core.sources import load_sources
    from rt.core.materials import cached_pages

    placement = load_image_placement(lesson_dir) or {}
    document = load_markdown_preview(lesson_dir) or ""
    descriptions = load_image_descriptions(lesson_dir)

    def find_units_for_image(img_name: str) -> list[str]:
        if not document or not img_name:
            return []
        found_units = []
        current_unit = None
        for line in document.splitlines():
            sub = re.match(r"^###\s+([0-9]+(?:\.[0-9]+)*)", line)
            if sub:
                current_unit = sub.group(1)
            else:
                macro = re.match(r"^##\s+([0-9]+)", line)
                if macro:
                    current_unit = macro.group(1)
            if img_name in line and current_unit and current_unit not in found_units:
                found_units.append(current_unit)
        return found_units

    images: list[LessonImage] = []
    processed_desc_hashes = set()

    # 1. Pagine delle fonti materiali
    sources = load_sources(lesson_dir)
    for src in sources:
        if src.rimossa_il:
            continue
        pages = cached_pages(lesson_dir, src)
        if not pages:
            continue
        src_name = os.path.basename(src.file)
        for page in pages:
            num = int(page.get("numero", 1))
            # Cerca se questa pagina è già in descriptions.json
            found_hash = None
            found_desc = None
            for h, d in descriptions.items():
                if d.get("crop_of"):
                    continue  # i ritagli stanno accanto alla pagina, non al suo posto
                s_tag = str(d.get("source") or "")
                if s_tag in (f"material:{src.id}:{num}", f"material:{src.impronta}:{num}",
                             f"pdf:{src_name}#{num}", f"pdf:{src.file}#{num}"):
                    found_hash = h
                    found_desc = d
                    break

            if found_desc and found_hash:
                processed_desc_hashes.add(found_hash)
                rel = str(found_desc.get("filename") or "")
                name = os.path.basename(rel)
                units = find_units_for_image(name)
                images.append(LessonImage(
                    name=name,
                    url=_asset_url(lesson_id, name),
                    source=str(found_desc.get("source") or f"material:{src.id}:{num}"),
                    source_name=src_name,
                    page=num,
                    in_assets=True,
                    units=units,
                    in_document=bool(units) or (bool(rel) and rel in document),
                    slide_title=str(found_desc.get("slide_title") or ""),
                    alt_text=str(found_desc.get("alt_text") or f"{src_name}, pagina {num}"),
                    crop_of=found_desc.get("crop_of"),
                    crop_index=found_desc.get("crop_index"),
                    macro_ids=[mid for mid, hashes in placement.get("macros", {}).items() if found_hash in hashes],
                ))
            else:
                # Non ancora in assets: servita dal suo file in materials/<impronta>/
                imgs = page.get("immagini", [])
                page_img_rel = imgs[0] if imgs else f"materials/{src.impronta}/page-{num}-1.png"
                img_filename = os.path.basename(page_img_rel)
                images.append(LessonImage(
                    name=f"material:{src.id}:{num}",
                    url=f"/api/v1/lessons/{lesson_id}/materials/{src.impronta}/{img_filename}",
                    source=f"material:{src.id}:{num}",
                    source_name=src_name,
                    page=num,
                    in_assets=False,
                    units=[],
                    in_document=False,
                    slide_title="",
                    alt_text=f"{src_name}, pagina {num}",
                    macro_ids=[],
                ))

    # 2. Immagini rimaste in descriptions.json (Arricchimento, web, editor, altre)
    for h, desc in descriptions.items():
        if h in processed_desc_hashes:
            continue
        rel = str(desc.get("filename") or "")
        name = os.path.basename(rel)
        if not _IMAGE_NAME.match(name):
            continue
        s_tag = str(desc.get("source") or "")
        page_num = None
        if s_tag.startswith("editor:"):
            group_name = "Dall'editor"
        elif s_tag.startswith("websearch:") or s_tag.startswith("web:"):
            group_name = "Dal web"
        elif s_tag.startswith("pdf:"):
            target = s_tag.removeprefix("pdf:")
            if "#" in target:
                fn, pstr = target.rsplit("#", 1)
                group_name = os.path.basename(fn)
                page_num = int(pstr) if pstr.isdigit() else None
            else:
                group_name = os.path.basename(target)
        elif s_tag.startswith("folder:"):
            group_name = os.path.basename(s_tag.removeprefix("folder:"))
        elif s_tag.startswith("material:"):
            parts = s_tag.split(":")
            source_files = {src.id: os.path.basename(src.file) for src in sources}
            group_name = source_files.get(parts[1], "Materiali") if len(parts) > 1 else "Materiali"
            page_num = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
        else:
            group_name = s_tag or "Altre immagini"

        units = find_units_for_image(name)
        images.append(LessonImage(
            name=name,
            url=_asset_url(lesson_id, name),
            source=s_tag,
            source_name=group_name,
            page=page_num,
            in_assets=True,
            units=units,
            in_document=bool(units) or (bool(rel) and rel in document),
            slide_title=str(desc.get("slide_title") or ""),
            alt_text=str(desc.get("alt_text") or ""),
            crop_of=desc.get("crop_of"),
            crop_index=desc.get("crop_index"),
            macro_ids=[mid for mid, hashes in placement.get("macros", {}).items() if h in hashes],
        ))

    def sort_key(img: LessonImage):
        priority = 0
        if img.source_name == "Dal web":
            priority = 2
        elif img.source_name == "Dall'editor":
            priority = 3
        return (priority, img.source_name, img.page if img.page is not None else 999999, img.crop_index or 0, img.name)

    images.sort(key=sort_key)
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


_MATERIAL_IMG_NAME = re.compile(r"^[A-Za-z0-9_-]+\.png$", re.IGNORECASE)
_IMPRONTA_RE = re.compile(r"^[a-fA-F0-9]{16,64}$")


@router.get("/lessons/{lesson_id}/materials/{impronta}/{name}", summary="File di una pagina dei materiali",
            response_class=Response, responses={200: {"content": {"image/png": {}}}})
def get_material_image(lesson_id: int, impronta: str, name: str, lesson_dir: LessonDir, _actor: Actor):
    if not _IMPRONTA_RE.match(impronta) or not _MATERIAL_IMG_NAME.match(name):
        raise ApiError(404, "image_not_found", "Immagine inesistente.")
    path = os.path.join(lesson_dir, "materials", impronta, name)
    if not fs.isfile(path):
        raise ApiError(404, "image_not_found", "Immagine inesistente.")
    headers = {"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"}
    real = fs.real_path(path)
    if real:
        return FileResponse(real, media_type="image/png", headers=headers)
    with fs.open(path, "rb") as f:
        return Response(content=f.read(), media_type="image/png", headers=headers)


class RemoveFromTextRequest(BaseModel):
    image_names: list[str]
    lease_token: Optional[str] = None


@router.post("/lessons/{lesson_id}/media/remove-from-text", summary="Toglie immagini dal testo e da placement")
def remove_from_text(
    lesson_id: int,
    lesson_dir: LessonDir,
    _actor: Actor,
    req: RemoveFromTextRequest,
):
    from rt.services.editor_media_service import remove_images_from_lesson
    return remove_images_from_lesson(
        lesson_id=lesson_id,
        lesson_dir=lesson_dir,
        image_names=req.image_names,
        lease_token=req.lease_token,
    )


class CropImageRequest(BaseModel):
    image_name: str = Field(..., description="Nome o identificativo dell'immagine da ritagliare")
    rect: list[float] = Field(..., min_length=4, max_length=4,
                              description="Rettangolo relativo [left, top, width, height] tra 0.0 e 1.0")
    replace: bool = Field(False, description="Se True, sostituisce la pagina nel documento e in placement")
    lease_token: Optional[str] = Field(None, description="Token di lease dell'editor se aperto")
    update_document: bool = Field(True, description="False se il testo lo cambia l'editor aperto")


@router.post("/lessons/{lesson_id}/media/crop", response_model=EditorImage, status_code=201,
             summary="Ritaglia un'immagine o pagina (nuova immagine o sostituzione)")
def crop_media(
    lesson_id: int,
    lesson_dir: LessonDir,
    _actor: Actor,
    req: CropImageRequest,
) -> EditorImage:
    from rt.services.editor_media_service import crop_image
    res = crop_image(
        lesson_id=lesson_id,
        lesson_dir=lesson_dir,
        image_name=req.image_name,
        rect=req.rect,
        replace=req.replace,
        lease_token=req.lease_token,
        update_document=req.update_document,
    )
    return EditorImage(**res)



