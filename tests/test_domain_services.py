"""
Comprehensive unit tests for ResolveX domain services (Phase 4).

Tests CustomerService, OrderService, PaymentService, ChatService, and TicketService
using mock Supabase PostgREST clients to verify business rules, database error wrapping,
and domain exception handling without live database mutations.
"""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock
import pytest

from Backend.core.exceptions import (
    DatabaseOperationError,
    InvalidOperationError,
    ResourceNotFoundError,
)
from Backend.schemas.common import (
    CustomerTier,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    SenderType,
    SessionStatus,
    TicketCategory,
    TicketPriority,
    TicketStatus,
)
from Backend.schemas.customer import CustomerCreate, CustomerUpdate
from Backend.schemas.order import OrderCreate, OrderItemCreate, OrderUpdate
from Backend.schemas.payment import PaymentCreate, PaymentUpdate
from Backend.schemas.chat import ChatSessionCreate, ChatSessionUpdate, MessageCreate
from Backend.schemas.ticket import TicketCreate, TicketUpdate
from Backend.services import (
    ChatService,
    CustomerService,
    OrderService,
    PaymentService,
    TicketService,
)


# Helper function to mock query chains
def create_mock_query(data=None, error=None):
    mock = MagicMock()
    if error:
        mock.execute.side_effect = error
    else:
        res = MagicMock()
        res.data = data
        mock.execute.return_value = res
    mock.select.return_value = mock
    mock.insert.return_value = mock
    mock.update.return_value = mock
    mock.delete.return_value = mock
    mock.eq.return_value = mock
    mock.order.return_value = mock
    mock.limit.return_value = mock
    return mock


# =============================================================================
# 1. CustomerService Tests
# =============================================================================

def test_customer_service_get_by_id_success():
    """Verify get_customer_by_id returns validated CustomerResponse."""
    mock_client = MagicMock()
    mock_query = create_mock_query(data=[{
        "customer_id": "CUST-001",
        "full_name": "Alice Johnson",
        "email": "alice@example.com",
        "phone": "+1234567890",
        "tier": "GOLD",
        "created_at": "2026-09-19T10:00:00Z",
        "updated_at": "2026-09-19T10:00:00Z",
    }])
    mock_client.table.return_value = mock_query

    service = CustomerService(client=mock_client)
    customer = service.get_customer_by_id("CUST-001")

    assert customer.customer_id == "CUST-001"
    assert customer.full_name == "Alice Johnson"
    assert customer.tier == CustomerTier.GOLD
    mock_client.table.assert_called_with("customers")
    mock_query.eq.assert_called_with("customer_id", "CUST-001")


def test_customer_service_get_by_id_not_found():
    """Verify get_customer_by_id raises ResourceNotFoundError when missing."""
    mock_client = MagicMock()
    mock_client.table.return_value = create_mock_query(data=[])

    service = CustomerService(client=mock_client)
    with pytest.raises(ResourceNotFoundError) as exc_info:
        service.get_customer_by_id("CUST-NONEXISTENT")

    assert exc_info.value.resource_type == "Customer"
    assert exc_info.value.resource_id == "CUST-NONEXISTENT"


def test_customer_service_get_by_email_success_and_none():
    """Verify get_customer_by_email returns CustomerResponse when found and None when absent."""
    mock_client = MagicMock()
    found_query = create_mock_query(data=[{
        "customer_id": "CUST-002",
        "full_name": "Bob Smith",
        "email": "bob@example.com",
        "tier": "STANDARD",
        "created_at": "2026-09-19T10:00:00Z",
        "updated_at": "2026-09-19T10:00:00Z",
    }])
    mock_client.table.return_value = found_query

    service = CustomerService(client=mock_client)
    res = service.get_customer_by_email("bob@example.com")
    assert res is not None
    assert res.email == "bob@example.com"

    mock_client.table.return_value = create_mock_query(data=[])
    res_none = service.get_customer_by_email("unknown@example.com")
    assert res_none is None


def test_customer_service_create_customer():
    """Verify create_customer inserts row and auto-generates ID if omitted."""
    mock_client = MagicMock()
    mock_query = create_mock_query(data=[{
        "customer_id": "CUST-12345",
        "full_name": "Charlie Brown",
        "email": "charlie@example.com",
        "phone": None,
        "tier": "PLATINUM",
        "created_at": "2026-09-19T10:00:00Z",
        "updated_at": "2026-09-19T10:00:00Z",
    }])
    mock_client.table.return_value = mock_query

    service = CustomerService(client=mock_client)
    payload = CustomerCreate(
        full_name="Charlie Brown",
        email="charlie@example.com",
        tier=CustomerTier.PLATINUM,
    )
    customer = service.create_customer(payload)

    assert customer.full_name == "Charlie Brown"
    assert customer.tier == CustomerTier.PLATINUM
    mock_query.insert.assert_called_once()


