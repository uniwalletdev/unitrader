"""
src/security/ — Security infrastructure (Phase 12+).

Submodules:
  • egress       — outbound HTTP choke point + allowlist + approval workflow
"""
from src.security.egress import (
    ApprovalRequiredError,
    EgressGateway,
    egress_request,
    get_egress_gateway,
)

__all__ = [
    "ApprovalRequiredError",
    "EgressGateway",
    "egress_request",
    "get_egress_gateway",
]
