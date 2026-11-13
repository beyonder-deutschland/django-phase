from django.contrib.auth.models import Group
from django.test import TestCase

from phase.exceptions import IllegalPhaseTransitionError, MissingPhaseFieldError
from phase.fields import get_phase_field
from phase.transitions import can_transition, move, move_many, targets
from testapp.models import Order


class TransitionsTest(TestCase):
    def test_get_phase_field_finds_the_field(self):
        self.assertIs(get_phase_field(model=Order), Order._meta.get_field("status"))

    def test_get_phase_field_of_model_without_one(self):
        with self.assertRaisesMessage(MissingPhaseFieldError, "auth.Group has no PhaseField."):
            get_phase_field(model=Group)

    def test_move(self):
        order = Order.objects.create()

        move(obj=order, to=Order.Status.PAID, note="paid")

        self.assertEqual(order.status, Order.Status.PAID)
        self.assertEqual(order.note, "paid")

    def test_move_refuses_illegal_transition(self):
        order = Order.objects.create()

        with self.assertRaises(IllegalPhaseTransitionError):
            move(obj=order, to=Order.Status.SHIPPED)

    def test_move_many(self):
        order = Order.objects.create()

        moved = move_many(
            queryset=Order.objects.filter(pk=order.pk), source=Order.Status.OPEN, to=Order.Status.PAID, note="paid"
        )

        self.assertEqual(moved, 1)
        order.refresh_from_db()
        self.assertEqual((order.status, order.note), (Order.Status.PAID, "paid"))

    def test_move_many_of_model_without_phase_field(self):
        with self.assertRaises(MissingPhaseFieldError):
            move_many(queryset=Group.objects.all(), source="open", to="paid")

    def test_can_transition(self):
        order = Order(status=Order.Status.PAID)

        self.assertTrue(can_transition(obj=order, to=Order.Status.SHIPPED))
        self.assertFalse(can_transition(obj=order, to=Order.Status.OPEN))

    def test_targets(self):
        self.assertEqual(targets(obj=Order(status=Order.Status.PAID)), (Order.Status.SHIPPED,))
