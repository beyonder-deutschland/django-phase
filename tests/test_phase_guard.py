from django.test import TestCase

from phase.exceptions import StalePhaseError
from phase.fields import REFRESHING_FLAG
from phase.transitions import move
from testapp.models import Order, Shipment


class PhaseGuardMixinSaveTest(TestCase):
    def test_new_instance_is_saved(self):
        order = Order(status=Order.Status.PAID)

        order.save()

        self.assertEqual(Order.objects.get(pk=order.pk).status, Order.Status.PAID)

    def test_current_instance_is_saved(self):
        order = Order.objects.create()
        order.note = "gift wrap"

        order.save()

        self.assertEqual(Order.objects.get(pk=order.pk).note, "gift wrap")

    def test_stale_instance_is_refused(self):
        order = Order.objects.create()
        move(obj=Order.objects.get(pk=order.pk), to=Order.Status.CANCELLED)
        order.note = "gift wrap"

        with self.assertRaisesMessage(
            StalePhaseError, f"testapp.Order ID #{order.pk} no longer has status='open' in the database"
        ):
            order.save(update_fields=["note"])

        stored = Order.objects.get(pk=order.pk)
        self.assertEqual(stored.status, Order.Status.CANCELLED)
        self.assertEqual(stored.note, "")

    def test_instance_without_loaded_phase_is_saved(self):
        order = Order.objects.create()
        deferred_order = Order.objects.defer("status").get(pk=order.pk)
        deferred_order.note = "gift wrap"

        deferred_order.save()

        self.assertEqual(Order.objects.get(pk=order.pk).note, "gift wrap")

    def test_save_of_deleted_row_is_refused(self):
        order = Order.objects.create()
        Order.objects.filter(pk=order.pk).delete()

        with self.assertRaises(StalePhaseError):
            order.save()

    def test_skipped_save_is_not_checked(self):
        order = Order.objects.create()
        move(obj=Order.objects.get(pk=order.pk), to=Order.Status.CANCELLED)

        for empty_update_fields in ([], (), set()):
            with self.subTest(update_fields=empty_update_fields):
                order.save(update_fields=empty_update_fields)

        self.assertEqual(Order.objects.get(pk=order.pk).status, Order.Status.CANCELLED)

    def test_save_with_explicit_database(self):
        order = Order.objects.create()
        order.note = "gift wrap"

        order.save(using="default")

        self.assertEqual(Order.objects.get(pk=order.pk).note, "gift wrap")

    def test_save_ignores_default_manager_filter(self):
        shipment = Shipment.objects.create(archived=True)
        shipment.refresh_from_db()

        shipment.save()

        self.assertTrue(Shipment._base_manager.get(pk=shipment.pk).archived)


class PhaseGuardMixinExplicitPrimaryKeyTest(TestCase):
    def test_new_row_is_inserted(self):
        Order(pk=4711, status=Order.Status.PAID).save()

        self.assertEqual(Order.objects.get(pk=4711).status, Order.Status.PAID)

    def test_forced_insert_is_not_checked(self):
        Order(pk=4711, status=Order.Status.PAID).save(force_insert=True)

        self.assertEqual(Order.objects.get(pk=4711).status, Order.Status.PAID)

    def test_existing_row_with_same_phase_is_updated(self):
        order = Order.objects.create()

        Order(pk=order.pk, status=Order.Status.OPEN, note="gift wrap").save()

        self.assertEqual(Order.objects.get(pk=order.pk).note, "gift wrap")

    def test_existing_row_with_other_phase_is_refused(self):
        order = Order.objects.create()

        with self.assertRaises(StalePhaseError):
            Order(pk=order.pk, status=Order.Status.SHIPPED).save()

        self.assertEqual(Order.objects.get(pk=order.pk).status, Order.Status.OPEN)


class PhaseGuardMixinRefreshTest(TestCase):
    def test_refresh_overwrites_phase(self):
        order = Order.objects.create()
        move(obj=Order.objects.get(pk=order.pk), to=Order.Status.PAID)

        order.refresh_from_db()

        self.assertEqual(order.status, Order.Status.PAID)
        self.assertNotIn(REFRESHING_FLAG, order.__dict__)

    def test_failed_refresh_removes_flag(self):
        order = Order.objects.create()
        Order.objects.filter(pk=order.pk).delete()

        with self.assertRaises(Order.DoesNotExist):
            order.refresh_from_db()

        self.assertNotIn(REFRESHING_FLAG, order.__dict__)

    def test_phase_fields(self):
        self.assertEqual(Order.phase_fields(), (Order._meta.get_field("status"),))
