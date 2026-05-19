"""Framework-provided agents."""

from pathlib import Path

FRAMEWORK_AGENTS_DIR = Path(__file__).parent


def list_framework_agents() -> list[Path]:
    """List all framework agent directories."""
    return sorted(
        [p for p in FRAMEWORK_AGENTS_DIR.iterdir() if p.is_dir() and (p / "agent.py").exists()],
        key=lambda p: p.name,
    )
