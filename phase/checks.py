from django.apps import apps
from django.core import checks

from phase.fields import PhaseField
from phase.mixins.phase_guard import PhaseGuardMixin


@checks.register(checks.Tags.models)
def check_phase_fields(app_configs: list | None = None, **kwargs: object) -> list[checks.Error]:
    """
    Every model with a PhaseField inherits PhaseGuardMixin and has exactly one PhaseField.

    Without the mixin the model can't be reloaded, because the field refuses the second assignment. With two phase
    fields `phase.transitions.move()` couldn't tell which one to move.
    """
    errors = []
    for model in apps.get_models():
        phase_fields = [field for field in model._meta.concrete_fields if isinstance(field, PhaseField)]
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
