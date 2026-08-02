"""Orchestration and domain logic: resume tailoring, job matching, application workflow.

No framework imports (FastAPI/Telegram) leak into this layer. Implemented across
Phases 2 and 4.
"""

from __future__ import annotations

from cinch.services.discovery import (
    DiscoveryService,
    DiscoverySummary,
    JobNotifier,
    query_from_resume,
)
from cinch.services.grounding import GroundingCheck, GroundingValidator
from cinch.services.tailoring import TailoringError, TailoringService
from cinch.services.workflow import ApprovalDecision, ApprovalService, DecisionOutcome

__all__ = [
    "ApprovalDecision",
    "ApprovalService",
    "DecisionOutcome",
    "DiscoveryService",
    "DiscoverySummary",
    "GroundingCheck",
    "GroundingValidator",
    "JobNotifier",
    "TailoringError",
    "TailoringService",
    "query_from_resume",
]
