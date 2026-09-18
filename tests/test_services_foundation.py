"""Unit tests for ResolveX service layer foundation and custom exceptions."""

import pytest
from unittest.mock import MagicMock

from Backend.core.exceptions import (
    DatabaseOperationError,
    InvalidOperationError,
    ResourceNotFoundError,
    ResolveXException,
)
from Backend.services import (
    BaseService,
    ChatService,
    CustomerService,
    OrderService,
    PaymentService,
    TicketService,
)


# =============================================================================
# 1. Custom Exceptions Tests
# =============================================================================

def test_resolvex_exception_basic():
    """Verify base exception message and details."""
    exc = ResolveXException("Base error occurred", details={"module": "test"})
    assert str(exc) == "Base error occurred (details={'module': 'test'})"
    assert exc.message == "Base error occurred"
    assert exc.details == {"module": "test"}

    exc_no_details = ResolveXException("Simple error")
    assert str(exc_no_details) == "Simple error"
    assert exc_no_details.details == {}


def test_resource_not_found_error_with_id():
    """Verify ResourceNotFoundError with ID formatting."""
    exc = ResourceNotFoundError(resource_type="Order", resource_id="ORD-101")
    assert isinstance(exc, ResolveXException)
    assert exc.resource_type == "Order"
    assert exc.resource_id == "ORD-101"
    assert "Order with ID 'ORD-101' was not found" in str(exc)
    assert exc.details["resource_type"] == "Order"
    assert exc.details["resource_id"] == "ORD-101"


def test_resource_not_found_error_without_id():
    """Verify ResourceNotFoundError without specific ID."""
    exc = ResourceNotFoundError(resource_type="ActiveSession")
    assert "ActiveSession was not found" in str(exc)
    assert exc.resource_id is None


def test_database_operation_error():
    """Verify DatabaseOperationError attributes and message."""
    exc = DatabaseOperationError(operation="INSERT", table_name="customers")
    assert isinstance(exc, ResolveXException)
    assert exc.operation == "INSERT"
    assert exc.table_name == "customers"
    assert "Database error during INSERT on table 'customers'" in str(exc)


def test_database_operation_error_chaining():
    """Verify exception chaining using standard Python from syntax."""
    original_exc = ConnectionResetError("Connection lost to database")
    try:
        try:
            raise original_exc
        except ConnectionResetError as err:
            raise DatabaseOperationError(
                operation="SELECT",
                table_name="orders",
                details={"host": "supabase.co"},
            ) from err
    except DatabaseOperationError as db_err:
        assert db_err.__cause__ is original_exc
        assert isinstance(db_err.__cause__, ConnectionResetError)


def test_invalid_operation_error():
    """Verify InvalidOperationError formatting and attributes."""
    exc = InvalidOperationError(
        operation="CANCEL_ORDER",
        reason="Order has already been shipped",
    )
    assert isinstance(exc, ResolveXException)
    assert exc.operation == "CANCEL_ORDER"
    assert exc.reason == "Order has already been shipped"
    assert "Invalid operation 'CANCEL_ORDER': Order has already been shipped" in str(exc)


# =============================================================================
# 2. BaseService & Error Handling Tests
# =============================================================================

def test_base_service_custom_client_injection():
    """Verify BaseService accepts an injected client."""
    mock_client = MagicMock()
    service = BaseService(client=mock_client)
    assert service.client is mock_client


def test_base_service_table_unconfigured_raises_error():
    """Verify accessing .table on unconfigured BaseService raises ValueError."""
    mock_client = MagicMock()
    service = BaseService(client=mock_client)
    with pytest.raises(ValueError, match="table_name is not configured"):
        _ = service.table


def test_base_service_table_access():
    """Verify .table calls client.table with configured table_name."""
    mock_client = MagicMock()
    service = BaseService(client=mock_client)
    service.table_name = "test_table"
    _ = service.table
    mock_client.table.assert_called_once_with("test_table")


def test_base_service_handle_db_error_creates_chained_exception():
    """Verify BaseService._handle_db_error constructs a chained DatabaseOperationError."""
    service = BaseService(client=MagicMock())
    service.table_name = "orders"
    original_exc = RuntimeError("PostgREST timeout")

    db_err = service._handle_db_error("UPDATE", original_exc, details={"order_id": "ORD-123"})
    assert isinstance(db_err, DatabaseOperationError)
    assert db_err.__cause__ is original_exc
    assert db_err.table_name == "orders"
    assert db_err.operation == "UPDATE"
    assert db_err.details["order_id"] == "ORD-123"
    assert db_err.details["original_error"] == "PostgREST timeout"


# =============================================================================
# 3. Domain Service Structure & Table Binding Tests
# =============================================================================

def test_customer_service_table_binding():
    """Verify CustomerService inheritance and table name."""
    mock_client = MagicMock()
    service = CustomerService(client=mock_client)
    assert isinstance(service, BaseService)
    assert service.table_name == "customers"
    _ = service.table
    mock_client.table.assert_called_once_with("customers")


def test_order_service_table_binding():
    """Verify OrderService inheritance and table names."""
    mock_client = MagicMock()
    service = OrderService(client=mock_client)
    assert isinstance(service, BaseService)
    assert service.table_name == "orders"
    assert service.items_table_name == "order_items"
    _ = service.table
    mock_client.table.assert_called_once_with("orders")


def test_payment_service_table_binding():
    """Verify PaymentService inheritance and table name."""
    mock_client = MagicMock()
    service = PaymentService(client=mock_client)
    assert isinstance(service, BaseService)
    assert service.table_name == "payments"
    _ = service.table
    mock_client.table.assert_called_once_with("payments")


def test_chat_service_table_binding():
    """Verify ChatService inheritance and table names."""
    mock_client = MagicMock()
    service = ChatService(client=mock_client)
    assert isinstance(service, BaseService)
    assert service.table_name == "chat_sessions"
    assert service.messages_table_name == "messages"
    _ = service.table
    mock_client.table.assert_called_once_with("chat_sessions")


def test_ticket_service_table_binding():
    """Verify TicketService inheritance and table name."""
    mock_client = MagicMock()
    service = TicketService(client=mock_client)
    assert isinstance(service, BaseService)
    assert service.table_name == "tickets"
    _ = service.table
    mock_client.table.assert_called_once_with("tickets")
