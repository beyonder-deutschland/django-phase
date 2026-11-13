# Changelog

**0.2.0** (2026-11-13)
  * `IntegerPhaseField`: a phase stored as a number, e.g. the values of an `IntegerChoices`, in a
    `PositiveSmallIntegerField`
  * Messages of `IllegalPhaseTransitionError` and `StalePhaseError` name a numeric phase by its choice label
  * System check `phase.E004` refuses a phase field with `null=True`

**0.1.1** (2026-11-13)
  * Shortened the package description

**0.1.0** (2026-11-13)
  * `PhaseField`: a `CharField` carrying its transition table, protected against direct assignment and never editable
  * `move()` writes the phase, further fields and the `auto_now` fields in one conditional `UPDATE`, so the loser of a
    race is refused like any illegal transition
  * `move()` sends `pre_save` and `post_save` like `save(update_fields=…)`
  * `PhaseGuardMixin` guards every `save()` against a stale phase and lets `refresh_from_db()` past the protection
  * System checks `phase.E001` (field without mixin), `phase.E002` (more than one phase field per model) and
    `phase.E003` (phase field inherited from a concrete parent model)
  * `PhaseGuardError` as base class for refused actions with a stable `code` and a human-readable `detail`
