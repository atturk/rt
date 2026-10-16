"""Impostazioni dei tipi di domanda e prova senza salvataggi."""
import json
from typing import Any, Literal, Optional

from fastapi import APIRouter, Response
from pydantic import BaseModel

from rt.api.deps import Actor
from rt.api.errors import ApiError
from rt.api.schemas import Message, JobAccepted
from rt.core.config import CustomQuestionType
from rt.services import custom_question_settings as service

router = APIRouter(tags=['impostazioni'])


class QuestionTemplate(BaseModel):
    id: str
    nome: str
    icona: str
    materie: list[str]
    cerca: str
    anche_adatti: bool
    continua: bool
    chiedi: str
    correzione: Literal["soluzione", "testo"]
    varianti: bool


class QuestionSettings(BaseModel):
    types: list[CustomQuestionType]
    templates: list[QuestionTemplate]
    materie: list[str]


class QuestionTrialIn(BaseModel):
    definition: CustomQuestionType
    lesson_id: int
    unit_id: str
    mock: bool = False


class QuestionTrialOut(BaseModel):
    label: str
    example: Optional[dict[str, Any]] = None


@router.get('/settings/questions', response_model=QuestionSettings)
def questions(_actor: Actor):
    return service.view()


@router.post('/settings/questions', response_model=CustomQuestionType, status_code=201)
def create(body: CustomQuestionType, _actor: Actor):
    return service.save(body, actor=_actor)


@router.post('/settings/questions/import', response_model=CustomQuestionType, status_code=201)
def import_type(body: CustomQuestionType, _actor: Actor):
    return service.save(body, actor=_actor)


@router.post('/settings/questions/trial', response_model=QuestionTrialOut)
def trial(body: QuestionTrialIn, _actor: Actor):
    try:
        return service.trial(body.definition, body.lesson_id, body.unit_id, mock=body.mock)
    except ValueError as exc:
        raise ApiError(422, 'validation_error', str(exc)) from exc


@router.put('/settings/questions/{identifier}', response_model=CustomQuestionType)
def update(identifier: str, body: CustomQuestionType, _actor: Actor):
    try:
        return service.save(body, identifier, actor=_actor)
    except ValueError as exc:
        raise ApiError(422, 'validation_error', str(exc)) from exc


@router.delete('/settings/questions/{identifier}', response_model=Message)
def delete(identifier: str, _actor: Actor):
    service.delete(identifier)
    return {'message': 'Tipo eliminato.'}


@router.get('/settings/questions/{identifier}/export', response_model=CustomQuestionType)
def export(identifier: str, _actor: Actor):
    item = service.get(identifier)
    return Response(json.dumps(item.model_dump(mode='json'), ensure_ascii=False, indent=2),
                    media_type='application/json', headers={'Content-Disposition': f'attachment; filename="{item.id}.json"'})


class RecallVoteSettings(BaseModel):
    votes_enabled: bool = True
    presave_check: bool = True


class RecallRuleGroup(BaseModel):
    type: str
    subject: str
    rules: list[str]
    votes: int
    updated_at: str | None = None


class RecallRulesView(RecallVoteSettings):
    groups: list[RecallRuleGroup]


class RecallRuleEdit(BaseModel):
    type: str
    subject: str
    rules: list[str]


class RecallRuleUpdate(BaseModel):
    type: str
    subject: str
    mock: bool = False


@router.get('/settings/recall-rules', response_model=RecallRulesView)
def recall_rules(_actor: Actor):
    from rt.services.recall_rules import view
    return view()


@router.put('/settings/recall-votes', response_model=RecallRulesView)
def recall_votes(body: RecallVoteSettings, _actor: Actor):
    from rt.services.recall_rules import settings
    return settings(body.votes_enabled, body.presave_check)


@router.put('/settings/recall-rules', response_model=RecallRulesView)
def edit_recall_rules(body: RecallRuleEdit, _actor: Actor):
    from rt.services.recall_rules import edit, view
    if len(body.rules) > 8 or any(len(r) > 2000 for r in body.rules):
        raise ApiError(422, 'validation_error', 'Indica al massimo 8 regole brevi.')
    edit(body.type, body.subject, body.rules)
    return view()


@router.post('/settings/recall-rules/update', response_model=JobAccepted, status_code=202)
def update_recall_rules(body: RecallRuleUpdate, _actor: Actor):
    from rt.api.jobs import enqueue_job
    return enqueue_job('recall_rules_update', None, body.model_dump(), _actor)
