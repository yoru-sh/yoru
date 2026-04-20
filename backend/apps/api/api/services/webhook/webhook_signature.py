"""
Helpers pour signatures HMAC des webhooks.

Respect des règles :
- python.security.mdc : HMAC pour sécurité, compare_digest pour timing-safe
- python.typing.mdc : Type hints complets
"""

import hashlib
import hmac
import json
import secrets


def generate_webhook_secret(length: int = 32) -> str:
    """
    Générer un secret HMAC sécurisé pour webhook.

    Args:
        length: Longueur du secret en bytes (défaut 32 = 256 bits)

    Returns:
        Secret hexadécimal de longueur 2*length caractères
    """
    return secrets.token_hex(length)


def generate_webhook_signature(payload: dict, secret: str) -> str:
    """
    Générer signature HMAC-SHA256 pour payload webhook.

    Args:
        payload: Dictionnaire à signer (sera sérialisé en JSON)
        secret: Secret HMAC du webhook

    Returns:
        Signature au format "sha256={hex_signature}"

    Example:
        >>> payload = {"event": "user.created", "data": {"id": "123"}}
        >>> secret = "whsec_abc123"
        >>> signature = generate_webhook_signature(payload, secret)
        >>> # signature = "sha256=a1b2c3..."
    """
    # Sérialisation déterministe avec clés triées
    payload_str = json.dumps(payload, sort_keys=True, separators=(",", ":"))

    signature = hmac.new(
        secret.encode("utf-8"),
        payload_str.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return f"sha256={signature}"


def verify_webhook_signature(payload: dict, signature: str, secret: str) -> bool:
    """
    Vérifier signature webhook reçue (timing-safe).

    Args:
        payload: Payload reçu (dictionnaire)
        signature: Signature reçue (format "sha256={hex}")
        secret: Secret HMAC attendu

    Returns:
        True si signature valide, False sinon

    Note:
        Utilise hmac.compare_digest pour éviter les timing attacks.

    Example:
        >>> payload = {"event": "user.created", "data": {"id": "123"}}
        >>> signature = "sha256=a1b2c3..."
        >>> secret = "whsec_abc123"
        >>> is_valid = verify_webhook_signature(payload, signature, secret)
    """
    expected = generate_webhook_signature(payload, secret)
    return hmac.compare_digest(expected, signature)


def get_signature_header_name() -> str:
    """
    Retourne le nom du header HTTP pour la signature webhook.

    Returns:
        Nom du header standard utilisé
    """
    return "X-Webhook-Signature"
