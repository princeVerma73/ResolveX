"""
Chat service module for conversation sessions and message history management.
"""

import uuid
from typing import Any

from Backend.core.exceptions import DatabaseOperationError, ResourceNotFoundError
from Backend.schemas.chat import (
    ChatSessionCreate,
    ChatSessionResponse,
    ChatSessionUpdate,
    ChatSessionWithMessagesResponse,
    MessageCreate,
    MessageResponse,
)
from Backend.services.base import BaseService


class ChatService(BaseService):
    """
    Service class responsible for chat session lifecycle and message thread persistence.
    """

    table_name: str = "chat_sessions"
    messages_table_name: str = "messages"

    @property
    def messages_table(self) -> Any:
        """Returns the PostgREST query builder for messages."""
        return self.client.table(self.messages_table_name)

    def create_session(self, payload: ChatSessionCreate | None = None) -> ChatSessionResponse:
        """
        Initializes a new conversational chat session.

        Args:
            payload: Optional ChatSessionCreate payload. Uses defaults if None.

        Returns:
            ChatSessionResponse: The newly created chat session record.

        Raises:
            DatabaseOperationError: If session insertion fails.
        """
        if payload is None:
            payload = ChatSessionCreate()

        session_id = payload.session_id or f"SES-{uuid.uuid4().hex[:12].upper()}"
        data = payload.model_dump(mode="json", exclude_none=True)
        data["session_id"] = session_id

        try:
            res = self.table.insert(data).execute()
        except Exception as exc:
            raise self._handle_db_error(
                operation="INSERT",
                exc=exc,
                details={"session_id": session_id, "customer_id": payload.customer_id},
            ) from exc

        if not res.data:
            raise DatabaseOperationError(
                operation="INSERT",
                table_name=self.table_name,
                message="Chat session could not be created; empty response returned from database.",
                details={"session_id": session_id},
            )

        return ChatSessionResponse.model_validate(res.data[0])

    def get_session(self, session_id: str) -> ChatSessionResponse:
        """
        Retrieves a chat session by its unique ID.

        Args:
            session_id: The unique chat session identifier.

        Returns:
            ChatSessionResponse: The validated session record.

        Raises:
            ResourceNotFoundError: If the session does not exist.
            DatabaseOperationError: If the query fails.
        """
        try:
            res = self.table.select("*").eq("session_id", session_id).execute()
        except Exception as exc:
            raise self._handle_db_error(
                operation="SELECT",
                exc=exc,
                details={"session_id": session_id},
            ) from exc

        if not res.data:
            raise ResourceNotFoundError(resource_type="ChatSession", resource_id=session_id)

        return ChatSessionResponse.model_validate(res.data[0])

    def update_session(self, session_id: str, payload: ChatSessionUpdate) -> ChatSessionResponse:
        """
        Updates session entities, conversation history, or status.

        Args:
            session_id: The unique chat session identifier.
            payload: ChatSessionUpdate schema with modified attributes.

        Returns:
            ChatSessionResponse: The updated session record.

        Raises:
            ResourceNotFoundError: If the session does not exist.
            DatabaseOperationError: If the update fails.
        """
        data = payload.model_dump(mode="json", exclude_unset=True)
        if not data:
            return self.get_session(session_id)

        try:
            res = self.table.update(data).eq("session_id", session_id).execute()
        except Exception as exc:
            raise self._handle_db_error(
                operation="UPDATE",
                exc=exc,
                details={"session_id": session_id, "update_fields": list(data.keys())},
            ) from exc

        if not res.data:
            raise ResourceNotFoundError(resource_type="ChatSession", resource_id=session_id)

        return ChatSessionResponse.model_validate(res.data[0])

    def add_message(self, payload: MessageCreate) -> MessageResponse:
        """
        Appends a new conversational message turn to a chat session.

        Args:
            payload: Validated MessageCreate schema payload.

        Returns:
            MessageResponse: Stored message record with timestamps.

        Raises:
            ResourceNotFoundError: If the target session does not exist.
            DatabaseOperationError: If message insertion fails.
        """
        # Ensure session exists
        _ = self.get_session(payload.session_id)

        message_id = payload.message_id or f"MSG-{uuid.uuid4().hex[:12].upper()}"
        data = payload.model_dump(mode="json", exclude_none=True)
        data["message_id"] = message_id

        try:
            res = self.messages_table.insert(data).execute()
        except Exception as exc:
            raise self._handle_db_error(
                operation="INSERT",
                exc=exc,
                details={"message_id": message_id, "session_id": payload.session_id},
            ) from exc

        if not res.data:
            raise DatabaseOperationError(
                operation="INSERT",
                table_name=self.messages_table_name,
                message="Message could not be persisted; empty response returned from database.",
                details={"message_id": message_id, "session_id": payload.session_id},
            )

        return MessageResponse.model_validate(res.data[0])

    def get_messages(self, session_id: str, limit: int = 100) -> list[MessageResponse]:
        """
        Retrieves chronological message history for a session.

        Args:
            session_id: Target chat session ID.
            limit: Maximum number of recent messages to return.

        Returns:
            list[MessageResponse]: Chronological list of message turns.

        Raises:
            DatabaseOperationError: If the query fails.
        """
        try:
            res = (
                self.messages_table.select("*")
                .eq("session_id", session_id)
                .order("created_at", desc=False)
                .limit(limit)
                .execute()
            )
        except Exception as exc:
            raise self._handle_db_error(
                operation="SELECT",
                exc=exc,
                details={"session_id": session_id, "table": self.messages_table_name},
            ) from exc

        return [MessageResponse.model_validate(row) for row in (res.data or [])]

    def get_session_with_messages(self, session_id: str) -> ChatSessionWithMessagesResponse:
        """
        Retrieves a chat session alongside its complete chronological message thread.

        Args:
            session_id: Target chat session ID.

        Returns:
            ChatSessionWithMessagesResponse: Composite session record with message history.

        Raises:
            ResourceNotFoundError: If the session does not exist.
            DatabaseOperationError: If queries fail.
        """
        session = self.get_session(session_id)
        messages = self.get_messages(session_id)

        session_dict = session.model_dump()
        session_dict["messages"] = [msg.model_dump() for msg in messages]

        return ChatSessionWithMessagesResponse.model_validate(session_dict)

