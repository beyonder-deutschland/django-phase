# Usage

## The field

A model whose status may only change along fixed transitions declares it as a `PhaseField`. The field owns the
transition table; `phase.transitions.move()` and, for a whole queryset, `move_many()` are the ways of changing it.
`force_move()` sets a phase outside the table, for data repairs.

```python
from django.db import models

from phase.fields import PhaseField
from phase.managers import PhaseManager
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

    objects = PhaseManager()
```

* A phase missing from `transitions` is final. Targets are tuples; a single target needs the trailing comma,
  `(Status.SHIPPED,)`. The field rejects anything else with `InvalidTransitionTableError`, because `(Status.SHIPPED)`
  is a plain string and `in` would match substrings.
* **Direct assignment raises** `ProtectedPhaseFieldError`. The value is set once when the instance is built or loaded;
  after that only `move()`, `move_many()` and `force_move()` change it. Factories keep working, because they pass the phase to the
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
  back as stored values. The model's `GeneratedField`s are refreshed as well, because the database may have recomputed
  them from the new phase.
* On failure the instance stays as it was. Its phase no longer matches the database, so a later `save()` is refused
  with `StalePhaseError` instead of overwriting what the winner of the race wrote. Reload it to go on. The exception's
  `source` is the phase in the database, or `None` if the row doesn't exist (anymore).
* **Signals** are sent as for `obj.save(update_fields=[<phase>, *fields, *<auto_now fields>])`: `pre_save` sees the new
  values on the instance and may still change the written fields (not the phase), `post_save` with `created=False`
  follows a successful `UPDATE` and sees the stored values. A refused transition sends no `post_save`; one that loses a
  race has already sent `pre_save`, as `save()` does when the write fails.
* **`phase_moved`** follows `post_save` and carries what the model signals don't: the phase the instance came from. See
  "Signals" below.
* **The model's own `save()` isn't called.** Whatever a `save()` override does — computing fields, validating,
  triggering side effects — doesn't happen on a transition. Put logic that belongs to every write into a `pre_save` or
  `post_save` receiver, and logic that belongs to one transition into its action.
* **In autocommit a transaction spans the write and the signals**, as for a guarded `save()`: a receiver of `pre_save`,
  `post_save` or `phase_moved` that raises rolls the transition back, and the instance stays as it was. Inside the
  caller's transaction nothing wraps them; the error leaves that transaction as a failing receiver of `save()` would.
* A successful `move()` costs two queries: the `UPDATE` and a `SELECT` that reloads the written and the generated
  fields. In autocommit the `BEGIN` and `COMMIT` of the transaction around them come on top.
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
* **No transaction of its own** while nobody listens to `phase_moved_many`. A single `UPDATE` is atomic by itself;
  inside the caller's `transaction.atomic()` it commits or rolls back with everything else there.
* **A sliced queryset is refused** with `TypeError` before anything is written, as `QuerySet.update()` does. Ordering
  has no effect.
* **One source per call.** The caller names the transition it means; moving rows from several phases to one target is
  one call per source.
* **No model signals.** Like `QuerySet.update()`, it sends no `pre_save` or `post_save`, and the model's `save()` isn't
  called. Logic in those receivers doesn't run. Where it must, or where each row needs its own logic (calls to other
  systems, failures isolated per row), loop over the rows and call `move()` for each. What it sends instead is
  `phase_moved_many`, once per call, see "Signals" below.
* **Instances in memory aren't updated.** An instance of a moved row keeps its old phase; a later `save()` on it is
  refused with `StalePhaseError`. Reload it to go on.
* The rows are written on the queryset's database. Which rows are moved is decided by the queryset, including the
  filter of the manager that built it.

### Rows with different targets

A job that decides the target per row — cancel the unpaid expired orders, mark the paid ones as paid — runs one
`move_many()` per pair of source and target. Express each decision as a filter where you can:

```python
from django.db import transaction
from django.utils import timezone

from phase.transitions import move_many

now = timezone.now()
expired = Order.objects.filter(expires_at__lt=now)
with transaction.atomic():
    move_many(queryset=expired.filter(paid_at__isnull=True), source=Order.Status.OPEN, to=Order.Status.CANCELLED)
    move_many(queryset=expired.filter(paid_at__isnull=False), source=Order.Status.OPEN, to=Order.Status.PAID)
```

Where the target is computed in Python, collect the primary keys per pair and pass each group as
`queryset=Order.objects.filter(pk__in=pks)`. Either way every call stays race-safe on its own: a row that another
request or an earlier call has moved out of `source` is skipped. The surrounding `transaction.atomic()` makes the
calls succeed or fail together. The number of queries grows with the number of pairs, not with the number of rows.

