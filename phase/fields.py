from collections.abc import Mapping
from types import SimpleNamespace

from django.db import models, router
from django.db.models import signals
from django.db.models.query_utils import DeferredAttribute

from phase.exceptions import (
    EditablePhaseFieldError,
    IllegalPhaseTransitionError,
    InvalidTransitionTableError,
    MissingPhaseFieldError,
    ProtectedPhaseFieldError,
)

# The value of a phase as the database stores it.
Phase = str | int

# Set on the instance while `PhaseGuardMixin.refresh_from_db()` runs, so the reload may overwrite the phase.
REFRESHING_FLAG = "_phase_field_refreshing"


class ProtectedPhaseDescriptor(DeferredAttribute):
    """
    Allow a phase value to be set once per instance, refuse every later assignment.

    Django sets field values with `setattr` when it builds an instance (constructor, loading from the database) and
    when it fetches a deferred field; in all these cases the instance holds no value yet. A reload through
    `PhaseGuardMixin.refresh_from_db()` may overwrite it, because it writes what the database holds. So may Django
    after an INSERT, when it replaces an expression such as a `db_default` with the value the database returned.

    Assigning the value the instance already holds changes nothing and passes. Django does that in
    `Model.clean_fields()` and when it writes back the columns an INSERT returned.
    """

    def __set__(self, instance: models.Model, value: object) -> None:
        if (
            self.field.attname in instance.__dict__
            and not instance.__dict__.get(REFRESHING_FLAG)
            and not is_expression(instance.__dict__[self.field.attname])
            and instance.__dict__[self.field.attname] != value
        ):
            raise ProtectedPhaseFieldError(field_name=self.field.attname)
        instance.__dict__[self.field.attname] = value


def is_expression(value: object) -> bool:
    """A placeholder the database resolves, e.g. `DatabaseDefault` for a field with `db_default` before the INSERT."""
    return hasattr(value, "resolve_expression")


