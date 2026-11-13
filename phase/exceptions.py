def _quote(phase: object, label: str | None) -> str:
    """A phase for a message: the stored value, led by its label when the value alone doesn't tell what it means."""
    return f"'{phase}'" if label is None else f"'{label}' ({phase})"


class IllegalPhaseTransitionError(Exception):
    """
    The transition isn't in the table, or the row changed or vanished since `obj` was loaded.

    `source` is the phase in the database when the row changed in the meantime, and `None` when the row doesn't exist.
    `source` and `target` are the stored values; the labels only make the message readable. `pk` is `None` when
    `move_many()` refused the transition for a set of rows rather than for one instance.
    """

    def __init__(  # noqa: PLR0913
        self,
        *,
        model_name: str,
        pk: int | None,
        source: str | int | None,
        target: str | int,
        source_label: str | None = None,
        target_label: str | None = None,
    ):
        self.model_name = model_name
        self.pk = pk
        self.source = source
        self.target = target
        self.source_label = source_label
        self.target_label = target_label
        quoted_target = _quote(target, target_label)
        if source is None:
            message = f"{model_name} ID #{pk} doesn't exist in the database and cannot change to {quoted_target}."
        elif pk is None:
            message = f"{model_name} cannot change from {_quote(source, source_label)} to {quoted_target}."
        else:
            message = f"{model_name} ID #{pk} cannot change from {_quote(source, source_label)} to {quoted_target}."
        super().__init__(message)

    def __reduce__(self) -> tuple:
        # The parallel test runner sends failures between processes; the default reduce calls __init__ positionally.
        return _rebuild_from_keywords, (
            type(self),
            {
                "model_name": self.model_name,
                "pk": self.pk,
                "source": self.source,
                "target": self.target,
                "source_label": self.source_label,
                "target_label": self.target_label,
            },
        )


class StalePhaseError(Exception):
    """
    The phase the instance was loaded with is no longer the one in the database.

    `phases` maps each phase field to the stored value the instance holds; `labels` names those that aren't readable
    by themselves.
    """

    def __init__(self, *, model_name: str, pk: int, phases: dict[str, str | int], labels: dict[str, str] | None = None):
        self.model_name = model_name
        self.pk = pk
        self.phases = phases
        self.labels = labels or {}
        loaded = ", ".join(f"{field}={_quote(phase, self.labels.get(field))}" for field, phase in phases.items())
        super().__init__(f"{model_name} ID #{pk} no longer has {loaded} in the database; reload it before saving.")

    def __reduce__(self) -> tuple:
        return _rebuild_from_keywords, (
            type(self),
            {"model_name": self.model_name, "pk": self.pk, "phases": self.phases, "labels": self.labels},
        )


def _rebuild_from_keywords(error_class: type[BaseException], kwargs: dict) -> BaseException:
    return error_class(**kwargs)


class RebuiltWithoutInitMixin:
    """
    Pickle an exception whose constructor takes keyword arguments.

    The default reduce calls `__init__` positionally with the message, which such a constructor refuses. The copy is
    rebuilt from message and attributes instead, so it works for any constructor signature a subclass defines.
    """

    def __reduce__(self) -> tuple:
        return _rebuild_without_init, (type(self), self.args, dict(self.__dict__))


def _rebuild_without_init(error_class: type[BaseException], args: tuple, attributes: dict) -> BaseException:
    error = error_class.__new__(error_class)
    error.args = args
    error.__dict__.update(attributes)
    return error


class PhaseGuardError(RebuiltWithoutInitMixin, Exception):
    """
    An action refuses to run because a condition on the current phase beyond the transition table isn't met.

    Every guard is its own subclass with a stable `code` for machines and a `detail` for humans, which tells the user
    why the action was refused and what to do next. `phase` doesn't translate; the subclass passes a translated text.
    The message given to the constructor is meant for logs and may contain IDs. A subclass is free in its constructor
    signature and stays picklable.
    """

    code: str
    detail: str


class ProtectedPhaseFieldError(RebuiltWithoutInitMixin, AttributeError):
    def __init__(self, *, field_name: str):
        super().__init__(f"'{field_name}' is a phase field and can only change through a transition.")


class EditablePhaseFieldError(TypeError):
    def __init__(self, *args):
        super().__init__("A PhaseField can't be editable; its value only changes through a transition.")


class InvalidTransitionTableError(RebuiltWithoutInitMixin, TypeError):
    def __init__(self, *, source: str | int):
        super().__init__(f"Targets of phase '{source}' must be a tuple, e.g. ('declined',) for a single target.")


class MissingPhaseFieldError(RebuiltWithoutInitMixin, TypeError):
    def __init__(self, *, model_name: str):
        super().__init__(f"{model_name} has no PhaseField.")
