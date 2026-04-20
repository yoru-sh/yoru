"""FastAPI entry point — Receipt v0.

Scope: session ingestion + list/detail/summary APIs only. The SaaSForge
machinery (auth, multi-tenancy, subscriptions, tracing, redis, email) is
disabled — Receipt doesn't need it for the overnight wedge. Original
main.py is preserved at main_saasforge.py.bak for post-v0 reactivation.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from apps.api.api.core.errors import install_error_handlers
from apps.api.api.middleware.security_headers import SecurityHeadersMiddleware
from apps.api.api.middleware.structured_logging import (
    StructuredLoggingMiddleware,
    configure_structured_logger,
)
from apps.api.api.middlewares.metrics import (
    CONTENT_TYPE_LATEST,
    RequestMetricsMiddleware,
    render_prometheus,
)
from apps.api.api.middlewares.rate_limit import RateLimitMiddleware
from apps.api.api.routers.billing.checkout import CheckoutRouter
from apps.api.api.routers.billing.webhook import WebhookRouter
from apps.api.api.routers.ops_router import OpsRouter
from apps.api.api.routers.ping_router import PingRouter
from apps.api.api.routers.receipt.auth_router import AuthRouter
from apps.api.api.routers.receipt.dashboard_router import DashboardRouter
from apps.api.api.routers.receipt.db import init_db
from apps.api.api.routers.receipt.events_router import EventsRouter
from apps.api.api.routers.receipt.health_deep_router import HealthDeepRouter
from apps.api.api.routers.receipt.sessions_router import SessionsRouter
from apps.api.api.routers.receipt.summary_router import SummaryRouter
from apps.api.api.routers.webhooks import WebhooksRouter
from apps.api.core.logging import configure_logging
from apps.api.core.max_body_size import MaxBodySizeMiddleware

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_structured_logger()
    init_db()
    yield


app = FastAPI(
    lifespan=lifespan,
    title="Receipt API",
    version="0.1.0-receipt",
    description="Audit-grade session receipts for autonomous AI coding agents.",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# Security headers — innermost middleware (first add_middleware = last on
# request, first on response). Stamps the 6-header bundle onto every response
# before CORS layers its headers on top. wave-50 C3.
app.add_middleware(SecurityHeadersMiddleware)

_cors_origins = [
    o.strip()
    for o in os.environ.get(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:5173,http://localhost:3000",
    ).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate-limit ONLY the ingest endpoint (CLI hooks can batch up to 1000 events
# per request — runaway hooks must not hammer us). SPA reads stay unthrottled.
app.add_middleware(RateLimitMiddleware)

# Fail fast on oversized POST bodies (256 KiB default) on ingest paths BEFORE
# CORS/RateLimit/app so a multi-MB attacker payload never reaches Pydantic's
# `max_length=1000` array guard. Scoped to POST + the three ingest paths only.
app.add_middleware(MaxBodySizeMiddleware)

# Mint/propagate X-Request-ID and emit one structured JSON log per request.
# wave-40 C1: schema is {timestamp, level, request_id, method, path, status,
# latency_ms, user_id}. C2 will front this middleware with a dedicated
# correlation-ID middleware that reads X-Request-ID from the inbound request.
app.add_middleware(StructuredLoggingMiddleware)

# Outermost: in-process request counter (sees status from every layer below).
app.add_middleware(RequestMetricsMiddleware)

# Global JSON error envelope + X-Request-ID propagation on error responses.
# Exception goes to ServerErrorMiddleware (outermost); others to ExceptionMiddleware.
install_error_handlers(app)

ping_router = PingRouter()
ping_router.initialize_services()
app.include_router(ping_router.get_router())

events_router = EventsRouter()
events_router.initialize_services()
app.include_router(events_router.get_router(), prefix="/api/v1")

sessions_router = SessionsRouter()
app.include_router(sessions_router.get_router(), prefix="/api/v1")

summary_router = SummaryRouter()
summary_router.initialize_services()
app.include_router(summary_router.get_router(), prefix="/api/v1")

auth_router = AuthRouter()
app.include_router(auth_router.get_router(), prefix="/api/v1")

dashboard_router = DashboardRouter()
app.include_router(dashboard_router.get_router(), prefix="/api/v1")

checkout_router = CheckoutRouter()
app.include_router(checkout_router.get_router(), prefix="/api/v1/billing")

billing_webhook_router = WebhookRouter()
app.include_router(billing_webhook_router.get_router(), prefix="/api/v1/billing")

webhooks_router = WebhooksRouter()
app.include_router(webhooks_router.get_router(), prefix="/api/v1")

health_deep_router = HealthDeepRouter()
app.include_router(health_deep_router.get_router(), prefix="/api/v1")

ops_router = OpsRouter()
app.include_router(ops_router.get_router())


@app.get("/", tags=["root"])
async def root():
    return {
        "message": "Receipt API",
        "docs": "/api/docs",
        "health": "/health",
    }


@app.get("/metrics", tags=["ops"])
async def metrics() -> Response:
    return Response(
        content=render_prometheus(),
        media_type=CONTENT_TYPE_LATEST,
    )
