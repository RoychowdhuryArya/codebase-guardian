"""
Archwarden — Configuration & Environment
All env vars, model IDs, and startup validation.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import Optional

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass


@dataclass
class Config:
    # ── NVIDIA NIM ─────────────────────────────────────────────────────────────
    nvidia_api_key: str = field(default_factory=lambda: os.getenv("NVIDIA_API_KEY", ""))
    nvidia_api_base: str = field(
        default_factory=lambda: os.getenv("NVIDIA_API_BASE", "https://integrate.api.nvidia.com/v1")
    )

    # ── Model IDs (defaults — verified against live model list at startup) ─────
    model_nano: str = field(
        default_factory=lambda: os.getenv("ARCHWARDEN_NANO", "nvidia/nemotron-nano-8b-instruct")
    )
    model_super: str = field(
        default_factory=lambda: os.getenv("ARCHWARDEN_SUPER", "nvidia/nemotron-super-49b-v1")
    )
    model_ultra: str = field(
        default_factory=lambda: os.getenv("ARCHWARDEN_ULTRA", "nvidia/nemotron-4-340b-instruct")
    )

    # ── FalkorDB ────────────────────────────────────────────────────────────────
    falkordb_host: str = field(default_factory=lambda: os.getenv("FALKORDB_HOST", "localhost"))
    falkordb_port: int = field(default_factory=lambda: int(os.getenv("FALKORDB_PORT", "6379")))
    falkordb_password: str = field(default_factory=lambda: os.getenv("FALKORDB_PASSWORD", ""))
    graph_engine: str = field(default_factory=lambda: os.getenv("ARCHWARDEN_GRAPH", "falkor"))

    # ── Archwarden tuning ───────────────────────────────────────────────────────
    k_hops: int = field(default_factory=lambda: int(os.getenv("ARCHWARDEN_K_HOPS", "2")))
    max_prompt_tokens: int = field(
        default_factory=lambda: int(os.getenv("ARCHWARDEN_MAX_PROMPT_TOKENS", "12000"))
    )
    max_depth: int = field(default_factory=lambda: int(os.getenv("ARCHWARDEN_MAX_DEPTH", "3")))
    live: bool = field(default_factory=lambda: os.getenv("ARCHWARDEN_LIVE", "0") == "1")

    # ── Tavily ─────────────────────────────────────────────────────────────────
    tavily_api_key: Optional[str] = field(
        default_factory=lambda: os.getenv("TAVILY_API_KEY") or None
    )

    def validate(self) -> list[str]:
        """Return a list of warnings (non-fatal) for missing optional config."""
        warnings: list[str] = []
        if not self.nvidia_api_key:
            warnings.append(
                "NVIDIA_API_KEY not set — LLM features disabled. "
                "Get a free key at https://build.nvidia.com"
            )
        if self.graph_engine not in ("falkor", "memory"):
            warnings.append(
                f"ARCHWARDEN_GRAPH={self.graph_engine!r} is invalid; defaulting to 'falkor'"
            )
            self.graph_engine = "falkor"
        return warnings


# Singleton
settings = Config()
