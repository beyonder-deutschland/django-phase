from django.test import TestCase

from phase.exceptions import IllegalPhaseTransitionError
from phase.transitions import can_transition, move, phase_field, targets
from testapp.models import Order


class TransitionsTest(TestCase):
    def test_phase_field_finds_the_field(self):
        self.assertIs(phase_field(model=Order), Order._meta.get_field("status"))

    def test_move(self):
        order = Order.objects.create()

        move(obj=order, to=Order.Status.PAID, note="paid")

        self.assertEqual(order.status, Order.Status.PAID)
        self.assertEqual(order.note, "paid")

    def test_move_refuses_illegal_transition(self):
        order = Order.objects.create()

        with self.assertRaises(IllegalPhaseTransitionError):
            move(obj=order, to=Order.Status.SHIPPED)

    def test_can_transition(self):
        order = Order(status=Order.Status.PAID)

        self.assertTrue(can_transition(obj=order, to=Order.Status.SHIPPED))
        self.assertFalse(can_transition(obj=order, to=Order.Status.OPEN))

    def test_targets(self):
        self.assertEqual(targets(obj=Order(status=Order.Status.PAID)), (Order.Status.SHIPPED,))
