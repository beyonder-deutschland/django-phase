from django.db import models

from phase.fields import IntegerPhaseField, PhaseField
from phase.mixins.phase_guard import PhaseGuardMixin


class Customer(models.Model):
    country = models.CharField(max_length=2, default="DE")

    def __str__(self) -> str:
        return f"Customer {self.pk}"


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
    customer = models.ForeignKey(Customer, null=True, blank=True, on_delete=models.CASCADE)
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


class Invoice(PhaseGuardMixin, models.Model):
    """Phase stored as a number."""

    class Status(models.IntegerChoices):
        DRAFT = 1, "Draft"
        SENT = 2, "Sent"
        PAID = 3, "Paid"
        VOID = 4, "Void"

    status = IntegerPhaseField(
        choices=Status.choices,
        default=Status.DRAFT,
        transitions={
            Status.DRAFT: (Status.SENT, Status.VOID),
            Status.SENT: (Status.PAID,),
        },
    )
    note = models.CharField(max_length=100, blank=True, default="")

    def __str__(self) -> str:
        return f"Invoice {self.pk}: {self.status}"
