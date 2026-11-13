from django.db.models import F, signals
from django.test import TestCase

from phase.exceptions import IllegalPhaseTransitionError, ProtectedPhaseFieldError
from phase.transitions import move
from testapp.models import Order

UPDATE_FIELDS = frozenset({"status", "note", "transition_count", "updated_at"})


class MoveSignalsTest(TestCase):
    def setUp(self):
        self.calls = []

    def connect(self, signal, receiver):
        signal.connect(receiver, sender=Order)
        self.addCleanup(signal.disconnect, receiver, sender=Order)

    def record(self, signal_name):
        def receiver(sender, instance, **kwargs):
            self.calls.append((signal_name, instance.status, instance.note, kwargs))

        return receiver

    def test_pre_save_sees_new_values_and_post_save_follows(self):
        self.connect(signals.pre_save, self.record("pre_save"))
        self.connect(signals.post_save, self.record("post_save"))
        order = Order.objects.create()
        self.calls.clear()

        move(obj=order, to=Order.Status.PAID, note="paid", transition_count=F("transition_count") + 1)

        self.assertEqual(
            self.calls,
            [
                (
                    "pre_save",
                    Order.Status.PAID,
                    "paid",
                    {"signal": signals.pre_save, "raw": False, "using": "default", "update_fields": UPDATE_FIELDS},
                ),
                (
                    "post_save",
                    Order.Status.PAID,
                    "paid",
                    {
                        "signal": signals.post_save,
                        "created": False,
                        "raw": False,
                        "using": "default",
                        "update_fields": UPDATE_FIELDS,
                    },
                ),
            ],
        )

    def test_post_save_sees_stored_values(self):
        seen = []
        self.connect(signals.post_save, lambda sender, instance, **kwargs: seen.append(instance.transition_count))
        order = Order.objects.create()
        seen.clear()

        move(obj=order, to=Order.Status.PAID, transition_count=F("transition_count") + 1)

        self.assertEqual(seen, [1])

    def test_pre_save_may_change_written_fields(self):
        def receiver(sender, instance, **kwargs):
            instance.note = instance.note.upper()

        self.connect(signals.pre_save, receiver)
        order = Order.objects.create()

        move(obj=order, to=Order.Status.PAID, note="paid")

        self.assertEqual(Order.objects.get(pk=order.pk).note, "PAID")

    def test_pre_save_may_not_change_phase(self):
        def receiver(sender, instance, **kwargs):
            instance.status = Order.Status.SHIPPED

        order = Order.objects.create()
        self.connect(signals.pre_save, receiver)

        with self.assertRaises(ProtectedPhaseFieldError):
            move(obj=order, to=Order.Status.PAID, note="paid")

        self.assertEqual((order.status, order.note), (Order.Status.OPEN, ""))
        self.assertEqual(Order.objects.get(pk=order.pk).status, Order.Status.OPEN)

    def test_refused_move_sends_no_post_save_and_restores_obj(self):
        self.connect(signals.pre_save, self.record("pre_save"))
        self.connect(signals.post_save, self.record("post_save"))
        order = Order.objects.create(note="loaded")
        move(obj=Order.objects.get(pk=order.pk), to=Order.Status.CANCELLED)
        self.calls.clear()

        with self.assertRaises(IllegalPhaseTransitionError):
            move(obj=order, to=Order.Status.PAID, note="never written")

        self.assertEqual([call[0] for call in self.calls], ["pre_save"])
        self.assertEqual((order.status, order.note), (Order.Status.OPEN, "loaded"))

    def test_illegal_transition_sends_nothing(self):
        self.connect(signals.pre_save, self.record("pre_save"))
        order = Order.objects.create()
        self.calls.clear()

        with self.assertRaises(IllegalPhaseTransitionError):
            move(obj=order, to=Order.Status.SHIPPED)

        self.assertEqual(self.calls, [])
