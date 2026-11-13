import datetime
from unittest import mock

from django.db import connection
from django.db.models import F
from django.test import TestCase

from phase.exceptions import (
    EditablePhaseFieldError,
    IllegalPhaseTransitionError,
    InvalidTransitionTableError,
    ProtectedPhaseFieldError,
    StalePhaseError,
)
from phase.fields import IntegerPhaseField, PhaseField
from testapp.models import Invoice, Order, Shipment

NOW = datetime.datetime(2026, 11, 13, 9, 0, tzinfo=datetime.UTC)


class PhaseFieldInitTest(TestCase):
    def test_targets_must_be_tuples(self):
        with self.assertRaisesMessage(InvalidTransitionTableError, "Targets of phase 'open' must be a tuple"):
            PhaseField(max_length=10, transitions={"open": "closed"})

    def test_editable_true_is_refused(self):
        with self.assertRaises(EditablePhaseFieldError):
            PhaseField(max_length=10, transitions={}, editable=True)

    def test_field_is_never_editable(self):
        self.assertFalse(PhaseField(max_length=10, transitions={}, editable=False).editable)
        self.assertFalse(Order._meta.get_field("status").editable)

    def test_deconstruct_returns_plain_charfield(self):
        _, path, _, kwargs = Order._meta.get_field("status").deconstruct()

        self.assertEqual(path, "django.db.models.CharField")
        self.assertNotIn("transitions", kwargs)
        self.assertNotIn("editable", kwargs)
        self.assertEqual(kwargs["max_length"], 10)

    def test_clone_keeps_transitions(self):
        field = Order._meta.get_field("status")

        clone = field.clone()

        self.assertIsInstance(clone, PhaseField)
        self.assertEqual(clone.transitions, field.transitions)


class ProtectedPhaseDescriptorTest(TestCase):
    def test_constructor_sets_phase(self):
        self.assertEqual(Order(status=Order.Status.PAID).status, Order.Status.PAID)

    def test_direct_assignment_is_refused(self):
        order = Order.objects.create()

        with self.assertRaisesMessage(ProtectedPhaseFieldError, "'status' is a phase field"):
            order.status = Order.Status.PAID

        self.assertEqual(order.status, Order.Status.OPEN)

    def test_assigning_the_current_phase_passes(self):
        order = Order.objects.create()

        order.status = Order.Status.OPEN

        self.assertEqual(order.status, Order.Status.OPEN)

    def test_full_clean_of_saved_instance(self):
        order = Order.objects.create()

        order.full_clean()

        self.assertEqual(order.status, Order.Status.OPEN)

    def test_full_clean_of_unsaved_instance(self):
        order = Order(status=Order.Status.PAID)

        order.full_clean()

        self.assertEqual(order.status, Order.Status.PAID)

    def test_loading_from_database_sets_phase(self):
        order = Order.objects.create(status=Order.Status.PAID)

        self.assertEqual(Order.objects.get(pk=order.pk).status, Order.Status.PAID)

    def test_deferred_phase_is_fetched_on_access(self):
        order = Order.objects.create(status=Order.Status.PAID)

        deferred_order = Order.objects.defer("status").get(pk=order.pk)

        self.assertEqual(deferred_order.status, Order.Status.PAID)

    def test_db_default_is_replaced_by_stored_value(self):
        shipment = Shipment.objects.create()

        self.assertEqual(shipment.status, "packed")
        with self.assertRaises(ProtectedPhaseFieldError):
            shipment.status = "sent"

    def test_create_with_explicit_phase_despite_db_default(self):
        shipment = Shipment.objects.create(status="sent")

        self.assertEqual(shipment.status, "sent")
        self.assertEqual(Shipment.objects.get(pk=shipment.pk).status, "sent")

    def test_save_with_explicit_phase_despite_db_default(self):
        shipment = Shipment(status="packed")

        shipment.save()

        self.assertEqual(shipment.status, "packed")

    def test_bulk_create_with_explicit_phase_despite_db_default(self):
        Shipment.objects.bulk_create([Shipment(status="sent")])

        self.assertEqual(Shipment.objects.get().status, "sent")