def test_customer_service_update_customer():
    """Verify update_customer updates fields and returns updated CustomerResponse."""
    mock_client = MagicMock()
    mock_query = create_mock_query(data=[{
        "customer_id": "CUST-001",
        "full_name": "Alice Updated",
        "email": "alice@example.com",
        "phone": "+9876543210",
        "tier": "PLATINUM",
        "created_at": "2026-09-19T10:00:00Z",
        "updated_at": "2026-09-19T11:00:00Z",
    }])
    mock_client.table.return_value = mock_query

    service = CustomerService(client=mock_client)
    payload = CustomerUpdate(full_name="Alice Updated", tier=CustomerTier.PLATINUM)
    updated = service.update_customer("CUST-001", payload)

    assert updated.full_name == "Alice Updated"
    assert updated.tier == CustomerTier.PLATINUM


def test_customer_service_db_error_wrapping():
    """Verify database exceptions are wrapped in DatabaseOperationError."""
    mock_client = MagicMock()
    mock_client.table.return_value = create_mock_query(error=RuntimeError("Connection reset"))

    service = CustomerService(client=mock_client)
    with pytest.raises(DatabaseOperationError) as exc_info:
        service.get_customer_by_id("CUST-001")

    assert exc_info.value.operation == "SELECT"
    assert exc_info.value.table_name == "customers"
    assert "Connection reset" in str(exc_info.value.__cause__)


# =============================================================================
# 2. OrderService Tests
# =============================================================================

def test_order_service_get_by_id_success():
    """Verify get_order_by_id returns OrderResponse."""
    mock_client = MagicMock()
    mock_query = create_mock_query(data=[{
        "order_id": "ORD-001",
        "customer_id": "CUST-001",
        "status": "PROCESSING",
        "total_amount": 99.99,
        "currency": "USD",
        "shipping_address": "123 Main St",
        "tracking_number": "TRK-123",
        "estimated_delivery": None,
        "created_at": "2026-09-19T10:00:00Z",
        "updated_at": "2026-09-19T10:00:00Z",
    }])
    mock_client.table.return_value = mock_query

    service = OrderService(client=mock_client)
    order = service.get_order_by_id("ORD-001")

    assert order.order_id == "ORD-001"
    assert order.status == OrderStatus.PROCESSING
    assert order.total_amount == Decimal("99.99")


def test_order_service_get_order_with_details():
    """Verify get_order_with_details fetches header, items, and payments."""
    mock_client = MagicMock()

    def table_router(table_name):
        if table_name == "orders":
            return create_mock_query(data=[{
                "order_id": "ORD-001",
                "customer_id": "CUST-001",
                "status": "SHIPPED",
                "total_amount": 150.00,
                "currency": "USD",
                "shipping_address": "123 Main St",
                "tracking_number": "TRK-999",
                "estimated_delivery": "2026-09-22T10:00:00Z",
                "created_at": "2026-09-19T10:00:00Z",
                "updated_at": "2026-09-19T10:00:00Z",
            }])
        elif table_name == "order_items":
            return create_mock_query(data=[{
                "item_id": "ITEM-1",
                "order_id": "ORD-001",
                "product_name": "Mechanical Keyboard",
                "quantity": 1,
                "unit_price": 150.00,
                "created_at": "2026-09-19T10:00:00Z",
            }])
        elif table_name == "payments":
            return create_mock_query(data=[{
                "payment_id": "PAY-1",
                "order_id": "ORD-001",
                "amount": 150.00,
                "status": "SUCCESS",
                "payment_method": "CREDIT_CARD",
                "transaction_ref": "TXN-999",
                "created_at": "2026-09-19T10:00:00Z",
                "updated_at": "2026-09-19T10:00:00Z",
            }])
        return create_mock_query(data=[])

    mock_client.table.side_effect = table_router
    service = OrderService(client=mock_client)
    composite = service.get_order_with_details("ORD-001")

    assert composite.order_id == "ORD-001"
    assert len(composite.items) == 1
    assert composite.items[0].product_name == "Mechanical Keyboard"
    assert len(composite.payments) == 1
    assert composite.payments[0]["status"] == "SUCCESS"


