import hashlib
import json
import redis  # Keep synchronous Redis for CacheManager
from typing import Optional, Dict, Any, List, Union, Callable, TypeVar
from functools import wraps
from datetime import datetime, timedelta
from libs.log_manager.controller import LoggingController
from libs.log_manager.core.utils import get_correlation_id
import os

T = TypeVar("T")


class CacheKeyError(Exception):
    """Raised when cache key generation fails."""

    pass


class CacheOperationError(Exception):
    """Raised when cache operations fail."""

    pass


class RedisConnectionError(Exception):
    """Raised when Redis connection fails."""

    pass


class CacheManager:
    """
    High-level Redis cache manager for caching database results, API responses,
    and other external service data.

    Features:
    - Automatic key generation with namespacing
    - TTL-based expiration policies
    - Cache invalidation patterns
    - Decorators for easy caching
    - JSON serialization for complex objects
    - Correlation ID propagation for debugging

    Use Cases:
    - Database query results caching
    - Business Central API responses
    - Supabase query results
    - External service API responses
    - Computed results caching

    Note: Uses SYNCHRONOUS Redis client for compatibility with workers
    """

    def __init__(
        self,
        redis_client: Optional[redis.Redis] = None,
        default_ttl: int = 3600,
        key_prefix: str = "cache",
    ):
        """
        Initialize the cache manager with synchronous Redis client.

        Args:
            redis_client: Optional Redis client instance (creates new if None)
            default_ttl: Default TTL in seconds (1 hour)
            key_prefix: Default prefix for cache keys
        """
        self.logger = LoggingController(app_name="CacheManager")

        if redis_client:
            self.redis = redis_client
        else:
            # Use global shared SYNC connection pool (prevents "Too many connections")
            from app.libs.redis.redis import get_global_sync_redis_pool
            pool = get_global_sync_redis_pool()
            self.redis = redis.Redis(connection_pool=pool)

        self.default_ttl = default_ttl
        self.key_prefix = key_prefix

        # Cache strategies
        self.TTL_SHORT = 300  # 5 minutes
        self.TTL_MEDIUM = 3600  # 1 hour
        self.TTL_LONG = 86400  # 24 hours
        self.TTL_WEEK = 604800  # 1 week

        self.logger.log_debug(
            "CacheManager initialized with synchronous Redis client",
            {
                "default_ttl": default_ttl,
                "key_prefix": key_prefix,
                "socket_timeout": 60,
                "socket_connect_timeout": 30,
            },
        )

    def generate_cache_key(
        self, namespace: str, identifier: str, params: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Generate a standardized cache key.

        Args:
            namespace: Cache namespace (e.g., 'db', 'bc', 'supabase')
            identifier: Resource identifier (e.g., table name, endpoint)
            params: Optional parameters to include in key

        Returns:
            Generated cache key

        Example:
            cache:db:clients:hash_of_params
            cache:bc:customers:hash_of_params
            cache:supabase:projects:hash_of_params
        """
        try:
            key_parts = [self.key_prefix, namespace, identifier]

            if params:
                # Create deterministic hash of parameters
                params_str = json.dumps(params, sort_keys=True, separators=(",", ":"))
                params_hash = hashlib.md5(params_str.encode()).hexdigest()[:16]
                key_parts.append(params_hash)

            return ":".join(key_parts)

        except Exception as e:
            raise CacheKeyError(f"Failed to generate cache key: {e}")

    def get(
        self,
        namespace: str,
        identifier: str,
        params: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
    ) -> Optional[Any]:
        """
        Get cached value.

        Args:
            namespace: Cache namespace
            identifier: Resource identifier
            params: Optional parameters
            correlation_id: Optional correlation ID

        Returns:
            Cached value or None if not found
        """
        correlation_id = correlation_id or get_correlation_id()
        key = self.generate_cache_key(namespace, identifier, params)

        context = {
            "correlation_id": correlation_id,
            "cache_key": key,
            "namespace": namespace,
            "identifier": identifier,
        }

        try:
            self.logger.log_debug("Getting cached value", context)

            value = self.redis.get(key)

            if value is not None:
                # Only decode values that were originally JSON-serialized (marked with prefix)
                if isinstance(value, str) and value.startswith("__JSON__:"):
                    try:
                        value = json.loads(value[9:])  # Remove "__JSON__:" prefix
                    except json.JSONDecodeError:
                        # If decoding fails, remove prefix and return as string
                        value = value[9:]

                self.logger.log_debug("Cache hit", context)
                return value
            else:
                self.logger.log_debug("Cache miss", context)
                return None

        except redis.RedisError as e:
            self.logger.log_exception(e, context)
            raise CacheOperationError(f"Cache get operation failed: {e}")
        except Exception as e:
            self.logger.log_exception(e, context)
            raise CacheOperationError(f"Unexpected error during cache get: {e}")

    def set(
        self,
        namespace: str,
        identifier: str,
        value: Any,
        ttl: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
    ) -> bool:
        """
        Set cached value with optional TTL.

        Args:
            namespace: Cache namespace
            identifier: Resource identifier
            value: Value to cache
            ttl: TTL in seconds (uses default if None)
            params: Optional parameters
            correlation_id: Optional correlation ID

        Returns:
            True if value was cached successfully
        """
        correlation_id = correlation_id or get_correlation_id()
        key = self.generate_cache_key(namespace, identifier, params)
        ttl = ttl or self.default_ttl

        context = {
            "correlation_id": correlation_id,
            "cache_key": key,
            "namespace": namespace,
            "identifier": identifier,
            "ttl": ttl,
        }

        try:
            self.logger.log_debug("Setting cached value", context)

            # Serialize complex types with prefix to identify JSON data
            if isinstance(value, str):
                # Store strings as-is (no prefix)
                serialized_value = value
            else:
                # Prefix JSON-serialized data with special marker
                serialized_value = "__JSON__:" + json.dumps(value)

            success = self.redis.set(key, serialized_value, ex=ttl)

            if success:
                self.logger.log_debug("Value cached successfully", context)
            else:
                self.logger.log_warning("Failed to cache value", context)

            return bool(success)

        except redis.RedisError as e:
            self.logger.log_exception(e, context)
            raise CacheOperationError(f"Cache set operation failed: {e}")
        except Exception as e:
            self.logger.log_exception(e, context)
            raise CacheOperationError(f"Unexpected error during cache set: {e}")

    def delete(
        self,
        namespace: str,
        identifier: str,
        params: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
    ) -> bool:
        """
        Delete cached value.

        Args:
            namespace: Cache namespace
            identifier: Resource identifier
            params: Optional parameters
            correlation_id: Optional correlation ID

        Returns:
            True if value was deleted
        """
        correlation_id = correlation_id or get_correlation_id()
        key = self.generate_cache_key(namespace, identifier, params)

        context = {
            "correlation_id": correlation_id,
            "cache_key": key,
            "namespace": namespace,
            "identifier": identifier,
        }

        try:
            self.logger.log_debug("Deleting cached value", context)

            success = self.redis.delete(key)

            if success:
                self.logger.log_debug("Cached value deleted", context)
            else:
                self.logger.log_debug("Cached value not found for deletion", context)

            return bool(success)

        except redis.RedisError as e:
            self.logger.log_exception(e, context)
            raise CacheOperationError(f"Cache delete operation failed: {e}")
        except Exception as e:
            self.logger.log_exception(e, context)
            raise CacheOperationError(f"Unexpected error during cache delete: {e}")

    def invalidate_pattern(
        self, namespace: str, pattern: str = "*", correlation_id: Optional[str] = None
    ) -> int:
        """
        Invalidate cache entries matching a pattern.

        Args:
            namespace: Cache namespace to target
            pattern: Pattern to match (default: all in namespace)
            correlation_id: Optional correlation ID

        Returns:
            Number of keys deleted
        """
        correlation_id = correlation_id or get_correlation_id()
        search_pattern = f"{self.key_prefix}:{namespace}:{pattern}"

        context = {
            "correlation_id": correlation_id,
            "namespace": namespace,
            "pattern": search_pattern,
        }

        try:
            self.logger.log_debug("Invalidating cache pattern", context)

            # Use scan_iter to avoid blocking Redis
            keys = list(self.redis.scan_iter(match=search_pattern))

            if not keys:
                self.logger.log_debug("No keys found for pattern", context)
                return 0

            deleted_count = self.redis.delete(*keys)

            self.logger.log_debug(
                f"Invalidated {deleted_count} cache entries",
                {**context, "deleted_count": deleted_count},
            )

            return deleted_count

        except redis.RedisError as e:
            self.logger.log_exception(e, context)
            raise CacheOperationError(f"Cache invalidation failed: {e}")
        except Exception as e:
            self.logger.log_exception(e, context)
            raise CacheOperationError(
                f"Unexpected error during cache invalidation: {e}"
            )

    def exists(
        self,
        namespace: str,
        identifier: str,
        params: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
    ) -> bool:
        """
        Check if cached value exists.

        Args:
            namespace: Cache namespace
            identifier: Resource identifier
            params: Optional parameters
            correlation_id: Optional correlation ID

        Returns:
            True if cached value exists
        """
        correlation_id = correlation_id or get_correlation_id()
        key = self.generate_cache_key(namespace, identifier, params)

        try:
            return bool(self.redis.exists(key))
        except redis.RedisError as e:
            self.logger.log_exception(
                e, {"correlation_id": correlation_id, "cache_key": key}
            )
            raise CacheOperationError(f"Cache exists check failed: {e}")

    def cached(
        self,
        namespace: str,
        identifier: str,
        ttl: Optional[int] = None,
        key_params: Optional[List[str]] = None,
    ):
        """
        Decorator for caching function results.

        Args:
            namespace: Cache namespace
            identifier: Resource identifier
            ttl: TTL in seconds
            key_params: Parameter names to include in cache key

        Example:
            @cache_manager.cached("db", "get_client", ttl=3600, key_params=["client_id"])
            def get_client(client_id: str):
                # Database query here
                return client_data
        """

        def decorator(func: Callable[..., T]) -> Callable[..., T]:
            @wraps(func)
            def wrapper(*args, **kwargs) -> T:
                correlation_id = kwargs.get("correlation_id") or get_correlation_id()

                # Extract parameters for cache key
                cache_params = {}
                if key_params:
                    # Get function signature to map args to param names
                    import inspect

                    sig = inspect.signature(func)
                    bound_args = sig.bind(*args, **kwargs)
                    bound_args.apply_defaults()

                    for param_name in key_params:
                        if param_name in bound_args.arguments:
                            cache_params[param_name] = bound_args.arguments[param_name]

                # Try to get from cache first
                try:
                    cached_result = self.get(
                        namespace, identifier, cache_params, correlation_id
                    )
                    if cached_result is not None:
                        return cached_result
                except CacheOperationError:
                    # Log but continue with function execution
                    self.logger.log_warning(
                        "Cache read failed, executing function",
                        {"correlation_id": correlation_id, "function": func.__name__},
                    )

                # Execute function and cache result
                result = func(*args, **kwargs)

                try:
                    self.set(
                        namespace, identifier, result, ttl, cache_params, correlation_id
                    )
                except CacheOperationError:
                    # Log but don't fail the function
                    self.logger.log_warning(
                        "Cache write failed",
                        {"correlation_id": correlation_id, "function": func.__name__},
                    )

                return result

            return wrapper

        return decorator

    def get_stats(self, correlation_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get cache statistics.

        Args:
            correlation_id: Optional correlation ID

        Returns:
            Dictionary with cache statistics
        """
        correlation_id = correlation_id or get_correlation_id()

        try:
            self.logger.log_debug("Starting cache statistics collection", {"correlation_id": correlation_id})
            
            # Use scan_iter to avoid blocking Redis - collect keys safely
            all_keys = []
            scan_iter = self.redis.scan_iter(match=f"{self.key_prefix}:*")

            # Handle both regular and async generators
            try:
                for key in scan_iter:
                    all_keys.append(key)
                    # Log progress for debugging
                    if len(all_keys) % 1000 == 0:
                        self.logger.log_debug(f"Scanned {len(all_keys)} keys so far", {"correlation_id": correlation_id})
            except TypeError:
                # If scan_iter is async generator, use keys() as fallback
                self.logger.log_warning("scan_iter failed, falling back to keys()", {"correlation_id": correlation_id})
                all_keys = self.redis.keys(f"{self.key_prefix}:*")

            self.logger.log_debug(f"Total keys found: {len(all_keys)}", {"correlation_id": correlation_id})

            stats = {
                "total_keys": len(all_keys),
                "namespaces": {},
                "total_memory_usage": 0,
            }

            # Analyze keys by namespace with detailed logging
            for key in all_keys:
                parts = key.split(":")
                if len(parts) >= 3:
                    namespace = parts[1]
                    if namespace not in stats["namespaces"]:
                        stats["namespaces"][namespace] = 0
                    stats["namespaces"][namespace] += 1
                else:
                    # Log malformed keys for debugging
                    self.logger.log_warning(f"Malformed cache key found: {key}", {"correlation_id": correlation_id})

            # Log namespace breakdown
            for namespace, count in stats["namespaces"].items():
                self.logger.log_debug(f"Namespace '{namespace}': {count} keys", {"correlation_id": correlation_id})

            self.logger.log_debug("Cache statistics collection completed", {
                "correlation_id": correlation_id,
                "total_keys": stats["total_keys"],
                "namespace_count": len(stats["namespaces"])
            })

            return stats

        except Exception as e:
            self.logger.log_exception(e, {"correlation_id": correlation_id})
            raise CacheOperationError(f"Failed to get cache stats: {e}")

    def health_check(self, correlation_id: Optional[str] = None) -> bool:
        """
        Perform cache health check.

        Args:
            correlation_id: Optional correlation ID

        Returns:
            True if cache is healthy
        """
        correlation_id = correlation_id or get_correlation_id()

        try:
            # Test basic operations
            self.set(
                "system", "health_check", "test", ttl=10, correlation_id=correlation_id
            )
            result = self.get("system", "health_check", correlation_id=correlation_id)
            self.delete("system", "health_check", correlation_id=correlation_id)

            return result == "test"

        except Exception as e:
            self.logger.log_exception(e, {"correlation_id": correlation_id})
            return False

    def scan_keys(
        self, namespace: str, pattern: str = "*", correlation_id: Optional[str] = None
    ):
        """
        Scan for cache keys matching a pattern within a namespace.

        Args:
            namespace: Cache namespace (e.g., 'ocr_workers', 'ocr_jobs')
            pattern: Pattern to match (default: '*' for all)
            correlation_id: Optional correlation ID

        Yields:
            Matching cache keys

        Example:
            for key in cache.scan_keys('ocr_workers', '*'):
                worker_id = key.split(':')[-1]
        """
        correlation_id = correlation_id or get_correlation_id()

        # Construct full pattern with key_prefix
        full_pattern = f"{self.key_prefix}:{namespace}:{pattern}"

        context = {
            "correlation_id": correlation_id,
            "namespace": namespace,
            "pattern": pattern,
            "full_pattern": full_pattern,
        }

        try:
            self.logger.log_debug("Scanning cache keys", context)

            for key in self.redis.scan_iter(match=full_pattern):
                yield key

        except redis.RedisError as e:
            self.logger.log_exception(e, context)
            raise CacheOperationError(f"Cache scan operation failed: {e}")
        except Exception as e:
            self.logger.log_exception(e, context)
            raise

    def close(self, correlation_id: Optional[str] = None):
        """
        Close cache manager and underlying Redis connection.

        Args:
            correlation_id: Optional correlation ID
        """
        correlation_id = correlation_id or get_correlation_id()

        try:
            self.logger.log_debug(
                "Closing cache manager", {"correlation_id": correlation_id}
            )
            self.redis.close()
        except Exception as e:
            self.logger.log_exception(e, {"correlation_id": correlation_id})
