"""Unit tests for ResolveX Pydantic domain models and validation schemas."""

from datetime import datetime, timezone
from decimal import Decimal
import pytest
from pydantic import ValidationError

from Backend.schemas import (
    CustomerCreate,
    CustomerResponse,
    CustomerTier,
    CustomerUpdate,
    OrderCreate,
    OrderItemCreate,
    OrderItemResponse,
    OrderResponse,
    OrderStatus,
    OrderUpdate,
    OrderWithDetailsResponse,
    PaymentCreate,
    PaymentMethod,
    PaymentResponse,
    PaymentStatus,
    PaymentUpdate,
    ChatSessionCreate,
    ChatSessionResponse,
    ChatSessionUpdate,
    ChatSessionWithMessagesResponse,
    MessageCreate,
    MessageResponse,
    SenderType,
    SessionStatus,
    TicketCategory,
    TicketCreate,
    TicketPriority,
    TicketResponse,
    TicketStatus,
    TicketUpdate,
)


# =============================================================================
# 1. Customer Schema Tests
# =============================================================================

def test_customer_create_valid():
    """Verify customer creation with standard and default attributes."""
    data = {"full_name": "Alice Smith", "email": "alice@example.com"}
    customer = CustomerCreate(**data)
    assert customer.full_name == "Alice Smith"
    assert customer.email == "alice@example.com"
    assert customer.tier == CustomerTier.STANDARD
    assert customer.phone is None
    assert customer.customer_id is None


def test_customer_create_custom_tier():
    """Verify tier assignment and validation."""
    data = {
        "customer_id": "CUST-001",
        "full_name": "Bob Jones",
        "email": "bob@example.com",
        "phone": "+1-555-0199",
        "tier": "PLATINUM",
    }
    customer = CustomerCreate(**data)
    assert customer.customer_id == "CUST-001"
    assert customer.tier == CustomerTier.PLATINUM


def test_customer_invalid_email_raises_error():
    """Verify email format validation."""
    with pytest.raises(ValidationError):
        CustomerCreate(full_name="Bad Email", email="not-an-email")


def test_customer_invalid_tier_raises_error():
    """Verify check constraint tier validation."""
    with pytest.raises(ValidationError):
        CustomerCreate(full_name="Bad Tier", email="tier@test.com", tier="DIAMOND")


def test_customer_response_parsing():
    """Verify full customer response deserialization from DB row format."""
    raw_db_row = {
        "customer_id": "CUST-100",
        "full_name": "Charlie Brown",
        "email": "charlie@peanuts.com",
        "phone": "555-1234",
        "tier": "GOLD",
        "created_at": "2026-09-17T12:00:00Z",
        "updated_at": "2026-09-17T12:05:00Z",
    }
    customer = CustomerResponse.model_validate(raw_db_row)
    assert customer.customer_id == "CUST-100"
    assert customer.tier == CustomerTier.GOLD
    assert isinstance(customer.created_at, datetime)


# =============================================================================
# 2. Order & Order Item Schema Tests
# =============================================================================

def test_order_item_valid():
    """Verify line item creation with decimal price and integer quantity."""
    item = OrderItemCreate(product_name="Wireless Noise-Canceling Headphones", quantity=2, unit_price=Decimal("149.99"))
    assert item.product_name == "Wireless Noise-Canceling Headphones"
    assert item.quantity == 2
    assert item.unit_price == Decimal("149.99")


def test_order_item_invalid_quantity():
    """Verify line item quantity must be > 0."""
    with pytest.raises(ValidationError):
        OrderItemCreate(product_name="Sample", quantity=0, unit_price=Decimal("10.00"))


def test_order_item_invalid_price():
    """Verify line item price cannot be negative."""
    with pytest.raises(ValidationError):
        OrderItemCreate(product_name="Sample", quantity=1, unit_price=Decimal("-5.00"))


def test_order_create_with_nested_items():
    """Verify order creation with nested item payloads."""
    order = OrderCreate(
        customer_id="CUST-001",
        status=OrderStatus.PENDING,
        total_amount=Decimal("299.98"),
        shipping_address="123 AI Boulevard, San Francisco, CA",
        items=[
            OrderItemCreate(product_name="Item 1", quantity=1, unit_price=Decimal("199.99")),
            OrderItemCreate(product_name="Item 2", quantity=1, unit_price=Decimal("99.99")),
        ],
    )
    assert order.customer_id == "CUST-001"
    assert order.status == OrderStatus.PENDING
    assert len(order.items) == 2


def test_order_invalid_status_raises_error():
    """Verify order status constraint validation."""
    with pytest.raises(ValidationError):
        OrderCreate(customer_id="CUST-001", status="FLYING")


