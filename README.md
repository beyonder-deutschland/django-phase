[![PyPI release](https://img.shields.io/pypi/v/django-phase.svg)](https://pypi.org/project/django-phase/)
[![Downloads](https://static.pepy.tech/badge/django-phase)](https://pepy.tech/project/django-phase)
[![Coverage](https://img.shields.io/badge/Coverage-100.0%25-success)](https://github.com/beyonder-deutschland/django-phase/actions?workflow=CI)
[![Linting](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Coding Style](https://img.shields.io/badge/code%20style-Ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Documentation Status](https://readthedocs.org/projects/django-phase/badge/?version=latest)](https://django-phase.readthedocs.io/en/latest/?badge=latest)

Race-safe state machines for Django models: a protected `PhaseField`, transitions as one conditional `UPDATE`, and
guards that tell humans and machines why an action was refused.

[PyPI](https://pypi.org/project/django-phase/) • [GitHub](https://github.com/beyonder-deutschland/django-phase) • [Full documentation](https://django-phase.readthedocs.io/en/latest/index.html)

Creator & Maintainer: [Beyonder Deutschland](https://beyonder.de/)

## Features

* Declare the allowed transitions once, as a table on the field
* Assigning the phase directly raises; only `move()` changes it
* `move()` writes phase and further fields in **one** conditional `UPDATE`, so of two concurrent transitions from the
  same phase exactly one succeeds
* Every `save()` is guarded against a stale phase, so it can't silently undo a concurrent transition
* Phases as strings (`PhaseField`) or numbers (`IntegerPhaseField`); migrations see a plain Django field and never
  import `phase`
* System checks catch a missing mixin, a second phase field, a nullable one or one inherited from a concrete parent
  model
* `PhaseGuardError` gives refused actions a stable `code` for machines and a `detail` for humans
* Overrides no private Django method

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

## Installation

- Install the package via pip:

  `pip install django_phase`

  or via uv:

  `uv add django_phase`

- Add module to `INSTALLED_APPS` within the main django `settings.py`:

```python
INSTALLED_APPS = (
    # ...
    "phase",
)
```

## Releasing a new version

Releases are fully automated. Push a version tag and the pipeline will build, sign with
[Sigstore](https://www.sigstore.dev/), publish to PyPI via
[Trusted Publishing](https://docs.pypi.org/trusted-publishers/), and create a GitHub Release —
no API tokens needed.

```bash
git tag v<version>          # e.g. git tag v1.2.3
git push origin v<version>
```

Tags **must** start with `v`. Tags without the prefix won't trigger the pipeline.

### First-time setup

Before the pipeline can run for the first time, an admin must:

1. **Create GitHub Environment `pypi`**
   - Go to *Settings → Environments → New environment*, name it exactly `pypi`
   - Under *Deployment branches and tags*, add a tag rule with pattern `v*`
   - Optionally add required reviewers for a manual approval gate

2. **Configure PyPI Trusted Publisher**
   - Go to *PyPI → Project settings → Publishing → Add a new publisher*
   - Fill in: Owner `beyonder-deutschland`, Repository `django-phase`,
     Workflow `release.yml`, Environment `pypi`

### Publish to ReadTheDocs.io

- Fetch the latest changes in GitHub mirror and push them
- Trigger new build at ReadTheDocs.io (follow instructions in admin panel at RTD) if the GitHub webhook is not yet set
  up.

### Maintenance

Please note that this package supports the [ambient-package-update](https://pypi.org/project/ambient-package-update/).
So you don't have to worry about the maintenance of this package. This updater is rendering all important
configuration and setup files. It works similar to well-known updaters like `pyupgrade` or `django-upgrade`.

To run an update, refer to the [documentation page](https://pypi.org/project/ambient-package-update/)
of the "ambient-package-update".
