"""Graceful shutdown manager for coordinating application cleanup."""

import asyncio
import os
from typing import Callable, List
from libs.log_manager.controller import LoggingController


class ShutdownManager:
    """
    Coordinates graceful shutdown of the application.

    Features:
    - Cleanup function registry
    - Connection draining with configurable timeout
    - Shutdown state tracking for health checks
    - In-flight request tracking

    Usage:
        >>> shutdown_manager = ShutdownManager(timeout=30)
        >>> shutdown_manager.register_cleanup(redis_manager.close)
        >>> shutdown_manager.register_cleanup(db_pool.close)
        >>> await shutdown_manager.shutdown()
    """

    def __init__(self, timeout: int = 30):
        """
        Initialize shutdown manager.

        Args:
            timeout: Maximum seconds to wait for cleanup (default: 30)
        """
        self.timeout = int(os.getenv("SHUTDOWN_TIMEOUT", str(timeout)))
        self._shutdown_initiated = False
        self._cleanup_functions: List[Callable] = []
        self._in_flight_requests = 0
        self.logger = LoggingController(app_name="ShutdownManager")

        self.logger.log_debug(
            "ShutdownManager initialized",
            {"timeout": self.timeout}
        )

    def register_cleanup(self, cleanup_fn: Callable):
        """
        Register a cleanup function to run during shutdown.

        Cleanup functions are executed in registration order.
        Functions can be sync or async.

        Args:
            cleanup_fn: Callable (sync or async) to run during shutdown

        Example:
            >>> shutdown_manager.register_cleanup(redis.close)
            >>> shutdown_manager.register_cleanup(db.disconnect)
        """
        self._cleanup_functions.append(cleanup_fn)

        self.logger.log_debug(
            f"Registered cleanup function: {cleanup_fn.__name__}",
            {"total_cleanup_functions": len(self._cleanup_functions)}
        )

    async def shutdown(self, correlation_id: str = ""):
        """
        Execute graceful shutdown sequence.

        Sequence:
        1. Set shutdown flag (health check returns 503)
        2. Wait for in-flight requests to complete (up to timeout)
        3. Run registered cleanup functions
        4. Log completion

        Args:
            correlation_id: Optional correlation ID for logging

        Example:
            >>> await shutdown_manager.shutdown()
        """
        if self._shutdown_initiated:
            self.logger.log_warning("Shutdown already initiated")
            return

        self._shutdown_initiated = True

        self.logger.log_info(
            "Graceful shutdown initiated",
            {
                "correlation_id": correlation_id,
                "timeout": self.timeout,
                "cleanup_functions": len(self._cleanup_functions),
                "in_flight_requests": self._in_flight_requests,
            }
        )

        # Wait for in-flight requests to complete
        if self._in_flight_requests > 0:
            self.logger.log_info(
                f"Waiting for {self._in_flight_requests} in-flight requests to complete..."
            )

            await self._wait_for_requests(self.timeout)

        # Run cleanup functions
        self.logger.log_info(
            f"Running {len(self._cleanup_functions)} cleanup functions..."
        )

        for cleanup_fn in self._cleanup_functions:
            try:
                fn_name = getattr(cleanup_fn, '__name__', str(cleanup_fn))
                self.logger.log_info(f"Running cleanup: {fn_name}")

                # Execute with timeout
                if asyncio.iscoroutinefunction(cleanup_fn):
                    # Async cleanup function
                    await asyncio.wait_for(cleanup_fn(), timeout=10)
                else:
                    # Sync cleanup function - run in executor
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, cleanup_fn)

                self.logger.log_info(f"Cleanup completed: {fn_name}")

            except asyncio.TimeoutError:
                self.logger.log_error(
                    f"Cleanup function timed out: {fn_name}",
                    {"timeout": 10}
                )

            except Exception as e:
                self.logger.log_error(
                    f"Cleanup function failed: {fn_name}",
                    {"error": str(e), "error_type": type(e).__name__}
                )

        self.logger.log_info(
            "Graceful shutdown completed",
            {"correlation_id": correlation_id}
        )

    async def _wait_for_requests(self, timeout: int):
        """
        Wait for in-flight requests to complete.

        Args:
            timeout: Maximum seconds to wait
        """
        import time
        start = time.time()

        while self._in_flight_requests > 0:
            elapsed = time.time() - start

            if elapsed > timeout:
                self.logger.log_warning(
                    f"Shutdown timeout reached: {self._in_flight_requests} requests still in-flight",
                    {
                        "timeout": timeout,
                        "in_flight_requests": self._in_flight_requests,
                    }
                )
                break

            # Wait a bit before checking again
            await asyncio.sleep(0.1)

        if self._in_flight_requests == 0:
            self.logger.log_info("All in-flight requests completed")

    def is_shutting_down(self) -> bool:
        """
        Check if shutdown has been initiated.

        Returns:
            True if shutdown is in progress

        Example:
            >>> if shutdown_manager.is_shutting_down():
            ...     return JSONResponse(status_code=503, content={"status": "shutting_down"})
        """
        return self._shutdown_initiated

    def increment_in_flight_requests(self):
        """
        Increment in-flight request counter.

        Call this at the start of request processing.
        """
        self._in_flight_requests += 1

    def decrement_in_flight_requests(self):
        """
        Decrement in-flight request counter.

        Call this at the end of request processing.
        """
        self._in_flight_requests = max(0, self._in_flight_requests - 1)

    @property
    def in_flight_requests(self) -> int:
        """Get current number of in-flight requests."""
        return self._in_flight_requests
