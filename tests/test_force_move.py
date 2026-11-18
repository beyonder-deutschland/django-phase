from django.db.models import F, signals
from django.test import TestCase

from phase.exceptions import ProtectedPhaseFieldError, StalePhaseError
from phase.signals import phase_moved
from phase.transitions import force_move, move
from testapp.models import Invoice, Order


class ForceMoveTest(TestCase):
    def test_moves_outside_the_table(self):
        order = Order.objects.create()
        move(obj=order, to=Order.Status.CANCELLED)
        updated_at = order.updated_at

        force_move(
            obj=order,
            to=Order.Status.OPEN,
            reason="Support ticket #123",
            note="reopened",
            transition_count=F("transition_count") + 1,
        )

        self.assertEqual((order.status, order.note, order.transition_count), (Order.Status.OPEN, "reopened", 1))
        self.assertGreater(order.updated_at, updated_at)
        stored = Order.objects.get(pk=order.pk)
        self.assertEqual((stored.status, stored.note, stored.transition_count), (Order.Status.OPEN, "reopened", 1))

    def test_refreshes_generated_fields(self):
        invoice = Invoice.objects.create()

        force_move(obj=invoice, to=Invoice.Status.PAID, reason="Paid by bank transfer")

        self.assertTrue(invoice.is_settled)

    def test_refuses_stale_instance(self):
        order = Order.objects.create(note="loaded")
        move(obj=Order.objects.get(pk=order.pk), to=Order.Status.PAID)

        with self.assertRaisesMessage(
            StalePhaseError, f"testapp.Order ID #{order.pk} no longer has status='open' in the database"
        ):
            force_move(obj=order, to=Order.Status.CANCELLED, reason="Support ticket #123", note="never written")

        self.assertEqual((order.status, order.note), (Order.Status.OPEN, "loaded"))
        stored = Order.objects.get(pk=order.pk)
        self.assertEqual((stored.status, stored.note), (Order.Status.PAID, "loaded"))

    def test_refuses_deleted_row(self):
        order = Order.objects.create()
        Order.objects.filter(pk=order.pk).delete()

        with self.assertRaises(StalePhaseError):
            force_move(obj=order, to=Order.Status.SHIPPED, reason="Support ticket #123")

    def test_stale_numeric_phase_is_named_by_label(self):
        invoice = Invoice.objects.create()
        move(obj=Invoice.objects.get(pk=invoice.pk), to=Invoice.Status.VOID)

        with self.assertRaises(StalePhaseError) as context:
            force_move(obj=invoice, to=Invoice.Status.PAID, reason="Support ticket #123")

        self.assertEqual(context.exception.phases, {"status": Invoice.Status.DRAFT})
        self.assertEqual(context.exception.labels, {"status": "Draft"})

    def test_phase_among_fields_is_refused(self):
        order = Order.objects.create()

        with self.assertRaises(ProtectedPhaseFieldError):
            force_move(obj=order, to=Order.Status.SHIPPED, reason="Support ticket #123", status=Order.Status.PAID)

        self.assertEqual(Order.objects.get(pk=order.pk).status, Order.Status.OPEN)


class ForceMoveSignalsTest(TestCase):
    def setUp(self):
        self.calls = []
        for signal in (signals.pre_save, signals.post_save, phase_moved):
            signal.connect(self.receiver, sender=Order)
            self.addCleanup(signal.disconnect, self.receiver, sender=Order)

    def receiver(self, sender, signal, **kwargs):
        self.calls.append((signal, kwargs))

    def test_sends_signals_of_a_transition_marked_as_forced(self):
        order = Order.objects.create()
        self.calls.clear()

        force_move(obj=order, to=Order.Status.SHIPPED, reason="Support ticket #123")

        self.assertEqual([call[0] for call in self.calls], [signals.pre_save, signals.post_save, phase_moved])
        self.assertEqual(
            self.calls[-1][1],
            {
                "instance": order,
                "field": Order._meta.get_field("status"),
                "source": Order.Status.OPEN,
                "target": Order.Status.SHIPPED,
                "forced": True,
                "reason": "Support ticket #123",
                "using": "default",
            },
        )

    def test_refused_force_move_sends_no_post_save(self):
        order = Order.objects.create()
        move(obj=Order.objects.get(pk=order.pk), to=Order.Status.PAID)
        self.calls.clear()

        with self.assertRaises(StalePhaseError):
            force_move(obj=order, to=Order.Status.SHIPPED, reason="Support ticket #123")

        self.assertEqual([call[0] for call in self.calls], [signals.pre_save])
