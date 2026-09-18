"""
Base service module for the ResolveX service layer.

Provides the foundational BaseService class with Supabase client management,
table binding, and centralized database exception wrapping.
"""

from typing import Any
from supabase import Client

from Backend.core.exceptions import DatabaseOperationError
from Backend.db.supabase_client import get_supabase_client


class BaseService:
    """
    Abstract base service providing shared database access and error handling.

    Attributes:
        table_name: The name of the database table associated with the service.
    """

    table_name: str = ""

    def __init__(self, client: Client | None = None) -> None:
        """
        Initializes the service with an optional Supabase client instance.
        If no client is provided, the singleton client is lazily acquired.

        Args:
            client: Optional Supabase client instance (useful for testing and dependency injection).
        """
        self._client = client

    @property
    def client(self) -> Client:
        """Returns the active Supabase client instance."""
        if self._client is None:
            self._client = get_supabase_client()
        return self._client

    @property
    def table(self) -> Any:
        """
        Returns the PostgREST query builder for the service's bound table.

        Raises:
            ValueError: If table_name is not configured on the service subclass.
        """
        if not self.table_name:
            raise ValueError(f"table_name is not configured for {self.__class__.__name__}")
        return self.client.table(self.table_name)

    def _handle_db_error(
        self,
        operation: str,
        exc: Exception,
        details: dict[str, Any] | None = None,
    ) -> DatabaseOperationError:
        """
        Constructs a structured DatabaseOperationError with exception chaining.

        Args:
            operation: Description of the attempted operation (e.g., 'SELECT', 'INSERT').
            exc: The caught low-level exception.
            details: Optional contextual metadata dictionary.

        Returns:
            DatabaseOperationError: A typed exception ready to be raised or logged.
        """
        merged_details = {"original_error": str(exc)}
        if details:
            merged_details.update(details)

        db_error = DatabaseOperationError(
            operation=operation,
            table_name=self.table_name,
            message=f"Database error during {operation} on '{self.table_name}': {exc}",
            details=merged_details,
        )
        db_error.__cause__ = exc
        return db_error
