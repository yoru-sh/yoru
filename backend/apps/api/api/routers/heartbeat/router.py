"""
Router pour le système heartbeat (keep-alive).

Les utilisateurs authentifiés doivent appeler POST /heartbeat/ping
toutes les 15 minutes pour maintenir leur session active.

Après 4 pings manqués (1 heure d'inactivité), la session est invalidée.

Respect des règles :
- api.routes.mdc : Router class avec prefix
- api.authentication.mdc : Depends(get_current_user_id) pour auth
- api.contracts.mdc : Status codes, response_model
- python.async.mdc : Tous endpoints async
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from libs.log_manager.controller import LoggingController
from apps.api.api.dependencies.auth import (
    get_correlation_id,
    get_current_user_id,
    get_current_user_token,
)
from apps.api.api.services.heartbeat.heartbeat_service import HeartbeatService


class HeartbeatPingResponse(BaseModel):
    """Réponse du ping heartbeat."""

    status: str = Field(..., description="Status du ping (ok)")
    last_ping_at: str = Field(..., description="Timestamp du dernier ping (ISO 8601)")
    next_ping_deadline: str = Field(
        ..., description="Deadline pour le prochain ping (ISO 8601)"
    )
    disconnect_deadline: str = Field(
        ..., description="Date de déconnexion si aucun ping (ISO 8601)"
    )
    ping_interval_seconds: int = Field(
        ..., description="Intervalle recommandé entre les pings (secondes)"
    )
    max_missed_pings: int = Field(
        ..., description="Nombre max de pings manqués avant déconnexion"
    )


class HeartbeatStatusResponse(BaseModel):
    """Statut du heartbeat utilisateur."""

    user_id: str
    last_ping_at: str
    elapsed_seconds: float = Field(..., description="Secondes depuis le dernier ping")
    missed_pings: int = Field(..., description="Nombre de pings manqués")
    is_active: bool = Field(..., description="User considéré actif")
    should_disconnect: bool = Field(..., description="Doit être déconnecté")


class HeartbeatRouter:
    """Router pour le système heartbeat."""

    def __init__(self):
        self.logger = LoggingController(app_name="HeartbeatRouter")
        self.router = APIRouter(prefix="/heartbeat", tags=["heartbeat"])
        self._setup_routes()

    def initialize_services(self) -> None:
        """Initialize required services - not used as services are created per-request."""
        pass

    def get_router(self) -> APIRouter:
        """Get the FastAPI router."""
        return self.router

    def _setup_routes(self) -> None:
        """Set up heartbeat routes."""
        self.router.post("/ping", response_model=HeartbeatPingResponse)(self.ping)
        self.router.get("/status", response_model=HeartbeatStatusResponse | None)(
            self.get_status
        )

    async def ping(
        self,
        user_id: UUID = Depends(get_current_user_id),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ) -> HeartbeatPingResponse:
        """
        Enregistrer un heartbeat (ping) pour maintenir la session active.

        **Important:** Appelez cet endpoint toutes les 15 minutes pour éviter
        la déconnexion automatique.

        **Timing:**
        - Intervalle recommandé: 15 minutes (900 secondes)
        - Déconnexion après: 4 pings manqués (1 heure)

        **Workflow client:**
        1. Appeler `/heartbeat/ping` immédiatement après login
        2. Répéter l'appel toutes les 15 minutes
        3. Utiliser `next_ping_deadline` pour planifier le prochain appel

        **Returns:**
        - **status**: "ok" si ping enregistré
        - **last_ping_at**: Timestamp du ping
        - **next_ping_deadline**: Deadline pour le prochain ping
        - **disconnect_deadline**: Date de déconnexion si inactif
        """
        context = {
            "operation": "ping",
            "component": "HeartbeatRouter",
            "correlation_id": correlation_id,
            "user_id": str(user_id),
        }
        self.logger.log_debug("Heartbeat ping received", context)

        service = HeartbeatService(access_token=token)
        result = await service.record_ping(
            user_id=user_id,
            correlation_id=correlation_id,
        )

        return HeartbeatPingResponse(**result)

    async def get_status(
        self,
        user_id: UUID = Depends(get_current_user_id),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ) -> HeartbeatStatusResponse | None:
        """
        Récupérer le statut heartbeat de l'utilisateur courant.

        **Returns:**
        - Statut du heartbeat avec informations de timing
        - `null` si aucun heartbeat enregistré

        **Champs retournés:**
        - **elapsed_seconds**: Temps écoulé depuis le dernier ping
        - **missed_pings**: Nombre de pings manqués
        - **is_active**: `true` si l'utilisateur est considéré actif
        - **should_disconnect**: `true` si la limite est atteinte
        """
        service = HeartbeatService(access_token=token)
        result = await service.get_heartbeat_status(
            user_id=user_id,
            correlation_id=correlation_id,
        )

        if not result:
            return None

        return HeartbeatStatusResponse(**result)
