# Setup

## Installation

- Install the package via pip: `pip install django-phase`
- Add the module to `INSTALLED_APPS` within the main Django `settings.py`, so its system checks are registered:

```python
INSTALLED_APPS = (
    # ...
    "phase",
)
```

`phase` has no models and no migrations.