def test_order_service_create_order_with_items():
    """Verify create_order writes order and nested order items."""
    mock_client = MagicMock()

    orders_query = create_mock_query(data=[{
        "order_id": "ORD-NEW",
        "customer_id": "CUST-001",
        "status": "PENDING",
        "total_amount": 200.00,
        "currency": "USD",
        "shipping_address": "456 Market St",
        "tracking_number": None,
        "estimated_delivery": None,
        "created_at": "2026-09-19T10:00:00Z",
        "updated_at": "2026-09-19T10:00:00Z",
    }])
    items_query = create_mock_query(data=[{
        "item_id": "ITEM-NEW",
        "order_id": "ORD-NEW",
        "product_name": "Gaming Mouse",
        "quantity": 2,
        "unit_price": 100.00,
        "created_at": "2026-09-19T10:00:00Z",
    }])
    payments_query = create_mock_query(data=[])

    def table_router(table_name):
        if table_name == "orders":
            return orders_query
        elif table_name == "order_items":
            return items_query
        elif table_name == "payments":
            return payments_query
        return create_mock_query()

    mock_client.table.side_effect = table_router

    service = OrderService(client=mock_client)
    payload = OrderCreate(
        order_id="ORD-NEW",
        customer_id="CUST-001",
        shipping_address="456 Market St",
        items=[
            OrderItemCreate(product_name="Gaming Mouse", quantity=2, unit_price=Decimal("100.00"))
        ],
    )
    res = service.create_order(payload)

    assert res.order_id == "ORD-NEW"
    assert len(res.items) == 1
    assert res.items[0].quantity == 2


def test_order_service_create_order_partial_failure_on_items():
    """
    Verify that if order header insertion succeeds but order_items insertion fails,
    the service raises a DatabaseOperationError with context details and chained exception.
    NOTE: This verifies the current non-transactional behavior (no RPC rollback).
    """
    mock_client = MagicMock()

    orders_query = create_mock_query(data=[{
        "order_id": "ORD-PARTIAL",
        "customer_id": "CUST-001",
        "status": "PENDING",
        "total_amount": 100.00,
        "currency": "USD",
        "shipping_address": "456 Market St",
        "tracking_number": None,
        "estimated_delivery": None,
        "created_at": "2026-09-19T10:00:00Z",
        "updated_at": "2026-09-19T10:00:00Z",
    }])
    # items query fails
    items_query = create_mock_query(error=RuntimeError("Foreign key or constraint violation on order_items"))

    def table_router(table_name):
        if table_name == "orders":
            return orders_query
        elif table_name == "order_items":
            return items_query
        return create_mock_query()

    mock_client.table.side_effect = table_router

    service = OrderService(client=mock_client)
    payload = OrderCreate(
        order_id="ORD-PARTIAL",
        customer_id="CUST-001",
        items=[
            OrderItemCreate(product_name="Item A", quantity=1, unit_price=Decimal("100.00"))
        ],
    )

    with pytest.raises(DatabaseOperationError) as exc_info:
        service.create_order(payload)

    assert exc_info.value.operation == "INSERT"
    assert exc_info.value.details["order_id"] == "ORD-PARTIAL"
    assert exc_info.value.details["table"] == "order_items"
    assert "Foreign key or constraint violation" in str(exc_info.value.__cause__)


def test_order_service_forbidden_status_transition():
    """Verify invalid order state transitions raise InvalidOperationError."""
    mock_client = MagicMock()
    mock_query = create_mock_query(data=[{
        "order_id": "ORD-DELIVERED",
        "customer_id": "CUST-001",
        "status": "DELIVERED",
        "total_amount": 50.00,
        "currency": "USD",
        "shipping_address": None,
        "tracking_number": None,
        "estimated_delivery": None,
        "created_at": "2026-09-19T10:00:00Z",
        "updated_at": "2026-09-19T10:00:00Z",
    }])
    mock_client.table.return_value = mock_query

    service = OrderService(client=mock_client)

    # Attempt to cancel delivered order -> must fail
    with pytest.raises(InvalidOperationError) as exc_info:
        service.update_order_status("ORD-DELIVERED", OrderStatus.CANCELLED)

    assert "Cannot cancel an order that has already been delivered" in str(exc_info.value)


# =============================================================================
# 3. PaymentService Tests
# =============================================================================

