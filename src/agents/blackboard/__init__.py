"""Compatibility exports for moved pipeline Blackboard storage."""

import sys

from bussiness_logic.pipeline.blackboard import store
from bussiness_logic.pipeline.blackboard.store import BlackboardStore, now_iso

sys.modules[__name__ + ".store"] = store

__all__ = ["BlackboardStore", "now_iso"]
