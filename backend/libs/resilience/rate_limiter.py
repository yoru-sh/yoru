"""Redis-based sliding window rate limiter."""

import time
from uuid import uuid4
from typing import Tuple, Optional
from libs.redis.redis import RedisManager
from libs.log_manager.controller import LoggingController


class RateLimitExceededError(Exception):
    """Raised when rate limit is exceeded."""
    pass


class RateLimiter:
    """
    Redis sliding window rate limiter.

    Uses Redis sorted sets (ZADD, ZREMRANGEBYSCORE, ZCARD) to implement
    accurate sliding window rate limiting across distributed instances.

    The sliding window algorithm:
    1. Remove entries outside the current time window
    2. Count remaining entries in window
    3. If count < limit: allow request and add timestamp
    4. If count >= limit: reject request
    """

    def __init__(self, redis: Optional[RedisManager] = None):
        """
        Initialize rate limiter.

        Args:
            redis: Optional Redis manager instance (creates new if None)
        """
        self.redis = redis or RedisManager()
        self.logger = LoggingController(app_name="RateLimiter")

    async def check_rate_limit(
        self,
        key: str,
        limit: int,
        window_seconds: int,
        correlation_id: str = ""
    ) -> Tuple[bool, int, int]:
        """
        Check rate limit with sliding window algorithm.

        Args:
            key: Redis key (e.g., "ratelimit:user:123:endpoint:/api/plans")
            limit: Maximum requests allowed in window
            window_seconds: Time window in seconds
            correlation_id: Optional correlation ID for logging

        Returns:
            Tuple of (allowed, remaining, reset_timestamp)
            - allowed: True if request is within limits
            - remaining: Number of requests remaining in window
            - reset_timestamp: Unix timestamp when window resets

        Example:
            >>> limiter = RateLimiter()
            >>> allowed, remaining, reset = await limiter.check_rate_limit(
            ...     "ratelimit:user:123", limit=100, window_seconds=60
            ... )
            >>> if not allowed:
            ...     raise RateLimitExceededError("Rate limit exceeded")
        """
        now = time.time()
        window_start = now - window_seconds

        try:
            redis_client = await self.redis.get_client()

            # Use pipeline for atomic operations
            pipe = redis_client.pipeline()

            # Remove entries outside current window
            pipe.zremrangebyscore(key, 0, window_start)

            # Count current entries in window
            pipe.zcard(key)

            # Execute pipeline
            results = await pipe.execute()
            current_count = results[1]

            # Check if within limit
            allowed = current_count < limit

            if allowed:
                # Add current request timestamp
                timestamp_id = str(uuid4())
                await redis_client.zadd(key, {timestamp_id: now})

                # Set TTL (slightly longer than window for cleanup)
                await redis_client.expire(key, window_seconds + 10)

                remaining = max(0, limit - current_count - 1)
            else:
                remaining = 0

            # Calculate reset time (end of current window)
            reset_timestamp = int(now + window_seconds)

            # Log if rate limit exceeded
            if not allowed:
                self.logger.log_warning(
                    "Rate limit exceeded",
                    {
                        "correlation_id": correlation_id,
                        "key": key,
                        "limit": limit,
                        "window_seconds": window_seconds,
                        "current_count": current_count,
                    }
                )

            return allowed, remaining, reset_timestamp

        except Exception as e:
            # Log error and allow request (fail open)
            self.logger.log_error(
                "Rate limiter error, allowing request",
                {
                    "correlation_id": correlation_id,
                    "key": key,
                    "error": str(e),
                }
            )
            # Fail open: allow request on error
            return True, limit, int(now + window_seconds)

    async def reset_limit(self, key: str, correlation_id: str = "") -> bool:
        """
        Reset rate limit for a specific key.

        Useful for admin operations or testing.

        Args:
            key: Redis key to reset
            correlation_id: Optional correlation ID for logging

        Returns:
            True if key was deleted
        """
        try:
            redis_client = await self.redis.get_client()
            deleted = await redis_client.delete(key)

            self.logger.log_info(
                f"Rate limit reset for key: {key}",
                {"correlation_id": correlation_id, "key": key}
            )

            return deleted > 0

        except Exception as e:
            self.logger.log_error(
                "Failed to reset rate limit",
                {"correlation_id": correlation_id, "key": key, "error": str(e)}
            )
            return False

    async def get_current_count(
        self, key: str, correlation_id: str = ""
    ) -> Optional[int]:
        """
        Get current request count for a key.

        Useful for monitoring and debugging.

        Args:
            key: Redis key to check
            correlation_id: Optional correlation ID for logging

        Returns:
            Current count or None if error
        """
        try:
            redis_client = await self.redis.get_client()
            count = await redis_client.zcard(key)

            return count

        except Exception as e:
            self.logger.log_error(
                "Failed to get rate limit count",
                {"correlation_id": correlation_id, "key": key, "error": str(e)}
            )
            return None
