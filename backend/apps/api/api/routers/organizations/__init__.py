"""Organizations router for multi-tenancy system."""

from apps.api.api.routers.organizations.router import (
    InvitationsPublicRouter,
    OrganizationsRouter,
)

__all__ = ["InvitationsPublicRouter", "OrganizationsRouter"]
