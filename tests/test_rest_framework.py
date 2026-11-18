from django.http import Http404
from django.test import TestCase
from django.utils.functional import Promise
from rest_framework import status
from rest_framework.exceptions import ValidationError

from phase.contrib.rest_framework import (
    ILLEGAL_PHASE_TRANSITION_DETAIL,
    STALE_PHASE_DETAIL,
    PhaseConflictError,
    exception_handler,
    to_conflict_error,
)
from phase.exceptions import IllegalPhaseTransitionError, PhaseGuardError, StalePhaseError


class OrderAlreadyShippedError(PhaseGuardError):
    code = "order_already_shipped"
    detail = "The order has already been shipped."


ILLEGAL_TRANSITION = IllegalPhaseTransitionError(model_name="shop.Order", pk=7, source="open", target="shipped")
STALE_PHASE = StalePhaseError(model_name="shop.Order", pk=7, phases={"status": "open"})


class ExceptionHandlerTest(TestCase):
    def test_phase_guard_error(self):
        response = exception_handler(OrderAlreadyShippedError("Order ID #7 is already shipped."), {})

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(
            response.data, {"code": "order_already_shipped", "detail": "The order has already been shipped."}
        )

    def test_illegal_phase_transition(self):
        response = exception_handler(ILLEGAL_TRANSITION, {})

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(
            response.data,
            {
                "code": "illegal_phase_transition",
                "detail": "This action isn't possible in the current status. Reload the page to see it.",
            },
        )

    def test_stale_phase(self):
        response = exception_handler(STALE_PHASE, {})

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(
            response.data,
            {"code": "stale_phase", "detail": "The data was changed in the meantime. Reload the page and try again."},
        )

    def test_other_api_exception_goes_to_default_handler(self):
        response = exception_handler(ValidationError({"note": ["Too long."]}), {})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data, {"note": ["Too long."]})

    def test_django_exception_goes_to_default_handler(self):
        self.assertEqual(exception_handler(Http404(), {}).status_code, status.HTTP_404_NOT_FOUND)

    def test_unhandled_exception_stays_unhandled(self):
        self.assertIsNone(exception_handler(ValueError("boom"), {}))


class ToConflictErrorTest(TestCase):
    def test_codes_of_refused_actions(self):
        for exc, code in (
            (OrderAlreadyShippedError(), "order_already_shipped"),
            (ILLEGAL_TRANSITION, "illegal_phase_transition"),
            (STALE_PHASE, "stale_phase"),
        ):
            with self.subTest(code=code):
                conflict = to_conflict_error(exc)

                self.assertIsInstance(conflict, PhaseConflictError)
                self.assertEqual(conflict.get_codes(), {"code": code, "detail": code})

    def test_other_exception(self):
        self.assertIsNone(to_conflict_error(ValueError("boom")))

    def test_default_texts_are_translatable(self):
        self.assertIsInstance(ILLEGAL_PHASE_TRANSITION_DETAIL, Promise)
        self.assertIsInstance(STALE_PHASE_DETAIL, Promise)

    def test_phase_guard_error_without_code_and_detail(self):
        conflict = to_conflict_error(PhaseGuardError("Order ID #7 can't be changed."))

        self.assertEqual(conflict.get_codes(), {"code": "phase_guard", "detail": "phase_guard"})
        self.assertEqual(conflict.detail["detail"], "This action isn't possible right now.")
