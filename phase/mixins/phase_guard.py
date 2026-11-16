from django.db import models, router, transaction

from phase.exceptions import StalePhaseError
from phase.fields import REFRESHING_FLAG, PhaseFieldMixin, get_phase_fields, is_expression

# The arguments of `Model.save()` in positional order.
SAVE_ARGUMENTS = ("force_insert", "force_update", "using", "update_fields")


class PhaseGuardMixin(models.Model):
    """
    Companion of a phase field: lets reloads past the field's write protection and guards every save against a stale
    phase.

    A save of an instance whose phase no longer matches the database would silently undo a concurrent transition, so
    it is refused. Because a phase field only changes through `move()`, the in-memory value always is the value last
    read from or written to the database, and comparing it with a locked row is enough.

    This also covers a new instance with an explicit primary key: Django tries an UPDATE first, which would otherwise
    overwrite the phase of an existing row without a transition.

    System check `phase.E001` makes sure every model with a phase field inherits this mixin.
    """

    class Meta:
        abstract = True

    def save(self, *args: object, **kwargs: object) -> None:
        loaded_phases = {
            field.attname: self.__dict__[field.attname]
            for field in self.phase_fields()
            if field.attname in self.__dict__ and not is_expression(self.__dict__[field.attname])
        }
        # Django 5.2 accepts the arguments of `save()` positionally as well.
        options = dict(zip(SAVE_ARGUMENTS, args, strict=False)) | kwargs
        update_fields = options.get("update_fields")
        is_skipped_by_django = update_fields is not None and not update_fields
        # Nothing to compare, an INSERT anyway, or a save Django skips (empty `update_fields`).
        if not loaded_phases or self.pk is None or options.get("force_insert") or is_skipped_by_django:
            super().save(*args, **kwargs)
            return

        using = options.get("using") or router.db_for_write(type(self), instance=self)
        if transaction.get_autocommit(using=using):
            # A row lock ends with its transaction, so in autocommit one has to span the check and the write.
            with transaction.atomic(using=using):
                self._save_checked(using=using, loaded_phases=loaded_phases, args=args, kwargs=kwargs)
        else:
            # The open transaction keeps the lock until it ends. Nothing wraps the save here, so an error in it leaves
            # that transaction in the state a save of a plain model would, and a caught `StalePhaseError` leaves it
            # usable.
            self._save_checked(using=using, loaded_phases=loaded_phases, args=args, kwargs=kwargs)

    def _save_checked(self, *, using: str, loaded_phases: dict[str, object], args: tuple, kwargs: dict) -> None:
        """Lock the row, compare its phases with the loaded ones and save. Runs inside a transaction."""
        stored_phases = (
            type(self)._base_manager.using(using).select_for_update().filter(pk=self.pk).values(*loaded_phases)
        ).first()
        is_new_row = stored_phases is None and self._state.adding
        if not is_new_row and stored_phases != loaded_phases:
            raise StalePhaseError(
                model_name=self._meta.label, pk=self.pk, phases=loaded_phases, labels=self._phase_labels()
            )
        super().save(*args, **kwargs)

    @classmethod
    def phase_fields(cls) -> tuple[PhaseFieldMixin, ...]:
        return get_phase_fields(model=cls)

    def _phase_labels(self) -> dict[str, str]:
        labels = {field.attname: field.label(self.__dict__.get(field.attname)) for field in self.phase_fields()}
        return {attname: label for attname, label in labels.items() if label is not None}

    def refresh_from_db(self, *args: object, **kwargs: object) -> None:
        self.__dict__[REFRESHING_FLAG] = True
        try:
            super().refresh_from_db(*args, **kwargs)
        finally:
            del self.__dict__[REFRESHING_FLAG]
