"""Receipt-local billing helpers (plan caps, paywall URL builder).

Upstream billing routers live at `apps.api.api.routers.billing` (checkout +
webhook). This subpackage hosts the receipt-side helpers that those routers
and the events ingester share — keeping the canonical plan-cap mapping out
of both modules so there is one source of truth.
"""
