import os
import json
import asyncio
from typing import Optional, Dict, Any, List, Union
import redis.asyncio as redis
import redis as redis_sync
from redis.exceptions import (
    RedisError,
    ConnectionError,
    TimeoutError,
    AuthenticationError,
)
from libs.log_manager.controller import LoggingController
from libs.log_manager.core.utils import get_correlation_id

# Import CircuitBreaker but handle circular dependency
# (CircuitBreaker uses Redis for state storage)
try:
    from libs.resilience.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
    CIRCUIT_BREAKER_AVAILABLE = True
except ImportError:
    CIRCUIT_BREAKER_AVAILABLE = False
    CircuitBreaker = None
    CircuitBreakerOpenError = Exception


# ============================================================================
# GLOBAL CONNECTION POOLS (Shared by all instances)
# ============================================================================
# Thread-safe singleton pattern: prevents "Too many connections" errors
# Redis ConnectionPool is thread-safe by design

_global_async_redis_pool = None
_global_sync_redis_pool = None


def get_global_async_redis_pool() -> redis.ConnectionPool:
    """
    Get or create the global ASYNC Redis connection pool (singleton).
    
    Thread-safe, shared by all RedisManager instances.
    
    Returns:
        redis.ConnectionPool: Shared async connection pool
    """
    global _global_async_redis_pool
    
    if _global_async_redis_pool is None:
        _global_async_redis_pool = redis.ConnectionPool(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            password=os.getenv("REDIS_PASSWORD"),
            db=int(os.getenv("REDIS_DB", "0")),
            decode_responses=True,
            retry_on_timeout=True,
            retry_on_error=[redis.ConnectionError, redis.TimeoutError],
            # Short-circuit: when Redis isn't reachable (e.g. no Redis
            # deployed in prod), we want to fail-fast and let callers
            # fallback to the authoritative store instead of hanging 60s
            # per request. Override via REDIS_SOCKET_CONNECT_TIMEOUT.
            socket_connect_timeout=int(os.getenv("REDIS_SOCKET_CONNECT_TIMEOUT", "2")),
            socket_timeout=int(os.getenv("REDIS_SOCKET_TIMEOUT", "5")),
            socket_keepalive=True,
            socket_keepalive_options={},
            health_check_interval=30,
            max_connections=100,  # Global limit across all instances
        )

    return _global_async_redis_pool


def get_global_sync_redis_pool() -> redis_sync.ConnectionPool:
    """
    Get or create the global SYNC Redis connection pool (singleton).
    
    Thread-safe, shared by all CacheManager instances.
    
    Returns:
        redis.ConnectionPool: Shared sync connection pool
    """
    global _global_sync_redis_pool
    
    if _global_sync_redis_pool is None:
        _global_sync_redis_pool = redis_sync.ConnectionPool(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            password=os.getenv("REDIS_PASSWORD"),
            db=int(os.getenv("REDIS_DB", "0")),
            decode_responses=True,
            retry_on_timeout=True,
            retry_on_error=[redis_sync.ConnectionError, redis_sync.TimeoutError],
            # See async-pool note above. Sync pool keeps a longer read
            # timeout for BRPOP-style blocking ops, but connect still
            # short-circuits fast when Redis isn't there.
            socket_connect_timeout=int(os.getenv("REDIS_SOCKET_CONNECT_TIMEOUT", "2")),
            socket_timeout=int(os.getenv("REDIS_SOCKET_BLOCKING_TIMEOUT", "30")),
            socket_keepalive=True,
            socket_keepalive_options={},
            health_check_interval=30,
            max_connections=100,  # Global limit across all instances
        )

    return _global_sync_redis_pool


def _serialize_redis_value(value: Any) -> Union[str, int, float]:
    """
    Centralized serialization helper for Redis values.

    Args:
        value: Value to serialize

    Returns:
        Serialized value ready for Redis storage
    """
    # JSON encode complex types (dict, list, bool) for consistent Redis storage
    if isinstance(value, (dict, list, bool)):
        return json.dumps(value)
    # Return primitive types as-is
    return value


def _deserialize_redis_value(value: Any, decode_json: bool = False) -> Any:
    """
    Centralized deserialization helper for Redis values.

    Args:
        value: Value from Redis to deserialize
        decode_json: Whether to attempt JSON decoding

    Returns:
        Deserialized value
    """
    if value is None:
        return None

    # Attempt JSON decoding if requested and value is string
    if decode_json and isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            # If JSON decoding fails, return the original string
            pass

    return value


