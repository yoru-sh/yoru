"""Unit tests for WebhookEventRegistry."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from apps.api.api.services.webhook.webhook_registry import (
    WebhookEventRegistry,
    get_webhook_registry,
)


@pytest.fixture
def fresh_registry():
    """Create a fresh registry instance for testing."""
    return WebhookEventRegistry()


class TestWebhookEventRegistry:
    """Tests for WebhookEventRegistry."""

    def test_default_events_registered(self, fresh_registry):
        """Test that default events are registered."""
        events = fresh_registry.list_events()

        # Check some standard events are present
        assert "user.created" in events
        assert "user.updated" in events
        assert "payment.succeeded" in events
        assert "payment.failed" in events
        assert "subscription.created" in events

    def test_register_custom_event(self, fresh_registry):
        """Test registering a custom event."""

        def custom_builder(event_name: str, data: dict) -> dict:
            return {
                "event": event_name,
                "custom": True,
                "data": data,
            }

        fresh_registry.register("custom.event", custom_builder)

        assert fresh_registry.is_registered("custom.event")
        assert "custom.event" in fresh_registry.list_events()

    def test_unregister_event(self, fresh_registry):
        """Test unregistering an event."""
        # Register then unregister
        fresh_registry.register("temp.event", lambda e, d: {})

        result = fresh_registry.unregister("temp.event")

        assert result is True
        assert not fresh_registry.is_registered("temp.event")

    def test_unregister_nonexistent_event(self, fresh_registry):
        """Test unregistering a non-existent event."""
        result = fresh_registry.unregister("nonexistent.event")
        assert result is False

    def test_is_registered(self, fresh_registry):
        """Test is_registered method."""
        assert fresh_registry.is_registered("user.created") is True
        assert fresh_registry.is_registered("nonexistent.event") is False

    def test_list_events_sorted(self, fresh_registry):
        """Test that list_events returns sorted list."""
        events = fresh_registry.list_events()
        assert events == sorted(events)


class TestPayloadBuilders:
    """Tests for payload builder methods."""

    def test_build_user_payload(self, fresh_registry):
        """Test user payload builder."""
        data = {
            "id": "user-123",
            "email": "test@example.com",
            "name": "Test User",
            "created_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
        }

        payload = fresh_registry.build_payload("user.created", data)

        assert payload["event"] == "user.created"
        assert "timestamp" in payload
        assert payload["data"]["id"] == "user-123"
        assert payload["data"]["email"] == "test@example.com"
        assert payload["data"]["name"] == "Test User"

    def test_build_payment_payload(self, fresh_registry):
        """Test payment payload builder."""
        data = {
            "id": "payment-123",
            "amount": 99.99,
            "currency": "EUR",
            "user_id": "user-456",
            "status": "succeeded",
        }

        payload = fresh_registry.build_payload("payment.succeeded", data)

        assert payload["event"] == "payment.succeeded"
        assert "timestamp" in payload
        assert payload["data"]["id"] == "payment-123"
        assert payload["data"]["amount"] == 99.99
        assert payload["data"]["currency"] == "EUR"

    def test_build_subscription_payload(self, fresh_registry):
        """Test subscription payload builder."""
        data = {
            "id": "sub-123",
            "user_id": "user-456",
            "plan_id": "plan-789",
            "status": "active",
        }

        payload = fresh_registry.build_payload("subscription.created", data)

        assert payload["event"] == "subscription.created"
        assert "timestamp" in payload
        assert payload["data"]["id"] == "sub-123"
        assert payload["data"]["user_id"] == "user-456"

    def test_build_generic_payload_for_unknown_event(self, fresh_registry):
        """Test generic payload for unregistered event."""
        data = {"custom_field": "value"}

        payload = fresh_registry.build_payload("unknown.event", data)

        assert payload["event"] == "unknown.event"
        assert "timestamp" in payload
        assert payload["data"] == data

    def test_custom_builder_overrides_default(self, fresh_registry):
        """Test that custom builder overrides default."""

        def custom_user_builder(event_name: str, data: dict) -> dict:
            return {
                "event": event_name,
                "custom": True,
                "user_data": data,
            }

        # Override default user.created builder
        fresh_registry.register("user.created", custom_user_builder)

        payload = fresh_registry.build_payload("user.created", {"id": "123"})

        assert payload["custom"] is True
        assert "user_data" in payload


class TestGetWebhookRegistry:
    """Tests for singleton pattern."""

    def test_singleton_returns_same_instance(self):
        """Test that get_webhook_registry returns singleton."""
        # Clear cache first
        get_webhook_registry.cache_clear()

        registry1 = get_webhook_registry()
        registry2 = get_webhook_registry()

        assert registry1 is registry2
