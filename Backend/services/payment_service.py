"""
Payment service module for financial transactions and payment gateway records.
"""

import uuid
from typing import Any

from Backend.core.exceptions import (
    DatabaseOperationError,
    InvalidOperationError,
    ResourceNotFoundError,
)
from Backend.schemas.common import PaymentStatus
from Backend.schemas.payment import (
    PaymentCreate,
    PaymentResponse,
    PaymentUpdate,
)
from Backend.services.base import BaseService


class PaymentService(BaseService):
    """
    Service class responsible for payment status lookups and transaction history.
    """

    table_name: str = "payments"

    def get_payment_by_id(self, payment_id: str) -> PaymentResponse:
        """
        Retrieves a payment transaction by its ID.

        Args:
            payment_id: The unique payment identifier.

        Returns:
            PaymentResponse: The validated payment record.

        Raises:
            ResourceNotFoundError: If the payment record does not exist.
            DatabaseOperationError: If the database query fails.
        """
        try:
            res = self.table.select("*").eq("payment_id", payment_id).execute()
        except Exception as exc:
            raise self._handle_db_error(
                operation="SELECT",
                exc=exc,
                details={"payment_id": payment_id},
            ) from exc

        if not res.data:
            raise ResourceNotFoundError(resource_type="Payment", resource_id=payment_id)

        return PaymentResponse.model_validate(res.data[0])

    def get_payments_by_order_id(self, order_id: str) -> list[PaymentResponse]:
        """
        Retrieves all payment transactions associated with an order.

        Args:
            order_id: The referenced order identifier.

        Returns:
            list[PaymentResponse]: List of payment records.

        Raises:
            DatabaseOperationError: If the query fails.
        """
        try:
            res = self.table.select("*").eq("order_id", order_id).execute()
        except Exception as exc:
            raise self._handle_db_error(
                operation="SELECT",
                exc=exc,
                details={"order_id": order_id},
            ) from exc

        return [PaymentResponse.model_validate(row) for row in (res.data or [])]

    def create_payment(self, payload: PaymentCreate) -> PaymentResponse:
        """
        Creates a new payment transaction record.

        Args:
            payload: Validated PaymentCreate schema payload.

        Returns:
            PaymentResponse: The recorded payment with timestamps.

        Raises:
            DatabaseOperationError: If insertion fails.
        """
        payment_id = payload.payment_id or f"PAY-{uuid.uuid4().hex[:12].upper()}"
        data = payload.model_dump(mode="json", exclude_none=True)
        data["payment_id"] = payment_id
        data["amount"] = float(payload.amount)

        try:
            res = self.table.insert(data).execute()
        except Exception as exc:
            raise self._handle_db_error(
                operation="INSERT",
                exc=exc,
                details={"payment_id": payment_id, "order_id": payload.order_id},
            ) from exc

        if not res.data:
            raise DatabaseOperationError(
                operation="INSERT",
                table_name=self.table_name,
                message="Payment record could not be created; empty response returned from database.",
                details={"payment_id": payment_id},
            )

        return PaymentResponse.model_validate(res.data[0])

    def verify_payment_status(self, payment_id: str) -> PaymentResponse:
        """
        Verifies and returns the current status of a payment transaction.

        Args:
            payment_id: The unique payment identifier.

        Returns:
            PaymentResponse: The verified payment transaction record.

        Raises:
            ResourceNotFoundError: If the payment is not found.
            DatabaseOperationError: If the database lookup fails.
        """
        return self.get_payment_by_id(payment_id)

    def update_payment_status(self, payment_id: str, payload: PaymentUpdate) -> PaymentResponse:
        """
        Updates an existing payment transaction's status or gateway reference.

        Args:
            payment_id: The unique payment identifier.
            payload: PaymentUpdate payload containing modified attributes.

        Returns:
            PaymentResponse: The updated payment transaction.

        Raises:
            InvalidOperationError: If attempting an illegal transition (e.g. from REFUNDED).
            ResourceNotFoundError: If the payment does not exist.
            DatabaseOperationError: If the update fails.
        """
        data = payload.model_dump(mode="json", exclude_unset=True)
        if not data:
            return self.get_payment_by_id(payment_id)

        # Enforce domain transition rules
        if "status" in data and data["status"] is not None:
            current_payment = self.get_payment_by_id(payment_id)
            if (
                current_payment.status == PaymentStatus.REFUNDED.value
                and data["status"] != PaymentStatus.REFUNDED.value
            ):
                raise InvalidOperationError(
                    operation="update_payment_status",
                    reason="Cannot modify status of an already refunded payment.",
                )

        try:
            res = self.table.update(data).eq("payment_id", payment_id).execute()
        except Exception as exc:
            raise self._handle_db_error(
                operation="UPDATE",
                exc=exc,
                details={"payment_id": payment_id, "update_fields": list(data.keys())},
            ) from exc

        if not res.data:
            raise ResourceNotFoundError(resource_type="Payment", resource_id=payment_id)

        return PaymentResponse.model_validate(res.data[0])