def test_payment_service_get_and_create():
    """Verify create_payment and get_payment_by_id."""
    mock_client = MagicMock()
    mock_query = create_mock_query(data=[{
        "payment_id": "PAY-001",
        "order_id": "ORD-001",
        "amount": 75.50,
        "status": "PENDING",
        "payment_method": "UPI",
        "transaction_ref": "UPI-REF-123",
        "created_at": "2026-09-19T10:00:00Z",
        "updated_at": "2026-09-19T10:00:00Z",
    }])
    mock_client.table.return_value = mock_query

    service = PaymentService(client=mock_client)

    # Test create
    payload = PaymentCreate(
        payment_id="PAY-001",
        order_id="ORD-001",
        amount=Decimal("75.50"),
        payment_method=PaymentMethod.UPI,
        transaction_ref="UPI-REF-123",
    )
    payment = service.create_payment(payload)
    assert payment.payment_id == "PAY-001"
    assert payment.amount == Decimal("75.50")
    assert payment.payment_method == PaymentMethod.UPI

    # Test verify
    verified = service.verify_payment_status("PAY-001")
    assert verified.status == PaymentStatus.PENDING


def test_payment_service_refunded_cannot_be_reopened():
    """Verify attempting to modify status of a refunded payment raises InvalidOperationError."""
    mock_client = MagicMock()
    mock_query = create_mock_query(data=[{
        "payment_id": "PAY-REFUNDED",
        "order_id": "ORD-001",
        "amount": 100.00,
        "status": "REFUNDED",
        "payment_method": "CREDIT_CARD",
        "transaction_ref": "TX-1",
        "created_at": "2026-09-19T10:00:00Z",
        "updated_at": "2026-09-19T10:00:00Z",
    }])
    mock_client.table.return_value = mock_query

    service = PaymentService(client=mock_client)
    with pytest.raises(InvalidOperationError) as exc_info:
        service.update_payment_status("PAY-REFUNDED", PaymentUpdate(status=PaymentStatus.SUCCESS))

    assert "Cannot modify status of an already refunded payment" in str(exc_info.value)


# =============================================================================
# 4. ChatService Tests
# =============================================================================

def test_chat_service_create_and_get_session():
    """Verify creating and retrieving chat session."""
    mock_client = MagicMock()
    mock_query = create_mock_query(data=[{
        "session_id": "SES-001",
        "customer_id": "CUST-001",
        "channel": "WEB_CHAT",
        "status": "ACTIVE",
        "context_entities": {"active_order_id": "ORD-101"},
        "conversation_history": [],
        "metadata": {},
        "created_at": "2026-09-19T10:00:00Z",
        "updated_at": "2026-09-19T10:00:00Z",
    }])
    mock_client.table.return_value = mock_query

    service = ChatService(client=mock_client)
    session = service.create_session(ChatSessionCreate(
        session_id="SES-001",
        customer_id="CUST-001",
        context_entities={"active_order_id": "ORD-101"},
    ))

    assert session.session_id == "SES-001"
    assert session.context_entities["active_order_id"] == "ORD-101"

    retrieved = service.get_session("SES-001")
    assert retrieved.session_id == "SES-001"


def test_chat_service_add_message_and_get_messages():
    """Verify adding message to session and retrieving chronological messages."""
    mock_client = MagicMock()

    def table_router(table_name):
        if table_name == "chat_sessions":
            return create_mock_query(data=[{
                "session_id": "SES-001",
                "customer_id": None,
                "channel": "WEB_CHAT",
                "status": "ACTIVE",
                "context_entities": {},
                "conversation_history": [],
                "metadata": {},
                "created_at": "2026-09-19T10:00:00Z",
                "updated_at": "2026-09-19T10:00:00Z",
            }])
        elif table_name == "messages":
            return create_mock_query(data=[
                {
                    "message_id": "MSG-1",
                    "session_id": "SES-001",
                    "sender_type": "USER",
                    "content": "Where is my order?",
                    "metadata": {},
                    "created_at": "2026-09-19T10:00:01Z",
                },
                {
                    "message_id": "MSG-2",
                    "session_id": "SES-001",
                    "sender_type": "AGENT",
                    "content": "Let me look that up for you.",
                    "metadata": {},
                    "created_at": "2026-09-19T10:00:02Z",
                },
            ])
        return create_mock_query()

    mock_client.table.side_effect = table_router
    service = ChatService(client=mock_client)

    msg = service.add_message(MessageCreate(
        message_id="MSG-1",
        session_id="SES-001",
        sender_type=SenderType.USER,
        content="Where is my order?",
    ))
    assert msg.message_id == "MSG-1"

    messages = service.get_messages("SES-001")
    assert len(messages) == 2
    assert messages[0].sender_type == SenderType.USER
    assert messages[1].sender_type == SenderType.AGENT


# =============================================================================
# 5. TicketService Tests
# =============================================================================

