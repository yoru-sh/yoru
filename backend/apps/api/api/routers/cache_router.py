from typing import Dict, Any, List, Optional, Union
import time
import asyncio
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Request, Depends, Query
from fastapi.security import HTTPBearer
from pydantic import BaseModel, Field
import redis.asyncio as redis
from collections import defaultdict
import os
import json

from libs.log_manager.controller import LoggingController
from libs.log_manager.core.utils import get_correlation_id
from libs.redis import RedisManager, CacheManager
from libs.redis.redis import RedisConnectionError, RedisPermissionError


# Request/Response Models
class CacheStatsResponse(BaseModel):
    """Cache statistics response model"""

    total_keys: int
    memory_usage: int
    hit_rate: float
    miss_rate: float
    uptime_seconds: int
    connections: int
    operations_per_second: float
    namespaces: Dict[str, int]
    last_updated: datetime


class CacheHealthResponse(BaseModel):
    """Cache health check response model"""

    status: str
    response_time_ms: float
    redis_version: str
    connected_clients: int
    used_memory_human: str
    uptime_in_seconds: int
    last_ping: datetime


class RedisInfoResponse(BaseModel):
    """Redis server info response model"""

    version: str
    mode: str
    role: str
    connected_clients: int
    used_memory: int
    used_memory_human: str
    used_memory_peak: int
    used_memory_peak_human: str
    total_system_memory: int
    maxmemory: int
    uptime_in_seconds: int
    total_commands_processed: int
    instantaneous_ops_per_sec: int
    keyspace_hits: int
    keyspace_misses: int
    expired_keys: int
    evicted_keys: int


class CacheMetricsResponse(BaseModel):
    """Performance metrics response model"""

    hit_ratio: float
    miss_ratio: float
    avg_response_time_ms: float
    total_operations: int
    operations_per_second: float
    memory_usage_mb: float
    peak_memory_mb: float
    connected_clients: int
    expired_keys: int
    evicted_keys: int
    network_input_mb: float
    network_output_mb: float


class NamespaceInfo(BaseModel):
    """Namespace information model"""

    namespace: str
    key_count: int
    estimated_memory_bytes: Optional[int] = None
    memory_estimation_note: str = "Rough estimate: key_count * 1KB average"
    sample_keys: List[str]


class NamespaceListResponse(BaseModel):
    """Namespace list response model"""

    namespaces: List[NamespaceInfo]
    total_namespaces: int
    total_keys: int
    scan_complete: bool = True


class KeyInfo(BaseModel):
    """Key information model"""

    key: str
    type: str
    ttl: int
    memory_usage: Optional[int] = (
        None  # Made optional since precise calculation may fail
    )
    memory_usage_note: Optional[str] = None
    value_preview: Optional[str] = Field(max_length=200)


class KeyListResponse(BaseModel):
    """Key list response model"""

    keys: List[KeyInfo]
    total_keys: int
    page: int
    page_size: int
    has_more: bool
    namespace: Optional[str] = None
    scan_complete: bool = True  # Indicates if scan covered all keys


class KeyValueResponse(BaseModel):
    """Key value response model"""

    key: str
    value: Any
    type: str
    ttl: int
    memory_usage: Optional[int] = None
    memory_usage_note: Optional[str] = None


class SetKeyRequest(BaseModel):
    """Set key value request model"""

    value: Any
    ttl: Optional[int] = Field(default=3600, ge=1, le=2592000)  # 1 sec to 30 days
    overwrite: bool = Field(default=True)


class InvalidateRequest(BaseModel):
    """Cache invalidation request model"""

    pattern: Optional[str] = Field(default="*", max_length=1000)
    namespace: Optional[str] = Field(max_length=100)
    dry_run: bool = Field(default=False)
    batch_size: Optional[int] = Field(
        default=100, ge=1, le=1000, description="Batch size for deletion"
    )


class SetTTLRequest(BaseModel):
    """Set TTL request model"""

    ttl: int = Field(ge=1, le=2592000)  # 1 sec to 30 days


class MemoryStatsResponse(BaseModel):
    """Memory usage statistics response model"""

    used_memory: int
    used_memory_human: str
    used_memory_peak: int
    used_memory_peak_human: str
    used_memory_percentage: float
    total_system_memory: int
    maxmemory: int
    maxmemory_human: str
    mem_fragmentation_ratio: float
    mem_allocator: str


class PerformanceStatsResponse(BaseModel):
    """Performance statistics response model"""

    hit_rate: float
    miss_rate: float
    total_commands: int
    commands_per_second: float
    avg_response_time_ms: float
    slow_log_count: int
    connected_clients: int
    blocked_clients: int
    network_input_bytes: int
    network_output_bytes: int


class ActivityLogEntry(BaseModel):
    """Activity log entry model"""

    timestamp: datetime
    operation: str
    key: Optional[str]
    namespace: Optional[str]
    client_info: str
    execution_time_ms: float
    status: str


