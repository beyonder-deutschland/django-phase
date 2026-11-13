from itertools import chain

from django.apps import AppConfig, apps
from django.core import checks

from phase.fields import get_phase_fields
from phase.mixins.phase_guard import PhaseGuardMixin


@checks.register(checks.Tags.models)
def check_phase_fields(app_configs: list[AppConfig] | None = None, **kwargs: object) -> list[checks.Error]:
    """
    Every model with a PhaseField inherits PhaseGuardMixin and has exactly one PhaseField.

    Without the mixin the model can't be reloaded, because the field refuses the second assignment. With two phase
    fields `phase.transitions.move()` couldn't tell which one to move. Proxy models share their concrete model's
    fields and are reported there.
    """
    if app_configs is None:
        models = apps.get_models()
    else:
        models = chain.from_iterable(app_config.get_models() for app_config in app_configs)

    errors = []
    for model in models:
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
    return errors
