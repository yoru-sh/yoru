"""Feature check middleware for subscription system."""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware

from libs.log_manager.controller import LoggingController
from apps.api.api.services.subscription.subscription_service import SubscriptionService


class FeatureCheckMiddleware(BaseHTTPMiddleware):
    """
    Middleware that checks if a user has access to required features.

    Feature access priority:
    1. user_grants (highest priority - admin overrides)
    2. subscription.plan_features
    3. feature.default_value (lowest priority)

    The middleware checks request.state.required_feature set by the
    require_feature dependency.
    """

    def __init__(self, app):
        super().__init__(app)
        self.logger = LoggingController(app_name="FeatureCheckMiddleware")
        self.subscription_service = SubscriptionService()

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

        if required_feature:
            # Get user ID from request state (set by auth middleware)
            user_id_str = getattr(request.state, "user_id", None)

            if not user_id_str:
                correlation_id = getattr(request.state, "correlation_id", "")
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
                correlation_id = getattr(request.state, "correlation_id", "")

                # Check feature access (checks grants first, then subscription)
                has_access = await self.subscription_service.check_feature_access(
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

                self.logger.log_debug(
                    "Feature access granted",
                    {
                        "correlation_id": correlation_id,
                        "user_id": str(user_id),
                        "required_feature": required_feature,
                    },
                )

            except HTTPException:
                raise
            except Exception as e:
                correlation_id = getattr(request.state, "correlation_id", "")
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
