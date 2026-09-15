"""Minimal test to verify Supabase client reachability and connectivity."""

import sys
from pathlib import Path

# Add project root directory to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from Backend.db.supabase_client import get_supabase_client, verify_connection


def test_supabase_client_initialization():
    """Verify that get_supabase_client initializes successfully."""
    client = get_supabase_client()
    assert client is not None


def test_supabase_connection_reachability():
    """Verify that the client can communicate with the remote Supabase instance."""
    is_connected = verify_connection()
    assert is_connected is True


if __name__ == "__main__":
    print("Running Supabase connection test...")
    try:
        test_supabase_client_initialization()
        test_supabase_connection_reachability()
        print(" Supabase connection test passed successfully!")
    except Exception as exc:
        print(f"❌ Supabase connection test failed: {exc}")
        sys.exit(1)
