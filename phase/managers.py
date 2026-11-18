from collections.abc import Iterable

from django.db import models

from phase.exceptions import ProtectedPhaseFieldError
from phase.fields import get_phase_fields, is_writing_phase


class PhaseQuerySetMixin:
    """
    Refuse bulk writes that would set the phase without a transition.

    `update()`, `bulk_update()` and `bulk_create(update_conflicts=True)` write the phase column directly, past the
    transition table and the guard of `save()`. With this mixin they raise `ProtectedPhaseFieldError` as soon as they
    would write the phase field; writes of other fields pass. `move()`, `move_many()` and `force_move()` keep working,
    also through a protected base manager.

    Mix it into a queryset of your own in front of `models.QuerySet`, or use `PhaseQuerySet` and `PhaseManager`.
    """

    def update(self, **kwargs: object) -> int:
        self._refuse_phase_writes(field_names=kwargs)
        return super().update(**kwargs)

    def bulk_update(self, objs: Iterable[models.Model], fields: Iterable[str], batch_size: int | None = None) -> int:
        fields = list(fields)
        self._refuse_phase_writes(field_names=fields)
        return super().bulk_update(objs, fields, batch_size=batch_size)

    def bulk_create(  # noqa: PLR0913, PLR0917 - the signature of `QuerySet.bulk_create()`
        self,
        objs: Iterable[models.Model],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Iterable[str] | None = None,
        unique_fields: Iterable[str] | None = None,
    ) -> list[models.Model]:
        if update_conflicts and update_fields:
            update_fields = list(update_fields)
            self._refuse_phase_writes(field_names=update_fields)
        return super().bulk_create(
            objs,
            batch_size=batch_size,
            ignore_conflicts=ignore_conflicts,
            update_conflicts=update_conflicts,
            update_fields=update_fields,
            unique_fields=unique_fields,
        )

    def _refuse_phase_writes(self, *, field_names: Iterable[str]) -> None:
        if is_writing_phase():
            return
        field_names = set(field_names)
        for field in get_phase_fields(model=self.model):
            if field.name in field_names or field.attname in field_names:
                raise ProtectedPhaseFieldError(field_name=field.attname)


class PhaseQuerySet(PhaseQuerySetMixin, models.QuerySet):
    pass


class PhaseManager(models.Manager.from_queryset(PhaseQuerySet)):
    """
    A manager whose querysets refuse bulk writes to the phase field, see `PhaseQuerySetMixin`.

    It isn't used in migrations, so data migrations write phases with the plain manager of the historical model.
    """