def test_ticket_service_create_and_get():
    """Verify creating and retrieving support tickets."""
    mock_client = MagicMock()
    mock_query = create_mock_query(data=[{
        "ticket_id": "TCK-001",
        "customer_id": "CUST-001",
        "session_id": "SES-001",
        "order_id": "ORD-001",
        "category": "BILLING",
        "priority": "HIGH",
        "status": "OPEN",
        "subject": "Double charged on order",
        "description": "Customer was charged twice for order ORD-001.",
        "assigned_agent": None,
        "resolution_notes": None,
        "created_at": "2026-09-19T10:00:00Z",
        "updated_at": "2026-09-19T10:00:00Z",
    }])
    mock_client.table.return_value = mock_query

    service = TicketService(client=mock_client)
    ticket = service.create_ticket(TicketCreate(
        ticket_id="TCK-001",
        customer_id="CUST-001",
        session_id="SES-001",
        order_id="ORD-001",
        category=TicketCategory.BILLING,
        priority=TicketPriority.HIGH,
        subject="Double charged on order",
        description="Customer was charged twice for order ORD-001.",
    ))

    assert ticket.ticket_id == "TCK-001"
    assert ticket.category == TicketCategory.BILLING
    assert ticket.priority == TicketPriority.HIGH
    assert ticket.status == TicketStatus.OPEN


def test_ticket_service_escalate_ticket():
    """Verify ticket escalation sets status to ESCALATED, updates priority and notes."""
    mock_client = MagicMock()

    # Step 1 returns open ticket
    open_ticket_data = [{
        "ticket_id": "TCK-001",
        "customer_id": "CUST-001",
        "session_id": None,
        "order_id": None,
        "category": "TECHNICAL",
        "priority": "MEDIUM",
        "status": "OPEN",
        "subject": "App crash on login",
        "description": "App crashes repeatedly on iOS.",
        "assigned_agent": None,
        "resolution_notes": "Initial triage complete.",
        "created_at": "2026-09-19T10:00:00Z",
        "updated_at": "2026-09-19T10:00:00Z",
    }]

    # Step 2 returns escalated ticket
    escalated_ticket_data = [{
        "ticket_id": "TCK-001",
        "customer_id": "CUST-001",
        "session_id": None,
        "order_id": None,
        "category": "TECHNICAL",
        "priority": "URGENT",
        "status": "ESCALATED",
        "subject": "App crash on login",
        "description": "App crashes repeatedly on iOS.",
        "assigned_agent": "tier2_support",
        "resolution_notes": "Initial triage complete.\n[Escalated]: Customer unable to access paid account.",
        "created_at": "2026-09-19T10:00:00Z",
        "updated_at": "2026-09-19T10:30:00Z",
    }]

    query_mock = MagicMock()
    # First call to execute (get_ticket_by_id) returns open_ticket_data
    # Second call to execute (update_ticket) returns escalated_ticket_data
    res1 = MagicMock(data=open_ticket_data)
    res2 = MagicMock(data=escalated_ticket_data)
    query_mock.execute.side_effect = [res1, res2]
    query_mock.select.return_value = query_mock
    query_mock.update.return_value = query_mock
    query_mock.eq.return_value = query_mock
    mock_client.table.return_value = query_mock

    service = TicketService(client=mock_client)
    escalated = service.escalate_ticket(
        ticket_id="TCK-001",
        priority=TicketPriority.URGENT,
        reason="Customer unable to access paid account.",
        assigned_agent="tier2_support",
    )

    assert escalated.status == TicketStatus.ESCALATED
    assert escalated.priority == TicketPriority.URGENT
    assert escalated.assigned_agent == "tier2_support"
    assert "[Escalated]" in str(escalated.resolution_notes)


def test_ticket_service_cannot_escalate_closed_ticket():
    """Verify attempting to escalate a CLOSED ticket raises InvalidOperationError."""
    mock_client = MagicMock()
    mock_query = create_mock_query(data=[{
        "ticket_id": "TCK-CLOSED",
        "customer_id": "CUST-001",
        "session_id": None,
        "order_id": None,
        "category": "GENERAL",
        "priority": "LOW",
        "status": "CLOSED",
        "subject": "Resolved inquiry",
        "description": "Everything is working.",
        "assigned_agent": None,
        "resolution_notes": "Issue closed by user.",
        "created_at": "2026-09-19T10:00:00Z",
        "updated_at": "2026-09-19T10:00:00Z",
    }])
    mock_client.table.return_value = mock_query

    service = TicketService(client=mock_client)
    with pytest.raises(InvalidOperationError) as exc_info:
        service.escalate_ticket("TCK-CLOSED", reason="User reopened issue.")

    assert "Cannot escalate a closed support ticket" in str(exc_info.value)
