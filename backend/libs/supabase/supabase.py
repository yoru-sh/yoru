import os
import json
from typing import Optional, Dict, Any, List, Union
import httpx
from supabase import create_client, Client
from postgrest.exceptions import APIError
from libs.log_manager.controller import LoggingController
from libs.log_manager.core.utils import get_correlation_id
from libs.redis.cache import CacheManager, CacheOperationError
from libs.resilience.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError


class SupabaseConnectionError(Exception):
    """Raised when a Supabase connection error occurs."""

    pass


class SupabasePermissionError(Exception):
    """Raised when a Supabase permission or access error occurs."""

    pass


class SupabaseManager:
    """
    SupabaseManager encapsulates Supabase database operations with unified async interface,
    project-standard logging, correlation_id propagation, and transparent Redis caching.

    Features:
    - Automatic caching for all read operations (get_record, query_records)
    - Smart cache invalidation on write operations (insert, update, delete, upsert)
    - Configurable TTL strategies by operation type
    - Cache namespace isolation by table
    - Fallback to direct DB access if cache fails

    Exceptions:
        - SupabaseConnectionError: Connection or authentication errors
        - SupabasePermissionError: Permission/access denied
        - ValueError: Invalid data or parameters
        - RuntimeError: Other Supabase or network errors
    """

    def __init__(
        self,
        url: Optional[str] = None,
        key: Optional[str] = None,
        access_token: Optional[str] = None,
        enable_cache: bool = True,
        cache_manager: Optional[CacheManager] = None,
        enable_circuit_breaker: bool = True,
        use_anon_key: bool = False,
    ):
        """
        Initializes the SupabaseManager with connection parameters and sets up the Supabase client.

        If parameters are not provided, values are loaded from environment variables.
        Logs the initialization status and raises an exception if client creation fails.

        Default key source is SUPABASE_SERVICE_ROLE_KEY so backend code runs at
        trusted-server scope (bypasses RLS). When acting on behalf of a user,
        pass their JWT via `access_token=` — PostgREST then evaluates RLS with
        `auth.uid()` set to that user. For rare pre-auth flows that genuinely
        need the public anon key (e.g. a signup endpoint that must fail the
        same way an anon browser would), pass `use_anon_key=True`.

        See https://github.com/helios-code/overnight-saas/issues/48 for the
        rationale — running everything on SUPABASE_ANON_KEY leaked the anon
        role's capabilities to all backend services and blocked every RLS
        tightening the Supabase advisor flagged.

        Args:
            url: Supabase project URL
            key: Supabase key override (takes precedence over env + use_anon_key)
            access_token: Optional user access token for authenticated requests
            enable_cache: Enable Redis caching (default: True)
            cache_manager: Optional CacheManager instance (creates new if None)
            enable_circuit_breaker: Enable circuit breaker protection (default: True)
            use_anon_key: Source the key from SUPABASE_ANON_KEY instead of
                SUPABASE_SERVICE_ROLE_KEY. Only use for deliberately
                low-privilege flows.
        """
        self.logger = LoggingController(app_name="SupabaseManager")

        # Initialize circuit breaker
        self.enable_circuit_breaker = enable_circuit_breaker and os.getenv("ENABLE_CIRCUIT_BREAKERS", "true").lower() == "true"
        if self.enable_circuit_breaker:
            failure_threshold = int(os.getenv("SUPABASE_CIRCUIT_FAILURE_THRESHOLD", "5"))
            timeout = int(os.getenv("SUPABASE_CIRCUIT_TIMEOUT", "60"))
            self.circuit_breaker = CircuitBreaker(
                name="supabase",
                failure_threshold=failure_threshold,
                timeout=timeout
            )
            self.logger.log_debug(
                "Circuit breaker enabled for Supabase",
                {"failure_threshold": failure_threshold, "timeout": timeout}
            )
        else:
            self.circuit_breaker = None
            self.logger.log_debug("Circuit breaker disabled for Supabase")

        self.url = url or os.environ.get("SUPABASE_URL")
        if key:
            self.key = key
        elif use_anon_key:
            self.key = os.environ.get("SUPABASE_ANON_KEY")
        else:
            # Default: service_role key — bypasses RLS, safe because backend
            # code is trusted and user-scoped operations pass `access_token=`.
            self.key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        self.access_token = access_token

        if not self.url or not self.key:
            key_var = "SUPABASE_ANON_KEY" if use_anon_key else "SUPABASE_SERVICE_ROLE_KEY"
            # Log exactly what the container sees so we can tell "secret not
            # injected at all" from "typo" from "set but empty".
            env_presence = {
                "url": bool(os.environ.get("SUPABASE_URL")),
                "anon": bool(os.environ.get("SUPABASE_ANON_KEY")),
                "service_role": bool(os.environ.get("SUPABASE_SERVICE_ROLE_KEY")),
            }
            error_msg = (
                f"SUPABASE_URL and {key_var} must be provided. "
                f"env presence: url={env_presence['url']}, "
                f"anon={env_presence['anon']}, service_role={env_presence['service_role']}"
            )
            self.logger.log_critical(error_msg)
            raise SupabaseConnectionError(error_msg)

        try:
            self.client: Client = create_client(self.url, self.key)

            # Wire the user's JWT so PostgREST RLS sees `auth.uid()` as that
            # user. `set_session(access, refresh)` requires BOTH args (gotrue
            # client-library quirk — an empty refresh silently raises and the
            # subsequent `.postgrest.auth()` call never runs, leaving us on
            # the anon key and RLS checks fail). The one line we actually need
            # for RLS is `postgrest.auth(token)`; the auth module's session
            # state only matters for client-side gotrue calls we don't use.
            # If access_token is provided, set it on the client for authenticated requests
            if self.access_token:
                self.client.auth.set_session(self.access_token, "")
                self.client.postgrest.auth(self.access_token)
                self.logger.log_debug("Supabase client initialized with user token", {"url": self.url})
            else:
                self.logger.log_debug("Supabase client initialized", {"url": self.url})
        except Exception as ex:
            self.logger.log_exception(ex, {"url": self.url})
            raise SupabaseConnectionError(f"Failed to initialize Supabase client: {ex}")

        # Initialize cache
        self.enable_cache = enable_cache
        self.cache = None

        if self.enable_cache:
            try:
                self.cache = cache_manager or CacheManager(
                    default_ttl=3600, key_prefix="supabase"  # 1 hour default
                )

                # Cache TTL strategies by operation type
                self.cache_ttl = {
                    "get_record": 1800,  # 30 minutes for single records
                    "query_records": 900,  # 15 minutes for queries
                    "execute_rpc": 600,  # 10 minutes for RPC calls
                }

                self.logger.log_debug(
                    "Redis cache enabled", {"cache_ttl": self.cache_ttl}
                )

            except Exception as e:
                self.logger.log_warning(
                    "Failed to initialize cache, disabling caching", {"error": str(e)}
                )
                self.enable_cache = False
                self.cache = None

    def _with_circuit_breaker(self, func: callable, *args, **kwargs):
        """
        Helper method to wrap operations with circuit breaker protection.

        Args:
            func: Function to execute
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Result of the function call

        Raises:
            SupabaseConnectionError: If circuit breaker is open
        """
        if self.enable_circuit_breaker and self.circuit_breaker:
            try:
                return self.circuit_breaker.call_sync(func, *args, **kwargs)
            except CircuitBreakerOpenError as e:
                # Wrap circuit breaker error as connection error
                raise SupabaseConnectionError(
                    f"Circuit breaker open for Supabase (too many failures): {e}"
                )
        else:
            # No circuit breaker, execute directly
            return func(*args, **kwargs)

    def _get_cache_key_params(self, table: str, **kwargs) -> Dict[str, Any]:
        """Generate cache key parameters from method arguments."""
        params = {"table": table}

        # Add relevant parameters for cache key generation
        for key, value in kwargs.items():
            if key not in ["correlation_id"] and value is not None:
                # Convert complex types to strings for cache key
                if isinstance(value, (dict, list)):
                    params[key] = json.dumps(value, sort_keys=True, default=str)
                else:
                    params[key] = str(value)

        return params

    def _invalidate_table_cache(self, table: str, correlation_id: Optional[str] = None):
        """Invalidate all cache entries for a specific table."""
        if not self.enable_cache or not self.cache:
            return

        try:
            deleted_count = self.cache.invalidate_pattern(
                namespace=table, pattern="*", correlation_id=correlation_id
            )
            self.logger.log_debug(
                f"Invalidated {deleted_count} cache entries for table '{table}'",
                {
                    "correlation_id": correlation_id,
                    "table": table,
                    "deleted_count": deleted_count,
                },
            )
        except CacheOperationError as e:
            self.logger.log_warning(
                f"Cache invalidation failed for table '{table}'",
                {"correlation_id": correlation_id, "error": str(e)},
            )

    def _invalidate_record_cache(
        self,
        table: str,
        record_id: str,
        user_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ):
        """
        Invalidate cache for a specific record with selective invalidation.

        This is more efficient than table-wide invalidation, only clearing:
        1. The specific record cache entry
        2. Related query caches (table-level queries)

        Args:
            table: Table name
            record_id: ID of the record that changed
            user_id: Optional user_id for user-scoped invalidations
            correlation_id: Optional correlation ID for logging
        """
        if not self.enable_cache or not self.cache:
            return

        try:
            # Invalidate specific record
            cache_params = {"table": table, "record_id": record_id}
            self.cache.delete(
                namespace=table,
                identifier="get_record",
                params=cache_params,
                correlation_id=correlation_id,
            )

            # Invalidate related queries (table-wide for queries)
            query_deleted = self.cache.invalidate_pattern(
                namespace=table,
                pattern="query_records:*",
                correlation_id=correlation_id,
            )

            self.logger.log_debug(
                f"Selectively invalidated cache for record in table '{table}'",
                {
                    "correlation_id": correlation_id,
                    "table": table,
                    "record_id": record_id,
                    "query_caches_deleted": query_deleted,
                },
            )

            # Special handling for RBAC-related tables
            if table in ["user_grants", "subscriptions", "user_group_members"] and user_id:
                # Invalidate RBAC feature cache for affected user
                rbac_deleted = self.cache.invalidate_pattern(
                    namespace="rbac",
                    pattern=f"*:{user_id}:*",
                    correlation_id=correlation_id,
                )
                self.logger.log_debug(
                    f"Invalidated RBAC cache for user due to {table} change",
                    {
                        "correlation_id": correlation_id,
                        "table": table,
                        "user_id": user_id,
                        "rbac_caches_deleted": rbac_deleted,
                    },
                )

        except CacheOperationError as e:
            self.logger.log_warning(
                f"Selective cache invalidation failed for table '{table}'",
                {"correlation_id": correlation_id, "error": str(e)},
            )

    def insert_record(
        self, table: str, data: Dict[str, Any], correlation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Inserts a new record into the specified table and invalidates related cache.

        Args:
            table: Name of the table to insert into
            data: Dictionary containing the data to insert
            correlation_id: Optional correlation ID for logging and tracing

        Returns:
            Dict containing the inserted record with any auto-generated fields

        Raises:
            SupabasePermissionError: If permission is denied
            ValueError: If data validation fails
            RuntimeError: For other insertion failures
        """
        correlation_id = correlation_id or get_correlation_id()
        context = {
            "correlation_id": correlation_id,
            "table": table,
            "data_keys": list(data.keys()),
        }

        try:
            self.logger.log_debug(f"Inserting record into table '{table}'", context)

            response = self.client.table(table).insert(data).execute()

            if response.data:
                inserted_record = (
                    response.data[0]
                    if isinstance(response.data, list)
                    else response.data
                )
                self.logger.log_debug(
                    f"Record inserted successfully into table '{table}'",
                    {**context, "record_id": inserted_record.get("id")},
                )

                # Selective cache invalidation
                self._invalidate_record_cache(
                    table,
                    record_id=str(inserted_record.get("id", "")),
                    user_id=str(inserted_record.get("user_id", "")),
                    correlation_id=correlation_id,
                )

                return inserted_record
            else:
                error_msg = f"No data returned after insertion into table '{table}'"
                self.logger.log_error(error_msg, context)
                raise RuntimeError(error_msg)

        except APIError as e:
            self.logger.log_exception(
                e, {**context, "error_code": getattr(e, "code", "unknown")}
            )
            if "permission" in str(e).lower() or "unauthorized" in str(e).lower():
                raise SupabasePermissionError(
                    f"Permission denied when inserting into table '{table}': {e}"
                )
            elif "validation" in str(e).lower() or "constraint" in str(e).lower():
                raise ValueError(f"Data validation failed for table '{table}': {e}")
            else:
                raise RuntimeError(
                    f"Supabase API error during insertion into table '{table}': {e}"
                )
        except Exception as e:
            self.logger.log_exception(e, context)
            raise RuntimeError(
                f"Unexpected error during insertion into table '{table}': {e}"
            )

    def get_record(
        self,
        table: str,
        record_id: Union[str, int],
        id_column: str = "id",
        correlation_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieves a single record from the specified table by ID with transparent caching.

        Args:
            table: Name of the table to query
            record_id: ID of the record to retrieve
            id_column: Name of the ID column (default: "id")
            correlation_id: Optional correlation ID for logging and tracing

        Returns:
            Dictionary containing the record data, or None if not found

        Raises:
            SupabasePermissionError: If permission is denied
            RuntimeError: For other query failures
        """
        correlation_id = correlation_id or get_correlation_id()
        context = {
            "correlation_id": correlation_id,
            "table": table,
            "record_id": record_id,
            "id_column": id_column,
        }

        # Try cache first
        if self.enable_cache and self.cache:
            try:
                cache_params = self._get_cache_key_params(
                    table, record_id=record_id, id_column=id_column
                )
                cached_result = self.cache.get(
                    namespace=table,
                    identifier="get_record",
                    params=cache_params,
                    correlation_id=correlation_id,
                )

                if cached_result is not None:
                    self.logger.log_debug(
                        f"Cache hit for record from table '{table}'", context
                    )
                    return cached_result

            except CacheOperationError as e:
                self.logger.log_warning(
                    "Cache read failed, falling back to database",
                    {**context, "cache_error": str(e)},
                )

        try:
            self.logger.log_debug(
                f"Retrieving record from table '{table}' with {id_column}={record_id}",
                context,
            )

            response = (
                self.client.table(table).select("*").eq(id_column, record_id).execute()
            )

            if response.data:
                record = (
                    response.data[0]
                    if isinstance(response.data, list)
                    else response.data
                )
                self.logger.log_debug(
                    f"Record retrieved successfully from table '{table}'", context
                )

                # Cache the result
                if self.enable_cache and self.cache:
                    try:
                        cache_params = self._get_cache_key_params(
                            table, record_id=record_id, id_column=id_column
                        )
                        self.cache.set(
                            namespace=table,
                            identifier="get_record",
                            value=record,
                            ttl=self.cache_ttl.get("get_record"),
                            params=cache_params,
                            correlation_id=correlation_id,
                        )
                    except CacheOperationError as e:
                        self.logger.log_warning(
                            "Cache write failed", {**context, "cache_error": str(e)}
                        )

                return record
            else:
                self.logger.log_debug(
                    f"No record found in table '{table}' with {id_column}={record_id}",
                    context,
                )
                return None

        except APIError as e:
            self.logger.log_exception(
                e, {**context, "error_code": getattr(e, "code", "unknown")}
            )
            if "permission" in str(e).lower() or "unauthorized" in str(e).lower():
                raise SupabasePermissionError(
                    f"Permission denied when querying table '{table}': {e}"
                )
            else:
                raise RuntimeError(
                    f"Supabase API error during query of table '{table}': {e}"
                )
        except Exception as e:
            self.logger.log_exception(e, context)
            raise RuntimeError(f"Unexpected error during query of table '{table}': {e}")

    def update_record(
        self,
        table: str,
        record_id: Union[str, int],
        data: Dict[str, Any],
        id_column: str = "id",
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Updates a record in the specified table and invalidates related cache.

        Args:
            table: Name of the table to update
            record_id: ID of the record to update
            data: Dictionary containing the data to update
            id_column: Name of the ID column (default: "id")
            correlation_id: Optional correlation ID for logging and tracing

        Returns:
            Dictionary containing the updated record

        Raises:
            SupabasePermissionError: If permission is denied
            ValueError: If data validation fails
            RuntimeError: For other update failures
        """
        correlation_id = correlation_id or get_correlation_id()
        context = {
            "correlation_id": correlation_id,
            "table": table,
            "record_id": record_id,
            "data_keys": list(data.keys()),
        }

        try:
            self.logger.log_debug(
                f"Updating record in table '{table}' with {id_column}={record_id}",
                context,
            )

            response = (
                self.client.table(table).update(data).eq(id_column, record_id).execute()
            )

            if response.data:
                updated_record = (
                    response.data[0]
                    if isinstance(response.data, list)
                    else response.data
                )
                self.logger.log_debug(
                    f"Record updated successfully in table '{table}'", context
                )

                # Selective cache invalidation
                self._invalidate_record_cache(
                    table,
                    record_id=str(record_id),
                    user_id=str(updated_record.get("user_id", data.get("user_id", ""))),
                    correlation_id=correlation_id,
                )

                return updated_record
            else:
                error_msg = f"No data returned after update in table '{table}' with {id_column}={record_id}"
                self.logger.log_error(error_msg, context)
                raise RuntimeError(error_msg)

        except APIError as e:
            self.logger.log_exception(
                e, {**context, "error_code": getattr(e, "code", "unknown")}
            )
            if "permission" in str(e).lower() or "unauthorized" in str(e).lower():
                raise SupabasePermissionError(
                    f"Permission denied when updating table '{table}': {e}"
                )
            elif "validation" in str(e).lower() or "constraint" in str(e).lower():
                raise ValueError(f"Data validation failed for table '{table}': {e}")
            else:
                raise RuntimeError(
                    f"Supabase API error during update of table '{table}': {e}"
                )
        except Exception as e:
            self.logger.log_exception(e, context)
            raise RuntimeError(
                f"Unexpected error during update of table '{table}': {e}"
            )

    def upsert_record(
        self,
        table: str,
        data: Dict[str, Any],
        on_conflict: Optional[str] = None,
        conflict_columns: Optional[List[str]] = None,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Upserts (insert or update) a record in the specified table and invalidates related cache.

        Args:
            table: Name of the table to upsert into
            data: Dictionary containing the data to upsert
            on_conflict: Optional conflict resolution strategy (default: None for auto-detection)
            conflict_columns: Optional list of columns to use for conflict detection
            correlation_id: Optional correlation ID for logging and tracing

        Returns:
            Dictionary containing the upserted record

        Raises:
            SupabasePermissionError: If permission is denied
            ValueError: If data validation fails
            RuntimeError: For other upsert failures
        """
        correlation_id = correlation_id or get_correlation_id()
        context = {
            "correlation_id": correlation_id,
            "table": table,
            "data_keys": list(data.keys()),
        }

        try:
            self.logger.log_debug(f"Upserting record in table '{table}'", context)

            # For Supabase Python client, upsert automatically handles conflicts based on primary keys
            # The conflict_columns parameter is for compatibility but the client uses primary keys
            response = self.client.table(table).upsert(data).execute()

            if response.data:
                upserted_record = (
                    response.data[0]
                    if isinstance(response.data, list)
                    else response.data
                )
                self.logger.log_debug(
                    f"Record upserted successfully in table '{table}'",
                    {**context, "record_id": upserted_record.get("id")},
                )

                # Selective cache invalidation
                self._invalidate_record_cache(
                    table,
                    record_id=str(upserted_record.get("id", "")),
                    user_id=str(upserted_record.get("user_id", "")),
                    correlation_id=correlation_id,
                )

                return upserted_record
            else:
                error_msg = f"No data returned after upsert in table '{table}'"
                self.logger.log_error(error_msg, context)
                raise RuntimeError(error_msg)

        except APIError as e:
            self.logger.log_exception(
                e, {**context, "error_code": getattr(e, "code", "unknown")}
            )
            if "permission" in str(e).lower() or "unauthorized" in str(e).lower():
                raise SupabasePermissionError(
                    f"Permission denied when upserting into table '{table}': {e}"
                )
            elif "validation" in str(e).lower() or "constraint" in str(e).lower():
                raise ValueError(f"Data validation failed for table '{table}': {e}")
            else:
                raise RuntimeError(
                    f"Supabase API error during upsert into table '{table}': {e}"
                )
        except Exception as e:
            self.logger.log_exception(e, context)
            raise RuntimeError(
                f"Unexpected error during upsert into table '{table}': {e}"
            )

    def delete_record(
        self,
        table: str,
        record_id: Union[str, int],
        id_column: str = "id",
        correlation_id: Optional[str] = None,
    ) -> bool:
        """
        Deletes a record from the specified table and invalidates related cache.

        This method fetches the record before deletion to enable selective cache
        invalidation (record-level + user-scoped) instead of table-wide invalidation.

        Args:
            table: Name of the table to delete from
            record_id: ID of the record to delete
            id_column: Name of the ID column (default: "id")
            correlation_id: Optional correlation ID for logging and tracing

        Returns:
            True if the record was deleted successfully

        Raises:
            SupabasePermissionError: If permission is denied
            RuntimeError: For other deletion failures
        """
        correlation_id = correlation_id or get_correlation_id()
        context = {
            "correlation_id": correlation_id,
            "table": table,
            "record_id": record_id,
            "id_column": id_column,
        }

        try:
            self.logger.log_debug(
                f"Deleting record from table '{table}' with {id_column}={record_id}",
                context,
            )

            # Fetch record BEFORE deletion for selective cache invalidation
            record_to_delete = None
            try:
                record_to_delete = self.get_record(
                    table, record_id, id_column, correlation_id
                )
            except Exception as e:
                # Log but continue with deletion even if fetch fails
                self.logger.log_warning(
                    f"Failed to fetch record before deletion, will use table-wide cache invalidation",
                    {**context, "fetch_error": str(e)},
                )

            # Delete the record
            response = (
                self.client.table(table).delete().eq(id_column, record_id).execute()
            )

            self.logger.log_debug(
                f"Record deleted successfully from table '{table}'", context
            )

            # Selective cache invalidation with data from fetched record
            if record_to_delete:
                self._invalidate_record_cache(
                    table,
                    record_id=str(record_id),
                    user_id=str(record_to_delete.get("user_id", "")),
                    correlation_id=correlation_id,
                )
            else:
                # Fallback to table-wide invalidation if record wasn't fetched
                self.logger.log_debug(
                    f"Using table-wide cache invalidation for delete (record not fetched)",
                    context,
                )
                self._invalidate_table_cache(table, correlation_id)

            return True

        except APIError as e:
            self.logger.log_exception(
                e, {**context, "error_code": getattr(e, "code", "unknown")}
            )
            if "permission" in str(e).lower() or "unauthorized" in str(e).lower():
                raise SupabasePermissionError(
                    f"Permission denied when deleting from table '{table}': {e}"
                )
            else:
                raise RuntimeError(
                    f"Supabase API error during deletion from table '{table}': {e}"
                )
        except Exception as e:
            self.logger.log_exception(e, context)
            raise RuntimeError(
                f"Unexpected error during deletion from table '{table}': {e}"
            )

    def query_records(
        self,
        table: str,
        filters: Optional[Dict[str, Any]] = None,
        select_columns: str = "*",
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        correlation_id: Optional[str] = None,
        order_by: Optional[str] = None,
        desc: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Queries records from the specified table with optional filters and ordering, with transparent caching.

        Args:
            table: Name of the table to query
            filters: Optional dictionary of column-value pairs to filter by
            select_columns: Columns to select (default: "*")
            limit: Optional limit on number of records to return
            correlation_id: Optional correlation ID for logging and tracing
            order_by: Optional column name to order by
            desc: If True, order descending (default: False)

        Returns:
            List of dictionaries containing the matching records

        Raises:
            SupabasePermissionError: If permission is denied
            RuntimeError: For other query failures
        """
        correlation_id = correlation_id or get_correlation_id()
        context = {
            "correlation_id": correlation_id,
            "table": table,
            "filters": filters,
            "limit": limit,
            "offset": offset,
            "order_by": order_by,
            "desc": desc,
        }

        # Try cache first
        if self.enable_cache and self.cache:
            try:
                cache_params = self._get_cache_key_params(
                    table,
                    filters=filters,
                    select_columns=select_columns,
                    limit=limit,
                    order_by=order_by,
                    desc=desc,
                    offset=offset,
                )
                cached_result = self.cache.get(
                    namespace=table,
                    identifier="query_records",
                    params=cache_params,
                    correlation_id=correlation_id,
                )

                if cached_result is not None:
                    self.logger.log_debug(
                        f"Cache hit for query on table '{table}'",
                        {**context, "record_count": len(cached_result)},
                    )
                    return cached_result

            except CacheOperationError as e:
                self.logger.log_warning(
                    "Cache read failed, falling back to database",
                    {**context, "cache_error": str(e)},
                )

        try:
            self.logger.log_debug(f"Querying records from table '{table}'", context)

            query = self.client.table(table).select(select_columns)

            # Apply filters if provided
            if filters:
                for column, value in filters.items():
                    if isinstance(value, list):
                        # Use 'in_' for list values
                        query = query.in_(column, value)
                    elif isinstance(value, dict):
                        for op, op_value in value.items():
                            if op in ("in", "any") and isinstance(op_value, list):
                                query = query.in_(column, op_value)
                            elif op == "gte":
                                query = query.gte(column, op_value)
                            elif op == "gt":
                                query = query.gt(column, op_value)
                            elif op == "lte":
                                query = query.lte(column, op_value)
                            elif op == "lt":
                                query = query.lt(column, op_value)
                            elif op == "neq":
                                query = query.neq(column, op_value)
                            elif op == "like":
                                query = query.like(column, op_value)
                            elif op == "ilike":
                                query = query.ilike(column, op_value)
                            elif op == "is":
                                query = query.is_(column, op_value)
                            elif op == "contains":
                                query = query.contains(column, op_value)
                            else:
                                query = query.eq(column, op_value)
                    else:
                        # Use 'eq' for single values
                        query = query.eq(column, value)

            # Apply ordering if provided
            if order_by:
                query = query.order(order_by, desc=desc)

            # Apply limit/offset if provided
            if offset is not None and limit is not None:
                query = query.range(offset, offset + limit - 1)
            elif limit is not None:
                query = query.limit(limit)
            elif offset is not None:
                # Offset without limit: use range with large upper bound to respect offset
                query = query.range(offset, offset + 999)

            response = query.execute()

            records = response.data if response.data else []
            self.logger.log_debug(
                f"Retrieved {len(records)} records from table '{table}'",
                {**context, "record_count": len(records)},
            )

            # Cache the result
            if self.enable_cache and self.cache:
                try:
                    cache_params = self._get_cache_key_params(
                        table,
                        filters=filters,
                        select_columns=select_columns,
                        limit=limit,
                        offset=offset,
                        order_by=order_by,
                        desc=desc,
                    )
                    self.cache.set(
                        namespace=table,
                        identifier="query_records",
                        value=records,
                        ttl=self.cache_ttl.get("query_records"),
                        params=cache_params,
                        correlation_id=correlation_id,
                    )
                except CacheOperationError as e:
                    self.logger.log_warning(
                        "Cache write failed", {**context, "cache_error": str(e)}
                    )

            return records

        except APIError as e:
            self.logger.log_exception(
                e, {**context, "error_code": getattr(e, "code", "unknown")}
            )
            if "permission" in str(e).lower() or "unauthorized" in str(e).lower():
                raise SupabasePermissionError(
                    f"Permission denied when querying table '{table}': {e}"
                )
            else:
                raise RuntimeError(
                    f"Supabase API error during query of table '{table}': {e}"
                )
        except Exception as e:
            self.logger.log_exception(e, context)
            raise RuntimeError(f"Unexpected error during query of table '{table}': {e}")

    def count_records(
        self,
        table: str,
        filters: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
    ) -> int:
        """
        Counts records in the specified table with optional filters.
        Uses PostgreSQL COUNT for efficiency instead of fetching all records.

        Args:
            table: Name of the table to count records from
            filters: Optional dictionary of column-value pairs to filter by
            correlation_id: Optional correlation ID for logging and tracing

        Returns:
            Integer count of matching records

        Raises:
            RuntimeError: For query failures
        """
        correlation_id = correlation_id or get_correlation_id()
        context = {
            "correlation_id": correlation_id,
            "table": table,
            "filters": filters,
        }

        try:
            self.logger.log_debug(
                f"Counting records from table '{table}' with filters: {filters}",
                context,
            )

            # Build the count query with head() to get only the count header
            query = self.client.table(table).select("*", count="exact")

            # Apply filters if provided
            if filters:
                for key, value in filters.items():
                    if isinstance(value, dict):
                        for op, op_value in value.items():
                            if op in ("in", "any") and isinstance(op_value, list):
                                query = query.in_(key, op_value)
                            elif op == "gte":
                                query = query.gte(key, op_value)
                            elif op == "gt":
                                query = query.gt(key, op_value)
                            elif op == "lte":
                                query = query.lte(key, op_value)
                            elif op == "lt":
                                query = query.lt(key, op_value)
                            elif op == "neq":
                                query = query.neq(key, op_value)
                            elif op == "is":
                                query = query.is_(key, op_value)
                            else:
                                query = query.eq(key, op_value)
                    elif value is None:
                        query = query.is_(key, "null")
                    elif isinstance(value, list):
                        query = query.in_(key, value)
                    else:
                        query = query.eq(key, value)

            # Execute with head to get count without fetching data
            response = query.limit(1).execute()
            
            count = response.count if hasattr(response, 'count') and response.count is not None else 0

            self.logger.log_debug(
                f"Count result for table '{table}': {count}",
                {**context, "count": count},
            )

            return count

        except APIError as e:
            error_details = e.message if hasattr(e, 'message') else str(e)
            self.logger.log_error(
                f"Supabase API error during count of table '{table}'",
                {
                    **context,
                    "error_code": getattr(e, 'code', 'unknown'),
                    "exception_type": type(e).__name__,
                    "exception_message": error_details,
                },
            )
            raise RuntimeError(
                f"Supabase API error during count of table '{table}': {error_details}"
            ) from e
        except Exception as e:
            self.logger.log_exception(
                e,
                {
                    **context,
                    "exception_type": type(e).__name__,
                    "exception_message": str(e),
                },
            )
            raise RuntimeError(
                f"Unexpected error during count from table '{table}': {e}"
            ) from e

    def count_records_cached(
        self,
        table: str,
        filters: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
        cache_ttl: int = 300,  # 5 minutes default
    ) -> int:
        """
        Count records with caching support.

        This method provides cached count operations to reduce database load
        for frequently-accessed counts (e.g., member counts, active records).

        Args:
            table: Name of the table to count records from
            filters: Optional dictionary of column-value pairs to filter by
            correlation_id: Optional correlation ID for logging and tracing
            cache_ttl: Cache TTL in seconds (default: 300 = 5 minutes)

        Returns:
            Integer count of matching records

        Raises:
            RuntimeError: For query failures
        """
        correlation_id = correlation_id or get_correlation_id()
        context = {
            "correlation_id": correlation_id,
            "table": table,
            "filters": filters,
        }

        # Try cache first
        if self.enable_cache and self.cache:
            try:
                cache_params = self._get_cache_key_params(table, filters=filters)
                cached_result = self.cache.get(
                    namespace=table,
                    identifier="count_records",
                    params=cache_params,
                    correlation_id=correlation_id,
                )

                if cached_result is not None:
                    self.logger.log_debug(
                        f"Cache hit for count on table '{table}'",
                        {**context, "count": cached_result},
                    )
                    return cached_result

            except CacheOperationError as e:
                self.logger.log_warning(
                    "Cache read failed, falling back to database count",
                    {**context, "cache_error": str(e)},
                )

        # Execute count
        count = self.count_records(table, filters, correlation_id)

        # Cache result
        if self.enable_cache and self.cache:
            try:
                cache_params = self._get_cache_key_params(table, filters=filters)
                self.cache.set(
                    namespace=table,
                    identifier="count_records",
                    value=count,
                    ttl=cache_ttl,
                    params=cache_params,
                    correlation_id=correlation_id,
                )
            except CacheOperationError as e:
                self.logger.log_warning(
                    "Cache write failed for count",
                    {**context, "cache_error": str(e)},
                )

        return count

    def execute_rpc(
        self,
        function_name: str,
        params: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
        cache_ttl: Optional[int] = None,
    ) -> Any:
        """
        Executes a Supabase RPC (Remote Procedure Call) function with optional caching.

        Args:
            function_name: Name of the RPC function to execute
            params: Optional parameters to pass to the function
            correlation_id: Optional correlation ID for logging and tracing
            cache_ttl: Optional TTL for caching (None = use default, 0 = no cache)

        Returns:
            The result of the RPC function execution

        Raises:
            SupabasePermissionError: If permission is denied
            RuntimeError: For other execution failures
        """
        correlation_id = correlation_id or get_correlation_id()
        context = {
            "correlation_id": correlation_id,
            "function_name": function_name,
            "params": params,
        }

        # Try cache first (if caching is enabled and TTL is not 0)
        if self.enable_cache and self.cache and cache_ttl != 0:
            try:
                cache_params = self._get_cache_key_params(
                    "rpc", function_name=function_name, params=params
                )
                cached_result = self.cache.get(
                    namespace="rpc",
                    identifier=function_name,
                    params=cache_params,
                    correlation_id=correlation_id,
                )

                if cached_result is not None:
                    self.logger.log_debug(
                        f"Cache hit for RPC function '{function_name}'", context
                    )
                    return cached_result

            except CacheOperationError as e:
                self.logger.log_warning(
                    "Cache read failed, falling back to RPC execution",
                    {**context, "cache_error": str(e)},
                )

        try:
            self.logger.log_debug(f"Executing RPC function '{function_name}'", context)

            response = self.client.rpc(function_name, params or {}).execute()

            self.logger.log_debug(
                f"RPC function '{function_name}' executed successfully", context
            )

            # Cache the result (if caching is enabled and TTL is not 0)
            if self.enable_cache and self.cache and cache_ttl != 0:
                try:
                    cache_params = self._get_cache_key_params(
                        "rpc", function_name=function_name, params=params
                    )
                    actual_ttl = cache_ttl or self.cache_ttl.get("execute_rpc")
                    self.cache.set(
                        namespace="rpc",
                        identifier=function_name,
                        value=response.data,
                        ttl=actual_ttl,
                        params=cache_params,
                        correlation_id=correlation_id,
                    )
                except CacheOperationError as e:
                    self.logger.log_warning(
                        "Cache write failed", {**context, "cache_error": str(e)}
                    )

            return response.data

        except APIError as e:
            self.logger.log_exception(
                e, {**context, "error_code": getattr(e, "code", "unknown")}
            )
            if "permission" in str(e).lower() or "unauthorized" in str(e).lower():
                raise SupabasePermissionError(
                    f"Permission denied when executing RPC function '{function_name}': {e}"
                )
            else:
                raise RuntimeError(
                    f"Supabase API error during RPC function '{function_name}' execution: {e}"
                )
        except Exception as e:
            self.logger.log_exception(e, context)
            raise RuntimeError(
                f"Unexpected error during RPC function '{function_name}' execution: {e}"
            )

    def invalidate_cache(
        self, table: Optional[str] = None, correlation_id: Optional[str] = None
    ) -> int:
        """
        Manually invalidate cache entries.

        Args:
            table: Optional table name to invalidate (None = invalidate all)
            correlation_id: Optional correlation ID for logging

        Returns:
            Number of cache entries invalidated
        """
        if not self.enable_cache or not self.cache:
            return 0

        correlation_id = correlation_id or get_correlation_id()

        if table:
            return self._invalidate_table_cache(table, correlation_id)
        else:
            # Invalidate all Supabase cache entries
            try:
                deleted_count = self.cache.invalidate_pattern(
                    namespace="*", pattern="*", correlation_id=correlation_id
                )
                self.logger.log_debug(
                    f"Invalidated {deleted_count} total cache entries",
                    {"correlation_id": correlation_id, "deleted_count": deleted_count},
                )
                return deleted_count
            except CacheOperationError as e:
                self.logger.log_warning(
                    "Global cache invalidation failed",
                    {"correlation_id": correlation_id, "error": str(e)},
                )
                return 0

    def get_cache_stats(self, correlation_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get cache statistics.

        Args:
            correlation_id: Optional correlation ID for logging

        Returns:
            Dictionary with cache statistics or empty dict if cache disabled
        """
        if not self.enable_cache or not self.cache:
            return {"cache_enabled": False}

        correlation_id = correlation_id or get_correlation_id()

        try:
            stats = self.cache.get_stats(correlation_id)
            stats["cache_enabled"] = True
            stats["cache_ttl_config"] = self.cache_ttl
            return stats
        except CacheOperationError as e:
            self.logger.log_warning(
                "Failed to get cache stats",
                {"correlation_id": correlation_id, "error": str(e)},
            )
            return {"cache_enabled": True, "error": str(e)}

    def get_client(self) -> Client:
        """
        Returns the underlying Supabase client for advanced operations.

        Returns:
            The Supabase client instance
        """
        return self.client