class PhaseFieldTransitionTest(TestCase):
    def setUp(self):
        self.field = Order._meta.get_field("status")

    def test_targets(self):
        self.assertEqual(
            self.field.targets(obj=Order(status=Order.Status.OPEN)), (Order.Status.PAID, Order.Status.CANCELLED)
        )

    def test_targets_of_final_phase_are_empty(self):
        self.assertEqual(self.field.targets(obj=Order(status=Order.Status.SHIPPED)), ())

    def test_can_transition(self):
        order = Order(status=Order.Status.OPEN)

        self.assertTrue(self.field.can_transition(obj=order, to=Order.Status.PAID))
        self.assertFalse(self.field.can_transition(obj=order, to=Order.Status.SHIPPED))

    def test_move_writes_phase_and_fields(self):
        order = Order.objects.create()

        self.field.move(obj=order, to=Order.Status.PAID, note="paid by card")

        self.assertEqual(order.status, Order.Status.PAID)
        self.assertEqual(order.note, "paid by card")
        stored = Order.objects.get(pk=order.pk)
        self.assertEqual(stored.status, Order.Status.PAID)
        self.assertEqual(stored.note, "paid by card")

    def test_move_reads_expressions_back_as_values(self):
        order = Order.objects.create()

        self.field.move(obj=order, to=Order.Status.PAID, transition_count=F("transition_count") + 1)

        self.assertEqual(order.transition_count, 1)

    def test_move_refuses_transition_missing_from_table(self):
        order = Order.objects.create()

        with self.assertRaisesMessage(
            IllegalPhaseTransitionError, f"testapp.Order ID #{order.pk} cannot change from 'open' to 'shipped'."
        ):
            self.field.move(obj=order, to=Order.Status.SHIPPED, note="never written")

        stored = Order.objects.get(pk=order.pk)
        self.assertEqual(stored.status, Order.Status.OPEN)
        self.assertEqual(stored.note, "")

    def test_move_refuses_the_loser_of_a_race(self):
        order = Order.objects.create()
        winner = Order.objects.get(pk=order.pk)
        self.field.move(obj=winner, to=Order.Status.CANCELLED, note="cancelled by phone")

        with self.assertRaises(IllegalPhaseTransitionError) as context:
            self.field.move(obj=order, to=Order.Status.PAID, note="never written")

        self.assertEqual(context.exception.source, Order.Status.CANCELLED)
        self.assertEqual(context.exception.target, Order.Status.PAID)
        stored = Order.objects.get(pk=order.pk)
        self.assertEqual(stored.status, Order.Status.CANCELLED)
        self.assertEqual(stored.note, "cancelled by phone")

    def test_loser_of_a_race_stays_stale(self):
        order = Order.objects.create()
        self.field.move(obj=Order.objects.get(pk=order.pk), to=Order.Status.CANCELLED, note="cancelled by phone")
        with self.assertRaises(IllegalPhaseTransitionError):
            self.field.move(obj=order, to=Order.Status.PAID)

        with self.assertRaises(StalePhaseError):
            order.save()

        self.assertEqual(order.status, Order.Status.OPEN)
        self.assertEqual(Order.objects.get(pk=order.pk).note, "cancelled by phone")

    def test_move_of_deleted_row(self):
        order = Order.objects.create()
        Order.objects.filter(pk=order.pk).delete()

        with self.assertRaisesMessage(
            IllegalPhaseTransitionError,
            f"testapp.Order ID #{order.pk} doesn't exist in the database and cannot change to 'paid'.",
        ) as context:
            self.field.move(obj=order, to=Order.Status.PAID)

        self.assertIsNone(context.exception.source)

    def test_move_of_unsaved_instance(self):
        with self.assertRaises(IllegalPhaseTransitionError) as context:
            self.field.move(obj=Order(), to=Order.Status.PAID)

        self.assertIsNone(context.exception.source)

    def test_move_writes_auto_now_fields(self):
        order = Order.objects.create()

        with mock.patch("django.utils.timezone.now", return_value=NOW):
            self.field.move(obj=order, to=Order.Status.PAID)

        self.assertEqual(order.updated_at, NOW)
        self.assertEqual(Order.objects.get(pk=order.pk).updated_at, NOW)

    def test_auto_now_wins_over_given_value_as_in_save(self):
        order = Order.objects.create()

        with mock.patch("django.utils.timezone.now", return_value=NOW):
            self.field.move(obj=order, to=Order.Status.PAID, updated_at=NOW - datetime.timedelta(days=1))

        self.assertEqual(order.updated_at, NOW)

    def test_refused_move_leaves_auto_now_fields_untouched(self):
        order = Order.objects.create()
        loaded_updated_at = order.updated_at
        self.field.move(obj=Order.objects.get(pk=order.pk), to=Order.Status.CANCELLED)

        with mock.patch("django.utils.timezone.now", return_value=NOW), self.assertRaises(IllegalPhaseTransitionError):
            self.field.move(obj=order, to=Order.Status.PAID)

        self.assertEqual(order.updated_at, loaded_updated_at)

    def test_move_resolves_db_default_left_by_backend_without_returning(self):
        with mock.patch.object(connection.features, "can_return_columns_from_insert", False):
            shipment = Shipment.objects.create()

        Shipment._meta.get_field("status").move(obj=shipment, to="sent")

        self.assertEqual(shipment.status, "sent")
        self.assertEqual(Shipment.objects.get(pk=shipment.pk).status, "sent")

    def test_move_resolves_db_default_placeholder_on_saved_instance(self):
        shipment = Shipment.objects.create()
        shipment.__dict__["status"] = Shipment().__dict__["status"]

        Shipment._meta.get_field("status").move(obj=shipment, to="sent")

        self.assertEqual(shipment.status, "sent")

    def test_move_of_unsaved_instance_with_db_default(self):
        with self.assertRaisesMessage(IllegalPhaseTransitionError, "doesn't exist in the database"):
            Shipment._meta.get_field("status").move(obj=Shipment(), to="sent")

    def test_move_asks_the_router_for_the_database_to_write_to(self):
        order = Order.objects.create()
        order._state.db = "replica"

        with mock.patch("phase.fields.router.db_for_write", return_value="default") as db_for_write:
            self.field.move(obj=order, to=Order.Status.PAID)

        db_for_write.assert_called_once_with(Order, instance=order)
        self.assertEqual(Order.objects.get(pk=order.pk).status, Order.Status.PAID)

    def test_move_refreshes_from_the_database_it_wrote_to(self):
        order = Order.objects.create()

        with mock.patch.object(Order, "refresh_from_db", autospec=True) as refresh_from_db:
            self.field.move(obj=order, to=Order.Status.PAID)

        self.assertEqual(refresh_from_db.call_args.kwargs["using"], "default")

    def test_move_ignores_default_manager_filter(self):
        shipment = Shipment.objects.create(archived=True)

        Shipment._meta.get_field("status").move(obj=shipment, to="sent")

        self.assertEqual(shipment.status, "sent")


