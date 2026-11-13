# Usage

## The field

A model whose status may only change along fixed transitions declares it as a `PhaseField`. The field owns the
transition table; `phase.transitions.move()` is the one way of changing it.

```python
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
```

* A phase missing from `transitions` is final. Targets are tuples; a single target needs the trailing comma,
  `(Status.SHIPPED,)`. The field rejects anything else with `InvalidTransitionTableError`, because `(Status.SHIPPED)`
  is a plain string and `in` would match substrings.
* **Direct assignment raises** `ProtectedPhaseFieldError`. The value is set once when the instance is built or loaded;
  after that only `move()` changes it. Factories keep working, because they pass the phase to the constructor.
* **Never editable.** Admin and model forms leave the field out; passing `editable=True` raises
  `EditablePhaseFieldError`. List it in an admin's `readonly_fields` to show it on the detail page.
* Migrations see a plain `CharField`, so no migration depends on `phase`. Changing the transition table needs no
  migration.
* **One `PhaseField` per model** (system check `phase.E002`). A model has one lifecycle; a second one usually belongs on
  its own model. This is what lets `move()` find the field without being told.

## Moving

```python
from django.utils import timezone

from phase.transitions import can_transition, move, targets

move(obj=order, to=Order.Status.PAID, paid_at=timezone.now())
```

* `move(obj=…, to=…, **fields)` checks the table and writes the phase and `fields` in **one** conditional `UPDATE`
  (`filter(pk=…, <field>=<source>).update(…)`). If no row changes, a concurrent request won the race and
  `IllegalPhaseTransitionError` is raised, exactly as for a transition missing from the table.
* Afterwards the instance is refreshed from the database, so `fields` given as expressions (`F("count") + 1`) are read
  back as stored values.
* `can_transition(obj=…, to=…)` and `targets(obj=…)` answer read-only questions. They only know the table, not further
  conditions your code checks.

## The mixin

Every model with a `PhaseField` inherits `PhaseGuardMixin` (system check `phase.E001`). It does two things:

* `refresh_from_db()` may overwrite the protected field, because it writes what the database holds.
* **Every `save()` is guarded against a stale phase.** Inside a transaction it locks the row with `select_for_update`
  and refuses the save with `StalePhaseError` if the phase in the database differs from the instance. This also covers
  saves that don't touch the phase (`save(update_fields=["note"])`), which would otherwise silently undo a concurrent
  transition. The price is one extra `SELECT … FOR UPDATE` per save of an existing instance.

## Limits

* `QuerySet.update()` and `bulk_update()` bypass both the field and the mixin. Data migrations and bulk writes have to
  respect the table by hand.
* A model can have only one `PhaseField`.

## Actions around a transition

What happens around a phase change — conditions beyond the table, emails, calls to other systems — is an action. Keep
actions out of the model, call `move()` from them and register side effects with `transaction.on_commit`, so a refused
or rolled-back transition triggers nothing:

```python
from django.db import transaction
from django.utils import timezone

from phase.transitions import move


class OrderTransitions:
    @staticmethod
    @transaction.atomic
    def cancel(*, order: Order) -> None:
        move(obj=order, to=Order.Status.CANCELLED, cancelled_at=timezone.now())
        transaction.on_commit(lambda: send_order_cancelled_email.delay(order_id=order.pk))
```

Several actions may lead to the same transition. The table says which phase pairs are allowed; the actions say what
else happens.
