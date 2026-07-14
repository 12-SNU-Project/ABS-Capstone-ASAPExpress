"""Compatibility exports for moved product LLM services."""

import sys

from bussiness_logic.product.services import identity_hint_agent
from bussiness_logic.product.services.identity_hint_agent import IdentityHintAgent

sys.modules[__name__ + ".identity_hint_agent"] = identity_hint_agent

__all__ = ["IdentityHintAgent"]
