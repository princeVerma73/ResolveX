"""Database schema validation tests for ResolveX.

Verifies that:
1. The local migration file 'database/migrations/001_initial_schema.sql' exists and
   defines all 7 core tables, relationships, constraints, indexes, and triggers.
2. The Supabase client initializes properly.
3. The 7 core tables (customers, orders, order_items, payments, chat_sessions, messages, tickets)
   are accessible and queryable via the Supabase REST/PostgREST API.
"""

import sys
import uuid
from pathlib import Path
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from Backend.db.supabase_client import get_supabase_client

MIGRATION_FILE = ROOT_DIR / "database" / "migrations" / "001_initial_schema.sql"

CORE_TABLES = [
    "customers",
    "orders",
    "order_items",
    "payments",
    "chat_sessions",
    "messages",
    "tickets",
]


# =============================================================================
# 1. Local SQL Migration File Structure Tests
# =============================================================================

def test_migration_file_exists():
    """Verify that the initial SQL migration file exists in the migrations directory."""
    assert MIGRATION_FILE.exists(), f"Migration file not found at: {MIGRATION_FILE}"
    content = MIGRATION_FILE.read_text(encoding="utf-8")
    assert len(content) > 0, "Migration file is empty"


def test_migration_file_defines_all_core_tables():
    """Verify that the migration file contains DDL definitions for all 7 required tables."""
    content = MIGRATION_FILE.read_text(encoding="utf-8").lower()
    for table in CORE_TABLES:
        assert f"create table if not exists {table}" in content or f"create table {table}" in content, (
            f"Table definition for '{table}' missing in migration file."
        )


def test_migration_file_contains_constraints_and_indexes():
    """Verify that foreign keys, status checks, indexes, and triggers are defined."""
    content = MIGRATION_FILE.read_text(encoding="utf-8").lower()
    
    # Check foreign keys
    assert "references customers(customer_id)" in content
    assert "references orders(order_id)" in content
    assert "references chat_sessions(session_id)" in content
    
    # Check constraints and checks
    assert "check (tier in" in content
    assert "check (status in" in content
    assert "check (sender_type in" in content
    assert "check (priority in" in content
    
    # Check indexes and triggers
    assert "create index if not exists idx_orders_customer_id" in content
    assert "create index if not exists idx_tickets_status" in content
    assert "update_updated_at_column" in content


# =============================================================================
# 2. Remote Supabase Database Connectivity & Schema Tests
# =============================================================================

def test_supabase_client_ready():
    """Verify Supabase client initializes properly."""
    client = get_supabase_client()
    assert client is not None


@pytest.mark.parametrize("table_name", CORE_TABLES)
def test_remote_table_exists_and_queryable(table_name: str):
    """Verify each core table exists and accepts queries via Supabase REST API."""
    client = get_supabase_client()
    try:
        response = client.table(table_name).select("*").limit(1).execute()
        assert response is not None
        assert hasattr(response, "data")
        assert isinstance(response.data, list)
    except Exception as exc:
        pytest.fail(
            f"Failed to query table '{table_name}'. "
            f"If you have not run the migration yet, please apply 'database/migrations/001_initial_schema.sql' "
            f"in your Supabase SQL Editor. Error: {exc}"
        )


def test_remote_customer_lifecycle_integrity():
    """Tests an isolated customer record lifecycle (insert -> query -> clean up)."""
    client = get_supabase_client()
    test_cust_id = f"TEST-CUST-{uuid.uuid4().hex[:8]}"
    test_email = f"test_{uuid.uuid4().hex[:8]}@example.com"

    try:
        # Insert
        insert_res = (
            client.table("customers")
            .insert(
                {
                    "customer_id": test_cust_id,
                    "full_name": "Test Lifecycle User",
                    "email": test_email,
                    "phone": "+1-555-0199",
                    "tier": "STANDARD",
                }
            )
            .execute()
        )
        assert insert_res.data is not None
        assert len(insert_res.data) > 0
        assert insert_res.data[0]["customer_id"] == test_cust_id

        # Query
        query_res = (
            client.table("customers")
            .select("*")
            .eq("customer_id", test_cust_id)
            .execute()
        )
        assert len(query_res.data) == 1
        assert query_res.data[0]["email"] == test_email

    finally:
        # Cleanup
        try:
            client.table("customers").delete().eq("customer_id", test_cust_id).execute()
        except Exception:
            pass
