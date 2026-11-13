import pickle

from django.test import SimpleTestCase

from phase.exceptions import (
    IllegalPhaseTransitionError,
    InvalidTransitionTableError,
    MissingPhaseFieldError,
    PhaseGuardError,
    ProtectedPhaseFieldError,
    StalePhaseError,
)


class OrderAlreadyShippedError(PhaseGuardError):
    code = "order_already_shipped"
    detail = "The order has already been shipped."

    def __init__(self, *, pk: int):
        self.pk = pk
        super().__init__(f"Order ID #{pk} is already shipped.")


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

    def test_subclass_with_keyword_constructor_survives_pickling(self):
        error = OrderAlreadyShippedError(pk=7)

        restored = pickle.loads(pickle.dumps(error))

        self.assertIsInstance(restored, OrderAlreadyShippedError)
        self.assertEqual(restored.pk, 7)
        self.assertEqual(str(restored), str(error))


class KeywordConstructorErrorsTest(SimpleTestCase):
    def test_survive_pickling(self):
        errors = (
            ProtectedPhaseFieldError(field_name="status"),
            InvalidTransitionTableError(source="open"),
            MissingPhaseFieldError(model_name="shop.Order"),
        )
        for error in errors:
            with self.subTest(error=type(error).__name__):
                restored = pickle.loads(pickle.dumps(error))

                self.assertIs(type(restored), type(error))
                self.assertEqual(str(restored), str(error))


class MissingPhaseFieldErrorTest(SimpleTestCase):
    def test_message(self):
        self.assertEqual(str(MissingPhaseFieldError(model_name="shop.Order")), "shop.Order has no PhaseField.")
