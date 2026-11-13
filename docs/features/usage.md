# Usage

## The field

A model whose status may only change along fixed transitions declares it as a `PhaseField`. The field owns the
transition table; `phase.transitions.move()` and, for a whole queryset, `move_many()` are the only ways of
changing it.

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
  after that only `move()` and `move_many()` change it. Factories keep working, because they pass the phase to the
  constructor.
* **Never editable.** Admin and model forms leave the field out; passing `editable=True` raises
  `EditablePhaseFieldError`. List it in an admin's `readonly_fields` to show it on the detail page.
* Migrations see a plain `CharField`, so no migration depends on `phase`. Changing the transition table needs no
  migration.
* **`null=True` is refused** (system check `phase.E004`). "No value" is not a phase: a refused transition reports a row
  that doesn't exist as `source=None`, and a lifecycle that starts in "nothing" hides its first state from the
  transition table. Give that state a phase of its own, e.g. `OPEN`.
* **One `PhaseField` per model** (system check `phase.E002`). A model has one lifecycle; a second one usually belongs on
  its own model. This is what lets `move()` find the field without being told.
* **The field lives in the model's own table** (system check `phase.E003`). A model must not inherit its `PhaseField`
  from a concrete parent model: Django would split the `UPDATE` of `move()` in two, and two concurrent transitions
  could both succeed. An abstract parent is fine.

## Phases stored as numbers

A status kept as `IntegerChoices` uses `IntegerPhaseField`. It behaves like `PhaseField` in every respect; only the
column differs.

```python
from phase.fields import IntegerPhaseField


class Invoice(PhaseGuardMixin, models.Model):
    class Status(models.IntegerChoices):
        DRAFT = 1, "Draft"
        SENT = 2, "Sent"
        PAID = 3, "Paid"

    status = IntegerPhaseField(
        choices=Status.choices,
        default=Status.DRAFT,
        transitions={
            Status.DRAFT: (Status.SENT,),
            Status.SENT: (Status.PAID,),
        },
    )
```

* **The column is always a `PositiveSmallIntegerField`**, and migrations see exactly that. A lifecycle has a handful of
  phases, so there is one integer field instead of one per Django integer type: a negative phase or one beyond 32767
  has no meaning, and a single type keeps the choice out of every model.
* A model that already stores its status in a `PositiveSmallIntegerField` switches without touching the data. A status
  in another integer type needs a migration to `PositiveSmallIntegerField` first.
* **Messages name a phase by its choice label**, followed by the stored value: `cannot change from 'Draft' (1) to
  'Paid' (3)`. A number alone doesn't tell what it means. A string phase names itself and is shown as stored. The
  exception attributes (`source`, `target`, `phases`) always hold the stored values.

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
* **The model's own `save()` isn't called.** Whatever a `save()` override does — computing fields, validating,
  triggering side effects — doesn't happen on a transition. Put logic that belongs to every write into a `pre_save` or
  `post_save` receiver, and logic that belongs to one transition into its action.
* A successful `move()` costs two queries: the `UPDATE` and a `SELECT` that reloads the written fields.
* The row is addressed through the model's base manager on the instance's database, so a filtering default manager
  doesn't hide it.
* `can_transition(obj=…, to=…)` and `targets(obj=…)` answer read-only questions. They only know the table, not further
  conditions your code checks.

## Moving many rows

A straight bulk change without logic per row — a nightly job closing all expired orders, an admin action on a
selection — uses `move_many()`:

```python
from django.utils import timezone

from phase.transitions import move_many

now = timezone.now()
moved = move_many(
    queryset=Order.objects.filter(expires_at__lt=now),
    source=Order.Status.OPEN,
    to=Order.Status.CANCELLED,
    cancelled_at=now,
)
```

* `move_many(queryset=…, source=…, to=…, **fields)` checks `source → to` against the table and raises
  `IllegalPhaseTransitionError` before touching the database. The exception's `pk` is `None`.