class IntegerPhaseFieldTest(TestCase):
    def setUp(self):
        self.field = Invoice._meta.get_field("status")

    def test_targets_must_be_tuples(self):
        with self.assertRaisesMessage(InvalidTransitionTableError, "Targets of phase '1' must be a tuple"):
            IntegerPhaseField(transitions={1: 2})

    def test_field_is_never_editable(self):
        self.assertFalse(self.field.editable)

    def test_deconstruct_returns_plain_positive_small_integer_field(self):
        _, path, _, kwargs = self.field.deconstruct()

        self.assertEqual(path, "django.db.models.PositiveSmallIntegerField")
        self.assertNotIn("transitions", kwargs)
        self.assertNotIn("editable", kwargs)

    def test_clone_keeps_transitions(self):
        clone = self.field.clone()

        self.assertIsInstance(clone, IntegerPhaseField)
        self.assertEqual(clone.transitions, self.field.transitions)

    def test_direct_assignment_is_refused(self):
        invoice = Invoice.objects.create()

        with self.assertRaises(ProtectedPhaseFieldError):
            invoice.status = Invoice.Status.SENT

        self.assertEqual(invoice.status, Invoice.Status.DRAFT)

    def test_full_clean_of_saved_instance(self):
        invoice = Invoice.objects.create()

        invoice.full_clean()

        self.assertEqual(invoice.status, Invoice.Status.DRAFT)

    def test_targets_of_instance_loaded_from_database(self):
        invoice = Invoice.objects.get(pk=Invoice.objects.create().pk)

        self.assertEqual(self.field.targets(obj=invoice), (Invoice.Status.SENT, Invoice.Status.VOID))
        self.assertTrue(self.field.can_transition(obj=invoice, to=Invoice.Status.VOID))

    def test_move_writes_phase_and_fields(self):
        invoice = Invoice.objects.create()

        self.field.move(obj=invoice, to=Invoice.Status.SENT, note="sent by mail")

        stored = Invoice.objects.get(pk=invoice.pk)
        self.assertEqual(invoice.status, Invoice.Status.SENT)
        self.assertEqual(stored.status, Invoice.Status.SENT)
        self.assertEqual(stored.note, "sent by mail")

    def test_refused_move_names_phases_by_label(self):
        invoice = Invoice.objects.create()

        with self.assertRaisesMessage(
            IllegalPhaseTransitionError,
            f"testapp.Invoice ID #{invoice.pk} cannot change from 'Draft' (1) to 'Paid' (3).",
        ) as context:
            self.field.move(obj=invoice, to=Invoice.Status.PAID)

        self.assertEqual(context.exception.source, Invoice.Status.DRAFT)
        self.assertEqual(context.exception.target, Invoice.Status.PAID)

    def test_move_refuses_the_loser_of_a_race(self):
        invoice = Invoice.objects.create()
        self.field.move(obj=Invoice.objects.get(pk=invoice.pk), to=Invoice.Status.VOID)

        with self.assertRaisesMessage(IllegalPhaseTransitionError, "cannot change from 'Void' (4) to 'Sent' (2)."):
            self.field.move(obj=invoice, to=Invoice.Status.SENT)

        self.assertEqual(Invoice.objects.get(pk=invoice.pk).status, Invoice.Status.VOID)

    def test_move_of_deleted_row_names_target_by_label(self):
        invoice = Invoice.objects.create()
        Invoice.objects.filter(pk=invoice.pk).delete()

        with self.assertRaisesMessage(
            IllegalPhaseTransitionError, "doesn't exist in the database and cannot change to 'Sent' (2)."
        ):
            self.field.move(obj=invoice, to=Invoice.Status.SENT)

    def test_stale_save_names_phase_by_label(self):
        invoice = Invoice.objects.create()
        self.field.move(obj=Invoice.objects.get(pk=invoice.pk), to=Invoice.Status.VOID)

        with self.assertRaisesMessage(StalePhaseError, "no longer has status='Draft' (1) in the database") as context:
            invoice.save()

        self.assertEqual(context.exception.phases, {"status": Invoice.Status.DRAFT})


class PhaseLabelTest(TestCase):
    def test_number_with_choice(self):
        self.assertEqual(Invoice._meta.get_field("status").label(Invoice.Status.PAID), "Paid")

    def test_number_without_choice(self):
        self.assertIsNone(IntegerPhaseField(transitions={}).label(7))

    def test_string_names_itself(self):
        self.assertIsNone(Order._meta.get_field("status").label(Order.Status.PAID))

    def test_missing_row(self):
        self.assertIsNone(Invoice._meta.get_field("status").label(None))
