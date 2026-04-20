from typing import Dict
from fastapi import APIRouter
from pydantic import BaseModel

from libs.log_manager.controller import LoggingController


class PingResponse(BaseModel):
    """Response model for ping endpoint"""

    message: str
    status: str


class PingRouter:
    """Simple router for ping/pong testing"""

    def __init__(self):
        """Initialize PingRouter"""
        self.logger = LoggingController(app_name="ping_router")
        self.router = APIRouter(prefix="/api", tags=["ping"])

        # Setup routes
        self._setup_routes()
        self.logger.log_info("Ping router initialized")

    def get_router(self) -> APIRouter:
        """Get the FastAPI router"""
        return self.router

    def initialize_services(self):
        """Initialize required services (none needed for ping)"""
        pass

    def _setup_routes(self):
        """Set up ping route"""
        self.router.get("/ping", response_model=PingResponse)(self.ping)
        self.logger.log_debug("Ping route configured")

    async def ping(self) -> PingResponse:
        """
        Simple ping endpoint that returns pong

        Returns:
            PingResponse with "pong" message
        """
        self.logger.log_debug("Ping request received")

        return PingResponse(message="pong", status="ok")
