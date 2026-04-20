"""Circuit breaker pattern implementation with Redis-backed state."""

import asyncio
from typing import Callable, Optional, Any
from libs.log_manager.controller import LoggingController
from libs.redis.redis import RedisManager


class CircuitBreakerOpenError(Exception):
    """Raised when circuit is open and request is blocked."""
    pass


class CircuitBreaker:
    """
    Circuit breaker pattern with shared Redis state.

    States:
    - closed: Normal operation, requests pass through
    - open: Too many failures, requests blocked
    - half_open: Testing if service recovered

    The state is stored in Redis to ensure consistency across distributed instances.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        timeout: int = 60,
        redis: Optional[RedisManager] = None
    ):
        """
        Initialize circuit breaker.

        Args:
            name: Unique identifier for this circuit
            failure_threshold: Number of failures before opening circuit
            timeout: Seconds to wait before attempting reset
            redis: Optional Redis manager instance
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.redis = redis or RedisManager()
        self.logger = LoggingController(app_name=f"CircuitBreaker:{name}")

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with circuit breaker protection.

        Args:
            func: Async function to execute
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func

        Returns:
            Result of func execution

        Raises:
            CircuitBreakerOpenError: If circuit is open
            Exception: Any exception raised by func
        """
        correlation_id = kwargs.get("correlation_id", "")
        state = await self._get_state()

        # Check if circuit is open
        if state == "open":
            if not await self._should_attempt_reset():
                self.logger.log_warning(
                    f"Circuit {self.name} is open, blocking request",
                    {"correlation_id": correlation_id}
                )
                raise CircuitBreakerOpenError(f"Circuit {self.name} is open")

            # Try transitioning to half-open
            await self._set_state("half_open")
            self.logger.log_info(
                f"Circuit {self.name} transitioning to half-open",
                {"correlation_id": correlation_id}
            )

        # Execute function
        try:
            result = await func(*args, **kwargs)

            # If we're in half-open and succeeded, reset circuit
            if state == "half_open":
                await self._reset()
                self.logger.log_info(
                    f"Circuit {self.name} reset to closed after successful test",
                    {"correlation_id": correlation_id}
                )

            return result

        except Exception as e:
            # Record failure
            await self._record_failure(correlation_id)
            raise

    async def _get_state(self) -> str:
        """
        Get current circuit state from Redis.

        Returns:
            State string: "closed", "open", or "half_open"
        """
        key = f"circuit:{self.name}:state"
        redis_client = await self.redis.get_client()
        state = await redis_client.get(key)
        return state.decode() if state else "closed"

    async def _record_failure(self, correlation_id: str = ""):
        """
        Record a failure and potentially open the circuit.

        Args:
            correlation_id: Request correlation ID for logging
        """
        key_failures = f"circuit:{self.name}:failures"
        redis_client = await self.redis.get_client()

        # Increment failure counter
        failures = await redis_client.incr(key_failures)
        await redis_client.expire(key_failures, self.timeout)

        self.logger.log_warning(
            f"Circuit {self.name} failure recorded",
            {
                "correlation_id": correlation_id,
                "failures": failures,
                "threshold": self.failure_threshold
            }
        )

        # Open circuit if threshold reached
        if failures >= self.failure_threshold:
            await self._set_state("open")
            self.logger.log_error(
                f"Circuit {self.name} opened after {failures} failures",
                {
                    "correlation_id": correlation_id,
                    "failures": failures,
                    "threshold": self.failure_threshold
                }
            )

    async def _set_state(self, state: str):
        """
        Set circuit state in Redis.

        Args:
            state: New state ("closed", "open", or "half_open")
        """
        key = f"circuit:{self.name}:state"
        redis_client = await self.redis.get_client()
        await redis_client.set(key, state, ex=self.timeout)

    async def _reset(self):
        """Reset circuit to closed state and clear failure counter."""
        redis_client = await self.redis.get_client()
        await redis_client.delete(f"circuit:{self.name}:state")
        await redis_client.delete(f"circuit:{self.name}:failures")
        self.logger.log_info(f"Circuit {self.name} reset to closed")

    async def _should_attempt_reset(self) -> bool:
        """
        Check if enough time has passed to attempt reset.

        Returns:
            True if circuit should attempt to reset (timeout expired)
        """
        key = f"circuit:{self.name}:state"
        redis_client = await self.redis.get_client()
        ttl = await redis_client.ttl(key)

        # If TTL is -2 (key doesn't exist) or -1 (no expiry), state has expired
        # and we should attempt reset
        return ttl <= 0

    def call_sync(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute synchronous function with circuit breaker protection.

        This is a synchronous wrapper around the async implementation.
        Use this for wrapping sync functions.

        Args:
            func: Synchronous function to execute
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func

        Returns:
            Result of func execution

        Raises:
            CircuitBreakerOpenError: If circuit is open
            Exception: Any exception raised by func
        """
        # Run the async logic in a new event loop
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        async def async_wrapper():
            correlation_id = kwargs.get("correlation_id", "")
            state = await self._get_state()

            # Check if circuit is open
            if state == "open":
                if not await self._should_attempt_reset():
                    self.logger.log_warning(
                        f"Circuit {self.name} is open, blocking request",
                        {"correlation_id": correlation_id}
                    )
                    raise CircuitBreakerOpenError(f"Circuit {self.name} is open")

                # Try transitioning to half-open
                await self._set_state("half_open")
                self.logger.log_info(
                    f"Circuit {self.name} transitioning to half-open",
                    {"correlation_id": correlation_id}
                )

            # Execute synchronous function
            try:
                result = func(*args, **kwargs)

                # If we're in half-open and succeeded, reset circuit
                if state == "half_open":
                    await self._reset()
                    self.logger.log_info(
                        f"Circuit {self.name} reset to closed after successful test",
                        {"correlation_id": correlation_id}
                    )

                return result

            except Exception as e:
                # Record failure
                await self._record_failure(correlation_id)
                raise

        return loop.run_until_complete(async_wrapper())