class ActivityLogResponse(BaseModel):
    """Activity log response model"""

    activities: List[ActivityLogEntry]
    total_entries: int
    page: int
    page_size: int
    has_more: bool


class RateLimiter:
    """Simple in-memory rate limiter for destructive operations"""

    def __init__(self):
        self.requests = defaultdict(list)
        self.limits = {
            "flush": {"count": 1, "window": 300},  # 1 per 5 minutes
            "invalidate": {"count": 10, "window": 60},  # 10 per minute
            "cleanup": {"count": 5, "window": 60},  # 5 per minute
            "delete_namespace": {"count": 3, "window": 60},  # 3 per minute
        }

    def is_allowed(self, client_id: str, operation: str) -> bool:
        """Check if operation is allowed for client"""
        if operation not in self.limits:
            return True

        now = time.time()
        limit_config = self.limits[operation]
        window = limit_config["window"]
        max_requests = limit_config["count"]

        # Clean old requests
        self.requests[f"{client_id}:{operation}"] = [
            req_time
            for req_time in self.requests[f"{client_id}:{operation}"]
            if now - req_time < window
        ]

        # Check if under limit
        current_requests = len(self.requests[f"{client_id}:{operation}"])
        if current_requests >= max_requests:
            return False

        # Add current request
        self.requests[f"{client_id}:{operation}"].append(now)
        return True


