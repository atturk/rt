"""
rt.llm.cancel
Annullamento di una run visto dal client LLM: il RunContext attivo rende corrente il suo
token, e lo streaming di una chiamata in corso si chiude appena arriva l'annullamento, senza
aspettare la fine della risposta. Sta in rt.llm perché il client non dipende dai servizi.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable, Iterator, Optional, Protocol


class RunCancelled(Exception):
    """La run è stata annullata tramite CancelToken; il lavoro già salvato resta valido."""


class Cancellable(Protocol):
    @property
    def cancelled(self) -> bool: ...

    def on_cancel(self, callback: Callable[[], None]) -> Callable[[], None]: ...


_CURRENT: "ContextVar[Optional[Cancellable]]" = ContextVar("rt_cancel_token", default=None)


def current_cancel_token() -> Optional[Cancellable]:
    return _CURRENT.get()


@contextmanager
def use_cancel_token(token: Optional[Cancellable]) -> Iterator[None]:
    reset = _CURRENT.set(token)
    try:
        yield
    finally:
        _CURRENT.reset(reset)


def raise_if_cancelled() -> None:
    token = _CURRENT.get()
    if token is not None and token.cancelled:
        raise RunCancelled("Esecuzione annullata")
