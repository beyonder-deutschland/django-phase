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
