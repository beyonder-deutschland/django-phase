# Scope

What `phase` deliberately leaves out, and why. Some of it doesn't belong into the package at all; some of it may come
later, once projects using the package show what it has to look like.

## Not part of the package

### Derived states

A status computed from other data — from the state of related objects, from timestamps, as a `GeneratedField` or as an
annotation — has no transitions. It is recalculated, not moved, and nobody may assign it anyway. A transition table for
it would have to allow every state to follow every other, and would protect nothing. Keep such a status out of a
`PhaseField`.

### States spread over several fields

A lifecycle held in a combination of flags, nullable fields and timestamps (`is_verified`, `verified_at`,
`session_id`, …) can't be guarded column by column. `phase` covers a lifecycle stored in exactly one field. To use it,
first merge the flags into one status field with an explicit phase for every combination that matters, including the
initial one — a phase field is never nullable (system check `phase.E004`).

### History of transitions

`phase` doesn't store which transitions happened. `move()` sends the usual model signals, so audit-log packages record
transitions as they record other saves, see "Working with other parts of Django". `phase_moved` and
`phase_moved_many` carry the source and the target phase, so a history model of the project's own takes a receiver of
a few lines, see "Signals" in Usage.

### Switching off the guard

`PhaseGuardMixin` checks every save of an existing instance, also one whose `update_fields` leave out the phase. There
is no setting to skip the check, for a model or for saves that don't write the phase.

The fields `move()` writes together with the phase (`paid_at`, `cancelled_by`, …) belong to the transition. A stale
instance saving one of them would overwrite what the transition wrote, even though the phase column stays untouched,
and the package can't tell those fields apart from unrelated ones like a note. The check costs little: the `UPDATE` of
the save takes the same row lock anyway, the `SELECT … FOR UPDATE` only takes it one statement earlier. What it adds
is one query per save inside a transaction, three in autocommit, see "What the guard costs" in Usage.

### Phase fields inherited through multi-table inheritance

A model must not inherit its `PhaseField` from a concrete parent model (system check `phase.E003`):

```python
class Parcel(PhaseGuardMixin, models.Model):
    status = PhaseField(...)


class ExpressParcel(Parcel):  # refused: status lives in the table of Parcel
    courier = models.CharField(max_length=20)
```

For a field of the parent's table, Django splits `filter(pk=…, status=<source>).update(…)` into a `SELECT` of the
primary keys and an `UPDATE` of the parent's table **without** the condition on the phase. Two concurrent transitions
could then both succeed, which is exactly what `move()` exists to prevent. Writing each table with its own conditional
`UPDATE` would make every transition of such a model cost two statements and a lock, and would put a second write path
into the core of the package for a layout that is easy to avoid.

There are three ways to give such a model a lifecycle.

**Replace the inheritance by an explicit one-to-one relation.** The child table of a multi-table inheritance already
is a table whose primary key is a one-to-one relation to the parent's table. Declaring that relation instead of
inheriting keeps the schema and the data, and the phase stays on the parent, where it is moved race-safely:

```python
class Parcel(PhaseGuardMixin, models.Model):
    status = PhaseField(...)

    objects = PhaseManager()


class ExpressParcel(models.Model):
    parcel = models.OneToOneField(Parcel, primary_key=True, on_delete=models.CASCADE, db_column="parcel_ptr_id")
    courier = models.CharField(max_length=20)


move(obj=express_parcel.parcel, to=Parcel.Status.SENT)
```

* `Parcel.objects.all()` still lists every parcel, `parcel.expressparcel` still leads from a parcel to its child, and
  the column `parcel_ptr_id` keeps its name.
* Fields of the parent are reached through the relation: `express_parcel.parcel.status`,
  `ExpressParcel.objects.filter(parcel__status=…)`. Creating a child creates the parent first.
* **Deleting changes direction.** With inheritance, deleting an `ExpressParcel` also deletes its `Parcel` row; with the
  relation it doesn't. Delete the parent where both have to go.
* `makemigrations` doesn't notice that the base class changed and writes an `AlterField` that fails. Replace it with a
  migration that only changes the state, because the table already has the right shape:

```python
migrations.SeparateDatabaseAndState(
    database_operations=[],
    state_operations=[
        migrations.DeleteModel(name="ExpressParcel"),
        migrations.CreateModel(
            name="ExpressParcel",
            fields=[
                (
                    "parcel",
                    models.OneToOneField(
                        db_column="parcel_ptr_id",
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        serialize=False,
                        to="shop.parcel",
                    ),
                ),
                ("courier", models.CharField(max_length=20)),
            ],
        ),
    ],
)
```

  Afterwards `makemigrations --check` reports no changes. Foreign keys to `ExpressParcel` keep working, since its
  table and primary key stay the same.

**Make the parent abstract.** Every child gets its own table with all fields, the phase included. This fits where the
children are used separately anyway. There is no common table any more: no query over all parcels, no foreign key to
`Parcel`, and the migration has to copy the parent's rows into the children's tables, whose primary keys may collide.
It is the most expensive way for an existing model.

**Move the phase into the children.** Where only some children have a lifecycle, each of them declares its own
`PhaseField`, possibly with its own transition table. The parent keeps the common data. There is no common phase
across all parcels then.

### API frameworks

`phase` ships no code for Django REST framework or any other API framework: no exception handler, no serializer
fields, no viewsets, no endpoints for transitions. Answering a refused action is a few lines that follow the error
format of the project's API, and an optional dependency on an API framework would tie the releases and the test matrix
of `phase` to it. "Refused actions" shows an exception handler for Django REST framework to copy, "Working with other
parts of Django" how a serializer treats a phase field.

### Diagrams

The transition table is a plain dict on the field and can be rendered by any tool that reads it. `phase` ships none.

## Not yet in the package

These are open on purpose. Each one is a trade-off that is better decided with experience from projects using the
package than up front.

### Admin integration

The admin leaves the phase field out of its forms. Offering transitions there is a matter of the project's actions,
which know conditions and side effects the package doesn't; an example of an admin action built on them is in
"Working with other parts of Django". A generic integration, e.g. one admin action per transition, may follow once it
is clear what projects need beyond that example.