* It writes with **one** conditional `UPDATE`, which also writes `fields` and stamps the model's `auto_now` fields.
  The `UPDATE` selects the rows of the queryset by primary key and checks the source phase on each written row itself:
  `UPDATE … WHERE <field> = <source> AND pk IN (SELECT pk FROM <queryset>)`. Passing the phase field among `fields`
  raises `ProtectedPhaseFieldError`.
* On MySQL and MariaDB, which refuse a subquery on the table being updated, it first reads the primary keys and then
  runs the `UPDATE` with them: two queries instead of one, still race-safe.
* **Returns the number of rows moved.** Rows of the queryset that aren't in `source` — because they never were or
  because someone moved them in the meantime — are skipped, not an error. Compare the count if it matters.
* It is race-safe for the same reason as `move()`: the condition on the source phase is part of the `UPDATE`. This
  also holds for a queryset that filters across relations (`filter(customer__country="DE")`), where a plain
  `QuerySet.update()` would move the condition into a subquery.
* **No transaction of its own.** A single `UPDATE` is atomic by itself; inside the caller's `transaction.atomic()` it
  commits or rolls back with everything else there.
* **A sliced queryset is refused** with `TypeError` before anything is written, as `QuerySet.update()` does. Ordering
  has no effect.
* **One source per call.** The caller names the transition it means; moving rows from several phases to one target is
  one call per source.
* **No signals.** Like `QuerySet.update()`, it sends no `pre_save` or `post_save`, and the model's `save()` isn't
  called. Logic in receivers doesn't run. Where it must, or where each row needs its own logic (calls to other
  systems, failures isolated per row), loop over the rows and call `move()` for each.
* **Instances in memory aren't updated.** An instance of a moved row keeps its old phase; a later `save()` on it is
  refused with `StalePhaseError`. Reload it to go on.
* The rows are written on the queryset's database. Which rows are moved is decided by the queryset, including the
  filter of the manager that built it.

## The mixin

Every model with a phase field inherits `PhaseGuardMixin` (system check `phase.E001`), listed before `models.Model`:

* `refresh_from_db()` may overwrite the protected field, because it writes what the database holds.
* **Every `save()` is guarded against a stale phase.** Inside a transaction it locks the row with `select_for_update`
  and refuses the save with `StalePhaseError` if the phase in the database differs from the instance. This also covers
  saves that don't touch the phase (`save(update_fields=["note"])`), which would otherwise silently undo a concurrent
  transition.
* A **new instance with an explicit primary key** is checked the same way when a row with that key exists, because
  Django then updates that row instead of inserting.
* **A `save()` override on the model has to call `super().save()`**, as any override should. The guard lives in the
  mixin's `save()`; an override that writes on its own way around it saves unguarded. An override also can't assign
  the phase: that raises `ProtectedPhaseFieldError` like any direct assignment.

### What the guard costs

A guarded save runs three statements on top of its `UPDATE`: the `SELECT … FOR UPDATE` and the transaction around it.
Inside a transaction that is `SAVEPOINT` and `RELEASE SAVEPOINT`, in autocommit `BEGIN` and `COMMIT`. Tests that count
queries (`assertNumQueries`) see all three, because a `TestCase` always runs in a transaction.

Only the save of an existing instance with a loaded phase is guarded. An `INSERT` (`create()`, a new instance without a
primary key, `force_insert=True`) and a save with empty `update_fields` cost nothing extra.

## Limits

* `QuerySet.update()` and `bulk_update()` bypass both the field and the mixin. Use `move_many()` for bulk transitions;
  data migrations and other bulk writes have to respect the table by hand.
* A model can have only one phase field, it can't be inherited from a concrete parent model, and it can't be
  nullable.
* Phases are strings (`PhaseField`) or small positive integers (`IntegerPhaseField`). Other column types aren't
  supported.
* An instance loaded without its phase (`defer("status")`, `only("note")`) is saved unguarded, because there is no
  loaded phase to compare with the database. Load the phase wherever you save.

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
