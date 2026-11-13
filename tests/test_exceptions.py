import pickle

from django.test import SimpleTestCase

from phase.exceptions import IllegalPhaseTransitionError, PhaseGuardError, StalePhaseError


class IllegalPhaseTransitionErrorTest(SimpleTestCase):
    def test_message(self):
        error = IllegalPhaseTransitionError(model_name="shop.Order", pk=7, source="open", target="shipped")

        self.assertEqual(str(error), "shop.Order ID #7 cannot change from 'open' to 'shipped'.")

    def test_survives_pickling(self):
        error = IllegalPhaseTransitionError(model_name="shop.Order", pk=7, source="open", target="shipped")

        restored = pickle.loads(pickle.dumps(error))

        self.assertEqual(
            (restored.model_name, restored.pk, restored.source, restored.target), ("shop.Order", 7, "open", "shipped")
        )
        self.assertEqual(str(restored), str(error))


class StalePhaseErrorTest(SimpleTestCase):
    def test_message(self):
        error = StalePhaseError(model_name="shop.Order", pk=7, phases={"status": "open"})

        self.assertEqual(
            str(error), "shop.Order ID #7 no longer has status='open' in the database; reload it before saving."
        )

    def test_survives_pickling(self):
        error = StalePhaseError(model_name="shop.Order", pk=7, phases={"status": "open"})

        restored = pickle.loads(pickle.dumps(error))

        self.assertEqual((restored.model_name, restored.pk, restored.phases), ("shop.Order", 7, {"status": "open"}))
        self.assertEqual(str(restored), str(error))


class PhaseGuardErrorTest(SimpleTestCase):
    def test_subclass_carries_code_and_detail(self):
        class OrderAlreadyShippedError(PhaseGuardError):
            code = "order_already_shipped"
            detail = "The order has already been shipped."

        error = OrderAlreadyShippedError("Order ID #7 is already shipped.")

        self.assertEqual(error.code, "order_already_shipped")
        self.assertEqual(error.detail, "The order has already been shipped.")
        self.assertEqual(str(error), "Order ID #7 is already shipped.")
