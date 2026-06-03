"""Agentic AI system that designs and builds end-to-end software solutions.

Five specialized architect agents (Solution, Data, Security, Observability,
Cloud) design the system; an engineering crew (Tech Lead, Backend, Frontend,
QA) then builds a runnable end-to-end repository from that design.
"""

from architects.agents import AGENTS, ARCHITECTS, ENGINEERS, Architect
from architects.codegen import BuildPlan, GeneratedFile
from architects.orchestrator import (
    ArchitectureReview,
    GeneratedSolution,
    RunResult,
    run_pipeline,
    run_review,
)

__all__ = [
    "AGENTS",
    "ARCHITECTS",
    "ENGINEERS",
    "Architect",
    "ArchitectureReview",
    "BuildPlan",
    "GeneratedFile",
    "GeneratedSolution",
    "RunResult",
    "run_pipeline",
    "run_review",
]

__version__ = "0.2.0"
