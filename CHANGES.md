# Changelog

**0.5.0** (2026-11-18)
  * `phase.contrib.rest_framework.exception_handler` answers `PhaseGuardError`, `IllegalPhaseTransitionError` and
    `StalePhaseError` in Django REST framework with HTTP 409 and `{"code": …, "detail": …}`; the extra `drf` installs
    `djangorestframework`

**0.4.2** (2026-11-18)
  * Switched the maintenance tooling from ambient-package-update to package-foundry; its configuration now lives in
    `.package-foundry/`
  * Updated the development dependencies to Sphinx 9 (`sphinx~=9.0`) and typer 0.29; package-foundry is only installed
    on Python 3.13 and newer
  * Updated the ruff pre-commit hook to v0.17.5 and `astral-sh/setup-uv` to v10.3.3
  * The documentation badge in the README is served by shields.io, and the Sphinx copyright names Beyonder GmbH

**0.4.1** (2026-11-17)
  * `move()` also refreshes the model's `GeneratedField`s, so the instance and `post_save` receivers see the values the
    database computed from the new phase
  * Documented that a phase field in `fields` or `fieldsets` of a `ModelAdmin` has to be in `readonly_fields` as well
  * Documented how to move many rows to different targets, and why the guard can't be switched off

**0.4.0** (2026-11-16)
  * Inside a transaction a guarded `save()` runs one extra statement, the `SELECT … FOR UPDATE`, without a savepoint
    around it
  * Inside a transaction a database error in a guarded `save()`, e.g. `IntegrityError`, marks the transaction for
    rollback, as the save of a plain model does; wrap the save in its own `transaction.atomic()` to catch it and go on
  * Documented how `phase` works with audit logs, `bulk_create()`, `get_or_create()` and `update_or_create()`, Django
    REST framework and the admin
  * Documented what the package leaves out on purpose and what may follow

**0.3.1** (2026-11-13)
  * `move_many()` checks the source phase on each written row also when the queryset filters across relations, so a
    concurrent transition is no longer overwritten; on MySQL and MariaDB it reads the primary keys first
  * Documented that `move_many()` opens no transaction of its own and refuses a sliced queryset

**0.3.0** (2026-11-13)
  * `move_many()`: moves the rows of a queryset from one phase to another with one conditional `UPDATE`, checked
    against the transition table, and returns the number of rows moved
  * `IllegalPhaseTransitionError` leaves out the ID when it refuses a transition for a set of rows

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
