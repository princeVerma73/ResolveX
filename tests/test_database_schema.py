"""Database schema validation tests for ResolveX.

Verifies that:
1. The local migration file 'database/migrations/001_initial_schema.sql' exists and
   defines all 7 core tables, relationships, constraints, indexes, triggers,
   role grants, and idempotent RLS policies.
2. The public Supabase client initializes properly with SUPABASE_PUBLISHABLE_KEY.
3. The 7 core tables (customers, orders, order_items, payments, chat_sessions, messages, tickets)
   are accessible and queryable via the PostgREST API.
4. An isolated conversational lifecycle (chat_sessions + messages) can be created and queried.
5. Privileged operations via get_supabase_service_client() function when configured.
"""

import os
import sys
import uuid
from pathlib import Path
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from Backend.db.supabase_client import (
    get_supabase_client,
    get_supabase_service_client,
)

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
# 1. Local SQL Migration File Structure & Security Validation
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

    # Foreign key references
    assert "references customers(customer_id)" in content
    assert "references orders(order_id)" in content
    assert "references chat_sessions(session_id)" in content

    # Check constraints
    assert "check (tier in" in content
    assert "check (status in" in content
    assert "check (sender_type in" in content
    assert "check (priority in" in content

    # Performance indexes and triggers
    assert "create index if not exists idx_orders_customer_id" in content
    assert "create index if not exists idx_tickets_status" in content
    assert "update_updated_at_column" in content


def test_migration_file_contains_grants_and_idempotent_rls():
    """Verify that schema grants and idempotent RLS policies are properly declared."""
    content = MIGRATION_FILE.read_text(encoding="utf-8").lower()

    # Role grants
    assert "grant usage on schema public to anon, authenticated, service_role" in content
    assert "grant all on all tables in schema public to service_role" in content

    # RLS enablement
    assert "enable row level security" in content

    # Idempotent policies
    assert "drop policy if exists" in content
    assert "create policy" in content


# =============================================================================
# 2. Client Initialization Tests
# =============================================================================

def test_public_supabase_client_ready():
    """Verify public Supabase client initializes properly."""
    client = get_supabase_client()
    assert client is not None


# =============================================================================
# 3. Remote Supabase Table Query Tests
# =============================================================================

@pytest.mark.parametrize("table_name", CORE_TABLES)
def test_remote_table_accessible(table_name: str):
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
            f"If you have updated the migration with grants and RLS, please run the SQL from "
            f"'database/migrations/001_initial_schema.sql' in your Supabase SQL Editor. Error: {exc}"
        )


def test_remote_chat_session_lifecycle():
    """Tests an isolated public chat session and message insertion and cleanup."""
    client = get_supabase_client()
    test_session_id = f"TEST-SES-{uuid.uuid4().hex[:8]}"
    test_msg_id = f"TEST-MSG-{uuid.uuid4().hex[:8]}"

    try:
        # 1. Insert chat session
        session_res = (
            client.table("chat_sessions")
            .insert(
                {
                    "session_id": test_session_id,
                    "channel": "WEB_CHAT",
                    "status": "ACTIVE",
                    "context_entities": {"topic": "order_inquiry"},
                }
            )
            .execute()
        )
        assert session_res.data is not None
        assert len(session_res.data) > 0
        assert session_res.data[0]["session_id"] == test_session_id

        # 2. Insert message into session
        msg_res = (
            client.table("messages")
            .insert(
                {
                    "message_id": test_msg_id,
                    "session_id": test_session_id,
                    "sender_type": "USER",
                    "content": "Hello, I want to check my order status.",
                }
            )
            .execute()
        )
        assert msg_res.data is not None
        assert len(msg_res.data) > 0

        # 3. Query message
        query_res = (
            client.table("messages")
            .select("*")
            .eq("session_id", test_session_id)
            .execute()
        )
        assert len(query_res.data) == 1
        assert query_res.data[0]["message_id"] == test_msg_id

    finally:
        # Cleanup
        has_service_key = bool(os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip())
        cleanup_client = get_supabase_service_client() if has_service_key else client
        try:
            cleanup_client.table("messages").delete().eq("message_id", test_msg_id).execute()
        except Exception:
            pass
        try:
            cleanup_client.table("chat_sessions").delete().eq("session_id", test_session_id).execute()
        except Exception:
            pass
