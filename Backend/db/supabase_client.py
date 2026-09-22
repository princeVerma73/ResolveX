"""
Supabase client initialization and connection module.

Loads Supabase credentials from the root .env file and provides
a reusable Supabase client instance across the application.
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from supabase import Client, create_client

# Locate project root and load environment variables from .env
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
ENV_PATH = ROOT_DIR / ".env"

if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)
else:
    load_dotenv()

# Read environment variables
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_PUBLISHABLE_KEY: str = (
    os.getenv("SUPABASE_SECRET_KEY", "")
    or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    or os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
    or os.getenv("SUPABASE_KEY", "")
    or os.getenv("SUPABASE_ANON_KEY", "")
).strip()

_supabase_client: Client | None = None


def get_supabase_client() -> Client:
    """
    Returns an initialized singleton instance of the Supabase client.

    Raises:
        ValueError: If SUPABASE_URL or SUPABASE_PUBLISHABLE_KEY is not configured in .env.
    """
    global _supabase_client

    if _supabase_client is not None:
        return _supabase_client

    if not SUPABASE_URL:
        raise ValueError(
            "Missing 'SUPABASE_URL'. Please set SUPABASE_URL in your root .env file."
        )

    if not SUPABASE_PUBLISHABLE_KEY:
        raise ValueError(
            "Missing 'SUPABASE_PUBLISHABLE_KEY'. Please set SUPABASE_PUBLISHABLE_KEY in your root .env file."
        )

    _supabase_client = create_client(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY)
    return _supabase_client


def verify_connection() -> bool:
    """
    Performs a lightweight connectivity check to verify that the client can reach Supabase.

    Returns:
        bool: True if connection succeeds.

    Raises:
        Exception: If the connection attempt fails.
    """
    client = get_supabase_client()
    client.storage.list_buckets()
    return True


if __name__ == "__main__":
    print("Testing Supabase connection...")
    try:
        verify_connection()
        print(" Successfully connected to Supabase!")
    except Exception as exc:
        print(f"❌ Connection failed: {exc}")
