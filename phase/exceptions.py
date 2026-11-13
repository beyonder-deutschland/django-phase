class IllegalPhaseTransitionError(Exception):
    """
    The transition isn't in the table, or the row changed or vanished since `obj` was loaded.

    `source` is the phase in the database when the row changed in the meantime, and `None` when the row doesn't exist.
    """

    def __init__(self, *, model_name: str, pk: int | None, source: str | None, target: str):
        self.model_name = model_name
        self.pk = pk
        self.source = source
        self.target = target
        if source is None:
            message = f"{model_name} ID #{pk} doesn't exist in the database and cannot change to '{target}'."
        else:
            message = f"{model_name} ID #{pk} cannot change from '{source}' to '{target}'."
        super().__init__(message)

    def __reduce__(self) -> tuple:
        # The parallel test runner sends failures between processes; the default reduce calls __init__ positionally.
        return _rebuild_illegal_phase_transition_error, (self.model_name, self.pk, self.source, self.target)


def _rebuild_illegal_phase_transition_error(
    model_name: str, pk: int | None, source: str | None, target: str
) -> IllegalPhaseTransitionError:
    return IllegalPhaseTransitionError(model_name=model_name, pk=pk, source=source, target=target)


class StalePhaseError(Exception):
    def __init__(self, *, model_name: str, pk: int, phases: dict[str, str]):
        self.model_name = model_name
        self.pk = pk
        self.phases = phases
        loaded = ", ".join(f"{field}='{phase}'" for field, phase in phases.items())
        super().__init__(f"{model_name} ID #{pk} no longer has {loaded} in the database; reload it before saving.")

    def __reduce__(self) -> tuple:
        return _rebuild_stale_phase_error, (self.model_name, self.pk, self.phases)


def _rebuild_stale_phase_error(model_name: str, pk: int, phases: dict[str, str]) -> StalePhaseError:
    return StalePhaseError(model_name=model_name, pk=pk, phases=phases)


class PhaseGuardError(Exception):
    """
    An action refuses to run because a condition on the current phase beyond the transition table isn't met.

    Every guard is its own subclass with a stable `code` for machines and a `detail` for humans, which tells the user
    why the action was refused and what to do next. `phase` doesn't translate; the subclass passes a translated text.
    The message given to the constructor is meant for logs and may contain IDs.
    """

    code: str
    detail: str


class ProtectedPhaseFieldError(AttributeError):
    def __init__(self, *, field_name: str):
        super().__init__(f"'{field_name}' is a phase field and can only change through a transition.")


class EditablePhaseFieldError(TypeError):
    def __init__(self, *args):
        super().__init__("A PhaseField can't be editable; its value only changes through a transition.")


class InvalidTransitionTableError(TypeError):
    def __init__(self, *, source: str):
        super().__init__(f"Targets of phase '{source}' must be a tuple, e.g. ('declined',) for a single target.")


class MissingPhaseFieldError(TypeError):
    def __init__(self, *, model_name: str):
        super().__init__(f"{model_name} has no PhaseField.")
