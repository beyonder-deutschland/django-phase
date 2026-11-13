from django.db import models, router, transaction

from phase.exceptions import StalePhaseError
from phase.fields import REFRESHING_FLAG, PhaseField, get_phase_fields, is_expression


class PhaseGuardMixin(models.Model):
    """
    Companion of `PhaseField`: lets reloads past the field's write protection and guards every save against a stale
    phase.

    A save of an instance whose phase no longer matches the database would silently undo a concurrent transition, so
    it is refused. Because a `PhaseField` only changes through `move()`, the in-memory value always is the value last
    read from or written to the database, and comparing it with a locked row is enough.

    This also covers a new instance with an explicit primary key: Django tries an UPDATE first, which would otherwise
    overwrite the phase of an existing row without a transition.

    System check `phase.E001` makes sure every model with a `PhaseField` inherits this mixin.
    """

    class Meta:
        abstract = True

    def save(self, *args: object, **kwargs: object) -> None:
        loaded_phases = {
            field.attname: self.__dict__[field.attname]
            for field in self.phase_fields()
            if field.attname in self.__dict__ and not is_expression(self.__dict__[field.attname])
        }
        # Nothing to compare, an INSERT anyway, or a save Django skips (`update_fields=[]`).
        if not loaded_phases or self.pk is None or kwargs.get("force_insert") or kwargs.get("update_fields") == []:
            super().save(*args, **kwargs)
            return

        using = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=using):
            stored_phases = (
                type(self)._base_manager.using(using).select_for_update().filter(pk=self.pk).values(*loaded_phases)
            ).first()
            if stored_phases is None and self._state.adding:
                super().save(*args, **kwargs)
                return
            if stored_phases != loaded_phases:
                raise StalePhaseError(model_name=self._meta.label, pk=self.pk, phases=loaded_phases)
            super().save(*args, **kwargs)

    @classmethod
    def phase_fields(cls) -> tuple[PhaseField, ...]:
        return get_phase_fields(model=cls)

    def refresh_from_db(self, *args: object, **kwargs: object) -> None:
        self.__dict__[REFRESHING_FLAG] = True
        try:
            super().refresh_from_db(*args, **kwargs)
        finally:
            del self.__dict__[REFRESHING_FLAG]
