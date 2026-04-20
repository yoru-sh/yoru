"""Centralized middleware configuration using pydantic-settings."""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class MiddlewareSettings(BaseSettings):
    """
    Configuration centralisée pour tous les middlewares.

    Conforme à python.state.rules.md BLOC-002 :
    Toute configuration doit passer par pydantic-settings, jamais os.environ direct.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Timeout Middleware
    request_timeout_seconds: int = 30

    # Request Size Limit Middleware
    max_request_size_mb: int = 10

    # Feature Flags Middleware
    feature_flags_ttl_seconds: int = 10
    api_enabled: bool = True
    maintenance_mode: bool = False

    # Rate Limiting Middleware
    rate_limit_window_seconds: int = 60
    rate_limit_free_plan: int = 100
    rate_limit_pro_plan: int = 1000
    rate_limit_enterprise_plan: int = 10000
    rate_limit_unauthenticated: int = 20
    enable_rate_limiting: bool = True

    # CORS Middleware
    cors_origins: str = "http://localhost:3000"

    # Tracing Middleware
    enable_tracing: bool = False


@lru_cache
def get_middleware_settings() -> MiddlewareSettings:
    """
    Singleton Settings instance.

    Conforme à python.state.rules.md BLOC-003 :
    Utiliser @lru_cache pour singletons de configuration.
    """
    return MiddlewareSettings()
