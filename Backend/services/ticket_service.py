"""
Ticket service module for support ticket creation, status updates, and escalation tracking.
"""

import uuid
from typing import Any

from Backend.core.exceptions import (
    DatabaseOperationError,
    InvalidOperationError,
    ResourceNotFoundError,
)
from Backend.schemas.common import TicketPriority, TicketStatus
from Backend.schemas.ticket import (
    TicketCreate,
    TicketResponse,
    TicketUpdate,
)
from Backend.services.base import BaseService


class TicketService(BaseService):
    """
    Service class responsible for support ticket operations and human agent dispatch.
    """

    table_name: str = "tickets"

    def create_ticket(self, payload: TicketCreate) -> TicketResponse:
        """
        Files a new customer support ticket.

        Args:
            payload: Validated TicketCreate schema payload.

        Returns:
            TicketResponse: Created ticket record with timestamps.

        Raises:
            DatabaseOperationError: If ticket insertion fails.
        """
        ticket_id = payload.ticket_id or f"TCK-{uuid.uuid4().hex[:12].upper()}"
        data = payload.model_dump(mode="json", exclude_none=True)
        data["ticket_id"] = ticket_id

        try:
            res = self.table.insert(data).execute()
        except Exception as exc:
            raise self._handle_db_error(
                operation="INSERT",
                exc=exc,
                details={"ticket_id": ticket_id, "customer_id": payload.customer_id},
            ) from exc

        if not res.data:
            raise DatabaseOperationError(
                operation="INSERT",
                table_name=self.table_name,
                message="Ticket record could not be created; empty response returned from database.",
                details={"ticket_id": ticket_id},
            )

        return TicketResponse.model_validate(res.data[0])

    def get_ticket_by_id(self, ticket_id: str) -> TicketResponse:
        """
        Retrieves a support ticket by its ID.

        Args:
            ticket_id: The unique support ticket identifier.

        Returns:
            TicketResponse: Validated ticket record.

        Raises:
            ResourceNotFoundError: If the ticket does not exist.
            DatabaseOperationError: If the query fails.
        """
        try:
            res = self.table.select("*").eq("ticket_id", ticket_id).execute()
        except Exception as exc:
            raise self._handle_db_error(
                operation="SELECT",
                exc=exc,
                details={"ticket_id": ticket_id},
            ) from exc

        if not res.data:
            raise ResourceNotFoundError(resource_type="Ticket", resource_id=ticket_id)

        return TicketResponse.model_validate(res.data[0])

    def get_tickets_by_customer_id(self, customer_id: str) -> list[TicketResponse]:
        """
        Retrieves all support tickets filed by a specific customer.

        Args:
            customer_id: The referenced customer ID.

        Returns:
            list[TicketResponse]: List of support tickets.

        Raises:
            DatabaseOperationError: If the query fails.
        """
        try:
            res = self.table.select("*").eq("customer_id", customer_id).execute()
        except Exception as exc:
            raise self._handle_db_error(
                operation="SELECT",
                exc=exc,
                details={"customer_id": customer_id},
            ) from exc

        return [TicketResponse.model_validate(row) for row in (res.data or [])]

    def update_ticket(self, ticket_id: str, payload: TicketUpdate) -> TicketResponse:
        """
        Updates support ticket attributes, status, or agent assignment.

        Args:
            ticket_id: The unique support ticket identifier.
            payload: TicketUpdate schema payload with fields to modify.

        Returns:
            TicketResponse: Updated ticket record.

        Raises:
            ResourceNotFoundError: If the ticket does not exist.
            DatabaseOperationError: If the update fails.
        """
        data = payload.model_dump(mode="json", exclude_unset=True)
        if not data:
            return self.get_ticket_by_id(ticket_id)

        try:
            res = self.table.update(data).eq("ticket_id", ticket_id).execute()
        except Exception as exc:
            raise self._handle_db_error(
                operation="UPDATE",
                exc=exc,
                details={"ticket_id": ticket_id, "update_fields": list(data.keys())},
            ) from exc

        if not res.data:
            raise ResourceNotFoundError(resource_type="Ticket", resource_id=ticket_id)

        return TicketResponse.model_validate(res.data[0])

    def update_ticket_status(
        self,
        ticket_id: str,
        status: TicketStatus | str,
        resolution_notes: str | None = None,
    ) -> TicketResponse:
        """
        Updates a ticket's status and optional resolution remarks.

        Args:
            ticket_id: The unique support ticket identifier.
            status: Target TicketStatus value.
            resolution_notes: Optional remarks from support agent.

        Returns:
            TicketResponse: Updated ticket record.
        """
        status_value = status.value if isinstance(status, TicketStatus) else str(status).upper()
        update_payload = TicketUpdate(status=status_value)
        if resolution_notes is not None:
            update_payload.resolution_notes = resolution_notes
        return self.update_ticket(ticket_id, update_payload)

    def escalate_ticket(
        self,
        ticket_id: str,
        priority: TicketPriority | str = TicketPriority.URGENT,
        reason: str | None = None,
        assigned_agent: str | None = None,
    ) -> TicketResponse:
        """
        Escalates a support ticket to urgent human agent review.

        Args:
            ticket_id: The unique support ticket identifier.
            priority: Escalated priority level (defaults to URGENT).
            reason: Optional justification for escalation.
            assigned_agent: Optional agent or queue name.

        Returns:
            TicketResponse: The escalated ticket record.

        Raises:
            InvalidOperationError: If attempting to escalate a closed ticket.
            ResourceNotFoundError: If the ticket is missing.
            DatabaseOperationError: If the update fails.
        """
        current_ticket = self.get_ticket_by_id(ticket_id)

        if current_ticket.status == TicketStatus.CLOSED.value:
            raise InvalidOperationError(
                operation="escalate_ticket",
                reason="Cannot escalate a closed support ticket.",
            )

        priority_value = (
            priority.value if isinstance(priority, TicketPriority) else str(priority).upper()
        )

        update_data = TicketUpdate(
            status=TicketStatus.ESCALATED.value,
            priority=priority_value,
        )

        if assigned_agent:
            update_data.assigned_agent = assigned_agent

        if reason:
            existing_notes = current_ticket.resolution_notes or ""
            escalation_entry = f"[Escalated]: {reason}"
            update_data.resolution_notes = (
                f"{existing_notes}\n{escalation_entry}".strip()
                if existing_notes
                else escalation_entry
            )

        return self.update_ticket(ticket_id, update_data)