class RedisConnectionError(Exception):
    """Raised when a Redis connection error occurs."""

    pass


class RedisPermissionError(Exception):
    """Raised when a Redis permission or access error occurs."""

    pass


class RedisManager:
    """
    RedisManager encapsulates Redis operations with unified async interface,
    project-standard logging, and correlation_id propagation.

    Exceptions:
        - RedisConnectionError: Connection or authentication errors
        - RedisPermissionError: Permission/access denied
        - ValueError: Invalid data or parameters
        - RuntimeError: Other Redis or network errors
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        password: Optional[str] = None,
        db: Optional[int] = None,
        decode_responses: bool = True,
        enable_circuit_breaker: bool = True,
    ):
        """
        Initializes the RedisManager with connection parameters and sets up the Redis client.

        If parameters are not provided, values are loaded from environment variables.
        Logs the initialization status and raises an exception if client creation fails.

        Args:
            host: Redis server host
            port: Redis server port
            password: Redis password (if required)
            db: Redis database number
            decode_responses: Whether to decode responses to strings
            enable_circuit_breaker: Enable circuit breaker protection (default: True)
                Note: Set to False for internal circuit breaker usage to avoid circular dependency
        """
        self.logger = LoggingController(app_name="RedisManager")

        self.host = host or os.environ.get("REDIS_HOST", "localhost")
        self.port = port or int(os.environ.get("REDIS_PORT", "6379"))
        self.password = password or os.environ.get("REDIS_PASSWORD")
        self.db = db if db is not None else int(os.environ.get("REDIS_DB", "0"))
        self.decode_responses = decode_responses

        self.client = None
        self._connection_pool = None

        # Initialize circuit breaker (but avoid circular dependency)
        # CircuitBreaker uses Redis for state, so we disable circuit breaker for
        # Redis instances used by CircuitBreaker itself
        self.enable_circuit_breaker = (
            enable_circuit_breaker
            and CIRCUIT_BREAKER_AVAILABLE
            and os.getenv("ENABLE_CIRCUIT_BREAKERS", "true").lower() == "true"
        )

        if self.enable_circuit_breaker:
            try:
                failure_threshold = int(os.getenv("REDIS_CIRCUIT_FAILURE_THRESHOLD", "5"))
                timeout = int(os.getenv("REDIS_CIRCUIT_TIMEOUT", "30"))

                # Create circuit breaker with Redis disabled to avoid circular dependency
                from libs.resilience.circuit_breaker import CircuitBreaker

                # Create a Redis instance without circuit breaker for the circuit breaker's own use
                cb_redis = RedisManager(enable_circuit_breaker=False)

                self.circuit_breaker = CircuitBreaker(
                    name="redis",
                    failure_threshold=failure_threshold,
                    timeout=timeout,
                    redis=cb_redis
                )
                self.logger.log_debug(
                    "Circuit breaker enabled for Redis",
                    {"failure_threshold": failure_threshold, "timeout": timeout}
                )
            except Exception as e:
                self.logger.log_warning(
                    f"Failed to initialize circuit breaker: {e}. Continuing without circuit breaker."
                )
                self.enable_circuit_breaker = False
                self.circuit_breaker = None
        else:
            self.circuit_breaker = None
            if enable_circuit_breaker:
                self.logger.log_debug("Circuit breaker disabled for Redis")

        try:
            # Use global shared connection pool (prevents "Too many connections")
            self._connection_pool = get_global_async_redis_pool()

            # Create Redis client using the global shared pool
            self.client = redis.Redis(connection_pool=self._connection_pool)

            # Note: Connection test is done asynchronously via ping() method
            # to avoid blocking the initialization

            self.logger.log_info(
                "Redis client initialized using global shared pool",
                {
                    "host": self.host,
                    "port": self.port,
                    "db": self.db,
                    "pool_type": "global_shared",
                    "circuit_breaker_enabled": self.enable_circuit_breaker,
                },
            )
        except Exception as ex:
            self.logger.log_exception(
                ex, {"host": self.host, "port": self.port, "db": self.db}
            )
            raise RedisConnectionError(f"Failed to initialize Redis client: {ex}")

    async def ping(self, correlation_id: Optional[str] = None) -> bool:
        """
        Tests the Redis connection.

        Args:
            correlation_id: Optional correlation ID for logging and tracing

        Returns:
            True if connection is successful

        Raises:
            RedisConnectionError: If connection fails
        """
        correlation_id = correlation_id or get_correlation_id()
        context = {"correlation_id": correlation_id}

        try:
            self.logger.log_info("Testing Redis connection", context)
            result = await self.client.ping()
            self.logger.log_info("Redis connection successful", context)
            return result
        except (ConnectionError, TimeoutError) as e:
            self.logger.log_exception(e, context)
            raise RedisConnectionError(f"Redis connection failed: {e}")
        except AuthenticationError as e:
            self.logger.log_exception(e, context)
            raise RedisPermissionError(f"Redis authentication failed: {e}")
        except Exception as e:
            self.logger.log_exception(e, context)
            raise RuntimeError(f"Unexpected error during Redis ping: {e}")

    async def health_check(self, correlation_id: Optional[str] = None) -> bool:
        """
        Performs a health check on the Redis connection.

        Args:
            correlation_id: Optional correlation ID for logging and tracing

        Returns:
            True if Redis is healthy

        Raises:
            RedisConnectionError: If health check fails
        """
        correlation_id = correlation_id or get_correlation_id()
        context = {"correlation_id": correlation_id, "operation": "health_check"}

        try:
            self.logger.log_info("Performing Redis health check", context)

            # Test basic connectivity
            await self.ping(correlation_id)

            # Test basic operations
            test_key = f"health_check_{correlation_id}"
            await self.set_value(test_key, "test", ex=10, correlation_id=correlation_id)
            value = await self.get_value(test_key, correlation_id=correlation_id)
            await self.delete_key(test_key, correlation_id=correlation_id)

            if value != "test":
                raise RedisConnectionError(
                    "Health check failed: set/get operation returned unexpected value"
                )

            self.logger.log_info("Redis health check successful", context)
            return True

        except RedisConnectionError:
            raise
        except Exception as e:
            self.logger.log_exception(e, context)
            raise RedisConnectionError(f"Redis health check failed: {e}")

    async def set_value(
        self,
        key: str,
        value: Union[str, int, float, dict, list],
        ex: Optional[int] = None,
        correlation_id: Optional[str] = None,
    ) -> bool:
        """
        Sets a value in Redis with optional expiration.

        Args:
            key: Redis key
            value: Value to store (will be JSON-encoded if complex type)
            ex: Expiration time in seconds
            correlation_id: Optional correlation ID for logging and tracing

        Returns:
            True if the value was set successfully

        Raises:
            RedisConnectionError: If connection fails
            RuntimeError: For other Redis errors
        """
        correlation_id = correlation_id or get_correlation_id()
        context = {"correlation_id": correlation_id, "key": key, "expiration": ex}

        try:
            self.logger.log_info(f"Setting Redis key '{key}'", context)

            # Use centralized serialization for consistent encoding
            value = _serialize_redis_value(value)

            result = await self.client.set(key, value, ex=ex)

            self.logger.log_info(f"Redis key '{key}' set successfully", context)
            return bool(result)

        except (ConnectionError, TimeoutError) as e:
            self.logger.log_exception(e, context)
            raise RedisConnectionError(
                f"Redis connection failed while setting key '{key}': {e}"
            )
        except AuthenticationError as e:
            self.logger.log_exception(e, context)
            raise RedisPermissionError(
                f"Redis authentication failed while setting key '{key}': {e}"
            )
        except Exception as e:
            self.logger.log_exception(e, context)
            raise RuntimeError(f"Unexpected error while setting Redis key '{key}': {e}")

    async def get_value(
        self, key: str, decode_json: bool = False, correlation_id: Optional[str] = None
    ) -> Optional[Union[str, dict, list]]:
        """
        Gets a value from Redis.

        Args:
            key: Redis key
            decode_json: Whether to attempt JSON decoding of the value
            correlation_id: Optional correlation ID for logging and tracing

        Returns:
            The value associated with the key, or None if key doesn't exist

        Raises:
            RedisConnectionError: If connection fails
            RuntimeError: For other Redis errors
        """
        correlation_id = correlation_id or get_correlation_id()
        context = {
            "correlation_id": correlation_id,
            "key": key,
            "decode_json": decode_json,
        }

        try:
            self.logger.log_info(f"Getting Redis key '{key}'", context)

            value = await self.client.get(key)

            if value is None:
                self.logger.log_info(f"Redis key '{key}' not found", context)
                return None

            # Use centralized deserialization for consistent decoding
            value = _deserialize_redis_value(value, decode_json)

            self.logger.log_info(f"Redis key '{key}' retrieved successfully", context)
            return value

        except (ConnectionError, TimeoutError) as e:
            self.logger.log_exception(e, context)
            raise RedisConnectionError(
                f"Redis connection failed while getting key '{key}': {e}"
            )
        except AuthenticationError as e:
            self.logger.log_exception(e, context)
            raise RedisPermissionError(
                f"Redis authentication failed while getting key '{key}': {e}"
            )
        except Exception as e:
            self.logger.log_exception(e, context)
            raise RuntimeError(f"Unexpected error while getting Redis key '{key}': {e}")

    async def incr(self, key: str, amount: int = 1, correlation_id: Optional[str] = None) -> int:
        """
        Increments a key in Redis by the given amount.
        
        If the key does not exist, it is set to 0 before performing the operation.

        Args:
            key: Redis key to increment
            amount: Amount to increment by (default: 1)
            correlation_id: Optional correlation ID for logging and tracing

        Returns:
            The new value after increment

        Raises:
            RedisConnectionError: If connection fails
            RuntimeError: For other Redis errors
        """
        correlation_id = correlation_id or get_correlation_id()
        context = {"correlation_id": correlation_id, "key": key, "amount": amount}

        try:
            self.logger.log_debug(f"Incrementing Redis key '{key}' by {amount}", context)

            result = await self.client.incrby(key, amount)

            self.logger.log_debug(f"Redis key '{key}' incremented to {result}", context)
            return result

        except (ConnectionError, TimeoutError) as e:
            self.logger.log_exception(e, context)
            raise RedisConnectionError(
                f"Redis connection failed while incrementing key '{key}': {e}"
            )
        except Exception as e:
            self.logger.log_exception(e, context)
            raise RuntimeError(f"Unexpected error while incrementing Redis key '{key}': {e}")

    async def delete_key(self, key: str, correlation_id: Optional[str] = None) -> bool:
        """
        Deletes a key from Redis.

        Args:
            key: Redis key to delete
            correlation_id: Optional correlation ID for logging and tracing

        Returns:
            True if the key was deleted, False if it didn't exist

        Raises:
            RedisConnectionError: If connection fails
            RuntimeError: For other Redis errors
        """
        correlation_id = correlation_id or get_correlation_id()
        context = {"correlation_id": correlation_id, "key": key}

        try:
            self.logger.log_info(f"Deleting Redis key '{key}'", context)

            result = await self.client.delete(key)

            if result:
                self.logger.log_info(f"Redis key '{key}' deleted successfully", context)
            else:
                self.logger.log_info(f"Redis key '{key}' did not exist", context)

            return bool(result)

        except (ConnectionError, TimeoutError) as e:
            self.logger.log_exception(e, context)
            raise RedisConnectionError(
                f"Redis connection failed while deleting key '{key}': {e}"
            )
        except AuthenticationError as e:
            self.logger.log_exception(e, context)
            raise RedisPermissionError(
                f"Redis authentication failed while deleting key '{key}': {e}"
            )
        except Exception as e:
            self.logger.log_exception(e, context)
            raise RuntimeError(
                f"Unexpected error while deleting Redis key '{key}': {e}"
            )

    async def exists(self, key: str, correlation_id: Optional[str] = None) -> bool:
        """
        Checks if a key exists in Redis.

        Args:
            key: Redis key to check
            correlation_id: Optional correlation ID for logging and tracing

        Returns:
            True if the key exists, False otherwise

        Raises:
            RedisConnectionError: If connection fails
            RuntimeError: For other Redis errors
        """
        correlation_id = correlation_id or get_correlation_id()
        context = {"correlation_id": correlation_id, "key": key}

        try:
            self.logger.log_info(f"Checking existence of Redis key '{key}'", context)

            result = await self.client.exists(key)
            exists = bool(result)

            self.logger.log_info(f"Redis key '{key}' exists: {exists}", context)
            return exists

        except (ConnectionError, TimeoutError) as e:
            self.logger.log_exception(e, context)
            raise RedisConnectionError(
                f"Redis connection failed while checking key '{key}': {e}"
            )
        except AuthenticationError as e:
            self.logger.log_exception(e, context)
            raise RedisPermissionError(
                f"Redis authentication failed while checking key '{key}': {e}"
            )
        except Exception as e:
            self.logger.log_exception(e, context)
            raise RuntimeError(
                f"Unexpected error while checking Redis key '{key}': {e}"
            )

    async def set_expiration(
        self, key: str, seconds: int, correlation_id: Optional[str] = None
    ) -> bool:
        """
        Sets expiration time for a key.

        Args:
            key: Redis key
            seconds: Expiration time in seconds
            correlation_id: Optional correlation ID for logging and tracing

        Returns:
            True if expiration was set successfully

        Raises:
            RedisConnectionError: If connection fails
            RuntimeError: For other Redis errors
        """
        correlation_id = correlation_id or get_correlation_id()
        context = {"correlation_id": correlation_id, "key": key, "seconds": seconds}

        try:
            self.logger.log_info(
                f"Setting expiration for Redis key '{key}' to {seconds} seconds",
                context,
            )

            result = await self.client.expire(key, seconds)

            if result:
                self.logger.log_info(
                    f"Expiration set successfully for Redis key '{key}'", context
                )
            else:
                self.logger.log_warning(
                    f"Failed to set expiration for Redis key '{key}' (key may not exist)",
                    context,
                )

            return bool(result)

        except (ConnectionError, TimeoutError) as e:
            self.logger.log_exception(e, context)
            raise RedisConnectionError(
                f"Redis connection failed while setting expiration for key '{key}': {e}"
            )
        except AuthenticationError as e:
            self.logger.log_exception(e, context)
            raise RedisPermissionError(
                f"Redis authentication failed while setting expiration for key '{key}': {e}"
            )
        except Exception as e:
            self.logger.log_exception(e, context)
            raise RuntimeError(
                f"Unexpected error while setting expiration for Redis key '{key}': {e}"
            )

    async def get_keys(
        self, pattern: str = "*", correlation_id: Optional[str] = None
    ) -> List[str]:
        """
        Gets all keys matching a pattern.

        Args:
            pattern: Pattern to match keys (default: "*" for all keys)
            correlation_id: Optional correlation ID for logging and tracing

        Returns:
            List of matching keys

        Raises:
            RedisConnectionError: If connection fails
            RuntimeError: For other Redis errors
        """
        correlation_id = correlation_id or get_correlation_id()
        context = {"correlation_id": correlation_id, "pattern": pattern}

        try:
            self.logger.log_info(
                f"Getting Redis keys matching pattern '{pattern}'", context
            )

            keys = await self.client.keys(pattern)

            self.logger.log_info(
                f"Found {len(keys)} Redis keys matching pattern '{pattern}'",
                {**context, "key_count": len(keys)},
            )
            return keys

        except (ConnectionError, TimeoutError) as e:
            self.logger.log_exception(e, context)
            raise RedisConnectionError(
                f"Redis connection failed while getting keys with pattern '{pattern}': {e}"
            )
        except AuthenticationError as e:
            self.logger.log_exception(e, context)
            raise RedisPermissionError(
                f"Redis authentication failed while getting keys with pattern '{pattern}': {e}"
            )
        except Exception as e:
            self.logger.log_exception(e, context)
            raise RuntimeError(
                f"Unexpected error while getting Redis keys with pattern '{pattern}': {e}"
            )

    async def push_to_queue(
        self,
        queue_name: str,
        item: Union[str, int, float, dict, list, bool],
        correlation_id: Optional[str] = None,
    ) -> int:
        """
        Pushes an item to a Redis list (queue).

        Args:
            queue_name: Name of the queue (Redis list)
            item: Item to push (will be JSON-encoded if complex type)
            correlation_id: Optional correlation ID for logging and tracing

        Returns:
            Length of the queue after the push operation

        Raises:
            RedisConnectionError: If connection fails
            RuntimeError: For other Redis errors
        """
        correlation_id = correlation_id or get_correlation_id()
        context = {"correlation_id": correlation_id, "queue_name": queue_name}

        try:
            self.logger.log_info(f"Pushing item to Redis queue '{queue_name}'", context)

            # Use centralized serialization for consistent encoding
            item = _serialize_redis_value(item)

            length = await self.client.lpush(queue_name, item)

            self.logger.log_info(
                f"Item pushed to Redis queue '{queue_name}', new length: {length}",
                {**context, "queue_length": length},
            )
            return length

        except (ConnectionError, TimeoutError) as e:
            self.logger.log_exception(e, context)
            raise RedisConnectionError(
                f"Redis connection failed while pushing to queue '{queue_name}': {e}"
            )
        except AuthenticationError as e:
            self.logger.log_exception(e, context)
            raise RedisPermissionError(
                f"Redis authentication failed while pushing to queue '{queue_name}': {e}"
            )
        except Exception as e:
            self.logger.log_exception(e, context)
            raise RuntimeError(
                f"Unexpected error while pushing to Redis queue '{queue_name}': {e}"
            )

    async def pop_from_queue(
        self,
        queue_name: str,
        decode_json: bool = False,
        timeout: Optional[int] = None,
        correlation_id: Optional[str] = None,
    ) -> Optional[Union[str, dict, list]]:
        """
        Pops an item from a Redis list (queue).

        Args:
            queue_name: Name of the queue (Redis list)
            decode_json: Whether to attempt JSON decoding of the item
            timeout: Timeout in seconds for blocking pop (None for non-blocking)
            correlation_id: Optional correlation ID for logging and tracing

        Returns:
            The popped item, or None if queue is empty (for non-blocking pop)

        Raises:
            RedisConnectionError: If connection fails
            RuntimeError: For other Redis errors
        """
        correlation_id = correlation_id or get_correlation_id()
        context = {
            "correlation_id": correlation_id,
            "queue_name": queue_name,
            "timeout": timeout,
        }

        try:
            self.logger.log_info(
                f"Popping item from Redis queue '{queue_name}'", context
            )

            if timeout is not None:
                # Blocking pop
                result = await self.client.brpop(queue_name, timeout=timeout)
                item = result[1] if result else None
            else:
                # Non-blocking pop
                item = await self.client.rpop(queue_name)

            if item is None:
                self.logger.log_info(
                    f"No item available in Redis queue '{queue_name}'", context
                )
                return None

            # Use centralized deserialization for consistent decoding
            item = _deserialize_redis_value(item, decode_json)

            self.logger.log_info(
                f"Item popped from Redis queue '{queue_name}'", context
            )
            return item

        except (ConnectionError, TimeoutError) as e:
            self.logger.log_exception(e, context)
            raise RedisConnectionError(
                f"Redis connection failed while popping from queue '{queue_name}': {e}"
            )
        except AuthenticationError as e:
            self.logger.log_exception(e, context)
            raise RedisPermissionError(
                f"Redis authentication failed while popping from queue '{queue_name}': {e}"
            )
        except Exception as e:
            self.logger.log_exception(e, context)
            raise RuntimeError(
                f"Unexpected error while popping from Redis queue '{queue_name}': {e}"
            )

    async def close(self, correlation_id: Optional[str] = None):
        """
        Closes the Redis connection.

        Args:
            correlation_id: Optional correlation ID for logging and tracing
        """
        correlation_id = correlation_id or get_correlation_id()
        context = {"correlation_id": correlation_id}

        try:
            if self.client:
                self.logger.log_info("Closing Redis connection", context)
                await self.client.close()
                self.logger.log_info("Redis connection closed successfully", context)
        except Exception as e:
            self.logger.log_exception(e, context)
            # Don't raise exception on close, just log it

    def get_client(self) -> redis.Redis:
        """
        Returns the underlying Redis client for advanced operations.

        Returns:
            The Redis client instance
        """
        return self.client

    # Alias methods for backward compatibility
    async def set_key(
        self,
        key: str,
        value: Union[str, int, float, dict, list],
        ex: Optional[int] = None,
        correlation_id: Optional[str] = None,
    ) -> bool:
        """Alias for set_value method."""
        return await self.set_value(key, value, ex, correlation_id)

    async def get_key(
        self, key: str, decode_json: bool = False, correlation_id: Optional[str] = None
    ) -> Optional[Union[str, dict, list]]:
        """Alias for get_value method."""
        return await self.get_value(key, decode_json, correlation_id)

    async def add_to_list(
        self,
        key: str,
        value: Union[str, int, float, dict, list, bool],
        correlation_id: Optional[str] = None,
    ) -> int:
        """
        Add an item to the beginning of a Redis list.

        Args:
            key: Redis list key
            value: Value to add (will be JSON-encoded if complex type)
            correlation_id: Optional correlation ID for logging and tracing

        Returns:
            Length of the list after the push operation

        Raises:
            RedisConnectionError: If connection fails
            RuntimeError: For other Redis errors
        """
        correlation_id = correlation_id or get_correlation_id()
        context = {"correlation_id": correlation_id, "key": key}

        try:
            self.logger.log_info(f"Adding item to Redis list '{key}'", context)

            # Use centralized serialization for consistent encoding
            value = _serialize_redis_value(value)

            length = await self.client.lpush(key, value)

            self.logger.log_info(
                f"Item added to Redis list '{key}', new length: {length}",
                {**context, "list_length": length},
            )
            return length

        except (ConnectionError, TimeoutError) as e:
            self.logger.log_exception(e, context)
            raise RedisConnectionError(
                f"Redis connection failed while adding to list '{key}': {e}"
            )
        except AuthenticationError as e:
            self.logger.log_exception(e, context)
            raise RedisPermissionError(
                f"Redis authentication failed while adding to list '{key}': {e}"
            )
        except Exception as e:
            self.logger.log_exception(e, context)
            raise RuntimeError(
                f"Unexpected error while adding to Redis list '{key}': {e}"
            )

    async def get_list_length(
        self, key: str, correlation_id: Optional[str] = None
    ) -> int:
        """
        Get the length of a Redis list.

        Args:
            key: Redis list key
            correlation_id: Optional correlation ID for logging and tracing

        Returns:
            Length of the list

        Raises:
            RedisConnectionError: If connection fails
            RuntimeError: For other Redis errors
        """
        correlation_id = correlation_id or get_correlation_id()
        context = {"correlation_id": correlation_id, "key": key}

        try:
            self.logger.log_info(f"Getting length of Redis list '{key}'", context)

            length = await self.client.llen(key)

            self.logger.log_info(
                f"Redis list '{key}' length: {length}",
                {**context, "list_length": length},
            )
            return length

        except (ConnectionError, TimeoutError) as e:
            self.logger.log_exception(e, context)
            raise RedisConnectionError(
                f"Redis connection failed while getting list length '{key}': {e}"
            )
        except AuthenticationError as e:
            self.logger.log_exception(e, context)
            raise RedisPermissionError(
                f"Redis authentication failed while getting list length '{key}': {e}"
            )
        except Exception as e:
            self.logger.log_exception(e, context)
            raise RuntimeError(
                f"Unexpected error while getting Redis list length '{key}': {e}"
            )

    async def get_list_range(
        self,
        key: str,
        start: int,
        end: int,
        decode_json: bool = False,
        correlation_id: Optional[str] = None,
    ) -> List[Union[str, dict, list]]:
        """
        Get a range of items from a Redis list.

        Args:
            key: Redis list key
            start: Start index
            end: End index (-1 for end of list)
            decode_json: Whether to attempt JSON decoding of items
            correlation_id: Optional correlation ID for logging and tracing

        Returns:
            List of items in the specified range

        Raises:
            RedisConnectionError: If connection fails
            RuntimeError: For other Redis errors
        """
        correlation_id = correlation_id or get_correlation_id()
        context = {
            "correlation_id": correlation_id,
            "key": key,
            "start": start,
            "end": end,
        }

        try:
            self.logger.log_info(
                f"Getting range from Redis list '{key}' [{start}:{end}]", context
            )

            items = await self.client.lrange(key, start, end)

            # Use centralized deserialization for consistent decoding
            if decode_json:
                items = [
                    _deserialize_redis_value(item, decode_json=True) for item in items
                ]

            self.logger.log_info(
                f"Retrieved {len(items)} items from Redis list '{key}'",
                {**context, "item_count": len(items)},
            )
            return items

        except (ConnectionError, TimeoutError) as e:
            self.logger.log_exception(e, context)
            raise RedisConnectionError(
                f"Redis connection failed while getting list range '{key}': {e}"
            )
        except AuthenticationError as e:
            self.logger.log_exception(e, context)
            raise RedisPermissionError(
                f"Redis authentication failed while getting list range '{key}': {e}"
            )
        except Exception as e:
            self.logger.log_exception(e, context)
            raise RuntimeError(
                f"Unexpected error while getting Redis list range '{key}': {e}"
            )

    async def remove_from_list(
        self, key: str, index: int, correlation_id: Optional[str] = None
    ) -> bool:
        """
        Remove an item from a Redis list by index.
        Note: This is implemented using a combination of lset and lrem for efficiency.

        Args:
            key: Redis list key
            index: Index of item to remove
            correlation_id: Optional correlation ID for logging and tracing

        Returns:
            True if item was removed successfully

        Raises:
            RedisConnectionError: If connection fails
            RuntimeError: For other Redis errors
        """
        correlation_id = correlation_id or get_correlation_id()
        context = {"correlation_id": correlation_id, "key": key, "index": index}

        try:
            self.logger.log_info(
                f"Removing item at index {index} from Redis list '{key}'", context
            )

            # Get the item at the index first
            item = await self.client.lindex(key, index)
            if item is None:
                self.logger.log_warning(
                    f"No item found at index {index} in Redis list '{key}'", context
                )
                return False

            # Mark the item for deletion with a unique placeholder
            placeholder = f"__DELETE_PLACEHOLDER_{correlation_id}__"
            await self.client.lset(key, index, placeholder)

            # Remove the placeholder
            removed_count = await self.client.lrem(key, 1, placeholder)

            success = removed_count > 0
            if success:
                self.logger.log_info(
                    f"Item removed from Redis list '{key}' at index {index}", context
                )
            else:
                self.logger.log_warning(
                    f"Failed to remove item from Redis list '{key}' at index {index}",
                    context,
                )

            return success

        except (ConnectionError, TimeoutError) as e:
            self.logger.log_exception(e, context)
            raise RedisConnectionError(
                f"Redis connection failed while removing from list '{key}': {e}"
            )
        except AuthenticationError as e:
            self.logger.log_exception(e, context)
            raise RedisPermissionError(
                f"Redis authentication failed while removing from list '{key}': {e}"
            )
        except Exception as e:
            self.logger.log_exception(e, context)
            raise RuntimeError(
                f"Unexpected error while removing from Redis list '{key}': {e}"
            )

    async def pop_from_list(
        self,
        key: str,
        decode_json: bool = False,
        timeout: Optional[int] = None,
        correlation_id: Optional[str] = None,
    ) -> Optional[Union[str, dict, list]]:
        """
        Pop an item from the end of a Redis list.
        This is an alias for pop_from_queue to maintain compatibility.

        Args:
            key: Redis list key
            decode_json: Whether to attempt JSON decoding of the item
            timeout: Timeout in seconds for blocking pop (None for non-blocking)
            correlation_id: Optional correlation ID for logging and tracing

        Returns:
            The popped item, or None if list is empty (for non-blocking pop)

        Raises:
            RedisConnectionError: If connection fails
            RuntimeError: For other Redis errors
        """
        return await self.pop_from_queue(key, decode_json, timeout, correlation_id)

    async def publish(
        self,
        channel: str,
        message: Union[str, dict, list],
        correlation_id: Optional[str] = None,
    ) -> int:
        """
        Publish a message to a Redis pub/sub channel.

        Args:
            channel: Channel name
            message: Message to publish (will be JSON-encoded if complex type)
            correlation_id: Optional correlation ID for logging and tracing

        Returns:
            Number of subscribers that received the message

        Raises:
            RedisConnectionError: If connection fails
            RuntimeError: For other Redis errors
        """
        correlation_id = correlation_id or get_correlation_id()
        context = {"correlation_id": correlation_id, "channel": channel}

        try:
            self.logger.log_debug(f"Publishing message to Redis channel '{channel}'", context)

            # Serialize message if needed
            if isinstance(message, (dict, list)):
                message = json.dumps(message)

            result = await self.client.publish(channel, message)

            self.logger.log_debug(
                f"Message published to Redis channel '{channel}', {result} subscribers received",
                {**context, "subscribers_count": result},
            )
            return result

        except (ConnectionError, TimeoutError) as e:
            self.logger.log_exception(e, context)
            raise RedisConnectionError(
                f"Redis connection failed while publishing to channel '{channel}': {e}"
            )
        except AuthenticationError as e:
            self.logger.log_exception(e, context)
            raise RedisPermissionError(
                f"Redis authentication failed while publishing to channel '{channel}': {e}"
            )
        except Exception as e:
            self.logger.log_exception(e, context)
            raise RuntimeError(
                f"Unexpected error while publishing to Redis channel '{channel}': {e}"
            )

    async def subscribe(self, channel: str, correlation_id: Optional[str] = None):
        """
        Subscribe to a Redis pub/sub channel.

        Args:
            channel: Channel name to subscribe to
            correlation_id: Optional correlation ID for logging and tracing

        Returns:
            PubSub object for listening to messages

        Raises:
            RedisConnectionError: If connection fails
            RuntimeError: For other Redis errors
        """
        correlation_id = correlation_id or get_correlation_id()
        context = {"correlation_id": correlation_id, "channel": channel}

        try:
            self.logger.log_debug(f"Subscribing to Redis channel '{channel}'", context)

            # Create a new pubsub instance
            pubsub = self.client.pubsub()
            await pubsub.subscribe(channel)

            self.logger.log_debug(f"Subscribed to Redis channel '{channel}'", context)
            return pubsub

        except (ConnectionError, TimeoutError) as e:
            self.logger.log_exception(e, context)
            raise RedisConnectionError(
                f"Redis connection failed while subscribing to channel '{channel}': {e}"
            )
        except AuthenticationError as e:
            self.logger.log_exception(e, context)
            raise RedisPermissionError(
                f"Redis authentication failed while subscribing to channel '{channel}': {e}"
            )
        except Exception as e:
            self.logger.log_exception(e, context)
            raise RuntimeError(
                f"Unexpected error while subscribing to Redis channel '{channel}': {e}"
            )
