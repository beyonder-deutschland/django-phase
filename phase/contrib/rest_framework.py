"""
Answer refused actions in Django REST framework with HTTP 409.

A refused action is a valid request that conflicts with the current state of the resource, so `PhaseGuardError`,
`IllegalPhaseTransitionError` and `StalePhaseError` all answer 409 with the body `{"code": …, "detail": …}`.
Requires the extra `django-phase[drf]`.
"""

from django.utils.translation import gettext_lazy as _
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from phase.exceptions import IllegalPhaseTransitionError, PhaseGuardError, StalePhaseError

ILLEGAL_PHASE_TRANSITION_CODE = "illegal_phase_transition"
ILLEGAL_PHASE_TRANSITION_DETAIL = _("This action isn't possible in the current status. Reload the page to see it.")

STALE_PHASE_CODE = "stale_phase"
STALE_PHASE_DETAIL = _("The data was changed in the meantime. Reload the page and try again.")

# For a `PhaseGuardError` subclass that doesn't define `code` or `detail`.
PHASE_GUARD_CODE = "phase_guard"
PHASE_GUARD_DETAIL = _("This action isn't possible right now.")


class PhaseConflictError(APIException):
    """HTTP 409 with a stable `code` for machines and a `detail` for humans as the response body."""

    status_code = status.HTTP_409_CONFLICT
    default_code = "conflict"

    def __init__(self, *, code: str, detail: str) -> None:
        super().__init__(detail={"code": code, "detail": detail}, code=code)


def to_conflict_error(exc: BaseException) -> PhaseConflictError | None:
    """The 409 a refused action answers with, or `None` for any other exception."""
    if isinstance(exc, PhaseGuardError):
        return PhaseConflictError(
            code=getattr(exc, "code", PHASE_GUARD_CODE), detail=getattr(exc, "detail", PHASE_GUARD_DETAIL)
        )
    if isinstance(exc, IllegalPhaseTransitionError):
        return PhaseConflictError(code=ILLEGAL_PHASE_TRANSITION_CODE, detail=ILLEGAL_PHASE_TRANSITION_DETAIL)
    if isinstance(exc, StalePhaseError):
        return PhaseConflictError(code=STALE_PHASE_CODE, detail=STALE_PHASE_DETAIL)
    return None


def exception_handler(exc: Exception, context: dict) -> Response | None:
    """DRF's default handler, with refused actions answered as HTTP 409."""
    return drf_exception_handler(to_conflict_error(exc) or exc, context)
