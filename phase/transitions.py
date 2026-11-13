from django.db import models

from phase.fields import Phase, get_phase_field


def move(*, obj: models.Model, to: Phase, **fields: object) -> None:
    """Move `obj` to phase `to` and write `fields` in the same conditional UPDATE, see `PhaseField.move()`."""
    get_phase_field(model=type(obj)).move(obj=obj, to=to, **fields)


def can_transition(*, obj: models.Model, to: Phase) -> bool:
    return get_phase_field(model=type(obj)).can_transition(obj=obj, to=to)


def targets(*, obj: models.Model) -> tuple[Phase, ...]:
    return get_phase_field(model=type(obj)).targets(obj=obj)
