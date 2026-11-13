# Changelog

**0.1.0** (2026-11-13)
  * `PhaseField`: a `CharField` carrying its transition table, protected against direct assignment and never editable
  * `move()` writes the phase, further fields and the `auto_now` fields in one conditional `UPDATE`, so the loser of a
    race is refused like any illegal transition
  * `PhaseGuardMixin` guards every `save()` against a stale phase and lets `refresh_from_db()` past the protection
  * System checks `phase.E001` (field without mixin) and `phase.E002` (more than one phase field per model)
  * `PhaseGuardError` as base class for refused actions with a stable `code` and a human-readable `detail`