## Forcing a phase

Support corrections and data repairs sometimes have to put an instance into a phase the table doesn't allow from where
it is. `force_move()` is the explicit, searchable way to do that:

```python
from django.utils import timezone

from phase.transitions import force_move

force_move(obj=order, to=Order.Status.OPEN, reason="Support ticket #123", reopened_at=timezone.now())
```

* **It ignores the transition table, nothing else.** It writes like `move()`: phase, `fields` and the `auto_now`
  fields in one conditional `UPDATE` on the phase the instance holds, and refreshes the instance afterwards.
* **A stale instance is refused** with `StalePhaseError`: if the phase in the database is no longer the one the
  instance holds, or the row doesn't exist, nothing is written and the instance stays as it was.
* **The target has to be a different phase** and, for a field with `choices`, one of them. Forcing an instance into
  the phase it already holds, or into a value that isn't a phase (`"shiped"`), raises `IllegalPhaseTransitionError`
  before anything is written or sent. An admin action over a selection skips such rows instead of reporting them as
  moved.
* **It sends the signals of a transition**: `pre_save` and `post_save` like `move()`, so audit logs record it, and
  `phase_moved` with `forced=True` and the `reason`.
* **`reason` is required** and only travels to the receivers; `phase` stores nothing. Record it in a `phase_moved`
  receiver or your audit log.
* There is no forced variant of `move_many()`. Repairs are deliberate and usually few; loop and call `force_move()`.

Prefer a correction edge in the table where a correction is a regular business case, e.g. "reopen a cancelled order".
`force_move()` is for the cases that must not become regular. Don't use it for statuses another system owns: those
aren't phases, see "Scope". An admin action built on it is in "Working with other parts of Django".

## Signals

`phase.signals` has one signal per way of moving. Both are sent only for rows that actually changed: never for a
transition missing from the table, never for one that lost a race.

### `phase_moved`

`move()` and `force_move()` send it after a successful `UPDATE`, right after `post_save`, with these arguments:

* `sender`: the model class, `instance`: the moved instance with the stored values
* `field`: the phase field
* `source`, `target`: the phase the instance came from and the one it is in now, as stored values
* `forced`: `True` for `force_move()`, which ignored the transition table, else `False`
* `reason`: the reason given to `force_move()`, else `None`
* `using`: the database alias

A receiver that records transitions or reacts to one edge reads the source phase from the signal instead of reloading
the row in `pre_save`:

```python
from django.dispatch import receiver

from phase.signals import phase_moved


@receiver(phase_moved, sender=Order)
def record_transition(sender, instance, source, target, **kwargs):
    OrderStatusChange.objects.create(order=instance, source=source, target=target)
```

### `phase_moved_many`

`move_many()` sends it once per call, if at least one row moved, with these arguments:

* `sender`: the model of the queryset
* `field`: the phase field
* `pks`: the primary keys of the moved rows, as a list
* `source`, `target`, `using`: as for `phase_moved`

An `UPDATE` reports how many rows it changed, not which ones. So **as soon as a receiver is connected for the model**,
`move_many()` writes differently: inside a transaction it locks the rows of the queryset that are in `source` with
`SELECT … FOR UPDATE`, reads their keys and updates exactly those rows. The lock keeps them in `source`, so every locked
row is moved and `pks` is exact. Without a receiver, `move_many()` writes with the single `UPDATE` described above.

What a receiver costs:

