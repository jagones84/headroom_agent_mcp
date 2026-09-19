import pytest
from pydantic import ValidationError

from headroom_agent_mcp.models import CommandAllowlistProfile, DiscoveryRequest, ObjectiveType


def test_request_rejects_blank_objective() -> None:
    with pytest.raises(ValidationError):
        DiscoveryRequest(
            objective="   ",
            objective_type=ObjectiveType.CODEBASE_DISCOVERY,
            command_allowlist_profile=CommandAllowlistProfile.SAFE_READONLY,
        )


def test_request_rejects_unknown_objective_type() -> None:
    with pytest.raises(ValidationError):
        DiscoveryRequest(
            objective="find auth flow",
            objective_type="bad-type",
            command_allowlist_profile=CommandAllowlistProfile.SAFE_READONLY,
        )


def test_request_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        DiscoveryRequest(
            objective="find auth flow",
            objective_type=ObjectiveType.CODEBASE_DISCOVERY,
            command_allowlist_profile=CommandAllowlistProfile.SAFE_READONLY,
            unexpected=True,
        )
