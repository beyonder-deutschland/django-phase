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
* The same `UPDATE` also stamps the model's `auto_now` fields. As with `save()`, they always get the current time.
* On success the instance is refreshed from the database, so `fields` given as expressions (`F("count") + 1`) are read
  back as stored values.
* On failure the instance stays as it was. Its phase no longer matches the database, so a later `save()` is refused
  with `StalePhaseError` instead of overwriting what the winner of the race wrote. Reload it to go on. The exception's
  `source` is the phase in the database, or `None` if the row doesn't exist (anymore).
* **Signals** are sent as for `obj.save(update_fields=[<phase>, *fields, *<auto_now fields>])`: `pre_save` sees the new
  values on the instance and may still change the written fields (not the phase), `post_save` with `created=False`
  follows a successful `UPDATE` and sees the stored values. A refused transition sends no `post_save`; one that loses a
  race has already sent `pre_save`, as `save()` does when the write fails.
* The model's own `save()` isn't called.
* The row is addressed through the model's base manager on the instance's database, so a filtering default manager
  doesn't hide it.
* `can_transition(obj=…, to=…)` and `targets(obj=…)` answer read-only questions. They only know the table, not further
  conditions your code checks.

## The mixin

Every model with a `PhaseField` inherits `PhaseGuardMixin` (system check `phase.E001`). It does two things:

* `refresh_from_db()` may overwrite the protected field, because it writes what the database holds.
* **Every `save()` is guarded against a stale phase.** Inside a transaction it locks the row with `select_for_update`
  and refuses the save with `StalePhaseError` if the phase in the database differs from the instance. This also covers
  saves that don't touch the phase (`save(update_fields=["note"])`), which would otherwise silently undo a concurrent
  transition. The price is one extra `SELECT … FOR UPDATE` per save of an existing instance.
* A **new instance with an explicit primary key** is checked the same way when a row with that key exists, because
  Django then updates that row instead of inserting.

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

### Suggested conventions

`phase` doesn't enforce any of this, but a fixed scheme makes actions easy to find without knowing them:

* **One class per model, named `<Model>Transitions`**, with the full model name, in `transitions/<model>.py` of the
  model's app — `OrderTransitions` in `shop/transitions/order.py`. The class is only a namespace for static methods.
  No abbreviations, so class and file are found by the model name alone.
* **An action is named after the business action, as a verb** — `pay`, `ship`, `cancel`. Mostly that matches the target
  phase; where it doesn't, the business action wins: a `reject_return()` that moves the order back to `SHIPPED` is
  still named after what the user does.
* **The object is passed as a keyword named after the model** — `order=`, not `obj=` or `instance=`. Further inputs are
  keyword-only as well.
* **Conditions beyond the table are checked in the action, before `move()`**, and raise a `PhaseGuardError` subclass,
  see "Refused actions".
* **Callers use the action, never `move()` directly**, and don't check the phase themselves.
