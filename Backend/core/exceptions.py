"""
Custom exception hierarchy for the ResolveX platform.

Provides structured, domain-specific exceptions for error handling,
resource resolution, database interactions, and business rule enforcement.
"""

from typing import Any


class ResolveXException(Exception):
    """
    Base exception for all ResolveX application and domain errors.

    Attributes:
        message: Human-readable error explanation.
        details: Optional dictionary containing context/metadata about the error.
    """

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} (details={self.details})"
        return self.message


class ResourceNotFoundError(ResolveXException):
    """
    Raised when a requested domain entity (Customer, Order, Payment, Session, Ticket)
    cannot be located in the database.

    Attributes:
        resource_type: Name of the resource entity (e.g., 'Customer', 'Order').
        resource_id: Identifier of the resource that was not found.
    """

    def __init__(
        self,
        resource_type: str,
        resource_id: str | None = None,
        message: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.resource_type = resource_type
        self.resource_id = resource_id
        if message is None:
            if resource_id is not None:
                message = f"{resource_type} with ID '{resource_id}' was not found."
            else:
                message = f"{resource_type} was not found."
        merged_details = {"resource_type": resource_type, "resource_id": resource_id}
        if details:
            merged_details.update(details)
        super().__init__(message=message, details=merged_details)


class DatabaseOperationError(ResolveXException):
    """
    Raised when a database query, transaction, or mutation fails due to
    connection drops, schema constraint violations, or unexpected PostgREST errors.

    Supports exception chaining using the standard Python `raise ... from original_exc` pattern.

    Attributes:
        operation: The database operation being attempted (e.g., 'SELECT', 'INSERT', 'UPDATE').
        table_name: The target table name (e.g., 'orders', 'payments').
    """

    def __init__(
        self,
        operation: str,
        table_name: str | None = None,
        message: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.operation = operation
        self.table_name = table_name
        if message is None:
            if table_name is not None:
                message = f"Database error during {operation} on table '{table_name}'."
            else:
                message = f"Database error during {operation}."
        merged_details = {"operation": operation, "table_name": table_name}
        if details:
            merged_details.update(details)
        super().__init__(message=message, details=merged_details)


class InvalidOperationError(ResolveXException):
    """
    Raised when a business rule, invariant, or invalid state transition is violated
    (e.g., attempting to cancel an already delivered order, or updating a closed ticket).

    Attributes:
        operation: The attempted operation.
        reason: The underlying reason why the operation is invalid.
    """

    def __init__(
        self,
        operation: str,
        reason: str,
        message: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.operation = operation
        self.reason = reason
        if message is None:
            message = f"Invalid operation '{operation}': {reason}"
        merged_details = {"operation": operation, "reason": reason}
        if details:
            merged_details.update(details)
        super().__init__(message=message, details=merged_details)
