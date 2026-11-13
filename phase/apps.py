from django.apps import AppConfig


class PhaseConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "phase"

    def ready(self) -> None:
        from phase import checks  # noqa: F401, PLC0415 - registers the system checks
