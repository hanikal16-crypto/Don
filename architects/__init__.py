"""Agentic AI architecture-design system.

Five specialized architect agents — Solution, Data, Security, Observability,
and Cloud — collaborate to turn a project brief into a complete architecture.
"""

from architects.agents import ARCHITECTS, Architect
from architects.orchestrator import ArchitectureReview, run_review

__all__ = ["ARCHITECTS", "Architect", "ArchitectureReview", "run_review"]

__version__ = "0.1.0"
