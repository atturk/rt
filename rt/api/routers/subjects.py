"""Materie registrate e note a RT."""
from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from rt.api.deps import Actor
from rt.services import subjects

router = APIRouter(tags=["subjects"])


class SubjectCreate(BaseModel):
    nome: str = Field(min_length=1, max_length=256)


class SubjectView(BaseModel):
    nome: str
    lezioni: int


@router.get("/subjects", response_model=list[SubjectView])
def list_subjects(_actor: Actor):
    return subjects.list_subjects()


@router.post("/subjects", response_model=SubjectView, status_code=201)
def create_subject(body: SubjectCreate, _actor: Actor):
    return subjects.create_subject(body.nome)


@router.delete("/subjects/{nome}", status_code=204)
def delete_subject(nome: str, _actor: Actor):
    subjects.delete_subject(nome)
    return Response(status_code=204)
