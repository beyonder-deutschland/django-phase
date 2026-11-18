from unittest import mock

from django.db import connection
from django.test import TestCase

from phase.exceptions import ProtectedPhaseFieldError
from phase.fields import is_writing_phase, writing_phase
from phase.managers import PhaseManager, PhaseQuerySet
from phase.signals import phase_moved_many
from phase.transitions import force_move, move, move_many
from testapp.models import Customer, Invoice, Order, Ticket


class PhaseQuerySetTest(TestCase):
    def test_manager_returns_phase_queryset(self):
        self.assertIsInstance(Order.objects.all(), PhaseQuerySet)

    def test_update_of_phase_is_refused(self):
        order = Order.objects.create()

        with self.assertRaisesMessage(ProtectedPhaseFieldError, "'status' is a phase field"):
            Order.objects.filter(pk=order.pk).update(status=Order.Status.SHIPPED, note="bypass")

        self.assertEqual(Order.objects.values_list("status", "note").get(), (Order.Status.OPEN, ""))

    def test_update_of_numeric_phase_is_refused(self):
        Invoice.objects.create()

        with self.assertRaises(ProtectedPhaseFieldError):
            Invoice.objects.update(status=Invoice.Status.PAID)

    def test_update_of_other_fields_passes(self):
        order = Order.objects.create()

        self.assertEqual(Order.objects.filter(pk=order.pk).update(note="changed"), 1)
        self.assertEqual(Order.objects.get(pk=order.pk).note, "changed")

    def test_update_through_related_manager_is_refused(self):
        customer = Customer.objects.create()
        Order.objects.create(customer=customer)

        with self.assertRaises(ProtectedPhaseFieldError):
            customer.order_set.update(status=Order.Status.CANCELLED)

    def test_bulk_update_of_phase_is_refused(self):
        order = Order.objects.create()

        with self.assertRaises(ProtectedPhaseFieldError):
            Order.objects.bulk_update([order], fields=["note", "status"])

    def test_bulk_update_of_other_fields_passes(self):
        order = Order.objects.create()
        order.note = "changed"

        self.assertEqual(Order.objects.bulk_update([order], fields=iter(["note"]), batch_size=10), 1)
        self.assertEqual(Order.objects.get(pk=order.pk).note, "changed")

    def test_bulk_create_overwriting_phase_on_conflict_is_refused(self):
        order = Order.objects.create()

        with self.assertRaises(ProtectedPhaseFieldError):
            Order.objects.bulk_create(
                [Order(pk=order.pk, status=Order.Status.SHIPPED)],
                update_conflicts=True,
                update_fields=["status"],
                unique_fields=["id"],
            )

        self.assertEqual(Order.objects.get(pk=order.pk).status, Order.Status.OPEN)

    def test_bulk_create_overwriting_other_fields_on_conflict_passes(self):
        order = Order.objects.create()

        Order.objects.bulk_create(
            [Order(pk=order.pk, status=Order.Status.SHIPPED, note="imported")],
            update_conflicts=True,
            update_fields=iter(["note"]),
            unique_fields=["id"],
        )

        stored = Order.objects.get(pk=order.pk)
        self.assertEqual((stored.status, stored.note), (Order.Status.OPEN, "imported"))

    def test_bulk_create_with_phase_passes(self):
        Order.objects.bulk_create([Order(status=Order.Status.SHIPPED)], ignore_conflicts=True)

        self.assertEqual(Order.objects.get().status, Order.Status.SHIPPED)

    def test_plain_base_manager_stays_unprotected(self):
        order = Order.objects.create()

        Order._base_manager.filter(pk=order.pk).update(status=Order.Status.SHIPPED)

        self.assertEqual(Order.objects.get(pk=order.pk).status, Order.Status.SHIPPED)

    def test_manager_is_not_used_in_migrations(self):
        self.assertFalse(PhaseManager.use_in_migrations)

    def test_writing_phase_is_reset_after_an_error(self):
        with self.assertRaises(RuntimeError), writing_phase():
            self.assertTrue(is_writing_phase())
            raise RuntimeError

        self.assertFalse(is_writing_phase())


class TransitionsThroughProtectedBaseManagerTest(TestCase):
    def test_base_manager_is_protected(self):
        self.assertIsInstance(Ticket._base_manager.all(), PhaseQuerySet)

    def test_save(self):
        ticket = Ticket.objects.create()
        ticket.note = "changed"

        ticket.save()

        self.assertEqual(Ticket.objects.get().note, "changed")

    def test_move(self):
        ticket = Ticket.objects.create()

        move(obj=ticket, to="done", note="closed")

        self.assertEqual(Ticket.objects.values_list("status", "note").get(), ("done", "closed"))

    def test_force_move(self):
        ticket = Ticket.objects.create()
        move(obj=ticket, to="done")

        force_move(obj=ticket, to="new", reason="Support ticket #123")

        self.assertEqual(Ticket.objects.get().status, "new")

    def test_move_many(self):
        Ticket.objects.create()

        self.assertEqual(move_many(queryset=Ticket.objects.all(), source="new", to="done"), 1)
        self.assertEqual(Ticket.objects.get().status, "done")

    def test_move_many_without_self_select(self):
        Ticket.objects.create()

        with mock.patch.object(connection.features, "update_can_self_select", False):
            moved = move_many(queryset=Ticket.objects.all(), source="new", to="done")

        self.assertEqual(moved, 1)

    def test_move_many_with_receiver(self):
        def receiver(sender, **kwargs):
            pass

        phase_moved_many.connect(receiver, sender=Ticket)
        self.addCleanup(phase_moved_many.disconnect, receiver, sender=Ticket)
        Ticket.objects.create()

        self.assertEqual(move_many(queryset=Ticket.objects.all(), source="new", to="done"), 1)

    def test_bypass_ends_with_the_transition(self):
        ticket = Ticket.objects.create()
        move(obj=ticket, to="done")

        with self.assertRaises(ProtectedPhaseFieldError):
            Ticket.objects.update(status="new")
