from unittest import mock

from django.core import checks
from django.db import models
from django.test import SimpleTestCase
from django.test.utils import isolate_apps

from phase.checks import check_phase_fields
from phase.fields import PhaseField
from phase.mixins.phase_guard import PhaseGuardMixin


class CheckPhaseFieldsTest(SimpleTestCase):
    def test_check_is_registered(self):
        self.assertIn(check_phase_fields, checks.registry.registry.get_checks())

    def test_installed_models_pass(self):
        self.assertEqual(check_phase_fields(), [])

    @isolate_apps("testapp")
    def test_phase_field_without_mixin(self):
        class Parcel(models.Model):  # noqa: DJ008
            status = PhaseField(max_length=10, transitions={})

            class Meta:
                app_label = "testapp"

        with mock.patch("phase.checks.apps.get_models", return_value=[Parcel]):
            errors = check_phase_fields()

        self.assertEqual([error.id for error in errors], ["phase.E001"])
        self.assertIs(errors[0].obj, Parcel)

    @isolate_apps("testapp")
    def test_two_phase_fields(self):
        class Parcel(PhaseGuardMixin, models.Model):  # noqa: DJ008
            status = PhaseField(max_length=10, transitions={})
            payment_status = PhaseField(max_length=10, transitions={})

            class Meta:
                app_label = "testapp"

        with mock.patch("phase.checks.apps.get_models", return_value=[Parcel]):
            errors = check_phase_fields()

        self.assertEqual([error.id for error in errors], ["phase.E002"])
        self.assertIs(errors[0].obj, Parcel)

    @isolate_apps("testapp")
    def test_model_without_phase_field(self):
        class Parcel(models.Model):  # noqa: DJ008
            status = models.CharField(max_length=10)

            class Meta:
                app_label = "testapp"

        with mock.patch("phase.checks.apps.get_models", return_value=[Parcel]):
            self.assertEqual(check_phase_fields(), [])
