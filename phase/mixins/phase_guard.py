from django.db import models, transaction

from phase.exceptions import StalePhaseError
from phase.fields import REFRESHING_FLAG, PhaseField


class PhaseGuardMixin(models.Model):
    """
    Companion of `PhaseField`: lets reloads past the field's write protection and guards every save against a stale
    phase.

    A save of an instance whose phase no longer matches the database would silently undo a concurrent transition, so
    it is refused. Because a `PhaseField` only changes through `move()`, the in-memory value always is the value last
    read from or written to the database, and comparing it with a locked row is enough.

    System check `phase.E001` makes sure every model with a `PhaseField` inherits this mixin.
    """

    class Meta:
        abstract = True

    def save(self, *args: object, **kwargs: object) -> None:
        if self._state.adding:
            super().save(*args, **kwargs)
            return

        loaded_phases = {
            field.attname: self.__dict__[field.attname]
            for field in self.phase_fields()
            if field.attname in self.__dict__
        }
        with transaction.atomic():
            if (
                loaded_phases
                and not type(self)._default_manager.select_for_update().filter(pk=self.pk, **loaded_phases).exists()
            ):
                raise StalePhaseError(model_name=self._meta.label, pk=self.pk, phases=loaded_phases)
            super().save(*args, **kwargs)

    @classmethod
    def phase_fields(cls) -> tuple[PhaseField, ...]:
        return tuple(field for field in cls._meta.concrete_fields if isinstance(field, PhaseField))

    def refresh_from_db(self, *args: object, **kwargs: object) -> None:
        self.__dict__[REFRESHING_FLAG] = True
        try:
            super().refresh_from_db(*args, **kwargs)
        finally:
            del self.__dict__[REFRESHING_FLAG]
