"""
Order service module for purchase orders and order item operations.
"""

import uuid
from decimal import Decimal
from typing import Any

from Backend.core.exceptions import (
    DatabaseOperationError,
    InvalidOperationError,
    ResourceNotFoundError,
)
from Backend.schemas.common import OrderStatus
from Backend.schemas.order import (
    OrderCreate,
    OrderItemCreate,
    OrderItemResponse,
    OrderResponse,
    OrderUpdate,
    OrderWithDetailsResponse,
)
from Backend.services.base import BaseService


class OrderService(BaseService):
    """
    Service class responsible for customer purchase orders and tracking inquiries.
    """

    table_name: str = "orders"
    items_table_name: str = "order_items"
    payments_table_name: str = "payments"

    @property
    def items_table(self) -> Any:
        """Returns the PostgREST query builder for order items."""
        return self.client.table(self.items_table_name)

    @property
    def payments_table(self) -> Any:
        """Returns the PostgREST query builder for payments."""
        return self.client.table(self.payments_table_name)

    def get_order_by_id(self, order_id: str) -> OrderResponse:
        """
        Retrieves a single order by its ID.

        Args:
            order_id: The unique order identifier.

        Returns:
            OrderResponse: The validated order record.

        Raises:
            ResourceNotFoundError: If the order does not exist.
            DatabaseOperationError: If the database query fails.
        """
        try:
            res = self.table.select("*").eq("order_id", order_id).execute()
        except Exception as exc:
            raise self._handle_db_error(
                operation="SELECT",
                exc=exc,
                details={"order_id": order_id},
            ) from exc

        if not res.data:
            raise ResourceNotFoundError(resource_type="Order", resource_id=order_id)

        return OrderResponse.model_validate(res.data[0])

    def get_order_items(self, order_id: str) -> list[OrderItemResponse]:
        """
        Retrieves all line items associated with an order.

        Args:
            order_id: The referenced order identifier.

        Returns:
            list[OrderItemResponse]: List of line items for the order.

        Raises:
            DatabaseOperationError: If the query fails.
        """
        try:
            res = self.items_table.select("*").eq("order_id", order_id).execute()
        except Exception as exc:
            raise self._handle_db_error(
                operation="SELECT",
                exc=exc,
                details={"order_id": order_id, "table": self.items_table_name},
            ) from exc

        return [OrderItemResponse.model_validate(row) for row in (res.data or [])]

    def get_order_with_details(self, order_id: str) -> OrderWithDetailsResponse:
        """
        Retrieves an order alongside its line items and associated payment records.

        Args:
            order_id: The unique order identifier.

        Returns:
            OrderWithDetailsResponse: Composite record with items and payments.

        Raises:
            ResourceNotFoundError: If the order is not found.
            DatabaseOperationError: If any query fails.
        """
        order = self.get_order_by_id(order_id)
        items = self.get_order_items(order_id)

        # Retrieve payments associated with this order
        try:
            pay_res = self.payments_table.select("*").eq("order_id", order_id).execute()
            payments = pay_res.data or []
        except Exception as exc:
            raise self._handle_db_error(
                operation="SELECT",
                exc=exc,
                details={"order_id": order_id, "table": self.payments_table_name},
            ) from exc

        order_dict = order.model_dump()
        order_dict["items"] = [item.model_dump() for item in items]
        order_dict["payments"] = payments

        return OrderWithDetailsResponse.model_validate(order_dict)

    def create_order(self, payload: OrderCreate) -> OrderWithDetailsResponse:
        """
        Creates an order and its associated line items atomically.

        Args:
            payload: Validated OrderCreate payload with optional items list.

        Returns:
            OrderWithDetailsResponse: Created composite order with items.

        Raises:
            DatabaseOperationError: If insertion fails.
        """
        order_id = payload.order_id or f"ORD-{uuid.uuid4().hex[:12].upper()}"

        # Calculate total amount if 0 and items provided
        total_amount = payload.total_amount
        if total_amount == Decimal("0.00") and payload.items:
            total_amount = sum(
                (Decimal(str(item.unit_price)) * item.quantity for item in payload.items),
                start=Decimal("0.00"),
            )

        order_data = payload.model_dump(mode="json", exclude={"items"}, exclude_none=True)
        order_data["order_id"] = order_id
        order_data["total_amount"] = float(total_amount)

        try:
            res = self.table.insert(order_data).execute()
        except Exception as exc:
            raise self._handle_db_error(
                operation="INSERT",
                exc=exc,
                details={"order_id": order_id, "customer_id": payload.customer_id},
            ) from exc

        if not res.data:
            raise DatabaseOperationError(
                operation="INSERT",
                table_name=self.table_name,
                message="Order record could not be created; empty response returned from database.",
                details={"order_id": order_id},
            )

        # Insert line items if any
        if payload.items:
            items_to_insert = []
            for item in payload.items:
                item_dict = item.model_dump(mode="json", exclude_none=True)
                item_dict["item_id"] = item.item_id or f"ITEM-{uuid.uuid4().hex[:12].upper()}"
                item_dict["order_id"] = order_id
                item_dict["unit_price"] = float(item.unit_price)
                items_to_insert.append(item_dict)

            try:
                self.items_table.insert(items_to_insert).execute()
            except Exception as exc:
                raise self._handle_db_error(
                    operation="INSERT",
                    exc=exc,
                    details={"order_id": order_id, "table": self.items_table_name},
                ) from exc

        return self.get_order_with_details(order_id)

    def update_order(self, order_id: str, payload: OrderUpdate) -> OrderResponse:
        """
        Updates fields on an existing order.

        Args:
            order_id: The unique order identifier.
            payload: OrderUpdate payload with fields to modify.

        Returns:
            OrderResponse: Updated order record.

        Raises:
            ResourceNotFoundError: If the order does not exist.
            DatabaseOperationError: If the update fails.
        """
        data = payload.model_dump(mode="json", exclude_unset=True)
        if not data:
            return self.get_order_by_id(order_id)

        # Check domain invariants if status is being updated
        if "status" in data:
            current_order = self.get_order_by_id(order_id)
            self._validate_status_transition(current_order.status, data["status"])

        if "total_amount" in data and data["total_amount"] is not None:
            data["total_amount"] = float(data["total_amount"])

        try:
            res = self.table.update(data).eq("order_id", order_id).execute()
        except Exception as exc:
            raise self._handle_db_error(
                operation="UPDATE",
                exc=exc,
                details={"order_id": order_id, "update_fields": list(data.keys())},
            ) from exc

        if not res.data:
            raise ResourceNotFoundError(resource_type="Order", resource_id=order_id)

        return OrderResponse.model_validate(res.data[0])

    def update_order_status(self, order_id: str, status: OrderStatus | str) -> OrderResponse:
        """
        Transitions an order to a new status with domain invariant validation.

        Args:
            order_id: The unique order identifier.
            status: Target OrderStatus enum or string value.

        Returns:
            OrderResponse: Updated order record.

        Raises:
            InvalidOperationError: If the transition violates business rules.
            ResourceNotFoundError: If the order does not exist.
            DatabaseOperationError: If the update fails.
        """
        status_value = status.value if isinstance(status, OrderStatus) else str(status).upper()
        return self.update_order(order_id, OrderUpdate(status=status_value))

    def _validate_status_transition(self, current_status: str, new_status: str) -> None:
        """
        Enforces domain rules for order state transitions.

        Raises:
            InvalidOperationError: If transition is forbidden.
        """
        current_status = str(current_status).upper()
        new_status = str(new_status).upper()

        if current_status == OrderStatus.DELIVERED.value and new_status == OrderStatus.CANCELLED.value:
            raise InvalidOperationError(
                operation="update_order_status",
                reason="Cannot cancel an order that has already been delivered.",
            )

        if current_status == OrderStatus.CANCELLED.value and new_status in {
            OrderStatus.SHIPPED.value,
            OrderStatus.DELIVERED.value,
        }:
            raise InvalidOperationError(
                operation="update_order_status",
                reason="Cannot ship or deliver a cancelled order.",
            )

