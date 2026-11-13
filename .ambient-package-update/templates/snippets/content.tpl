## Features

* Declare the allowed transitions once, as a table on the field
* Assigning the phase directly raises; only `move()` changes it
* `move()` writes phase and further fields in **one** conditional `UPDATE`, so of two concurrent transitions from the
  same phase exactly one succeeds
* Every `save()` is guarded against a stale phase, so it can't silently undo a concurrent transition
* Migrations see a plain `CharField` and never import `phase`
* System checks catch a missing mixin or a second phase field
* `PhaseGuardError` gives refused actions a stable `code` for machines and a `detail` for humans
* Uses documented Django API only

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