* one query more, the `SELECT … FOR UPDATE`, plus the transaction (a savepoint inside the caller's transaction)
* row locks on the moved rows until the surrounding transaction ends; rows of tables the queryset joins aren't locked
* the keys in memory; the `UPDATE` runs in batches the database accepts as query parameters (a few hundred rows per batch on SQLite)

The signal is sent inside that transaction, so a receiver that writes, e.g. history rows with `bulk_create()`, commits or
rolls back together with the move, and a receiver that raises rolls the move back.

```python
from django.dispatch import receiver

from phase.signals import phase_moved_many


@receiver(phase_moved_many, sender=Order)
def record_transitions(sender, pks, source, target, **kwargs):
    OrderStatusChange.objects.bulk_create(OrderStatusChange(order_id=pk, source=source, target=target) for pk in pks)
```

Receivers are matched by `sender` as for Django's model signals: one connected for the concrete model doesn't receive
a `move_many()` on a queryset of a proxy model. A receiver connected without `sender` listens to every model, so it
switches every `move_many()` in the project to the locked way of writing. Connect receivers for the models they are
meant for.

## The mixin

Every model with a phase field inherits `PhaseGuardMixin` (system check `phase.E001`), listed before `models.Model`:

* `refresh_from_db()` may overwrite the protected field, because it writes what the database holds.
* **Every `save()` is guarded against a stale phase.** It locks the row with `select_for_update` and refuses the save
  with `StalePhaseError` if the phase in the database differs from the instance. This also covers saves that don't
  touch the phase (`save(update_fields=["note"])`), which would otherwise silently undo a concurrent transition.
* **Inside a transaction the guard adds no savepoint.** It runs its `SELECT` in the caller's transaction, which keeps
  the row lock until it ends. A caught `StalePhaseError` leaves the transaction usable. An error in the save itself
  leaves it as the save of a plain model does: a database error such as `IntegrityError` marks the transaction for
  rollback, so a caller that wants to catch it and go on wraps the save in its own `transaction.atomic()`.
* **In autocommit the guard opens a transaction** around the check and the write. It is rolled back when the save is
  refused or fails, including a failing `post_save` receiver.
* A **new instance with an explicit primary key** is checked the same way when a row with that key exists, because
  Django then updates that row instead of inserting.
* **A `save()` override on the model has to call `super().save()`**, as any override should. The guard lives in the
  mixin's `save()`; an override that writes on its own way around it saves unguarded. An override also can't assign
  the phase: that raises `ProtectedPhaseFieldError` like any direct assignment.

### What the guard costs

Inside a transaction a guarded save runs one statement on top of its `UPDATE`: the `SELECT … FOR UPDATE`. That is the
case in a request with `ATOMIC_REQUESTS`, inside `transaction.atomic()` and in a `TestCase`, so tests that count
queries (`assertNumQueries`) see one more query per guarded save.

In autocommit it runs three: the `SELECT … FOR UPDATE` and the `BEGIN` and `COMMIT` of the transaction around it.

The lock taken by the `SELECT` lasts until the surrounding transaction ends, also when the save was refused.

Only the save of an existing instance with a loaded phase is guarded. An `INSERT` (`create()`, a new instance without a
primary key, `force_insert=True`) and a save with empty `update_fields` cost nothing extra.

## Protected managers

`QuerySet.update()`, `bulk_update()` and `bulk_create(update_conflicts=True)` write the phase column without passing
the field, so they would bypass the transition table and the guard. A manager built on `PhaseQuerySet` refuses them:

```python
from phase.managers import PhaseManager


class Order(PhaseGuardMixin, models.Model):
    status = PhaseField(...)

    objects = PhaseManager()
```

* `update()` raises `ProtectedPhaseFieldError` when its keywords contain the phase field, `bulk_update()` when its
  `fields` do, and `bulk_create(update_conflicts=True)` when its `update_fields` do. Writes of other fields pass, and
  `bulk_create()` without `update_conflicts` inserts rows in any phase, see "Bulk creation and imports" in "Working with
  other parts of Django".
* Related managers (`customer.order_set.update(…)`) use the class of the default manager and are protected with it.
* `move()`, `move_many()` and `force_move()` keep working, also when the model's base manager is protected
  (`Meta.base_manager_name`): they let exactly their own `UPDATE` through.
* `PhaseQuerySet.as_manager()` works as well. A project with querysets of its own (custom managers, packages such as
  django-treebeard) puts `PhaseQuerySetMixin` in front of its queryset:

```python
from django.utils import timezone

from phase.managers import PhaseQuerySetMixin


class OrderQuerySet(PhaseQuerySetMixin, models.QuerySet):
    def expired(self):
        return self.filter(expires_at__lt=timezone.now())


class Order(PhaseGuardMixin, models.Model):
    objects = OrderQuerySet.as_manager()
```

* **Data migrations are unaffected.** `PhaseManager` isn't used in migrations (`use_in_migrations` is `False`), and
  the historical model sees a plain `CharField`, so a data migration writes phases like any other column and has to
  respect the table by hand.

**System check `phase.W001`** warns about every manager of a phase model that isn't built on `PhaseQuerySetMixin`,
including the automatic `objects` of a model that declares none and a plain second manager next to a protected one. A
proxy model is checked for the managers it declares itself. The base manager isn't checked, because Django uses it
internally; a model only declares it with `Meta.base_manager_name`. A project that deliberately allows bulk writes to
the phase silences the warning with `SILENCED_SYSTEM_CHECKS = ["phase.W001"]`.

When converting an existing model, protecting its managers turns every bulk write of the phase into an exception in the
test suite. Replace each one with `move_many()` or, for repairs, `force_move()`.

## Limits

* With a plain manager (`phase.W001` silenced), `QuerySet.update()`, `bulk_update()` and
  `bulk_create(update_conflicts=True)` bypass both the field and the mixin. So does the plain base manager,
  `Order._base_manager`, which isn't protected unless the model names a protected one in `Meta.base_manager_name`.
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
