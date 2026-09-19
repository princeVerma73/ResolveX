"""
Customer service module for managing customer profiles and account queries.
"""

import uuid
from typing import Any

from Backend.core.exceptions import DatabaseOperationError, ResourceNotFoundError
from Backend.schemas.customer import CustomerCreate, CustomerResponse, CustomerUpdate
from Backend.services.base import BaseService


class CustomerService(BaseService):
    """
    Service class responsible for customer profile management and lookup operations.
    """

    table_name: str = "customers"

    def get_customer_by_id(self, customer_id: str) -> CustomerResponse:
        """
        Retrieves a customer by their unique ID.

        Args:
            customer_id: The unique customer identifier.

        Returns:
            CustomerResponse: The validated customer record.

        Raises:
            ResourceNotFoundError: If the customer does not exist.
            DatabaseOperationError: If the database query fails.
        """
        try:
            res = self.table.select("*").eq("customer_id", customer_id).execute()
        except Exception as exc:
            raise self._handle_db_error(
                operation="SELECT",
                exc=exc,
                details={"customer_id": customer_id},
            ) from exc

        if not res.data:
            raise ResourceNotFoundError(resource_type="Customer", resource_id=customer_id)

        return CustomerResponse.model_validate(res.data[0])

    def get_customer_by_email(self, email: str) -> CustomerResponse | None:
        """
        Retrieves a customer by their unique email address.

        Args:
            email: The customer's email address.

        Returns:
            CustomerResponse | None: Customer record if found, otherwise None.

        Raises:
            DatabaseOperationError: If the database query fails.
        """
        try:
            res = self.table.select("*").eq("email", email.strip()).execute()
        except Exception as exc:
            raise self._handle_db_error(
                operation="SELECT",
                exc=exc,
                details={"email": email},
            ) from exc

        if not res.data:
            return None

        return CustomerResponse.model_validate(res.data[0])

    def create_customer(self, payload: CustomerCreate) -> CustomerResponse:
        """
        Creates a new customer profile.

        Args:
            payload: Validated CustomerCreate schema payload.

        Returns:
            CustomerResponse: The created customer record with timestamps.

        Raises:
            DatabaseOperationError: If insertion violates constraints or fails.
        """
        customer_id = payload.customer_id or f"CUST-{uuid.uuid4().hex[:12].upper()}"
        data = payload.model_dump(mode="json", exclude_none=True)
        data["customer_id"] = customer_id

        try:
            res = self.table.insert(data).execute()
        except Exception as exc:
            raise self._handle_db_error(
                operation="INSERT",
                exc=exc,
                details={"customer_id": customer_id, "email": payload.email},
            ) from exc

        if not res.data:
            raise DatabaseOperationError(
                operation="INSERT",
                table_name=self.table_name,
                message="Customer record could not be created; empty response returned from database.",
                details={"customer_id": customer_id},
            )

        return CustomerResponse.model_validate(res.data[0])

    def update_customer(self, customer_id: str, payload: CustomerUpdate) -> CustomerResponse:
        """
        Updates an existing customer profile with partial data.

        Args:
            customer_id: The unique customer identifier.
            payload: CustomerUpdate schema containing fields to update.

        Returns:
            CustomerResponse: The updated customer record.

        Raises:
            ResourceNotFoundError: If the customer does not exist.
            DatabaseOperationError: If the database update fails.
        """
        data = payload.model_dump(mode="json", exclude_unset=True)
        if not data:
            # Nothing to update; return existing customer record
            return self.get_customer_by_id(customer_id)

        try:
            res = self.table.update(data).eq("customer_id", customer_id).execute()
        except Exception as exc:
            raise self._handle_db_error(
                operation="UPDATE",
                exc=exc,
                details={"customer_id": customer_id, "update_fields": list(data.keys())},
            ) from exc

        if not res.data:
            raise ResourceNotFoundError(resource_type="Customer", resource_id=customer_id)

        return CustomerResponse.model_validate(res.data[0])

