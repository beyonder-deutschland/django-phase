## Features

* Declare the allowed transitions once, as a table on the field
* Assigning the phase directly raises; only `move()` and `move_many()` change it
* `move()` writes phase and further fields in **one** conditional `UPDATE`, so of two concurrent transitions from the
  same phase exactly one succeeds
* `move_many()` moves a whole queryset from one phase to another with one conditional `UPDATE`, checked against
  the same table
* Every `save()` is guarded against a stale phase, so it can't silently undo a concurrent transition
* Phases as strings (`PhaseField`) or numbers (`IntegerPhaseField`); migrations see a plain Django field and never
  import `phase`
* System checks catch a missing mixin, a second phase field, a nullable one or one inherited from a concrete parent
  model
* `PhaseGuardError` gives refused actions a stable `code` for machines and a `detail` for humans
* Overrides no private Django method

```python
from django.db import models
from django.utils import timezone

from phase.fields import PhaseField
from phase.mixins.phase_guard import PhaseGuardMixin
from phase.transitions import move


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
    paid_at = models.DateTimeField(null=True, blank=True)


order = Order.objects.create()
move(obj=order, to=Order.Status.PAID, paid_at=timezone.now())

order.status = Order.Status.OPEN  # raises ProtectedPhaseFieldError
move(obj=order, to=Order.Status.OPEN)  # raises IllegalPhaseTransitionError
```
