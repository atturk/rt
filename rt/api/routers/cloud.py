"""Modalità facilitata (RT Cloud): accesso con email, abbonamento e saldo.
Nessuna risposta contiene la chiave OpenRouter o il token di sessione."""
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from rt.api.deps import Actor
from rt.api.errors import ApiError

router = APIRouter(tags=["rt cloud"])


class CloudSubscription(BaseModel):
    status: str = Field(description="none, active, canceled (attivo fino a fine periodo), revoked")
    plan: Optional[str] = None
    current_period_end: Optional[str] = None
    monthly_quota_usd: float = 0


class CloudTopup(BaseModel):
    balance_usd: float = Field(0, description="Credito delle ricariche extra all'ultimo conteggio")
    next_expiry: Optional[str] = Field(None, description="Scadenza della ricarica più vecchia")


class CloudBalance(BaseModel):
    limit_usd: Optional[float] = None
    usage_usd: float = 0
    remaining_usd: Optional[float] = None


class CloudStatus(BaseModel):
    available: bool = Field(description="False finché RT Cloud non è pubblicato")
    logged_in: bool
    email: Optional[str] = None
    subscription: Optional[CloudSubscription] = None
    topup: Optional[CloudTopup] = None
    balance: Optional[CloudBalance] = Field(None, description="Letto direttamente da OpenRouter")
    connection: bool = Field(description="La connessione 'RT Cloud' esiste")


class EmailIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class VerifyIn(EmailIn):
    code: str = Field(min_length=6, max_length=6)


class SyncIn(BaseModel):
    assign_all: bool = Field(False, description="Porta tutte le fasi testuali su RT Cloud")


class CheckoutIn(BaseModel):
    plan: Optional[str] = None


class TopupIn(BaseModel):
    amount_cents: int = Field(ge=100, le=1_000_000, description="Importo in centesimi di euro")


class UrlOut(BaseModel):
    url: str


class CloudPlan(BaseModel):
    id: str
    label: str


class CloudTopupRules(BaseModel):
    min_cents: int
    max_cents: int
    valid_days: int


class CloudPlans(BaseModel):
    plans: list[CloudPlan]
    models: list[str] = Field(description="Modelli usati in modalità facilitata")
    topup: Optional[CloudTopupRules] = Field(None, description="Null se le ricariche extra sono spente")


def _root() -> Path:
    from rt.core.config import _default_project_root
    return Path(_default_project_root())


def _call(fn, *args, **kwargs):
    from rt.services.cloud_service import CloudError
    try:
        return fn(*args, **kwargs)
    except CloudError as exc:
        raise ApiError(exc.status, exc.code, exc.message)
    except ValueError as exc:
        raise ApiError(422, "invalid_setting", str(exc).splitlines()[0] if str(exc) else "Valore non valido.")


@router.get("/cloud", response_model=CloudStatus, summary="Stato della modalità facilitata")
def get_status(_actor: Actor):
    from rt.services import cloud_service
    return _call(cloud_service.status, _root())


@router.get("/cloud/plans", response_model=CloudPlans, summary="Piani di abbonamento disponibili")
def get_plans(_actor: Actor):
    from rt.services import cloud_service
    return _call(cloud_service.plans)


@router.post("/cloud/login/start", status_code=204, summary="Manda il codice di accesso all'email")
def login_start(body: EmailIn, _actor: Actor):
    from rt.services import cloud_service
    _call(cloud_service.start_login, body.email)


@router.post("/cloud/login/verify", response_model=CloudStatus, summary="Verifica il codice e collega l'account")
def login_verify(body: VerifyIn, _actor: Actor):
    from rt.services import cloud_service
    return _call(cloud_service.verify_login, _root(), body.email, body.code)


@router.post("/cloud/sync", response_model=CloudStatus, summary="Aggiorna abbonamento e chiave da RT Cloud")
def sync(body: SyncIn, _actor: Actor):
    from rt.services import cloud_service
    return _call(cloud_service.sync, _root(), body.assign_all)


@router.post("/cloud/checkout", response_model=UrlOut, summary="Pagina di pagamento dell'abbonamento")
def checkout(body: CheckoutIn, _actor: Actor):
    from rt.services import cloud_service
    return UrlOut(url=_call(cloud_service.checkout, body.plan))


@router.post("/cloud/topup", response_model=UrlOut, summary="Pagina di pagamento di una ricarica extra")
def topup(body: TopupIn, _actor: Actor):
    from rt.services import cloud_service
    return UrlOut(url=_call(cloud_service.topup, body.amount_cents))


@router.post("/cloud/portal", response_model=UrlOut, summary="Portale per disdire o cambiare carta")
def portal(_actor: Actor):
    from rt.services import cloud_service
    return UrlOut(url=_call(cloud_service.portal))


@router.post("/cloud/logout", response_model=CloudStatus, summary="Scollega l'account (la connessione resta)")
def logout(_actor: Actor):
    from rt.services import cloud_service
    return _call(cloud_service.logout, _root())
