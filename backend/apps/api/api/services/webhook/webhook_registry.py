"""
Registre extensible pour événements webhooks.

Design extensible : Les devs backend peuvent ajouter leurs propres événements facilement.

Respect des règles :
- python.typing.mdc : Type hints, Callable pour payload builders
- python.state.mdc : @lru_cache pour singleton registry
- se.evolution.mdc : Design extensible, pas de breaking changes
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Callable


# Type pour payload builders
PayloadBuilder = Callable[[str, dict[str, Any]], dict[str, Any]]


class WebhookEventRegistry:
    """
    Registre extensible pour événements webhooks et leurs payload builders.

    Usage par les devs :
        from apps.api.api.services.webhook.webhook_registry import webhook_registry

        def build_custom_payload(event_name: str, data: dict) -> dict:
            return {
                "event": event_name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": {
                    "id": str(data["id"]),
                    "custom_field": data["custom_field"],
                }
            }

        webhook_registry.register("my_custom.event", build_custom_payload)
    """

    def __init__(self) -> None:
        self._builders: dict[str, PayloadBuilder] = {}
        self._register_default_events()

    def _register_default_events(self) -> None:
        """Enregistrer événements standards fournis par le template."""
        # User events
        self.register("user.created", self._build_user_payload)
        self.register("user.updated", self._build_user_payload)
        self.register("user.deleted", self._build_user_payload)

        # Payment events
        self.register("payment.succeeded", self._build_payment_payload)
        self.register("payment.failed", self._build_payment_payload)
        self.register("payment.refunded", self._build_payment_payload)

        # Subscription events
        self.register("subscription.created", self._build_subscription_payload)
        self.register("subscription.updated", self._build_subscription_payload)
        self.register("subscription.cancelled", self._build_subscription_payload)

        # Generic entity events (catch-all)
        self.register("entity.created", self._build_generic_payload)
        self.register("entity.updated", self._build_generic_payload)
        self.register("entity.deleted", self._build_generic_payload)

    def register(self, event_name: str, payload_builder: PayloadBuilder) -> None:
        """
        Enregistrer un nouvel événement webhook.

        Args:
            event_name: Nom de l'événement (ex: "order.shipped")
            payload_builder: Fonction pour construire le payload

        Example:
            webhook_registry.register("order.shipped", build_order_payload)
        """
        self._builders[event_name] = payload_builder

    def unregister(self, event_name: str) -> bool:
        """
        Désinscrire un événement webhook.

        Args:
            event_name: Nom de l'événement à désinscrire

        Returns:
            True si l'événement était enregistré, False sinon
        """
        if event_name in self._builders:
            del self._builders[event_name]
            return True
        return False

    def is_registered(self, event_name: str) -> bool:
        """
        Vérifier si un événement est enregistré.

        Args:
            event_name: Nom de l'événement

        Returns:
            True si l'événement est enregistré
        """
        return event_name in self._builders

    def build_payload(self, event_name: str, data: dict[str, Any]) -> dict[str, Any]:
        """
        Construire payload pour un événement.

        Si événement non enregistré, utilise format générique.

        Args:
            event_name: Nom de l'événement
            data: Données de l'événement

        Returns:
            Payload formaté pour le webhook
        """
        builder = self._builders.get(event_name, self._build_generic_payload)
        return builder(event_name, data)

    def list_events(self) -> list[str]:
        """
        Liste tous les événements enregistrés.

        Returns:
            Liste triée des noms d'événements
        """
        return sorted(self._builders.keys())

    def _build_generic_payload(
        self, event_name: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Format générique si événement non enregistré."""
        return {
            "event": event_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }

    def _build_user_payload(
        self, event_name: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Builder pour événements user.*"""
        return {
            "event": event_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {
                "id": str(data.get("id", "")),
                "email": data.get("email"),
                "name": data.get("name"),
                "created_at": (
                    data["created_at"].isoformat()
                    if isinstance(data.get("created_at"), datetime)
                    else data.get("created_at")
                ),
            },
        }

    def _build_payment_payload(
        self, event_name: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Builder pour événements payment.*"""
        return {
            "event": event_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {
                "id": str(data.get("id", "")),
                "amount": float(data.get("amount", 0)),
                "currency": data.get("currency", "USD"),
                "user_id": str(data.get("user_id", "")),
                "status": data.get("status"),
                "provider_id": data.get("provider_id"),
            },
        }

    def _build_subscription_payload(
        self, event_name: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Builder pour événements subscription.*"""
        return {
            "event": event_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {
                "id": str(data.get("id", "")),
                "user_id": str(data.get("user_id", "")),
                "plan_id": str(data.get("plan_id", "")),
                "status": data.get("status"),
                "current_period_start": data.get("current_period_start"),
                "current_period_end": data.get("current_period_end"),
            },
        }


@lru_cache(maxsize=1)
def get_webhook_registry() -> WebhookEventRegistry:
    """
    Obtenir l'instance singleton du registre webhook.

    Returns:
        Instance unique du WebhookEventRegistry
    """
    return WebhookEventRegistry()


# Alias pour usage simplifié
webhook_registry = get_webhook_registry()
