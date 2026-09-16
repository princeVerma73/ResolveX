"""
Supabase client initialization and connection module for ResolveX.

Provides clean separation between:
- `get_supabase_client()`: Public / anon client using SUPABASE_PUBLISHABLE_KEY or SUPABASE_ANON_KEY.
- `get_supabase_service_client()`: Privileged backend-only client using SUPABASE_SERVICE_ROLE_KEY.
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
    os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
    or os.getenv("SUPABASE_ANON_KEY", "")
    or os.getenv("SUPABASE_KEY", "")
).strip()
SUPABASE_SERVICE_ROLE_KEY: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()

_supabase_public_client: Client | None = None
_supabase_service_client: Client | None = None


def get_supabase_client() -> Client:
    """
    Returns an initialized singleton instance of the public / anon Supabase client.
    Used for client-facing operations subject to Row Level Security (RLS).

    Raises:
        ValueError: If SUPABASE_URL or SUPABASE_PUBLISHABLE_KEY is not configured in .env.
    """
    global _supabase_public_client

    if _supabase_public_client is not None:
        return _supabase_public_client

    if not SUPABASE_URL:
        raise ValueError(
            "Missing 'SUPABASE_URL'. Please set SUPABASE_URL in your root .env file."
        )

    if not SUPABASE_PUBLISHABLE_KEY:
        raise ValueError(
            "Missing 'SUPABASE_PUBLISHABLE_KEY' (or SUPABASE_ANON_KEY). "
            "Please configure your publishable/anon key in the root .env file."
        )

    _supabase_public_client = create_client(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY)
    return _supabase_public_client


def get_supabase_service_client() -> Client:
    """
    Returns an initialized singleton instance of the privileged service-role Supabase client.
    Used ONLY by trusted backend services, background workers, and admin tasks to bypass RLS.

    Raises:
        ValueError: If SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY is not configured in .env.
    """
    global _supabase_service_client

    if _supabase_service_client is not None:
        return _supabase_service_client

    if not SUPABASE_URL:
        raise ValueError(
            "Missing 'SUPABASE_URL'. Please set SUPABASE_URL in your root .env file."
        )

    if not SUPABASE_SERVICE_ROLE_KEY:
        raise ValueError(
            "Missing 'SUPABASE_SERVICE_ROLE_KEY'. "
            "Please configure your service role secret key in your root .env file "
            "for backend administrative operations."
        )

    _supabase_service_client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    return _supabase_service_client


def verify_connection(use_service_client: bool = False) -> bool:
    """
    Performs a lightweight connectivity check to verify that Supabase is reachable.

    Args:
        use_service_client: If True, tests the service-role client; otherwise tests public client.

    Returns:
        bool: True if connection succeeds.

    Raises:
        Exception: If the connection attempt fails.
    """
    client = get_supabase_service_client() if use_service_client else get_supabase_client()
    client.storage.list_buckets()
    return True


if __name__ == "__main__":
    print("Testing Supabase public client connection...")
    try:
        verify_connection()
        print(" Successfully connected to Supabase via public client!")
    except Exception as exc:
        print(f"❌ Public client connection failed: {exc}")
