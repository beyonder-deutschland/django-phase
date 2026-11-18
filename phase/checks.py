from collections.abc import Iterable
from itertools import chain

from django.apps import AppConfig, apps
from django.core import checks
from django.db.models import Manager, Model

from phase.fields import get_phase_fields
from phase.managers import PhaseQuerySetMixin
from phase.mixins.phase_guard import PhaseGuardMixin


@checks.register(checks.Tags.models)
def check_phase_fields(app_configs: list[AppConfig] | None = None, **kwargs: object) -> list[checks.Error]:
    """
    Every model with a phase field inherits PhaseGuardMixin, has exactly one phase field, stores it in its own table
    and doesn't allow NULL in it.

    Without the mixin the model can't be reloaded, because the field refuses the second assignment. With two phase
    fields `phase.transitions.move()` couldn't tell which one to move. A phase field in the table of a concrete parent
    makes Django split the UPDATE of `move()` into a SELECT of the primary keys and an UPDATE without the condition on
    the phase, so two concurrent transitions could both succeed. NULL can't be a phase, because a refused transition
    reports a row that doesn't exist as "no phase". Proxy models share their concrete model's fields and are reported
    there.
    """
    errors = []
    for model in _models(app_configs=app_configs):
        if model._meta.proxy:
            continue
        phase_fields = get_phase_fields(model=model)
        if phase_fields and not issubclass(model, PhaseGuardMixin):
            errors.append(
                checks.Error(
                    f"{model._meta.label} has a PhaseField but doesn't inherit from PhaseGuardMixin.",
                    obj=model,
                    id="phase.E001",
                )
            )
        if len(phase_fields) > 1:
            errors.append(
                checks.Error(
                    f"{model._meta.label} has more than one PhaseField.",
                    hint="A model has one lifecycle; a second one usually belongs on its own model.",
                    obj=model,
                    id="phase.E002",
                )
            )
        if any(field.model is not model for field in phase_fields):
            errors.append(
                checks.Error(
                    f"{model._meta.label} inherits its PhaseField from a concrete parent model.",
                    hint="Make the parent abstract, or give the lifecycle its own model without concrete children.",
                    obj=model,
                    id="phase.E003",
                )
            )
        if any(field.null for field in phase_fields):
            errors.append(
                checks.Error(
                    f"{model._meta.label} has a PhaseField that allows NULL.",
                    hint="Give the state without a value a phase of its own, e.g. 'open'.",
                    obj=model,
                    id="phase.E004",
                )
            )
    return errors


@checks.register(checks.Tags.models)
def check_phase_managers(app_configs: list[AppConfig] | None = None, **kwargs: object) -> list[checks.Warning]:
    """
    Every manager of a model with a phase field refuses bulk writes to it.

    `update()`, `bulk_update()` and `bulk_create(update_conflicts=True)` on a plain manager set the phase past the
    transition table and the guard. A manager built on `PhaseQuerySetMixin` refuses them. Every declared manager is
    checked, so a second plain manager next to a protected one doesn't leave the gap open. A proxy model is checked
    for the managers it declares itself; those it inherits are reported on its concrete model. The base manager isn't
    checked: Django uses it internally, and only a model that names one in `Meta.base_manager_name` declares it.
    """
    warnings = []
    for model in _models(app_configs=app_configs):
        if not get_phase_fields(model=model):
            continue
        managers = model._meta.local_managers if model._meta.proxy else model._meta.managers
        warnings.extend(
            checks.Warning(
                f"{model._meta.label}.{manager.name} doesn't refuse bulk writes to the phase field.",
                hint=(
                    "Build the manager on PhaseQuerySet or PhaseQuerySetMixin, e.g. objects = PhaseManager(). To "
                    "allow update() and bulk_update() on the phase, add 'phase.W001' to SILENCED_SYSTEM_CHECKS."
                ),
                obj=model,
                id="phase.W001",
            )
            for manager in managers
            if not _is_protected(manager=manager)
        )
    return warnings


def _is_protected(*, manager: Manager) -> bool:
    """
    Whether the querysets of `manager` refuse bulk writes to the phase.

    A manager may need context its `get_queryset()` doesn't have while checks run, e.g. the current tenant. Then the
    queryset class it was built with decides.
    """
    try:
        queryset = manager.get_queryset()
    except Exception:  # noqa: BLE001 - any error of a project's manager; the check must not crash on it
        return issubclass(manager._queryset_class, PhaseQuerySetMixin)
    return isinstance(queryset, PhaseQuerySetMixin)


def _models(*, app_configs: list[AppConfig] | None) -> Iterable[type[Model]]:
    if app_configs is None:
        return apps.get_models()
    return chain.from_iterable(app_config.get_models() for app_config in app_configs)
