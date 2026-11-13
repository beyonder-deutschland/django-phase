from django.db import models

from phase.fields import PhaseField


def phase_field(*, model: type[models.Model]) -> PhaseField:
    """
    Return the one `PhaseField` of `model`.

    A model has at most one phase field (system check `phase.E002`), so callers never name the field.
    """
    return next(field for field in model._meta.concrete_fields if isinstance(field, PhaseField))


def move(*, obj: models.Model, to: str, **fields: object) -> None:
    """Move `obj` to phase `to` and write `fields` in the same conditional UPDATE, see `PhaseField.move()`."""
    phase_field(model=type(obj)).move(obj=obj, to=to, **fields)


def can_transition(*, obj: models.Model, to: str) -> bool:
    return phase_field(model=type(obj)).can_transition(obj=obj, to=to)


def targets(*, obj: models.Model) -> tuple[str, ...]:
    return phase_field(model=type(obj)).targets(obj=obj)
