from unittest import mock

from django.db import connection
from django.db.models import F, signals
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from phase.exceptions import IllegalPhaseTransitionError, ProtectedPhaseFieldError
from phase.signals import phase_moved, phase_moved_many
from phase.transitions import move, move_many
from testapp.models import Customer, Invoice, Order

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


class PhaseMovedTest(TestCase):
    def setUp(self):
        self.calls = []
        phase_moved.connect(self.receiver, sender=Order)
        self.addCleanup(phase_moved.disconnect, self.receiver, sender=Order)

    def receiver(self, sender, **kwargs):
        self.calls.append((sender, kwargs))

    def post_save_receiver(self, sender, **kwargs):
        self.calls.append(("post_save", sender))

    def test_sent_after_post_save_with_source_and_target(self):
        order = Order.objects.create()
        signals.post_save.connect(self.post_save_receiver, sender=Order)
        self.addCleanup(signals.post_save.disconnect, self.post_save_receiver, sender=Order)

        move(obj=order, to=Order.Status.PAID, note="paid")

        self.assertEqual(
            self.calls,
            [
                ("post_save", Order),
                (
                    Order,
                    {
                        "signal": phase_moved,
                        "instance": order,
                        "field": Order._meta.get_field("status"),
                        "source": Order.Status.OPEN,
                        "target": Order.Status.PAID,
                        "forced": False,
                        "reason": None,
                        "using": "default",
                    },
                ),
            ],
        )

    def test_not_sent_for_illegal_transition(self):
        order = Order.objects.create()

        with self.assertRaises(IllegalPhaseTransitionError):
            move(obj=order, to=Order.Status.SHIPPED)

        self.assertEqual(self.calls, [])

    def test_not_sent_for_lost_race(self):
        order = Order.objects.create()
        move(obj=Order.objects.get(pk=order.pk), to=Order.Status.CANCELLED)
        self.calls.clear()

        with self.assertRaises(IllegalPhaseTransitionError):
            move(obj=order, to=Order.Status.PAID)

        self.assertEqual(self.calls, [])


class PhaseMovedManyTest(TestCase):
    def setUp(self):
        self.calls = []
        self.customer = Customer.objects.create()
        self.open_orders = [Order.objects.create(customer=self.customer) for _ in range(3)]
        self.paid_order = Order.objects.create(customer=self.customer)
        move(obj=self.paid_order, to=Order.Status.PAID)

    def listen(self, receiver=None):
        receiver = receiver or self.receiver
        phase_moved_many.connect(receiver, sender=Order)
        self.addCleanup(phase_moved_many.disconnect, receiver, sender=Order)

    def receiver(self, sender, **kwargs):
        self.calls.append((sender, kwargs))

    def test_sent_with_the_keys_of_the_moved_rows(self):
        self.listen()

        moved = move_many(
            queryset=Order.objects.filter(customer__country="DE"), source=Order.Status.OPEN, to=Order.Status.CANCELLED
        )

        self.assertEqual(moved, 3)
        sender, kwargs = self.calls[0]
        self.assertEqual(len(self.calls), 1)
        self.assertIs(sender, Order)
        self.assertEqual(sorted(kwargs.pop("pks")), sorted(order.pk for order in self.open_orders))
        self.assertEqual(
            kwargs,
            {
                "signal": phase_moved_many,
                "field": Order._meta.get_field("status"),
                "source": Order.Status.OPEN,
                "target": Order.Status.CANCELLED,
                "using": "default",
            },
        )
        self.assertEqual(
            set(Order.objects.values_list("status", flat=True)), {Order.Status.CANCELLED, Order.Status.PAID}
        )

    def test_writes_fields_and_stamps_auto_now(self):
        self.listen()
        before = Order.objects.get(pk=self.open_orders[0].pk).updated_at

        move_many(
            queryset=Order.objects.filter(pk=self.open_orders[0].pk),
            source=Order.Status.OPEN,
            to=Order.Status.PAID,
            note="bulk",
        )

        order = Order.objects.get(pk=self.open_orders[0].pk)
        self.assertEqual((order.status, order.note), (Order.Status.PAID, "bulk"))
        self.assertGreater(order.updated_at, before)

    def test_moves_in_batches(self):
        self.listen()

        with (
            mock.patch.object(connection.ops, "bulk_batch_size", return_value=2),
            CaptureQueriesContext(connection) as queries,
        ):
            moved = move_many(queryset=Order.objects.all(), source=Order.Status.OPEN, to=Order.Status.CANCELLED)

        self.assertEqual(moved, 3)
        self.assertEqual(len([query for query in queries if query["sql"].startswith("UPDATE")]), 2)
        self.assertEqual(sorted(self.calls[0][1]["pks"]), sorted(order.pk for order in self.open_orders))

    def test_not_sent_when_no_row_moved(self):
        self.listen()

        moved = move_many(
            queryset=Order.objects.filter(pk=self.paid_order.pk), source=Order.Status.OPEN, to=Order.Status.PAID
        )

        self.assertEqual(moved, 0)
        self.assertEqual(self.calls, [])

    def test_failing_receiver_rolls_back_the_move(self):
        def receiver(sender, **kwargs):
            raise RuntimeError

        self.listen(receiver)

        with self.assertRaises(RuntimeError):
            move_many(queryset=Order.objects.all(), source=Order.Status.OPEN, to=Order.Status.CANCELLED)

        self.assertEqual(Order.objects.filter(status=Order.Status.OPEN).count(), 3)

    def test_without_receiver_one_update(self):
        receiver_of_other_model = lambda sender, **kwargs: None  # noqa: E731
        phase_moved_many.connect(receiver_of_other_model, sender=Invoice)
        self.addCleanup(phase_moved_many.disconnect, receiver_of_other_model, sender=Invoice)

        with CaptureQueriesContext(connection) as queries:
            moved = move_many(queryset=Order.objects.all(), source=Order.Status.OPEN, to=Order.Status.CANCELLED)

        self.assertEqual(moved, 3)
        self.assertEqual(len(queries), 1)
