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

    def __str__(self) -> str:
        return f"Order {self.pk}: {self.status}"
