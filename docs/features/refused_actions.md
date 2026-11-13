# Refused actions

An action may refuse to run for a reason beyond the transition table, e.g. "the order must not be shipped yet to change
its address". A client has to understand why: a machine has to branch on it, a human has to know what to do next.

Every such condition is its own subclass of `PhaseGuardError` with two class attributes:

* **`code`**: stable snake_case, meant for machines. Clients branch on it, never on `detail`.
* **`detail`**: written for the user — why the action was refused and what to do next. `phase` doesn't translate;
  pass a translated text.

The message given to the constructor is meant for logs and may contain IDs.

```python
from django.utils.translation import gettext_lazy as _

from phase.exceptions import PhaseGuardError


class OrderAlreadyShippedError(PhaseGuardError):
    code = "order_already_shipped"
    detail = _("The order has already been shipped, so its address can't be changed anymore.")

    def __init__(self, *, pk: int):
        super().__init__(f"Order ID #{pk} is already shipped.")
```

`IllegalPhaseTransitionError` and `StalePhaseError` come without a domain reason. An action whose refusal the user
should understand checks the phase itself and raises a guard instead of relying on the table alone.

## Answering with HTTP 409

`phase` knows nothing about your API framework. With Django REST framework, map the exceptions in a custom exception
handler, so views neither catch them nor build responses by hand:

```python
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler as drf_exception_handler

from phase.exceptions import IllegalPhaseTransitionError, PhaseGuardError, StalePhaseError


class ConflictError(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "conflict"

    def __init__(self, *, code: str, detail: str):
        super().__init__(detail={"code": code, "detail": detail}, code=code)


def exception_handler(exc, context):
    if isinstance(exc, PhaseGuardError):
        exc = ConflictError(code=exc.code, detail=exc.detail)
    elif isinstance(exc, IllegalPhaseTransitionError):
        exc = ConflictError(
            code="illegal_phase_transition",
            detail="This action isn't possible in the current status. Reload the page to see it.",
        )
    elif isinstance(exc, StalePhaseError):
        exc = ConflictError(
            code="stale_phase",
            detail="The data was changed in the meantime. Reload the page and try again.",
        )
    return drf_exception_handler(exc, context)
```

Every 409 then has the same body:

```json
{
  "code": "order_already_shipped",
  "detail": "The order has already been shipped, so its address can't be changed anymore."
}
```
