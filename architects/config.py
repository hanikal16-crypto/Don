"""Shared configuration and client construction."""

from __future__ import annotations

import os
from dataclasses import dataclass

from anthropic import AsyncAnthropic

try:
    from dotenv import load_dotenv

    load_dotenv()
except ModuleNotFoundError:  # dotenv is optional at runtime
    pass


# Default to the most capable Claude model. Override via ARCHITECT_MODEL.
DEFAULT_MODEL = "claude-opus-4-8"

# Effort controls how deeply each agent thinks. high is the sweet spot for
# design work; bump to xhigh/max for harder briefs. Override via ARCHITECT_EFFORT.
DEFAULT_EFFORT = "high"

# Generous ceiling — architecture write-ups are long. Streaming keeps us under
# the SDK's HTTP timeout at this size.
MAX_TOKENS = 32_000


@dataclass(frozen=True)
class Settings:
    """Runtime configuration resolved from the environment."""

    model: str = os.getenv("ARCHITECT_MODEL", DEFAULT_MODEL)
    effort: str = os.getenv("ARCHITECT_EFFORT", DEFAULT_EFFORT)
    max_tokens: int = MAX_TOKENS

    def validate(self) -> None:
        if not os.getenv("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add "
                "your key, or export ANTHROPIC_API_KEY in your shell."
            )
        allowed = {"low", "medium", "high", "xhigh", "max"}
        if self.effort not in allowed:
            raise RuntimeError(
                f"ARCHITECT_EFFORT={self.effort!r} is invalid; "
                f"choose one of {sorted(allowed)}."
            )


def build_client() -> AsyncAnthropic:
    """Construct the async Claude client (reads ANTHROPIC_API_KEY from env)."""
    return AsyncAnthropic()
