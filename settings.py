SECRET_KEY = "not-a-secret-only-for-tests"

INSTALLED_APPS = (
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "phase",
    "testapp",
)

DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": "db.sqlite",
    }
}

USE_TZ = True
TIME_ZONE = "UTC"
