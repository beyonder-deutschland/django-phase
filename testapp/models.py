from django.db import models

from phase.fields import PhaseField
from phase.mixins.phase_guard import PhaseGuardMixin


class Order(PhaseGuardMixin, models.Model):
    class Status(models.TextChoices):
        OPEN = "open"
        PAID = "paid"
        SHIPPED = "shipped"
        CANCELLED = "cancelled"

    status = PhaseField(
        max_length=10,
        choices=Status.choices,
        default=Status.OPEN,
        transitions={
            Status.OPEN: (Status.PAID, Status.CANCELLED),
            Status.PAID: (Status.SHIPPED,),
        },
    )
    note = models.CharField(max_length=100, blank=True, default="")
    transition_count = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Order {self.pk}: {self.status}"


class ActiveShipmentManager(models.Manager):
    def get_queryset(self) -> models.QuerySet:
        return super().get_queryset().filter(archived=False)


class Shipment(PhaseGuardMixin, models.Model):
    """Phase from `db_default` and a default manager that hides rows."""

    status = PhaseField(max_length=10, db_default="packed", transitions={"packed": ("sent",)})
    archived = models.BooleanField(default=False)

    objects = ActiveShipmentManager()

    def __str__(self) -> str:
        return f"Shipment {self.pk}: {self.status}"
