"""Minimal test to verify Supabase client reachability and client separation."""

import os
import sys
from pathlib import Path
import pytest

# Add project root directory to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from Backend.db.supabase_client import (
    get_supabase_client,
    get_supabase_service_client,
    verify_connection,
)


def test_supabase_public_client_initialization():
    """Verify that get_supabase_client initializes successfully using publishable key."""
    client = get_supabase_client()
    assert client is not None


def test_supabase_public_connection_reachability():
    """Verify that the public client can communicate with the remote Supabase instance."""
    is_connected = verify_connection(use_service_client=False)
    assert is_connected is True


def test_supabase_service_client_behavior():
    """Verify that get_supabase_service_client handles configured/unconfigured state properly."""
    has_service_key = bool(os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip())
    if has_service_key:
        client = get_supabase_service_client()
        assert client is not None
        assert verify_connection(use_service_client=True) is True
    else:
        with pytest.raises(ValueError, match="Missing 'SUPABASE_SERVICE_ROLE_KEY'"):
            get_supabase_service_client()


if __name__ == "__main__":
    print("Running Supabase connection tests...")
    try:
        test_supabase_public_client_initialization()
        test_supabase_public_connection_reachability()
        test_supabase_service_client_behavior()
        print(" All Supabase connection tests passed successfully!")
    except Exception as exc:
        print(f"❌ Supabase connection test failed: {exc}")
        sys.exit(1)