def test_order_with_details_composite_response():
    """Verify composite order response schema."""
    composite_data = {
        "order_id": "ORD-500",
        "customer_id": "CUST-001",
        "status": "PROCESSING",
        "total_amount": "299.98",
        "currency": "USD",
        "shipping_address": "123 Main St",
        "tracking_number": "TRK-990",
        "estimated_delivery": "2026-09-20T18:00:00Z",
        "created_at": "2026-09-17T10:00:00Z",
        "updated_at": "2026-09-17T11:00:00Z",
        "items": [
            {
                "item_id": "ITEM-1",
                "order_id": "ORD-500",
                "product_name": "Laptop Stand",
                "quantity": 1,
                "unit_price": "49.99",
                "created_at": "2026-09-17T10:00:00Z",
            }
        ],
        "payments": [
            {
                "payment_id": "PAY-1",
                "order_id": "ORD-500",
                "amount": "299.98",
                "status": "SUCCESS",
                "payment_method": "CREDIT_CARD",
                "transaction_ref": "TXN_7761",
                "created_at": "2026-09-17T10:01:00Z",
                "updated_at": "2026-09-17T10:01:00Z",
            }
        ],
    }
    order_details = OrderWithDetailsResponse.model_validate(composite_data)
    assert order_details.order_id == "ORD-500"
    assert len(order_details.items) == 1
    assert order_details.items[0].product_name == "Laptop Stand"
    assert len(order_details.payments) == 1


# =============================================================================
# 3. Payment Schema Tests
# =============================================================================

def test_payment_create_valid():
    """Verify payment record creation with valid payment method."""
    payment = PaymentCreate(
        order_id="ORD-100",
        amount=Decimal("120.50"),
        status=PaymentStatus.SUCCESS,
        payment_method=PaymentMethod.CREDIT_CARD,
        transaction_ref="CHG_990182",
    )
    assert payment.order_id == "ORD-100"
    assert payment.amount == Decimal("120.50")
    assert payment.payment_method == PaymentMethod.CREDIT_CARD


def test_payment_invalid_method_raises_error():
    """Verify check constraint on payment method."""
    with pytest.raises(ValidationError):
        PaymentCreate(order_id="ORD-100", amount=Decimal("50.00"), payment_method="BITCOIN")


def test_payment_negative_amount_raises_error():
    """Verify payment amount cannot be negative."""
    with pytest.raises(ValidationError):
        PaymentCreate(order_id="ORD-100", amount=Decimal("-10.00"))


# =============================================================================
# 4. Chat Session & Message Schema Tests
# =============================================================================

def test_message_create_valid():
    """Verify message schema with sender type and metadata."""
    msg = MessageCreate(
        session_id="SES-001",
        sender_type=SenderType.USER,
        content="Where is my delivery?",
        metadata={"client_ip": "127.0.0.1"},
    )
    assert msg.session_id == "SES-001"
    assert msg.sender_type == SenderType.USER
    assert msg.content == "Where is my delivery?"
    assert msg.metadata["client_ip"] == "127.0.0.1"


def test_message_invalid_sender_raises_error():
    """Verify sender type constraint validation."""
    with pytest.raises(ValidationError):
        MessageCreate(session_id="SES-001", sender_type="BOT", content="Hi")


def test_chat_session_create_defaults():
    """Verify default values in chat session creation."""
    session = ChatSessionCreate()
    assert session.channel == "WEB_CHAT"
    assert session.status == SessionStatus.ACTIVE
    assert session.context_entities == {}
    assert session.conversation_history == []


def test_chat_session_with_messages_response():
    """Verify composite chat session response with message history."""
    session_data = {
        "session_id": "SES-99",
        "customer_id": "CUST-01",
        "channel": "WEB_CHAT",
        "status": "ACTIVE",
        "context_entities": {"active_order_id": "ORD-123"},
        "conversation_history": [{"turn": 1, "query": "hello"}],
        "metadata": {},
        "created_at": "2026-09-17T12:00:00Z",
        "updated_at": "2026-09-17T12:05:00Z",
        "messages": [
            {
                "message_id": "MSG-1",
                "session_id": "SES-99",
                "sender_type": "USER",
                "content": "Hello",
                "metadata": {},
                "created_at": "2026-09-17T12:00:10Z",
            },
            {
                "message_id": "MSG-2",
                "session_id": "SES-99",
                "sender_type": "AGENT",
                "content": "Hello! How can I help you today?",
                "metadata": {},
                "created_at": "2026-09-17T12:00:12Z",
            },
        ],
    }
    session = ChatSessionWithMessagesResponse.model_validate(session_data)
    assert session.session_id == "SES-99"
    assert session.context_entities["active_order_id"] == "ORD-123"
    assert len(session.messages) == 2
    assert session.messages[1].sender_type == SenderType.AGENT


# =============================================================================
# 5. Ticket Schema Tests
# =============================================================================

def test_ticket_create_valid():
    """Verify support ticket creation with default status and priority."""
    ticket = TicketCreate(
        customer_id="CUST-001",
        category=TicketCategory.ORDER,
        priority=TicketPriority.HIGH,
        subject="Damaged Item on Arrival",
        description="The screen on the monitor is cracked.",
    )
    assert ticket.customer_id == "CUST-001"
    assert ticket.category == TicketCategory.ORDER
    assert ticket.priority == TicketPriority.HIGH
    assert ticket.status == TicketStatus.OPEN
    assert ticket.subject == "Damaged Item on Arrival"


def test_ticket_invalid_category_raises_error():
    """Verify check constraint on ticket category."""
    with pytest.raises(ValidationError):
        TicketCreate(
            category="UNKNOWN_CAT",
            subject="Test",
            description="Test description",
        )


def test_ticket_empty_subject_raises_error():
    """Verify subject cannot be empty string."""
    with pytest.raises(ValidationError):
        TicketCreate(subject="", description="Valid description")
