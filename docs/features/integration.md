# Working with other parts of Django

How the protected field and `move()` behave towards the parts of a project that read or write models besides your own
code.

## Audit logs and history

`move()` sends `pre_save` and `post_save` like `obj.save(update_fields=[<phase>, *fields, *<auto_now fields>])`, so
packages built on these signals record a transition like any other save:

* **django-auditlog** computes its diff in `pre_save`, reading the old row from the database and comparing it with the
  instance. `move()` sends `pre_save` with the new values on the instance and the old ones still in the database, so
  the entry shows the phase change. `update_fields` limits the diff to the written fields. The lookup of the old row is
  one more query per transition, as for every audited save.
* **django-simple-history** writes the historical record in `post_save`. `move()` sends it after reloading the written
  fields, so the record holds the stored values.

`move_many()` sends no signals, so neither package records it. Where every transition has to show up in the audit log,
loop over the rows and call `move()` for each.

A receiver that writes in `pre_save` writes **before** the conditional `UPDATE`. If `move()` then loses a race, the
audit entry for a transition that didn't happen is already in the database, unless a transaction around the move rolls
it back. Call `move()` from an action wrapped in `transaction.atomic()` (see "Actions around a transition" in Usage)
and let `IllegalPhaseTransitionError` leave that block instead of catching it inside.

## Bulk creation and imports

`bulk_create()` builds its instances with the constructor, which sets the phase once, as for any new instance. Rows are
inserted with the phase given, **without a check against the transition table**: an import may create rows in any
phase, including a final one. That is what an import of existing data needs, and it means the import is responsible
for valid values.

`bulk_create(update_conflicts=True, update_fields=[…])` with the phase field among `update_fields` overwrites the phase
of existing rows without a transition and without the guard, like `QuerySet.update()`. Leave the phase field out of
`update_fields` unless the import is meant to overwrite phases.

## `get_or_create()` and `update_or_create()`

* `get_or_create(defaults={"status": …})` passes the phase to the constructor when it creates the row and works as
  expected.
* `update_or_create(defaults={"status": …})` assigns `defaults` to an existing instance, which raises
  `ProtectedPhaseFieldError` unless the value equals the stored phase. Leave the phase out of `defaults` and call the
  action for the transition separately; use `create_defaults` for the phase of a newly created row.

## Django REST framework

A `ModelSerializer` turns a field with `editable=False` into a read-only serializer field, so a phase field is listed in
responses and ignored in requests. Nothing has to be configured.

A serializer field declared by hand for the phase (`status = serializers.IntegerField()`) is writable. Saving such a
serializer assigns the phase to the instance and raises `ProtectedPhaseFieldError`, which surfaces as a server error.
That is intended: a phase taken from a request without passing the transition table is a bug. Change the phase through
an action in the view instead, and map refused actions to HTTP 409 as shown in "Refused actions".

## Django admin

The admin leaves the field out of its forms, because it is never editable. List it in `readonly_fields` to show it on
the detail page.

A `ModelAdmin` that names its fields itself has to do the same: a phase field in `fields` or `fieldsets` but not in
`readonly_fields` makes the admin raise `FieldError` when it builds the form, because a form can't contain a
non-editable field. Converting a model whose status the admin could edit means moving the field to `readonly_fields`.

To change the phase in the admin, offer the business actions as admin actions. Loop over the selection and call the
action for each row, so signals, audit log and conditions beyond the table apply as everywhere else:

```python
from django.contrib import admin, messages

from phase.exceptions import IllegalPhaseTransitionError, PhaseGuardError, StalePhaseError
from shop.models import Order
from shop.transitions.order import OrderTransitions


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    readonly_fields = ("status",)
    actions = ("cancel",)

    @admin.action(description="Cancel selected orders")
    def cancel(self, request, queryset):
        cancelled = 0
        for order in queryset:
            try:
                OrderTransitions.cancel(order=order)
            except PhaseGuardError as error:
                self.message_user(request, f"{order}: {error.detail}", messages.WARNING)
            except (IllegalPhaseTransitionError, StalePhaseError):
                self.message_user(request, f"{order} can't be cancelled in its current status.", messages.WARNING)
            else:
                cancelled += 1
        self.message_user(request, f"{cancelled} orders cancelled.", messages.SUCCESS)
```

`move_many()` fits an admin action only where no signal receiver has to run for the transition, see "Moving many rows"
in Usage.
