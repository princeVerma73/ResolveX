"""Redis In-Memory Query Caching Service for ResolveX.

Provides high-throughput sub-10ms query caching for grounded policy inquiries,
reducing repetitive LLM inference costs and protecting upstream API rate limits.
Includes graceful fallback so agent execution never breaks if Redis is unreachable.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any

import redis
import redis.asyncio as aioredis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError, TimeoutError as RedisTimeoutError

logger = logging.getLogger(__name__)

# Cache Configuration
DEFAULT_CACHE_TTL = 3600  # 1 hour expiration
KEY_PREFIX = "cache:query:"


class RedisCacheService:
    """Production Redis caching client with async/sync APIs and graceful degradation."""

    def __init__(
        self,
        redis_url: str | None = None,
        host: str | None = None,
        port: int | None = None,
        password: str | None = None,
        default_ttl: int = DEFAULT_CACHE_TTL,
        socket_timeout: float = 1.0,
    ) -> None:
        """Initializes Redis configuration parameters."""
        self.redis_url = (redis_url or os.getenv("REDIS_URL", "")).strip()
        self.host = (host or os.getenv("REDIS_HOST", "localhost")).strip()
        self.port = int(port or os.getenv("REDIS_PORT", "6379"))
        self.password = (password or os.getenv("REDIS_PASSWORD", "")).strip() or None
        self.default_ttl = default_ttl
        self.socket_timeout = socket_timeout

        self._async_client: aioredis.Redis | None = None
        self._sync_client: redis.Redis | None = None
        self._warned_unreachable = False

    def _get_async_client(self) -> aioredis.Redis:
        """Lazy-initializes and returns the async Redis client."""
        if self._async_client is None:
            if self.redis_url:
                self._async_client = aioredis.from_url(
                    self.redis_url,
                    decode_responses=True,
                    socket_timeout=self.socket_timeout,
                    socket_connect_timeout=self.socket_timeout,
                )
            else:
                self._async_client = aioredis.Redis(
                    host=self.host,
                    port=self.port,
                    password=self.password,
                    decode_responses=True,
                    socket_timeout=self.socket_timeout,
                    socket_connect_timeout=self.socket_timeout,
                )
        return self._async_client

    def _get_sync_client(self) -> redis.Redis:
        """Lazy-initializes and returns the sync Redis client."""
        if self._sync_client is None:
            if self.redis_url:
                self._sync_client = redis.from_url(
                    self.redis_url,
                    decode_responses=True,
                    socket_timeout=self.socket_timeout,
                    socket_connect_timeout=self.socket_timeout,
                )
            else:
                self._sync_client = redis.Redis(
                    host=self.host,
                    port=self.port,
                    password=self.password,
                    decode_responses=True,
                    socket_timeout=self.socket_timeout,
                    socket_connect_timeout=self.socket_timeout,
                )
        return self._sync_client

    @staticmethod
    def hash_query(query: str) -> str:
        """Generates a deterministic SHA-256 hash for normalized natural language queries."""
        normalized = query.strip().lower()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def get_cache_key(self, query: str) -> str:
        """Formats the Redis key for a query string: `cache:query:<hashed_query_text>`."""
        return f"{KEY_PREFIX}{self.hash_query(query)}"

    @staticmethod
    def should_cache(
        intent: str | None,
        is_escalated: bool = False,
        clarification_needed: bool = False,
    ) -> bool:
        """Enforces cache filtering rules.

        - CACHE ONLY: Grounded policy inquiries (POLICY_INQUIRY).
        - BYPASS: Dynamic customer data (DATABASE_LOOKUP, ACTION_EXECUTION),
          troubleshooting diagnostics (TECHNICAL_SUPPORT), or escalations.
        """
        if not intent:
            return False

        norm_intent = str(intent).strip().upper()
        # Strictly cache only policy inquiries
        if norm_intent != "POLICY_INQUIRY":
            return False

        # Do not cache escalations or missing parameter prompts
        if is_escalated or clarification_needed:
            return False

        return True

    # -------------------------------------------------------------------------
    # Asynchronous APIs (FastAPI & WebSockets)
    # -------------------------------------------------------------------------

    async def get_cached_response(self, query: str) -> dict[str, Any] | None:
        """Retrieves a cached response with sub-10ms lookup latency.

        Returns None on cache miss or if Redis is unreachable (graceful fallback).
        """
        if not query or not query.strip():
            return None

        key = self.get_cache_key(query)
        try:
            client = self._get_async_client()
            raw_data = await client.get(key)
            if raw_data:
                logger.info("Redis Cache HIT: key=%s query='%s'", key, query[:40])
                return json.loads(raw_data)
            return None
        except (RedisConnectionError, RedisTimeoutError, OSError) as exc:
            if not self._warned_unreachable:
                logger.warning("Redis cache unreachable, operating in direct orchestrator fallback mode: %s", exc)
                self._warned_unreachable = True
            else:
                logger.debug("Redis cache get error: %s", exc)
            return None
        except Exception as exc:
            logger.warning("Unexpected error during Redis get: %s", exc)
            return None

    async def set_cached_response(
        self,
        query: str,
        data: dict[str, Any],
        ttl: int | None = None,
    ) -> bool:
        """Writes query response payload to Redis with TTL expiration (default 3600s).

        Returns False gracefully if Redis is unreachable without raising exceptions.
        """
        if not query or not query.strip() or not data:
            return False

        key = self.get_cache_key(query)
        expiration = ttl if ttl is not None else self.default_ttl
        try:
            client = self._get_async_client()
            serialized = json.dumps(data)
            await client.set(key, serialized, ex=expiration)
            logger.info("Redis Cache SET: key=%s ttl=%ds", key, expiration)
            return True
        except (RedisConnectionError, RedisTimeoutError, OSError) as exc:
            if not self._warned_unreachable:
                logger.warning("Redis cache unreachable during set: %s", exc)
                self._warned_unreachable = True
            return False
        except Exception as exc:
            logger.warning("Unexpected error during Redis set: %s", exc)
            return False

    # -------------------------------------------------------------------------
    # Synchronous APIs (Testing & Synchronous Callers)
    # -------------------------------------------------------------------------

    def get_cached_response_sync(self, query: str) -> dict[str, Any] | None:
        """Synchronous version of get_cached_response with graceful fallback."""
        if not query or not query.strip():
            return None

        key = self.get_cache_key(query)
        try:
            client = self._get_sync_client()
            raw_data = client.get(key)
            if raw_data:
                return json.loads(raw_data)
            return None
        except (RedisConnectionError, RedisTimeoutError, OSError, RedisError) as exc:
            logger.debug("Redis sync get fallback: %s", exc)
            return None
        except Exception as exc:
            logger.warning("Unexpected sync get error: %s", exc)
            return None

    def set_cached_response_sync(
        self,
        query: str,
        data: dict[str, Any],
        ttl: int | None = None,
    ) -> bool:
        """Synchronous version of set_cached_response with graceful fallback."""
        if not query or not query.strip() or not data:
            return False

        key = self.get_cache_key(query)
        expiration = ttl if ttl is not None else self.default_ttl
        try:
            client = self._get_sync_client()
            client.set(key, json.dumps(data), ex=expiration)
            return True
        except (RedisConnectionError, RedisTimeoutError, OSError, RedisError) as exc:
            logger.debug("Redis sync set fallback: %s", exc)
            return False
        except Exception as exc:
            logger.warning("Unexpected sync set error: %s", exc)
            return False

    async def ping(self) -> bool:
        """Checks if Redis instance is active and reachable."""
        try:
            client = self._get_async_client()
            return await client.ping()
        except Exception:
            return False

    async def clear_cache(self, pattern: str = f"{KEY_PREFIX}*") -> int:
        """Evicts cached query keys matching the pattern."""
        try:
            client = self._get_async_client()
            keys = await client.keys(pattern)
            if keys:
                return await client.delete(*keys)
            return 0
        except Exception as exc:
            logger.warning("Error clearing Redis cache: %s", exc)
            return 0

    async def close(self) -> None:
        """Closes active Redis client connections."""
        if self._async_client is not None:
            await self._async_client.aclose()
            self._async_client = None
        if self._sync_client is not None:
            self._sync_client.close()
            self._sync_client = None


# Global singleton instance
redis_cache = RedisCacheService()


def get_redis_cache() -> RedisCacheService:
    """Dependency injection helper returning singleton RedisCacheService."""
    return redis_cache
