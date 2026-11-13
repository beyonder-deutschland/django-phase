# Motivation

## The problem

A status field that is assigned directly and saved keeps producing the same class of bugs:

* transitions out of final states, e.g. a closed request accepted again,
* side effects in the wrong order, e.g. an email sent for a transition that is rolled back afterwards,
* concurrent requests overwriting each other's status: both read `open`, both write their target, the last one wins.

Every fix plugs a single code path. What is missing is one place per model that says which transitions are allowed, and
a way of writing the status that rejects everything else — including the loser of a race.

## Goals

* **Concurrency:** two requests from the same phase must not both succeed
* **No way around the table:** a direct assignment to the phase must fail, not just be discouraged
* **Logic out of the model:** the model holds data and the transition table; emails, calls to other systems and work on
  other models belong elsewhere
* **One readable table per model**, not rules spread over decorators
* **Side effects only after commit** (`transaction.on_commit`), so a refused transition triggers nothing
* **No overridden private Django method**, so a Django upgrade can't break it unnoticed
* **No permanent dependency in migrations**

## Why not an existing library?

### django-fsm 5.x

Licensed under AGPL-3.0 since 5.0, which rules it out for many projects. Otherwise as django-fsm-2.

### django-fsm-2

The MIT fork of django-fsm, maintained under django-commons. It solves a lot: `protected=True` blocks direct
assignment, `ConcurrentTransitionMixin` guards `save()`, and diagrams and admin integration come for free. But:

* Transitions are decorated methods on the model. Keeping side effects out of them needs many extra methods and
  helpers; the logic stays in the model.
* A transition only changes the state in memory. Persisting it needs a separate `save()` of the whole object, and a
  forgotten `save()` writes nothing.
* It overrides the private `Model._do_update`, whose signature changed in Django 6.
* The migration to `FSMField` imports `django_fsm` permanently.
* Its transition exception can't be pickled, so under the parallel test runner an unexpected one shows up as a
  pickling error instead of the real failure.

### Viewflow `fsm`

The flow class can live outside the model, but it ships with django-fsm 5.x under AGPL, its admin integrations are part
of Viewflow Pro, and transitions still change state in memory and rely on `save()`.

### python-statemachine

MIT, maintained, with a readable declarative definition and diagrams. But it works on in-memory state only: no
protection against concurrent requests and none against direct assignment. Callbacks are resolved by string name,
invisible to type checkers and linters. It would cover the easy part, the table, and leave the hard part, persistence,
to you.

## What django-phase does instead

* The table lives on the field, the phase changes only through `move()`, and `move()` is one conditional `UPDATE`. An
  illegal transition and a lost race fail the same way, before anything is saved or sent.
* The model shrinks to data plus table; the whole lifecycle of a model is readable in one module of actions.
* No private Django method is overridden, and no migration imports `phase`. The field's descriptor relies on where
  Django assigns field values; the test suite pins those places for every supported Django version.

## The trade-offs

* You own edge cases a large library has already met in many projects. The ones known so far — deferred fields,
  `refresh_from_db()`, `full_clean()`, `db_default`, pickling of the exceptions — are covered by tests.
* `QuerySet.update()` and `bulk_update()` bypass field and mixin; data migrations and bulk writes have to respect the
  table by hand.
* Every save of an existing instance costs one extra `SELECT … FOR UPDATE`.
* A model can have only one `PhaseField`, and none inherited from a concrete parent model.
* An instance loaded without its phase (`defer()`, `only()`) is saved unguarded.
* No diagrams, no admin integration.
