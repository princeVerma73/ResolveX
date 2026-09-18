"""
Customer service module for managing customer profiles and account queries.
"""

from typing import Any
from Backend.services.base import BaseService


class CustomerService(BaseService):
    """
    Service class responsible for customer profile management and lookup operations.
    """

    table_name: str = "customers"

    # NOTE: Full CRUD operations will be implemented in Step 4 — Phase 4.
