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

With Django REST framework, `phase` ships an exception handler, so views neither catch refused actions nor build
responses by hand. Install the extra and register the handler:

```bash
pip install django-phase[drf]
```

```python
REST_FRAMEWORK = {
    "EXCEPTION_HANDLER": "phase.contrib.rest_framework.exception_handler",
}
```

`PhaseGuardError`, `IllegalPhaseTransitionError` and `StalePhaseError` then answer **HTTP 409** with the same body:

```json
{
  "code": "order_already_shipped",
  "detail": "The order has already been shipped, so its address can't be changed anymore."
}
```

* A refused action is a valid request that conflicts with the current state of the resource, so a `PhaseGuardError`
  answers 409 as well, not 400. Its `code` and `detail` are the class attributes of the subclass; a subclass that
  lacks one answers with the code `phase_guard` and a generic text instead of failing.
* `IllegalPhaseTransitionError` answers with the code `illegal_phase_transition`, `StalePhaseError` with
  `stale_phase`. Their texts ask the user to reload.
* **The default texts are English.** They are marked for translation, but `phase` ships no translations, and
  `makemessages` in your project doesn't collect texts from installed packages. To translate them, add their msgids
  by hand to a catalogue in one of your `LOCALE_PATHS`; they are the constants `ILLEGAL_PHASE_TRANSITION_DETAIL`,
  `STALE_PHASE_DETAIL` and `PHASE_GUARD_DETAIL` in `phase.contrib.rest_framework`.
* Every other exception goes to DRF's default handler.
* `djangorestframework` is an optional dependency; `phase` imports it only in `phase.contrib.rest_framework`.

A project with an exception handler of its own uses the pieces it needs: `to_conflict_error(exc)` returns the
`PhaseConflictError` (an `APIException` with status 409) for a refused action and `None` for anything else.

```python
from rest_framework.views import exception_handler as drf_exception_handler

from phase.contrib.rest_framework import to_conflict_error


def exception_handler(exc, context):
    exc = to_conflict_error(exc) or exc
    # ... the project's own mappings
    return drf_exception_handler(exc, context)
```
