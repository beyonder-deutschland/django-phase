import warnings
from unittest import skipIf

import django
from django.db import IntegrityError, connection, transaction
from django.db.models import signals
from django.db.transaction import TransactionManagementError
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext

from phase.exceptions import StalePhaseError
from phase.fields import REFRESHING_FLAG
from phase.transitions import move
from testapp.models import Customer, Order, Shipment


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

    @skipIf(django.VERSION >= (6, 0), "Django 6.0 accepts the arguments of save() by keyword only.")
    def test_positional_arguments_are_read_like_keywords(self):
        order = Order.objects.create()
        move(obj=Order.objects.get(pk=order.pk), to=Order.Status.CANCELLED)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            order.save(False, False, "default", [])

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


class PhaseGuardMixinOpenTransactionTest(TestCase):
    """A `TestCase` runs in a transaction, as a request with `ATOMIC_REQUESTS` does."""

    def test_guarded_save_adds_one_query(self):
        order = Order.objects.create()
        order.note = "gift wrap"

        with CaptureQueriesContext(connection) as queries:
            order.save()

        statements = [query["sql"].split()[0] for query in queries]
        self.assertEqual(statements, ["SELECT", "UPDATE"])

    def test_new_row_with_explicit_primary_key_adds_one_query(self):
        with CaptureQueriesContext(connection) as queries:
            Order(pk=4711, status=Order.Status.PAID).save()

        statements = [query["sql"].split()[0] for query in queries]
        self.assertEqual(statements, ["SELECT", "UPDATE", "INSERT"])

    def test_refused_save_leaves_transaction_usable(self):
        order = Order.objects.create()
        move(obj=Order.objects.get(pk=order.pk), to=Order.Status.CANCELLED)
        order.note = "gift wrap"

        with transaction.atomic():
            with self.assertRaises(StalePhaseError):
                order.save()

            self.assertFalse(transaction.get_rollback())
            order.refresh_from_db()
            order.note = "gift wrap"
            order.save()

        stored = Order.objects.get(pk=order.pk)
        self.assertEqual(stored.status, Order.Status.CANCELLED)
        self.assertEqual(stored.note, "gift wrap")

    def test_database_error_marks_transaction_for_rollback_like_plain_model(self):
        order = Order.objects.create()
        order.note = None
        customer = Customer.objects.create()
        customer.country = None

        for instance in (customer, order):
            with self.subTest(model=type(instance).__name__), transaction.atomic():
                with self.assertRaises(IntegrityError):
                    instance.save()

                self.assertTrue(transaction.get_rollback())
                with self.assertRaises(TransactionManagementError):
                    type(instance)._base_manager.count()

    def test_error_in_receiver_leaves_transaction_usable_like_plain_model(self):
        def refuse(**kwargs):
            raise ValueError("refused")

        order = Order.objects.create()
        customer = Customer.objects.create()

        for instance in (customer, order):
            model = type(instance)
            signals.pre_save.connect(refuse, sender=model)
            self.addCleanup(signals.pre_save.disconnect, refuse, sender=model)
            with self.subTest(model=model.__name__), transaction.atomic():
                with self.assertRaisesMessage(ValueError, "refused"):
                    instance.save()

                self.assertFalse(transaction.get_rollback())
                self.assertEqual(model._base_manager.count(), 1)


class PhaseGuardMixinAutocommitTest(TransactionTestCase):
    def test_transaction_spans_lock_and_write(self):
        order = Order.objects.create()
        order.note = "gift wrap"

        with CaptureQueriesContext(connection) as queries:
            order.save()

        statements = [query["sql"].split()[0] for query in queries]
        self.assertEqual(statements, ["BEGIN", "SELECT", "UPDATE", "COMMIT"])
        self.assertTrue(transaction.get_autocommit())
        self.assertEqual(Order.objects.get(pk=order.pk).note, "gift wrap")

    def test_refused_save_ends_its_transaction(self):
        order = Order.objects.create()
        move(obj=Order.objects.get(pk=order.pk), to=Order.Status.CANCELLED)
        order.note = "gift wrap"

        with CaptureQueriesContext(connection) as queries, self.assertRaises(StalePhaseError):
            order.save()

        statements = [query["sql"].split()[0] for query in queries]
        self.assertEqual(statements, ["BEGIN", "SELECT", "ROLLBACK"])
        self.assertTrue(transaction.get_autocommit())
        self.assertEqual(Order.objects.get(pk=order.pk).note, "")

    def test_failed_write_is_rolled_back(self):
        def fail(**kwargs):
            raise ValueError("failed")

        order = Order.objects.create()
        order.note = "gift wrap"
        signals.post_save.connect(fail, sender=Order)
        self.addCleanup(signals.post_save.disconnect, fail, sender=Order)

        with self.assertRaisesMessage(ValueError, "failed"):
            order.save()

        self.assertTrue(transaction.get_autocommit())
        self.assertEqual(Order.objects.get(pk=order.pk).note, "")
