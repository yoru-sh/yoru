"""RBAC middleware for hierarchical permission verification."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware

from libs.log_manager.controller import LoggingController
from libs.supabase.supabase import SupabaseManager


class RBACMiddleware(BaseHTTPMiddleware):
    """
    Middleware for Role-Based Access Control with hierarchical permission checking.

    Permission hierarchy (highest to lowest priority):
    1. user_grants - Admin overrides for specific users
    2. user_group_features - Features via group membership
    3. plan_features - Features via subscription plan
    4. default_value - Feature default value

    The middleware checks request.state.required_feature set by the
    require_feature dependency.
    """

    def __init__(self, app, supabase: SupabaseManager | None = None):
        super().__init__(app)
        self.supabase = supabase or SupabaseManager()
        self.logger = LoggingController(app_name="RBACMiddleware")

    async def dispatch(self, request: Request, call_next):
        """
        Check feature access before executing the endpoint.

        Args:
            request: The FastAPI request object
            call_next: The next middleware or endpoint

        Returns:
            Response from the next middleware/endpoint

        Raises:
            HTTPException: 401 if not authenticated, 403 if feature not available
        """
        required_feature = getattr(request.state, "required_feature", None)

        if not required_feature:
            # No feature check required
            return await call_next(request)

        # Get user ID from request state (set by auth middleware)
        user_id_str = getattr(request.state, "user_id", None)
        correlation_id = getattr(request.state, "correlation_id", "")

        if not user_id_str:
            self.logger.log_warning(
                "Feature check failed: user not authenticated",
                {
                    "correlation_id": correlation_id,
                    "required_feature": required_feature,
                },
            )
            raise HTTPException(
                status_code=401,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )

        try:
            user_id = UUID(user_id_str)

            # Check feature access with hierarchical priority
            has_access, value = await self._check_feature_access(
                user_id, required_feature, correlation_id
            )

            if not has_access:
                self.logger.log_warning(
                    "Feature access denied",
                    {
                        "correlation_id": correlation_id,
                        "user_id": str(user_id),
                        "required_feature": required_feature,
                    },
                )
                raise HTTPException(
                    status_code=403,
                    detail=f"Feature '{required_feature}' not available in your plan. Please upgrade your subscription.",
                )

            # Store feature value in request state for use in endpoint
            request.state.feature_value = value

            self.logger.log_debug(
                "Feature access granted",
                {
                    "correlation_id": correlation_id,
                    "user_id": str(user_id),
                    "required_feature": required_feature,
                    "value": value,
                },
            )

        except HTTPException:
            raise
        except Exception as e:
            self.logger.log_error(
                "Error checking feature access",
                {
                    "correlation_id": correlation_id,
                    "required_feature": required_feature,
                },
                e,
            )
            raise HTTPException(
                status_code=500,
                detail="Error checking feature access",
            )

        return await call_next(request)

    async def _check_feature_access(
        self, user_id: UUID, feature_key: str, correlation_id: str
    ) -> tuple[bool, dict | bool | int | str | None]:
        """
        Check if user has access to a feature using hierarchical priority with caching.

        Priority order:
        1. user_grants (admin override)
        2. user_group_features (via groups)
        3. plan_features (via subscription)
        4. default_value (feature default)

        Args:
            user_id: ID of the user
            feature_key: Key of the feature to check
            correlation_id: Request correlation ID

        Returns:
            Tuple of (has_access: bool, value: any)
        """
        context = {
            "operation": "check_feature_access",
            "component": "RBACMiddleware",
            "correlation_id": correlation_id,
            "user_id": str(user_id),
            "feature_key": feature_key,
        }

        # Try cache first
        if self.supabase.enable_cache and self.supabase.cache:
            try:
                cache_key_params = {
                    "user_id": str(user_id),
                    "feature_key": feature_key,
                }
                cached_result = self.supabase.cache.get(
                    namespace="rbac",
                    identifier="feature_access",
                    params=cache_key_params,
                    correlation_id=correlation_id,
                )
                if cached_result is not None:
                    self.logger.log_debug(
                        "Feature access from cache",
                        {**context, "source": "cache", "cached_has_access": cached_result.get("has_access")},
                    )
                    return cached_result["has_access"], cached_result["value"]
            except Exception as e:
                self.logger.log_warning(
                    "Cache read failed for RBAC feature check",
                    {**context, "cache_error": str(e)},
                )

        try:
            # Get feature details
            features = self.supabase.query_records(
                "features",
                filters={"key": feature_key},
                correlation_id=correlation_id,
            )
            if not features:
                self.logger.log_debug(
                    "Feature not found", {**context, "reason": "feature_not_found"}
                )
                return False, None

            feature = features[0]
            feature_id = feature["id"]

            # 1. Check user_grants (highest priority)
            grants = self.supabase.query_records(
                "user_grants",
                filters={"user_id": str(user_id), "feature_id": feature_id},
                correlation_id=correlation_id,
            )
            if grants:
                grant = grants[0]
                # Check if grant is expired
                if grant.get("expires_at"):
                    expires_at = datetime.fromisoformat(
                        grant["expires_at"].replace("Z", "+00:00")
                    )
                    if expires_at <= datetime.now(timezone.utc):
                        self.logger.log_debug(
                            "Grant expired",
                            {**context, "expires_at": grant["expires_at"]},
                        )
                    else:
                        self.logger.log_debug(
                            "Access granted via user_grants",
                            {**context, "source": "user_grants"},
                        )
                        # Cache positive result
                        if self.supabase.enable_cache and self.supabase.cache:
                            try:
                                cache_key_params = {
                                    "user_id": str(user_id),
                                    "feature_key": feature_key,
                                }
                                self.supabase.cache.set(
                                    namespace="rbac",
                                    identifier="feature_access",
                                    value={"has_access": True, "value": grant["value"]},
                                    ttl=300,  # 5 minutes
                                    params=cache_key_params,
                                    correlation_id=correlation_id,
                                )
                            except Exception as cache_error:
                                self.logger.log_warning(
                                    "Cache write failed for RBAC feature check",
                                    {**context, "cache_error": str(cache_error)},
                                )
                        return True, grant["value"]
                else:
                    # No expiration, grant is active
                    self.logger.log_debug(
                        "Access granted via user_grants",
                        {**context, "source": "user_grants"},
                    )
                    # Cache positive result
                    if self.supabase.enable_cache and self.supabase.cache:
                        try:
                            cache_key_params = {
                                "user_id": str(user_id),
                                "feature_key": feature_key,
                            }
                            self.supabase.cache.set(
                                namespace="rbac",
                                identifier="feature_access",
                                value={"has_access": True, "value": grant["value"]},
                                ttl=300,  # 5 minutes
                                params=cache_key_params,
                                correlation_id=correlation_id,
                            )
                        except Exception as cache_error:
                            self.logger.log_warning(
                                "Cache write failed for RBAC feature check",
                                {**context, "cache_error": str(cache_error)},
                            )
                    return True, grant["value"]

            # 2. Check user_group_features (via group membership)
            try:
                group_feature = (
                    self.supabase.client.rpc(
                        "get_user_feature_via_groups",
                        {"p_user_id": str(user_id), "p_feature_key": feature_key},
                    )
                    .execute()
                )
                if group_feature.data and len(group_feature.data) > 0:
                    value = group_feature.data[0]["value"]
                    self.logger.log_debug(
                        "Access granted via user_groups",
                        {**context, "source": "user_groups"},
                    )
                    # Cache positive result
                    if self.supabase.enable_cache and self.supabase.cache:
                        try:
                            cache_key_params = {
                                "user_id": str(user_id),
                                "feature_key": feature_key,
                            }
                            self.supabase.cache.set(
                                namespace="rbac",
                                identifier="feature_access",
                                value={"has_access": True, "value": value},
                                ttl=300,  # 5 minutes
                                params=cache_key_params,
                                correlation_id=correlation_id,
                            )
                        except Exception as cache_error:
                            self.logger.log_warning(
                                "Cache write failed for RBAC feature check",
                                {**context, "cache_error": str(cache_error)},
                            )
                    return True, value
            except Exception as e:
                self.logger.log_warning(
                    "Error checking group features",
                    {**context, "error": str(e)},
                )
                # Continue to next priority level

            # 3. Check plan_features (via subscription)
            subscriptions = self.supabase.query_records(
                "subscriptions",
                filters={"user_id": str(user_id), "status": "active"},
                correlation_id=correlation_id,
            )
            if subscriptions:
                # Get most recent active subscription
                subscription = sorted(
                    subscriptions, key=lambda x: x.get("created_at", ""), reverse=True
                )[0]

                plan_features = self.supabase.query_records(
                    "plan_features",
                    filters={
                        "plan_id": subscription["plan_id"],
                        "feature_id": feature_id,
                    },
                    correlation_id=correlation_id,
                )
                if plan_features:
                    value = plan_features[0]["value"]
                    self.logger.log_debug(
                        "Access granted via plan_features",
                        {**context, "source": "plan_features"},
                    )
                    # Cache positive result
                    if self.supabase.enable_cache and self.supabase.cache:
                        try:
                            cache_key_params = {
                                "user_id": str(user_id),
                                "feature_key": feature_key,
                            }
                            self.supabase.cache.set(
                                namespace="rbac",
                                identifier="feature_access",
                                value={"has_access": True, "value": value},
                                ttl=300,  # 5 minutes
                                params=cache_key_params,
                                correlation_id=correlation_id,
                            )
                        except Exception as cache_error:
                            self.logger.log_warning(
                                "Cache write failed for RBAC feature check",
                                {**context, "cache_error": str(cache_error)},
                            )
                    return True, value

            # 4. Check default_value (lowest priority)
            default_value = feature.get("default_value")
            if default_value is not None:
                # For boolean flags, check if true
                if isinstance(default_value, bool):
                    if default_value:
                        self.logger.log_debug(
                            "Access granted via default_value",
                            {**context, "source": "default_value"},
                        )
                        # Cache positive result
                        if self.supabase.enable_cache and self.supabase.cache:
                            try:
                                cache_key_params = {
                                    "user_id": str(user_id),
                                    "feature_key": feature_key,
                                }
                                self.supabase.cache.set(
                                    namespace="rbac",
                                    identifier="feature_access",
                                    value={"has_access": True, "value": default_value},
                                    ttl=300,  # 5 minutes
                                    params=cache_key_params,
                                    correlation_id=correlation_id,
                                )
                            except Exception as cache_error:
                                self.logger.log_warning(
                                    "Cache write failed for RBAC feature check",
                                    {**context, "cache_error": str(cache_error)},
                                )
                        return True, default_value
                    else:
                        self.logger.log_debug(
                            "Access denied: default is false",
                            {**context, "source": "default_value"},
                        )
                        # Cache negative result
                        if self.supabase.enable_cache and self.supabase.cache:
                            try:
                                cache_key_params = {
                                    "user_id": str(user_id),
                                    "feature_key": feature_key,
                                }
                                self.supabase.cache.set(
                                    namespace="rbac",
                                    identifier="feature_access",
                                    value={"has_access": False, "value": default_value},
                                    ttl=300,  # 5 minutes
                                    params=cache_key_params,
                                    correlation_id=correlation_id,
                                )
                            except Exception as cache_error:
                                self.logger.log_warning(
                                    "Cache write failed for RBAC feature check",
                                    {**context, "cache_error": str(cache_error)},
                                )
                        return False, default_value
                else:
                    # For quotas/configs, always allow with default value
                    self.logger.log_debug(
                        "Access granted via default_value",
                        {**context, "source": "default_value"},
                    )
                    # Cache positive result
                    if self.supabase.enable_cache and self.supabase.cache:
                        try:
                            cache_key_params = {
                                "user_id": str(user_id),
                                "feature_key": feature_key,
                            }
                            self.supabase.cache.set(
                                namespace="rbac",
                                identifier="feature_access",
                                value={"has_access": True, "value": default_value},
                                ttl=300,  # 5 minutes
                                params=cache_key_params,
                                correlation_id=correlation_id,
                            )
                        except Exception as cache_error:
                            self.logger.log_warning(
                                "Cache write failed for RBAC feature check",
                                {**context, "cache_error": str(cache_error)},
                            )
                    return True, default_value

            # No access found at any level
            self.logger.log_debug(
                "Access denied: no grant found at any level",
                {**context, "reason": "no_grant"},
            )
            # Cache negative result
            if self.supabase.enable_cache and self.supabase.cache:
                try:
                    cache_key_params = {
                        "user_id": str(user_id),
                        "feature_key": feature_key,
                    }
                    self.supabase.cache.set(
                        namespace="rbac",
                        identifier="feature_access",
                        value={"has_access": False, "value": None},
                        ttl=300,  # 5 minutes
                        params=cache_key_params,
                        correlation_id=correlation_id,
                    )
                except Exception as cache_error:
                    self.logger.log_warning(
                        "Cache write failed for RBAC feature check",
                        {**context, "cache_error": str(cache_error)},
                    )
            return False, None

        except Exception as e:
            self.logger.log_error(
                "Error in feature access check",
                context,
                e,
            )
            # On error, deny access (don't cache errors)
            return False, None