class PhaseFieldMixin:
    """
    What `PhaseField` and `IntegerPhaseField` share: a value that only changes along `transitions`, via `move()`.

    A phase missing from `transitions` is final. `move()` writes with a conditional UPDATE on the source phase, so two
    concurrent transitions from the same phase cannot both succeed: the second one updates no row and is rejected like
    any other illegal transition.

    The field is never editable: admin and model forms leave it out, because saving a form would assign it directly.
    """

    descriptor_class = ProtectedPhaseDescriptor
    # The plain Django field migrations see.
    django_field_path: str

    def __init__(self, *args: object, transitions: Mapping[Phase, tuple[Phase, ...]], **kwargs: object) -> None:
        # `(DECLINED)` without a trailing comma is the phase itself, and `in` on a string matches substrings.
        for source, targets in transitions.items():
            if not isinstance(targets, tuple):
                raise InvalidTransitionTableError(source=source)
        if kwargs.get("editable", False):
            raise EditablePhaseFieldError
        kwargs["editable"] = False
        self.transitions = transitions
        super().__init__(*args, **kwargs)

    def deconstruct(self) -> tuple:
        # Migrations see the plain Django field: the table and the editability are behaviour, not schema, and must
        # not pin migrations to phase.
        name, _, args, kwargs = super().deconstruct()
        kwargs.pop("editable", None)
        return name, self.django_field_path, args, kwargs

    def clone(self) -> "PhaseFieldMixin":
        # Field.clone() rebuilds from deconstruct(), which drops the table on purpose; the clone still needs it.
        _, _, args, kwargs = self.deconstruct()
        return self.__class__(*args, transitions=self.transitions, **kwargs)

    def label(self, phase: Phase | None) -> str | None:
        """
        The choice label of a phase that isn't readable by itself, e.g. "Paid" for 2.

        A string phase names itself and has no label here, so messages show the stored value.
        """
        if phase is None or isinstance(phase, str):
            return None
        label = dict(self.flatchoices).get(phase)
        return None if label is None else str(label)

    def targets(self, *, obj: models.Model) -> tuple[Phase, ...]:
        return self.transitions.get(getattr(obj, self.attname), ())

    def can_transition(self, *, obj: models.Model, to: Phase) -> bool:
        return to in self.targets(obj=obj)

    def move(self, *, obj: models.Model, to: Phase, **fields: object) -> None:
        """
        Move `obj` to phase `to` and write `fields` and the model's `auto_now` fields in the same UPDATE.

        Towards signals this behaves like `obj.save(update_fields=[<phase>, *fields, *<auto_now fields>])`: `pre_save`
        sees the new values on `obj` and may change those fields, `post_save` follows a successful UPDATE.

        On success `obj` is refreshed, so field values given as expressions are read back as stored values. On failure
        `obj` stays as it was: its phase no longer matches the database, so a later `save()` is refused as stale
        instead of overwriting what the winner of a race wrote.
        """
        model = type(obj)
        using = router.db_for_write(model, instance=obj)
        rows = model._base_manager.using(using).filter(pk=obj.pk)

        source = getattr(obj, self.attname)
        if is_expression(source):
            # On Django 5.2 a backend without INSERT … RETURNING leaves the `db_default` placeholder on the instance.
            source = rows.values_list(self.attname, flat=True).first()
            if source is not None:
                obj.__dict__[self.attname] = source
        if to not in self.transitions.get(source, ()):
            raise self._illegal_transition(obj=obj, source=source, to=to)

        written_fields = self._written_fields(obj=obj, fields=fields)
        update_fields = frozenset(field.name for field in written_fields)

        loaded_state = (dict(obj.__dict__), dict(obj._state.fields_cache))
        try:
            obj.__dict__[self.attname] = to
            for name, value in fields.items():
                setattr(obj, name, value)
            signals.pre_save.send(sender=model, instance=obj, raw=False, using=using, update_fields=update_fields)
            # Like `save()`: values are read after `pre_save`, and `Field.pre_save()` stamps the `auto_now` fields.
            values = {field.attname: field.pre_save(obj, add=False) for field in written_fields}
            updated_rows = rows.filter(**{self.attname: source}).update(**values)
        except BaseException:
            self._restore(obj=obj, loaded_state=loaded_state)
            raise
        if not updated_rows:
            self._restore(obj=obj, loaded_state=loaded_state)
            raise self._illegal_transition(obj=obj, source=rows.values_list(self.attname, flat=True).first(), to=to)

        obj.refresh_from_db(using=using, fields=[field.attname for field in written_fields])
        signals.post_save.send(
            sender=model, instance=obj, created=False, update_fields=update_fields, raw=False, using=using
        )

    def move_many(self, *, queryset: models.QuerySet, source: Phase, to: Phase, **fields: object) -> int:
        """
        Move the rows of `queryset` that are in phase `source` to phase `to` with one conditional UPDATE.

        The UPDATE also writes `fields` and stamps the model's `auto_now` fields. Rows in another phase are skipped,
        so the return value, the number of rows moved, may be lower than the size of `queryset`. Like
        `QuerySet.update()` this sends no signals and leaves instances in memory as they are.
        """
        if self.name in fields or self.attname in fields:
            raise ProtectedPhaseFieldError(field_name=self.attname)
        if to not in self.transitions.get(source, ()):
            raise IllegalPhaseTransitionError(
                model_name=queryset.model._meta.label,
                pk=None,
                source=source,
                target=to,
                source_label=self.label(source),
                target_label=self.label(to),
            )
        values = {self.attname: to, **fields}
        stamp = SimpleNamespace()
        for field in queryset.model._meta.concrete_fields:
            if getattr(field, "auto_now", False):
                # As in `save()` and `move()`, the current time wins over a value given for an `auto_now` field.
                # `Field.pre_save()` only sets the attribute on the object it is given; nothing reads it back here.
                values[field.attname] = field.pre_save(stamp, add=False)
        return queryset.filter(**{self.attname: source}).update(**values)

    def _illegal_transition(self, *, obj: models.Model, source: Phase | None, to: Phase) -> IllegalPhaseTransitionError:
        return IllegalPhaseTransitionError(
            model_name=obj._meta.label,
            pk=obj.pk,
            source=source,
            target=to,
            source_label=self.label(source),
            target_label=self.label(to),
        )

    def _written_fields(self, *, obj: models.Model, fields: Mapping[str, object]) -> list[models.Field]:
        """The phase, `fields` and the `auto_now` fields not among them, as `save(update_fields=…)` would write them."""
        written_fields = [self, *(obj._meta.get_field(name) for name in fields)]
        written_fields += [
            field
            for field in obj._meta.concrete_fields
            if getattr(field, "auto_now", False) and field not in written_fields
        ]
        return written_fields

    @staticmethod
    def _restore(*, obj: models.Model, loaded_state: tuple[dict, dict]) -> None:
        instance_dict, fields_cache = loaded_state
        obj.__dict__.clear()
        obj.__dict__.update(instance_dict)
        obj._state.fields_cache = fields_cache


class PhaseField(PhaseFieldMixin, models.CharField):
    """A phase stored as a string, e.g. the values of a `TextChoices`."""

    django_field_path = "django.db.models.CharField"


class IntegerPhaseField(PhaseFieldMixin, models.PositiveSmallIntegerField):
    """
    A phase stored as a number, e.g. the values of an `IntegerChoices`.

    The column is a `PositiveSmallIntegerField`: phases are a handful of values counted from zero.
    """

    django_field_path = "django.db.models.PositiveSmallIntegerField"


def get_phase_fields(*, model: type[models.Model]) -> tuple[PhaseFieldMixin, ...]:
    return tuple(field for field in model._meta.concrete_fields if isinstance(field, PhaseFieldMixin))


def get_phase_field(*, model: type[models.Model]) -> PhaseFieldMixin:
    """
    Return the one phase field of `model`.

    A model has at most one phase field (system check `phase.E002`), so callers never name the field.
    """
    phase_fields = get_phase_fields(model=model)
    if not phase_fields:
        raise MissingPhaseFieldError(model_name=model._meta.label)
    return phase_fields[0]
