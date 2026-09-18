"""
Chat service module for conversation sessions and message history management.
"""

from typing import Any
from Backend.services.base import BaseService


class ChatService(BaseService):
    """
    Service class responsible for chat session lifecycle and message thread persistence.
    """

    table_name: str = "chat_sessions"
    messages_table_name: str = "messages"

    # NOTE: Full CRUD operations will be implemented in Step 4 — Phase 4.
