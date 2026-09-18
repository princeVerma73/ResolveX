"""
Payment service module for financial transactions and payment gateway records.
"""

from typing import Any
from Backend.services.base import BaseService


class PaymentService(BaseService):
    """
    Service class responsible for payment status lookups and transaction history.
    """

    table_name: str = "payments"

    # NOTE: Full CRUD operations will be implemented in Step 4 — Phase 4.