class CacheRouter:
    """Redis cache management router for FastAPI"""

    def __init__(self):
        """Initialize CacheRouter with required components"""
        self.router = APIRouter(prefix="/api/cache", tags=["cache"])
        self.logger = LoggingController(app_name="cache_router")
        self.rate_limiter = RateLimiter()

        # Initialize Redis managers as None - lazy initialization
        self.redis_manager = None
        self.cache_manager = None

        # Configuration
        self.max_keys_scan = 10000  # Maximum keys to scan in one operation
        self.batch_delete_size = 100  # Batch size for deletions

        # Setup routes
        self._setup_routes()
        self.logger.log_info("Cache router initialized")

    def get_router(self) -> APIRouter:
        """Get the FastAPI router"""
        return self.router

    def initialize_services(self):
        """Initialize Redis managers if not already done"""
        if self.redis_manager is None:
            self.redis_manager = RedisManager()
            self.cache_manager = CacheManager()
            self.logger.log_info("Redis managers initialized")

    def _get_client_id(self, request: Request) -> str:
        """Extract client ID for rate limiting"""
        return request.client.host if request.client else "unknown"

    def _check_rate_limit(self, client_id: str, operation: str) -> None:
        """Check rate limit and raise exception if exceeded"""
        if not self.rate_limiter.is_allowed(client_id, operation):
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded for operation '{operation}'",
            )

    async def _get_memory_usage(self, key: str) -> tuple[Optional[int], str]:
        """
        Get memory usage for a key using Redis MEMORY USAGE command.
        Returns (memory_bytes, note) tuple.
        """
        try:
            # Try Redis MEMORY USAGE command (available in Redis 4.0+)
            memory_bytes = await self.redis_manager.client.memory_usage(key)
            return memory_bytes, "Precise measurement via Redis MEMORY USAGE"
        except Exception:
            # Fallback to rough estimate if MEMORY USAGE is not available
            return None, "Memory usage not available (Redis < 4.0 or command failed)"

    async def _scan_keys_safely(
        self, pattern: str, max_keys: int = None, correlation_id: str = None
    ) -> tuple[List[str], bool]:
        """
        Safely scan keys using Redis SCAN to avoid blocking.
        Returns (keys_list, scan_complete) tuple.
        """
        max_keys = max_keys or self.max_keys_scan
        keys = []
        cursor = 0
        scan_complete = True

        try:
            self.logger.log_info(f"Starting SCAN operation with pattern: {pattern}", {
                "correlation_id": correlation_id,
                "max_keys": max_keys,
                "pattern": pattern
            })

            while len(keys) < max_keys:
                # Use SCAN with pattern and count
                cursor, batch_keys = await self.redis_manager.client.scan(
                    cursor=cursor, match=pattern, count=min(1000, max_keys - len(keys))
                )
                
                self.logger.log_info(f"SCAN batch: cursor={cursor}, found={len(batch_keys)} keys", {
                    "correlation_id": correlation_id,
                    "total_keys_so_far": len(keys)
                })
                
                keys.extend(batch_keys)

                # If cursor is 0, we've completed the scan
                if cursor == 0:
                    break

            # If we hit the limit but cursor isn't 0, scan isn't complete
            if len(keys) >= max_keys and cursor != 0:
                scan_complete = False
                keys = keys[:max_keys]  # Trim to exact limit

            self.logger.log_info(f"SCAN operation completed: {len(keys)} keys found", {
                "correlation_id": correlation_id,
                "scan_complete": scan_complete,
                "pattern": pattern
            })

        except Exception as e:
            self.logger.log_warning(
                f"SCAN operation failed, falling back to KEYS: {str(e)}",
                {"correlation_id": correlation_id, "pattern": pattern},
            )
            # Fallback to KEYS but with warning
            try:
                self.logger.log_info("Attempting KEYS fallback", {"correlation_id": correlation_id})
                all_keys = await self.redis_manager.get_keys(pattern, correlation_id)
                if len(all_keys) > max_keys:
                    keys = all_keys[:max_keys]
                    scan_complete = False
                else:
                    keys = all_keys
                    scan_complete = True
                    
                self.logger.log_info(f"KEYS fallback completed: {len(keys)} keys found", {
                    "correlation_id": correlation_id,
                    "scan_complete": scan_complete
                })
            except Exception as fallback_error:
                self.logger.log_error(
                    f"Both SCAN and KEYS failed: {str(fallback_error)}",
                    {"correlation_id": correlation_id, "pattern": pattern},
                )
                raise

        return keys, scan_complete

    async def _batch_delete_keys(
        self, keys: List[str], batch_size: int = None, correlation_id: str = None
    ) -> int:
        """
        Delete keys in batches to avoid blocking Redis.
        Returns total number of keys deleted.
        """
        batch_size = batch_size or self.batch_delete_size
        total_deleted = 0

        try:
            # Process keys in batches
            for i in range(0, len(keys), batch_size):
                batch = keys[i : i + batch_size]
                if batch:
                    try:
                        # Use UNLINK for non-blocking deletion when possible
                        if hasattr(self.redis_manager.client, "unlink"):
                            deleted = await self.redis_manager.client.unlink(*batch)
                        else:
                            # Fallback to regular DELETE
                            deleted = await self.redis_manager.client.delete(*batch)
                        total_deleted += deleted

                        # Small delay between batches to avoid overwhelming Redis
                        if i + batch_size < len(keys):
                            await asyncio.sleep(0.001)  # 1ms delay

                    except Exception as batch_error:
                        self.logger.log_warning(
                            f"Failed to delete batch {i//batch_size + 1}: {str(batch_error)}",
                            {
                                "correlation_id": correlation_id,
                                "batch_size": len(batch),
                            },
                        )
                        continue

        except Exception as e:
            self.logger.log_error(
                f"Batch deletion failed: {str(e)}",
                {"correlation_id": correlation_id, "total_keys": len(keys)},
            )
            raise

        return total_deleted

    def _setup_routes(self):
        """Set up routes for cache management endpoints"""

        @self.router.get(
            "/stats",
            response_model=CacheStatsResponse,
            summary="Get global cache statistics",
        )
        async def get_stats(request: Request):
            """Get global cache statistics"""
            correlation_id = (
                getattr(request.state, "request_id", None) or get_correlation_id()
            )
            context = {"correlation_id": correlation_id}

            self.logger.log_info("Getting cache statistics", context)

            try:
                self.initialize_services()

                # Test connection first
                await self.redis_manager.ping(correlation_id)

                # Get Redis info
                info = await self.redis_manager.client.info()

                # Calculate hit rate
                hits = info.get("keyspace_hits", 0)
                misses = info.get("keyspace_misses", 0)
                total_ops = hits + misses
                hit_rate = (hits / total_ops * 100) if total_ops > 0 else 0
                miss_rate = 100 - hit_rate

                # Get namespace statistics using safe scanning
                cache_keys, _ = await self._scan_keys_safely(
                    "cache:*", correlation_id=correlation_id
                )

                # Group by namespace
                namespaces = defaultdict(int)
                for key in cache_keys:
                    parts = key.split(":")
                    if len(parts) >= 3:
                        namespace = parts[1]
                        namespaces[namespace] += 1

                return CacheStatsResponse(
                    total_keys=len(cache_keys),
                    memory_usage=info.get("used_memory", 0),
                    hit_rate=hit_rate,
                    miss_rate=miss_rate,
                    uptime_seconds=info.get("uptime_in_seconds", 0),
                    connections=info.get("connected_clients", 0),
                    operations_per_second=info.get("instantaneous_ops_per_sec", 0),
                    namespaces=dict(namespaces),
                    last_updated=datetime.now(),
                )

            except RedisConnectionError as e:
                self.logger.log_exception(e, context)
                raise HTTPException(
                    status_code=503, detail=f"Redis connection failed: {str(e)}"
                )
            except Exception as e:
                self.logger.log_exception(e, context)
                raise HTTPException(
                    status_code=500, detail=f"Failed to get cache statistics: {str(e)}"
                )

        @self.router.get(
            "/health", response_model=CacheHealthResponse, summary="Redis health check"
        )
        async def health_check(request: Request):
            """Perform Redis health check"""
            correlation_id = (
                getattr(request.state, "request_id", None) or get_correlation_id()
            )
            context = {"correlation_id": correlation_id}

            self.logger.log_info("Performing cache health check", context)

            try:
                self.initialize_services()

                start_time = time.time()
                await self.redis_manager.ping(correlation_id)
                response_time = (time.time() - start_time) * 1000

                info = await self.redis_manager.client.info()

                return CacheHealthResponse(
                    status="healthy",
                    response_time_ms=response_time,
                    redis_version=info.get("redis_version", "unknown"),
                    connected_clients=info.get("connected_clients", 0),
                    used_memory_human=info.get("used_memory_human", "0B"),
                    uptime_in_seconds=info.get("uptime_in_seconds", 0),
                    last_ping=datetime.now(),
                )

            except Exception as e:
                self.logger.log_exception(e, context)
                return CacheHealthResponse(
                    status="unhealthy",
                    response_time_ms=0,
                    redis_version="unknown",
                    connected_clients=0,
                    used_memory_human="0B",
                    uptime_in_seconds=0,
                    last_ping=datetime.now(),
                )

        @self.router.get(
            "/info",
            response_model=RedisInfoResponse,
            summary="Get Redis server information",
        )
        async def get_info(request: Request):
            """Get Redis server information"""
            correlation_id = (
                getattr(request.state, "request_id", None) or get_correlation_id()
            )
            context = {"correlation_id": correlation_id}

            self.logger.log_info("Getting Redis server info", context)

            try:
                self.initialize_services()
                info = await self.redis_manager.client.info()

                return RedisInfoResponse(
                    version=info.get("redis_version", "unknown"),
                    mode=info.get("redis_mode", "standalone"),
                    role=info.get("role", "master"),
                    connected_clients=info.get("connected_clients", 0),
                    used_memory=info.get("used_memory", 0),
                    used_memory_human=info.get("used_memory_human", "0B"),
                    used_memory_peak=info.get("used_memory_peak", 0),
                    used_memory_peak_human=info.get("used_memory_peak_human", "0B"),
                    total_system_memory=info.get("total_system_memory", 0),
                    maxmemory=info.get("maxmemory", 0),
                    uptime_in_seconds=info.get("uptime_in_seconds", 0),
                    total_commands_processed=info.get("total_commands_processed", 0),
                    instantaneous_ops_per_sec=info.get("instantaneous_ops_per_sec", 0),
                    keyspace_hits=info.get("keyspace_hits", 0),
                    keyspace_misses=info.get("keyspace_misses", 0),
                    expired_keys=info.get("expired_keys", 0),
                    evicted_keys=info.get("evicted_keys", 0),
                )

            except Exception as e:
                self.logger.log_exception(e, context)
                raise HTTPException(
                    status_code=500, detail=f"Failed to get Redis info: {str(e)}"
                )

        @self.router.get(
            "/namespaces",
            response_model=NamespaceListResponse,
            summary="List all namespaces",
        )
        async def list_namespaces(
            request: Request,
            max_keys: int = Query(
                10000, ge=100, le=50000, description="Maximum keys to scan"
            ),
        ):
            """List all namespaces with key counts"""
            correlation_id = (
                getattr(request.state, "request_id", None) or get_correlation_id()
            )
            context = {"correlation_id": correlation_id}

            self.logger.log_info("Listing cache namespaces", context)

            try:
                self.initialize_services()

                # Use safe scanning to get cache keys
                all_keys, scan_complete = await self._scan_keys_safely(
                    "cache:*", max_keys, correlation_id
                )

                self.logger.log_info(f"Found {len(all_keys)} total keys", {
                    "correlation_id": correlation_id,
                    "scan_complete": scan_complete
                })

                # Group by namespace
                namespaces = defaultdict(list)
                malformed_keys = []
                
                for key in all_keys:
                    parts = key.split(":")
                    if len(parts) >= 3:
                        namespace = parts[1]
                        namespaces[namespace].append(key)
                    else:
                        malformed_keys.append(key)

                if malformed_keys:
                    self.logger.log_warning(f"Found {len(malformed_keys)} malformed keys", {
                        "correlation_id": correlation_id,
                        "malformed_keys": malformed_keys[:10]  # Log first 10
                    })

                self.logger.log_info(f"Found {len(namespaces)} namespaces", {
                    "correlation_id": correlation_id,
                    "namespaces": list(namespaces.keys())
                })

                namespace_infos = []
                total_keys = 0

                for namespace, keys in namespaces.items():
                    # Get sample keys (remove cache:namespace: prefix for display)
                    sample_keys = [key.split(":", 2)[2] for key in keys[:5]]

                    # Calculate rough memory estimate (clearly labeled)
                    estimated_memory = len(keys) * 1024  # 1KB average per key

                    self.logger.log_info(f"Processing namespace '{namespace}' with {len(keys)} keys", {
                        "correlation_id": correlation_id,
                        "sample_keys": sample_keys
                    })

                    namespace_infos.append(
                        NamespaceInfo(
                            namespace=namespace,
                            key_count=len(keys),
                            estimated_memory_bytes=estimated_memory,
                            memory_estimation_note=f"Rough estimate: {len(keys)} keys × 1KB average = {estimated_memory:,} bytes",
                            sample_keys=sample_keys,
                        )
                    )
                    total_keys += len(keys)

                self.logger.log_info("Namespace listing completed", {
                    "correlation_id": correlation_id,
                    "total_namespaces": len(namespaces),
                    "total_keys": total_keys,
                    "scan_complete": scan_complete
                })

                return NamespaceListResponse(
                    namespaces=namespace_infos,
                    total_namespaces=len(namespaces),
                    total_keys=total_keys,
                    scan_complete=scan_complete,
                )

            except Exception as e:
                self.logger.log_exception(e, context)
                raise HTTPException(
                    status_code=500, detail=f"Failed to list namespaces: {str(e)}"
                )

        @self.router.get(
            "/keys", response_model=KeyListResponse, summary="List all keys (paginated)"
        )
        async def list_all_keys(
            request: Request,
            page: int = Query(1, ge=1, description="Page number"),
            page_size: int = Query(50, ge=1, le=1000, description="Items per page"),
            max_scan: int = Query(
                10000, ge=100, le=50000, description="Maximum keys to scan"
            ),
        ):
            """List all keys with pagination"""
            correlation_id = (
                getattr(request.state, "request_id", None) or get_correlation_id()
            )
            context = {
                "correlation_id": correlation_id,
                "page": page,
                "page_size": page_size,
            }

            self.logger.log_info("Listing all cache keys", context)

            try:
                self.initialize_services()

                # Use safe scanning
                all_keys, scan_complete = await self._scan_keys_safely(
                    "cache:*", max_scan, correlation_id
                )
                total_keys = len(all_keys)

                # Pagination
                start_idx = (page - 1) * page_size
                end_idx = start_idx + page_size
                page_keys = all_keys[start_idx:end_idx]

                key_infos = []
                for key in page_keys:
                    try:
                        # Get key type and TTL
                        key_type = await self.redis_manager.client.type(key)
                        ttl = await self.redis_manager.client.ttl(key)

                        # Get precise memory usage
                        memory_usage, memory_note = await self._get_memory_usage(key)

                        # Get value preview
                        value = await self.redis_manager.get_value(
                            key, decode_json=True, correlation_id=correlation_id
                        )
                        preview = str(value)[:200] if value is not None else None

                        key_infos.append(
                            KeyInfo(
                                key=key,
                                type=key_type,
                                ttl=ttl,
                                memory_usage=memory_usage,
                                memory_usage_note=memory_note,
                                value_preview=preview,
                            )
                        )
                    except Exception as key_error:
                        self.logger.log_warning(
                            f"Failed to get info for key {key}: {str(key_error)}",
                            context,
                        )
                        continue

                return KeyListResponse(
                    keys=key_infos,
                    total_keys=total_keys,
                    page=page,
                    page_size=page_size,
                    has_more=end_idx < total_keys,
                    scan_complete=scan_complete,
                )

            except Exception as e:
                self.logger.log_exception(e, context)
                raise HTTPException(
                    status_code=500, detail=f"Failed to list keys: {str(e)}"
                )

        @self.router.get(
            "/keys/{namespace}",
            response_model=KeyListResponse,
            summary="List keys in namespace",
        )
        async def list_namespace_keys(
            namespace: str,
            request: Request,
            page: int = Query(1, ge=1),
            page_size: int = Query(50, ge=1, le=1000),
            max_scan: int = Query(10000, ge=100, le=50000),
        ):
            """List keys in a specific namespace"""
            correlation_id = (
                getattr(request.state, "request_id", None) or get_correlation_id()
            )
            context = {
                "correlation_id": correlation_id,
                "namespace": namespace,
                "page": page,
            }

            self.logger.log_info(f"Listing keys in namespace '{namespace}'", context)

            try:
                self.initialize_services()

                # Use safe scanning for namespace
                pattern = f"cache:{namespace}:*"
                all_keys, scan_complete = await self._scan_keys_safely(
                    pattern, max_scan, correlation_id
                )
                total_keys = len(all_keys)

                # Pagination
                start_idx = (page - 1) * page_size
                end_idx = start_idx + page_size
                page_keys = all_keys[start_idx:end_idx]

                key_infos = []
                for key in page_keys:
                    try:
                        key_type = await self.redis_manager.client.type(key)
                        ttl = await self.redis_manager.client.ttl(key)

                        memory_usage, memory_note = await self._get_memory_usage(key)

                        value = await self.redis_manager.get_value(
                            key, decode_json=True, correlation_id=correlation_id
                        )
                        preview = str(value)[:200] if value is not None else None

                        key_infos.append(
                            KeyInfo(
                                key=key,
                                type=key_type,
                                ttl=ttl,
                                memory_usage=memory_usage,
                                memory_usage_note=memory_note,
                                value_preview=preview,
                            )
                        )
                    except Exception:
                        continue

                return KeyListResponse(
                    keys=key_infos,
                    total_keys=total_keys,
                    page=page,
                    page_size=page_size,
                    has_more=end_idx < total_keys,
                    namespace=namespace,
                    scan_complete=scan_complete,
                )

            except Exception as e:
                self.logger.log_exception(e, context)
                raise HTTPException(
                    status_code=500, detail=f"Failed to list namespace keys: {str(e)}"
                )

        @self.router.get(
            "/keys/{namespace}/{key}",
            response_model=KeyValueResponse,
            summary="Get key value",
        )
        async def get_key_value(namespace: str, key: str, request: Request):
            """Get the value of a specific key"""
            correlation_id = (
                getattr(request.state, "request_id", None) or get_correlation_id()
            )
            context = {
                "correlation_id": correlation_id,
                "namespace": namespace,
                "key": key,
            }

            self.logger.log_info(f"Getting key value: {namespace}:{key}", context)

            try:
                self.initialize_services()

                # Use cache manager to get value
                value = self.cache_manager.get(
                    namespace, key, correlation_id=correlation_id
                )

                if value is None:
                    raise HTTPException(status_code=404, detail="Key not found")

                # Get additional info
                cache_key = self.cache_manager.generate_cache_key(namespace, key)
                key_type = await self.redis_manager.client.type(cache_key)
                ttl = await self.redis_manager.client.ttl(cache_key)

                # Get precise memory usage
                memory_usage, memory_note = await self._get_memory_usage(cache_key)

                return KeyValueResponse(
                    key=f"{namespace}:{key}",
                    value=value,
                    type=key_type,
                    ttl=ttl,
                    memory_usage=memory_usage,
                    memory_usage_note=memory_note,
                )

            except HTTPException:
                raise
            except Exception as e:
                self.logger.log_exception(e, context)
                raise HTTPException(
                    status_code=500, detail=f"Failed to get key value: {str(e)}"
                )

        @self.router.post("/keys/{namespace}/{key}", summary="Set key value")
        async def set_key_value(
            namespace: str, key: str, request: Request, body: SetKeyRequest
        ):
            """Set the value of a specific key"""
            correlation_id = (
                getattr(request.state, "request_id", None) or get_correlation_id()
            )
            context = {
                "correlation_id": correlation_id,
                "namespace": namespace,
                "key": key,
            }

            self.logger.log_info(f"Setting key value: {namespace}:{key}", context)

            try:
                self.initialize_services()

                # Check if key exists and overwrite flag
                if not body.overwrite:
                    exists = self.cache_manager.exists(
                        namespace, key, correlation_id=correlation_id
                    )
                    if exists:
                        raise HTTPException(
                            status_code=409,
                            detail="Key already exists and overwrite is disabled",
                        )

                # Set the value using cache manager
                success = self.cache_manager.set(
                    namespace,
                    key,
                    body.value,
                    ttl=body.ttl,
                    correlation_id=correlation_id,
                )

                if not success:
                    raise HTTPException(
                        status_code=500, detail="Failed to set key value"
                    )

                return {"message": "Key set successfully", "key": f"{namespace}:{key}"}

            except HTTPException:
                raise
            except Exception as e:
                self.logger.log_exception(e, context)
                raise HTTPException(
                    status_code=500, detail=f"Failed to set key value: {str(e)}"
                )

        @self.router.delete("/keys/{namespace}/{key}", summary="Delete specific key")
        async def delete_key(namespace: str, key: str, request: Request):
            """Delete a specific key"""
            correlation_id = (
                getattr(request.state, "request_id", None) or get_correlation_id()
            )
            context = {
                "correlation_id": correlation_id,
                "namespace": namespace,
                "key": key,
            }

            self.logger.log_info(f"Deleting key: {namespace}:{key}", context)

            try:
                self.initialize_services()

                # Delete using cache manager
                success = self.cache_manager.delete(
                    namespace, key, correlation_id=correlation_id
                )

                if success:
                    return {
                        "message": "Key deleted successfully",
                        "key": f"{namespace}:{key}",
                    }
                else:
                    raise HTTPException(status_code=404, detail="Key not found")

            except HTTPException:
                raise
            except Exception as e:
                self.logger.log_exception(e, context)
                raise HTTPException(
                    status_code=500, detail=f"Failed to delete key: {str(e)}"
                )

        @self.router.delete(
            "/namespaces/{namespace}", summary="Clear namespace (rate limited)"
        )
        async def delete_namespace(namespace: str, request: Request):
            """Delete all keys in a namespace (rate limited)"""
            correlation_id = (
                getattr(request.state, "request_id", None) or get_correlation_id()
            )
            client_id = self._get_client_id(request)
            context = {
                "correlation_id": correlation_id,
                "namespace": namespace,
                "client_id": client_id,
            }

            # Check rate limit
            self._check_rate_limit(client_id, "delete_namespace")

            self.logger.log_info(f"Deleting namespace: {namespace}", context)

            try:
                self.initialize_services()

                # Get all keys in namespace using safe scanning
                pattern = f"cache:{namespace}:*"
                keys_to_delete, _ = await self._scan_keys_safely(
                    pattern, correlation_id=correlation_id
                )

                if not keys_to_delete:
                    return {
                        "message": f"Namespace '{namespace}' is already empty",
                        "deleted_keys": 0,
                    }

                # Use batch deletion
                deleted_count = await self._batch_delete_keys(
                    keys_to_delete, correlation_id=correlation_id
                )

                return {
                    "message": f"Namespace '{namespace}' cleared successfully",
                    "deleted_keys": deleted_count,
                }

            except Exception as e:
                self.logger.log_exception(e, context)
                raise HTTPException(
                    status_code=500, detail=f"Failed to clear namespace: {str(e)}"
                )

        @self.router.post(
            "/invalidate", summary="Invalidate cache by pattern (rate limited)"
        )
        async def invalidate_cache(request: Request, body: InvalidateRequest):
            """Invalidate cache entries by pattern"""
            correlation_id = (
                getattr(request.state, "request_id", None) or get_correlation_id()
            )
            client_id = self._get_client_id(request)
            context = {
                "correlation_id": correlation_id,
                "pattern": body.pattern,
                "namespace": body.namespace,
            }

            # Check rate limit
            self._check_rate_limit(client_id, "invalidate")

            self.logger.log_info("Invalidating cache by pattern", context)

            try:
                self.initialize_services()

                # Build the search pattern
                if body.namespace:
                    search_pattern = f"cache:{body.namespace}:{body.pattern or '*'}"
                else:
                    search_pattern = f"cache:*:{body.pattern or '*'}"

                # Use safe scanning to find keys
                keys_to_delete, scan_complete = await self._scan_keys_safely(
                    search_pattern, correlation_id=correlation_id
                )

                if body.dry_run:
                    return {
                        "message": "Dry run completed",
                        "would_delete": len(keys_to_delete),
                        "sample_keys": keys_to_delete[:10],
                        "scan_complete": scan_complete,
                        "pattern_used": search_pattern,
                    }

                if not keys_to_delete:
                    return {
                        "message": "No keys found matching pattern",
                        "deleted_keys": 0,
                        "pattern_used": search_pattern,
                    }

                # Use batch deletion
                deleted_count = await self._batch_delete_keys(
                    keys_to_delete, body.batch_size, correlation_id
                )

                return {
                    "message": "Cache invalidation completed",
                    "deleted_keys": deleted_count,
                    "scan_complete": scan_complete,
                    "pattern_used": search_pattern,
                }

            except Exception as e:
                self.logger.log_exception(e, context)
                raise HTTPException(
                    status_code=500, detail=f"Failed to invalidate cache: {str(e)}"
                )

        @self.router.post(
            "/flush", summary="Flush all cache (admin only, heavily rate limited)"
        )
        async def flush_cache(request: Request):
            """Flush all cache data (admin only, heavily rate limited)"""
            correlation_id = (
                getattr(request.state, "request_id", None) or get_correlation_id()
            )
            client_id = self._get_client_id(request)
            context = {"correlation_id": correlation_id, "client_id": client_id}

            # Check rate limit - very restrictive
            self._check_rate_limit(client_id, "flush")

            self.logger.log_warning("FLUSH ALL CACHE requested", context)

            try:
                self.initialize_services()

                # Use safe scanning to get all cache keys
                cache_keys, scan_complete = await self._scan_keys_safely(
                    "cache:*", correlation_id=correlation_id
                )

                if not cache_keys:
                    return {
                        "message": "Cache is already empty",
                        "deleted_keys": 0,
                        "warning": "No cache data found",
                    }

                # Use batch deletion to avoid blocking Redis
                deleted_count = await self._batch_delete_keys(
                    cache_keys, correlation_id=correlation_id
                )

                self.logger.log_warning(
                    f"Cache flush completed: {deleted_count} keys deleted", context
                )

                return {
                    "message": "Cache flush completed",
                    "deleted_keys": deleted_count,
                    "scan_complete": scan_complete,
                    "warning": "All cache data has been cleared",
                }

            except Exception as e:
                self.logger.log_exception(e, context)
                raise HTTPException(
                    status_code=500, detail=f"Failed to flush cache: {str(e)}"
                )

        @self.router.get("/ttl/{namespace}/{key}", summary="Get key TTL")
        async def get_key_ttl(namespace: str, key: str, request: Request):
            """Get the TTL of a specific key"""
            correlation_id = (
                getattr(request.state, "request_id", None) or get_correlation_id()
            )
            context = {
                "correlation_id": correlation_id,
                "namespace": namespace,
                "key": key,
            }

            try:
                self.initialize_services()

                cache_key = self.cache_manager.generate_cache_key(namespace, key)
                ttl = await self.redis_manager.client.ttl(cache_key)

                return {
                    "key": f"{namespace}:{key}",
                    "ttl": ttl,
                    "expires_in_seconds": ttl if ttl > 0 else None,
                    "expires_at": (
                        datetime.now() + timedelta(seconds=ttl) if ttl > 0 else None
                    ),
                }

            except Exception as e:
                self.logger.log_exception(e, context)
                raise HTTPException(
                    status_code=500, detail=f"Failed to get TTL: {str(e)}"
                )

        @self.router.put("/ttl/{namespace}/{key}", summary="Set key TTL")
        async def set_key_ttl(
            namespace: str, key: str, request: Request, body: SetTTLRequest
        ):
            """Set the TTL of a specific key"""
            correlation_id = (
                getattr(request.state, "request_id", None) or get_correlation_id()
            )
            context = {
                "correlation_id": correlation_id,
                "namespace": namespace,
                "key": key,
                "ttl": body.ttl,
            }

            self.logger.log_info(f"Setting TTL for key: {namespace}:{key}", context)

            try:
                self.initialize_services()

                cache_key = self.cache_manager.generate_cache_key(namespace, key)
                success = await self.redis_manager.set_expiration(
                    cache_key, body.ttl, correlation_id
                )

                if not success:
                    raise HTTPException(status_code=404, detail="Key not found")

                return {
                    "message": "TTL set successfully",
                    "key": f"{namespace}:{key}",
                    "ttl": body.ttl,
                    "expires_at": datetime.now() + timedelta(seconds=body.ttl),
                }

            except HTTPException:
                raise
            except Exception as e:
                self.logger.log_exception(e, context)
                raise HTTPException(
                    status_code=500, detail=f"Failed to set TTL: {str(e)}"
                )

        @self.router.get("/debug", summary="Debug cache namespaces and keys")
        async def debug_cache(request: Request):
            """Debug endpoint to test cache namespaces and keys"""
            correlation_id = (
                getattr(request.state, "request_id", None) or get_correlation_id()
            )
            context = {"correlation_id": correlation_id}

            self.logger.log_info("Starting cache debug", context)

            try:
                self.initialize_services()

                # Test 1: Create some test keys
                await self.redis_manager.set_value("cache:debug:test1", "value1", ex=300, correlation_id=correlation_id)
                await self.redis_manager.set_value("cache:debug:test2", "value2", ex=300, correlation_id=correlation_id)
                await self.redis_manager.set_value("cache:debug:test3", "value3", ex=300, correlation_id=correlation_id)

                # Test 2: Get all keys
                all_keys = await self.redis_manager.get_keys("cache:*", correlation_id=correlation_id)

                # Test 3: Analyze namespaces
                namespaces = {}
                malformed_keys = []

                for key in all_keys:
                    parts = key.split(":")
                    if len(parts) >= 3:
                        namespace = parts[1]
                        if namespace not in namespaces:
                            namespaces[namespace] = []
                        namespaces[namespace].append(key)
                    else:
                        malformed_keys.append(key)

                # Test 4: Get Redis info
                redis_info = await self.redis_manager.client.info()
                dbsize = await self.redis_manager.client.dbsize()

                # Test 5: Test CacheManager stats
                cache_stats = self.cache_manager.get_stats(correlation_id=correlation_id)

                debug_info = {
                    "total_keys_found": len(all_keys),
                    "namespaces_found": len(namespaces),
                    "namespace_details": {
                        namespace: {
                            "key_count": len(keys),
                            "sample_keys": keys[:5]
                        }
                        for namespace, keys in namespaces.items()
                    },
                    "malformed_keys_count": len(malformed_keys),
                    "malformed_keys_samples": malformed_keys[:10],
                    "redis_info": {
                        "version": redis_info.get("redis_version"),
                        "dbsize": dbsize,
                        "used_memory_human": redis_info.get("used_memory_human"),
                        "connected_clients": redis_info.get("connected_clients")
                    },
                    "cache_manager_stats": cache_stats,
                    "test_keys_created": [
                        "cache:debug:test1",
                        "cache:debug:test2", 
                        "cache:debug:test3"
                    ]
                }

                self.logger.log_info("Cache debug completed", {
                    **context,
                    "total_keys": len(all_keys),
                    "namespaces": list(namespaces.keys())
                })

                return debug_info

            except Exception as e:
                self.logger.log_exception(e, context)
                raise HTTPException(
                    status_code=500, detail=f"Cache debug failed: {str(e)}"
                )

        self.logger.log_debug("Cache router routes configured")


# Create router instance
cache_router_instance = CacheRouter()
router = cache_router_instance.get_router()
