"""Unit tests for webhook signature helpers."""

from __future__ import annotations

import pytest

from apps.api.api.services.webhook.webhook_signature import (
    generate_webhook_secret,
    generate_webhook_signature,
    verify_webhook_signature,
    get_signature_header_name,
)


class TestGenerateWebhookSecret:
    """Tests for secret generation."""

    def test_default_length(self):
        """Test default secret length."""
        secret = generate_webhook_secret()
        # Default 32 bytes = 64 hex characters
        assert len(secret) == 64

    def test_custom_length(self):
        """Test custom secret length."""
        secret = generate_webhook_secret(length=16)
        # 16 bytes = 32 hex characters
        assert len(secret) == 32

    def test_secrets_are_unique(self):
        """Test that secrets are unique."""
        secrets = [generate_webhook_secret() for _ in range(100)]
        assert len(set(secrets)) == 100  # All unique

    def test_secret_is_hex(self):
        """Test that secret is valid hex."""
        secret = generate_webhook_secret()
        # Should not raise ValueError
        int(secret, 16)


class TestGenerateWebhookSignature:
    """Tests for signature generation."""

    def test_basic_signature(self):
        """Test basic signature generation."""
        payload = {"event": "test", "data": {"id": "123"}}
        secret = "test_secret"

        signature = generate_webhook_signature(payload, secret)

        assert signature.startswith("sha256=")
        assert len(signature) > 7  # "sha256=" + at least 1 char

    def test_deterministic_signature(self):
        """Test that same input produces same signature."""
        payload = {"event": "test", "data": {"id": "123"}}
        secret = "test_secret"

        sig1 = generate_webhook_signature(payload, secret)
        sig2 = generate_webhook_signature(payload, secret)

        assert sig1 == sig2

    def test_different_payload_different_signature(self):
        """Test that different payloads produce different signatures."""
        payload1 = {"event": "test", "data": {"id": "123"}}
        payload2 = {"event": "test", "data": {"id": "456"}}
        secret = "test_secret"

        sig1 = generate_webhook_signature(payload1, secret)
        sig2 = generate_webhook_signature(payload2, secret)

        assert sig1 != sig2

    def test_different_secret_different_signature(self):
        """Test that different secrets produce different signatures."""
        payload = {"event": "test", "data": {"id": "123"}}

        sig1 = generate_webhook_signature(payload, "secret1")
        sig2 = generate_webhook_signature(payload, "secret2")

        assert sig1 != sig2

    def test_key_order_doesnt_matter(self):
        """Test that dict key order doesn't affect signature."""
        payload1 = {"a": 1, "b": 2}
        payload2 = {"b": 2, "a": 1}
        secret = "test_secret"

        sig1 = generate_webhook_signature(payload1, secret)
        sig2 = generate_webhook_signature(payload2, secret)

        assert sig1 == sig2  # Sort_keys ensures deterministic order


class TestVerifyWebhookSignature:
    """Tests for signature verification."""

    def test_valid_signature(self):
        """Test verification of valid signature."""
        payload = {"event": "test", "data": {"id": "123"}}
        secret = "test_secret"

        signature = generate_webhook_signature(payload, secret)
        is_valid = verify_webhook_signature(payload, signature, secret)

        assert is_valid is True

    def test_invalid_signature(self):
        """Test verification of invalid signature."""
        payload = {"event": "test", "data": {"id": "123"}}
        secret = "test_secret"

        is_valid = verify_webhook_signature(payload, "sha256=invalid", secret)

        assert is_valid is False

    def test_wrong_secret(self):
        """Test verification with wrong secret."""
        payload = {"event": "test", "data": {"id": "123"}}

        signature = generate_webhook_signature(payload, "correct_secret")
        is_valid = verify_webhook_signature(payload, signature, "wrong_secret")

        assert is_valid is False

    def test_tampered_payload(self):
        """Test verification with tampered payload."""
        original_payload = {"event": "test", "data": {"id": "123"}}
        tampered_payload = {"event": "test", "data": {"id": "456"}}
        secret = "test_secret"

        signature = generate_webhook_signature(original_payload, secret)
        is_valid = verify_webhook_signature(tampered_payload, signature, secret)

        assert is_valid is False


class TestGetSignatureHeaderName:
    """Tests for header name helper."""

    def test_header_name(self):
        """Test signature header name."""
        header_name = get_signature_header_name()
        assert header_name == "X-Webhook-Signature"
