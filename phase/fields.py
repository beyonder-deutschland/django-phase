import copy
from collections.abc import Mapping

from django.db import models
from django.db.models.query_utils import DeferredAttribute

from phase.exceptions import (
    EditablePhaseFieldError,
    IllegalPhaseTransitionError,
    InvalidTransitionTableError,
    MissingPhaseFieldError,
    ProtectedPhaseFieldError,
)

# Set on the instance while `PhaseGuardMixin.refresh_from_db()` runs, so the reload may overwrite the phase.
REFRESHING_FLAG = "_phase_field_refreshing"


class ProtectedPhaseDescriptor(DeferredAttribute):
    """
    Allow a phase value to be set once per instance, refuse every later assignment.

    Django sets field values with `setattr` when it builds an instance (constructor, loading from the database) and
    when it fetches a deferred field; in all these cases the instance holds no value yet. A reload through
    `PhaseGuardMixin.refresh_from_db()` may overwrite it, because it writes what the database holds. So may Django
    after an INSERT, when it replaces an expression such as a `db_default` with the value the database returned.
    """

    def __set__(self, instance: models.Model, value: str) -> None:
        if (
            self.field.attname in instance.__dict__
            and not instance.__dict__.get(REFRESHING_FLAG)
            and not is_expression(instance.__dict__[self.field.attname])
        ):
            raise ProtectedPhaseFieldError(field_name=self.field.attname)
        instance.__dict__[self.field.attname] = value


def is_expression(value: object) -> bool:
    """A placeholder the database resolves, e.g. `DatabaseDefault` for a field with `db_default` before the INSERT."""
    return hasattr(value, "resolve_expression")


class PhaseField(models.CharField):
    """
    A CharField whose value only changes along `transitions`, via `move()`.

    A phase missing from `transitions` is final. `move()` writes with a conditional UPDATE on the source phase, so two
    concurrent transitions from the same phase cannot both succeed: the second one updates no row and is rejected like
    any other illegal transition.

    The field is never editable: admin and model forms leave it out, because saving a form would assign it directly.
    """

    descriptor_class = ProtectedPhaseDescriptor

    def __init__(self, *args: object, transitions: Mapping[str, tuple[str, ...]], **kwargs: object) -> None:
        # `(DECLINED)` without a trailing comma is a plain string, and `in` on a string matches substrings.
        for source, targets in transitions.items():
            if not isinstance(targets, tuple):
                raise InvalidTransitionTableError(source=source)
        if kwargs.get("editable", False):
            raise EditablePhaseFieldError
        kwargs["editable"] = False
        self.transitions = transitions
        super().__init__(*args, **kwargs)

    def deconstruct(self) -> tuple:
        # Migrations see a plain CharField: the table and the editability are behaviour, not schema, and must not pin
        # migrations to phase.
        name, _, args, kwargs = super().deconstruct()
        kwargs.pop("editable", None)
        return name, "django.db.models.CharField", args, kwargs

    def clone(self) -> "PhaseField":
        # Field.clone() rebuilds from deconstruct(), which drops the table on purpose; the clone still needs it.
        _, _, args, kwargs = self.deconstruct()
        return self.__class__(*args, transitions=self.transitions, **kwargs)

    def targets(self, *, obj: models.Model) -> tuple[str, ...]:
        return self.transitions.get(getattr(obj, self.attname), ())

    def can_transition(self, *, obj: models.Model, to: str) -> bool:
        return to in self.targets(obj=obj)

    def move(self, *, obj: models.Model, to: str, **fields: object) -> None:
        """
        Move `obj` to phase `to` and write `fields` and the model's `auto_now` fields in the same UPDATE.

        On success `obj` is refreshed, so field values given as expressions are read back as stored values. On failure
        `obj` stays as it was: its phase no longer matches the database, so a later `save()` is refused as stale
        instead of overwriting what the winner of a race wrote.

        Like `QuerySet.update()`, this sends no `pre_save`/`post_save` signals and doesn't call `save()`.
        """
        source = getattr(obj, self.attname)
        if not self.can_transition(obj=obj, to=to):
            raise IllegalPhaseTransitionError(model_name=obj._meta.label, pk=obj.pk, source=source, target=to)

        rows = type(obj)._base_manager.db_manager(obj._state.db).filter(pk=obj.pk)
        auto_now_values = self._auto_now_values(obj=obj, fields=fields)
        updated_rows = rows.filter(**{self.attname: source}).update(**{self.attname: to}, **auto_now_values, **fields)
        if not updated_rows:
            raise IllegalPhaseTransitionError(
                model_name=obj._meta.label,
                pk=obj.pk,
                source=rows.values_list(self.attname, flat=True).first(),
                target=to,
            )

        obj.refresh_from_db(fields=[self.attname, *auto_now_values, *fields])

    @staticmethod
    def _auto_now_values(*, obj: models.Model, fields: Mapping[str, object]) -> dict[str, object]:
        # `pre_save()` computes the value as `save()` would, but also assigns it; a copy keeps `obj` untouched until the
        # UPDATE succeeded.
        stamped = copy.copy(obj)
        return {
            field.attname: field.pre_save(stamped, add=False)
            for field in obj._meta.concrete_fields
            if getattr(field, "auto_now", False) and field.name not in fields and field.attname not in fields
        }


def get_phase_fields(*, model: type[models.Model]) -> tuple[PhaseField, ...]:
    return tuple(field for field in model._meta.concrete_fields if isinstance(field, PhaseField))


def get_phase_field(*, model: type[models.Model]) -> PhaseField:
    """
    Return the one `PhaseField` of `model`.

    A model has at most one phase field (system check `phase.E002`), so callers never name the field.
    """
    phase_fields = get_phase_fields(model=model)
    if not phase_fields:
        raise MissingPhaseFieldError(model_name=model._meta.label)
    return phase_fields[0]
