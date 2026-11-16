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
transitions as they record other saves, see "Working with other parts of Django".

### Diagrams

The transition table is a plain dict on the field and can be rendered by any tool that reads it. `phase` ships none.

## Not yet in the package

These are open on purpose. Each one is a trade-off that is better decided with experience from projects using the
package than up front.

### Protection against `QuerySet.update()` and `bulk_update()`

Both write the phase column without passing the field, so they bypass the transition table and the guard. A queryset
mixin could refuse any `update()` or `bulk_update()` that writes the phase field, so existing bypasses fail in the test
suite instead of having to be found by review.

Not included yet, because it only works where a project opts in on every manager of the model — many models bring
their own managers and querysets — and because it changes how the package's own bulk writes have to reach the
database. Until then, `move_many()` is the way to change the phase of many rows, and a review rule or lint check keeps
`update(<phase>=…)` and `bulk_update(…, [<phase>])` out of the code.

### Signals for `move_many()`

`move_many()` writes with one `UPDATE` and doesn't know which rows it moved, so it can't send signals per row, and
audit logs don't see it. Sending them would need the moved rows back from the `UPDATE` (`UPDATE … RETURNING`), which
Django's public queryset API doesn't offer. Where signals matter, loop and call `move()`.

### Admin integration

The admin leaves the phase field out of its forms. Offering transitions there is a matter of the project's actions,
which know conditions and side effects the package doesn't; an example of an admin action built on them is in
"Working with other parts of Django". A generic integration, e.g. one admin action per transition, may follow once it
is clear what projects need beyond that example.
