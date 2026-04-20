"""Feature access dependencies."""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends, Request

from apps.api.api.dependencies.auth import get_current_user_id


def require_feature(feature_key: str):
    """
    FastAPI dependency factory that requires a specific feature.

    Sets the required_feature attribute on request.state, which is then
    checked by the FeatureCheckMiddleware.

    Feature access priority:
    1. user_grants (highest priority - admin overrides)
    2. subscription.plan_features
    3. feature.default_value (lowest priority)

    Usage:
        @router.post("/analyze")
        async def analyze_video(
            video_id: UUID,
            _: None = Depends(require_feature("ai_analysis"))
        ):
            # This endpoint requires the "ai_analysis" feature
            pass

    Args:
        feature_key: The key of the feature to require (e.g., "ai_analysis")

    Returns:
        A FastAPI dependency function

    Raises:
        HTTPException: 401 if not authenticated, 403 if feature not available
    """

    async def dependency(
        request: Request,
        user_id: UUID = Depends(get_current_user_id),
    ) -> None:
        """Set required feature on request state and store user_id."""
        request.state.required_feature = feature_key
        request.state.user_id = str(user_id)

    return Depends(dependency)
