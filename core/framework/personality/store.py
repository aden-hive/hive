"""
PersonalityStore - File-based storage for Agent Personality DNA.

Provides a persistent storage layer for APDNA with:
- CRUD operations for DNA records
- Versioning and parent-chain tracking
- Atomic writes for safety
- Index by agent_id for quick lookup

Storage Structure:
{base_path}/
  dna/
    {agent_id}/
      current.json         # Current DNA for this agent
      history/
        {dna_id}.json      # Historical DNA versions
  signals/
    {agent_id}/
      {session_id}.json    # Extracted signals per session
  index/
    by_agent.json          # agent_id -> current dna_id mapping
"""

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

from framework.personality.dna import (
    AgentPersonalityDNA,
    DNADiff,
    DNAMutation,
    PersonalitySignal,
)
from framework.utils.io import atomic_write

logger = logging.getLogger(__name__)


class PersonalityStore(ABC):
    """Abstract base class for DNA storage."""

    @abstractmethod
    def save_dna(self, dna: AgentPersonalityDNA) -> None:
        """Save DNA to storage."""
        pass

    @abstractmethod
    def load_dna(self, agent_id: str) -> AgentPersonalityDNA | None:
        """Load current DNA for an agent."""
        pass

    @abstractmethod
    def load_dna_by_id(self, agent_id: str, dna_id: str) -> AgentPersonalityDNA | None:
        """Load a specific DNA version by ID."""
        pass

    @abstractmethod
    def delete_dna(self, agent_id: str) -> bool:
        """Delete DNA for an agent."""
        pass

    @abstractmethod
    def list_agents(self) -> list[str]:
        """List all agent IDs with DNA records."""
        pass

    @abstractmethod
    def save_signals(self, signals: list[PersonalitySignal]) -> None:
        """Save extracted signals for later synthesis."""
        pass

    @abstractmethod
    def load_signals(self, agent_id: str, session_id: str | None = None) -> list[PersonalitySignal]:
        """Load signals for an agent, optionally filtered by session."""
        pass

    @abstractmethod
    def get_dna_history(self, agent_id: str, limit: int = 10) -> list[AgentPersonalityDNA]:
        """Get historical DNA versions for an agent."""
        pass

    @abstractmethod
    def diff_dna(self, agent_id: str, from_dna_id: str, to_dna_id: str) -> DNADiff:
        """Compare two DNA versions."""
        pass


class FilePersonalityStore(PersonalityStore):
    """
    File-based implementation of PersonalityStore.

    Stores DNA and signals as JSON files with atomic writes.
    Provides versioning and history tracking.

    Example:
        store = FilePersonalityStore(Path.home() / ".hive" / "personality")

        dna = AgentPersonalityDNA(agent_id="support-agent")
        store.save_dna(dna)

        loaded = store.load_dna("support-agent")
    """

    def __init__(self, base_path: Path):
        self.base_path = Path(base_path)
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        """Create directory structure if it doesn't exist."""
        (self.base_path / "dna").mkdir(parents=True, exist_ok=True)
        (self.base_path / "signals").mkdir(parents=True, exist_ok=True)
        (self.base_path / "index").mkdir(parents=True, exist_ok=True)

    def _validate_agent_id(self, agent_id: str) -> None:
        """Validate agent_id to prevent path traversal."""
        if not agent_id or agent_id.strip() == "":
            raise ValueError("agent_id cannot be empty")

        if "/" in agent_id or "\\" in agent_id:
            raise ValueError(f"Invalid agent_id: path separators not allowed in '{agent_id}'")

        if ".." in agent_id or agent_id.startswith("."):
            raise ValueError(f"Invalid agent_id: path traversal detected in '{agent_id}'")

    def _dna_path(self, agent_id: str) -> Path:
        """Get path to current DNA file for an agent."""
        self._validate_agent_id(agent_id)
        return self.base_path / "dna" / agent_id / "current.json"

    def _history_path(self, agent_id: str, dna_id: str) -> Path:
        """Get path to historical DNA file."""
        self._validate_agent_id(agent_id)
        return self.base_path / "dna" / agent_id / "history" / f"{dna_id}.json"

    def _signals_path(self, agent_id: str, session_id: str) -> Path:
        """Get path to signals file for a session."""
        self._validate_agent_id(agent_id)
        return self.base_path / "signals" / agent_id / f"{session_id}.json"

    def _index_path(self) -> Path:
        """Get path to agent index file."""
        return self.base_path / "index" / "by_agent.json"

    def _load_index(self) -> dict[str, str]:
        """Load the agent -> dna_id index."""
        index_path = self._index_path()
        if not index_path.exists():
            return {}
        try:
            with open(index_path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load DNA index: {e}")
            return {}

    def _save_index(self, index: dict[str, str]) -> None:
        """Save the agent -> dna_id index."""
        index_path = self._index_path()
        with atomic_write(index_path) as f:
            json.dump(index, f, indent=2)

    def save_dna(self, dna: AgentPersonalityDNA) -> None:
        """Save DNA to storage, updating current and archiving previous."""
        agent_id = dna.agent_id
        agent_dir = self.base_path / "dna" / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)

        history_dir = agent_dir / "history"
        history_dir.mkdir(parents=True, exist_ok=True)

        current_path = self._dna_path(agent_id)

        if current_path.exists():
            with open(current_path, encoding="utf-8") as f:
                old_data = json.load(f)
            old_dna_id = old_data.get("dna_id", "unknown")
            old_dna_path = self._history_path(agent_id, old_dna_id)

            if not old_dna_path.exists():
                with atomic_write(old_dna_path) as f:
                    json.dump(old_data, f, indent=2, default=str)

        dna_data = dna.model_dump(mode="json")
        with atomic_write(current_path) as f:
            json.dump(dna_data, f, indent=2, default=str)

        index = self._load_index()
        index[agent_id] = dna.dna_id
        self._save_index(index)

        logger.info(f"Saved DNA {dna.dna_id} for agent {agent_id}")

    def load_dna(self, agent_id: str) -> AgentPersonalityDNA | None:
        """Load current DNA for an agent."""
        dna_path = self._dna_path(agent_id)
        if not dna_path.exists():
            return None

        try:
            with open(dna_path, encoding="utf-8") as f:
                data = json.load(f)
            return AgentPersonalityDNA.model_validate(data)
        except (json.JSONDecodeError, OSError, ValueError) as e:
            logger.error(f"Failed to load DNA for {agent_id}: {e}")
            return None

    def load_dna_by_id(self, agent_id: str, dna_id: str) -> AgentPersonalityDNA | None:
        """Load a specific DNA version by ID."""
        history_path = self._history_path(agent_id, dna_id)
        if not history_path.exists():
            current = self.load_dna(agent_id)
            if current and current.dna_id == dna_id:
                return current
            return None

        try:
            with open(history_path, encoding="utf-8") as f:
                data = json.load(f)
            return AgentPersonalityDNA.model_validate(data)
        except (json.JSONDecodeError, OSError, ValueError) as e:
            logger.error(f"Failed to load DNA {dna_id} for {agent_id}: {e}")
            return None

    def delete_dna(self, agent_id: str) -> bool:
        """Delete DNA for an agent (including history)."""
        agent_dir = self.base_path / "dna" / agent_id
        if not agent_dir.exists():
            return False

        import shutil

        shutil.rmtree(agent_dir)

        index = self._load_index()
        if agent_id in index:
            del index[agent_id]
            self._save_index(index)

        signals_dir = self.base_path / "signals" / agent_id
        if signals_dir.exists():
            shutil.rmtree(signals_dir)

        logger.info(f"Deleted DNA for agent {agent_id}")
        return True

    def list_agents(self) -> list[str]:
        """List all agent IDs with DNA records."""
        dna_dir = self.base_path / "dna"
        if not dna_dir.exists():
            return []
        return [d.name for d in dna_dir.iterdir() if d.is_dir()]

    def save_signals(self, signals: list[PersonalitySignal]) -> None:
        """Save extracted signals for later synthesis."""
        if not signals:
            return

        by_agent: dict[str, list[PersonalitySignal]] = {}
        for signal in signals:
            if signal.agent_id not in by_agent:
                by_agent[signal.agent_id] = []
            by_agent[signal.agent_id].append(signal)

        for agent_id, agent_signals in by_agent.items():
            by_session: dict[str, list[PersonalitySignal]] = {}
            for signal in agent_signals:
                if signal.session_id not in by_session:
                    by_session[signal.session_id] = []
                by_session[signal.session_id].append(signal)

            for session_id, session_signals in by_session.items():
                signals_path = self._signals_path(agent_id, session_id)
                signals_path.parent.mkdir(parents=True, exist_ok=True)

                signals_data = [s.model_dump(mode="json") for s in session_signals]
                with atomic_write(signals_path) as f:
                    json.dump(signals_data, f, indent=2, default=str)

                logger.debug(f"Saved {len(session_signals)} signals for {agent_id}/{session_id}")

    def load_signals(self, agent_id: str, session_id: str | None = None) -> list[PersonalitySignal]:
        """Load signals for an agent, optionally filtered by session."""
        signals_dir = self.base_path / "signals" / agent_id
        if not signals_dir.exists():
            return []

        signals: list[PersonalitySignal] = []

        if session_id:
            signals_path = self._signals_path(agent_id, session_id)
            if signals_path.exists():
                try:
                    with open(signals_path, encoding="utf-8") as f:
                        data = json.load(f)
                    signals.extend(PersonalitySignal.model_validate(s) for s in data)
                except (json.JSONDecodeError, OSError, ValueError) as e:
                    logger.error(f"Failed to load signals for {agent_id}/{session_id}: {e}")
        else:
            for signals_file in signals_dir.glob("*.json"):
                try:
                    with open(signals_file, encoding="utf-8") as f:
                        data = json.load(f)
                    signals.extend(PersonalitySignal.model_validate(s) for s in data)
                except (json.JSONDecodeError, OSError, ValueError) as e:
                    logger.error(f"Failed to load signals from {signals_file}: {e}")

        return signals

    def get_dna_history(self, agent_id: str, limit: int = 10) -> list[AgentPersonalityDNA]:
        """Get historical DNA versions for an agent."""
        history_dir = self.base_path / "dna" / agent_id / "history"
        if not history_dir.exists():
            current = self.load_dna(agent_id)
            return [current] if current else []

        dna_versions: list[AgentPersonalityDNA] = []

        for dna_file in sorted(
            history_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
        )[:limit]:
            try:
                with open(dna_file, encoding="utf-8") as f:
                    data = json.load(f)
                dna_versions.append(AgentPersonalityDNA.model_validate(data))
            except (json.JSONDecodeError, OSError, ValueError) as e:
                logger.error(f"Failed to load DNA from {dna_file}: {e}")

        current = self.load_dna(agent_id)
        if current:
            dna_versions.insert(0, current)

        return dna_versions[:limit]

    def diff_dna(self, agent_id: str, from_dna_id: str, to_dna_id: str) -> DNADiff:
        """Compare two DNA versions."""
        from_dna = self.load_dna_by_id(agent_id, from_dna_id)
        to_dna = self.load_dna_by_id(agent_id, to_dna_id)

        if from_dna is None or to_dna is None:
            raise ValueError(f"Could not load DNA versions for diff: {from_dna_id} -> {to_dna_id}")

        diff = DNADiff(
            from_generation=from_dna.generation,
            to_generation=to_dna.generation,
            from_hash=from_dna.compute_hash(),
            to_hash=to_dna.compute_hash(),
        )

        from_traits = set(from_dna.domain_heuristics.keys())
        to_traits = set(to_dna.domain_heuristics.keys())

        diff.added_traits = list(to_traits - from_traits)
        diff.removed_traits = list(from_traits - to_traits)

        for key in from_traits & to_traits:
            from_h = from_dna.domain_heuristics[key]
            to_h = to_dna.domain_heuristics[key]
            if from_h.rule != to_h.rule or abs(from_h.confidence - to_h.confidence) > 0.1:
                diff.modified_traits[f"heuristic.{key}"] = {
                    "from": from_h.model_dump(mode="json"),
                    "to": to_h.model_dump(mode="json"),
                }

        if from_dna.communication_style.style != to_dna.communication_style.style:
            diff.modified_traits["communication_style.style"] = {
                "from": from_dna.communication_style.style.value,
                "to": to_dna.communication_style.style.value,
            }

        if from_dna.decision_patterns.risk_tolerance != to_dna.decision_patterns.risk_tolerance:
            diff.modified_traits["decision_patterns.risk_tolerance"] = {
                "from": from_dna.decision_patterns.risk_tolerance.value,
                "to": to_dna.decision_patterns.risk_tolerance.value,
            }

        diff.mutations = [m for m in to_dna.mutation_history if m not in from_dna.mutation_history]

        summary_parts = []
        if diff.added_traits:
            summary_parts.append(f"+{len(diff.added_traits)} traits")
        if diff.removed_traits:
            summary_parts.append(f"-{len(diff.removed_traits)} traits")
        if diff.modified_traits:
            summary_parts.append(f"~{len(diff.modified_traits)} modified")

        diff.summary = ", ".join(summary_parts) or "No changes"

        return diff

    def get_stats(self) -> dict[str, Any]:
        """Get storage statistics."""
        agents = self.list_agents()
        total_sessions = 0

        for agent_id in agents:
            signals_dir = self.base_path / "signals" / agent_id
            if signals_dir.exists():
                total_sessions += len(list(signals_dir.glob("*.json")))

        return {
            "total_agents": len(agents),
            "total_sessions_analyzed": total_sessions,
            "storage_path": str(self.base_path),
        }

    def clone_dna(self, source_agent_id: str, target_agent_id: str) -> AgentPersonalityDNA | None:
        """Clone DNA from one agent to another (for personality transfer)."""
        source_dna = self.load_dna(source_agent_id)
        if source_dna is None:
            return None

        from uuid import uuid4

        cloned_data = source_dna.model_dump()
        cloned_data["agent_id"] = target_agent_id
        cloned_data["dna_id"] = str(uuid4())[:12]
        cloned_data["parent_hash"] = source_dna.compute_hash()
        cloned_data["generation"] = source_dna.generation + 1
        cloned_data["created_at"] = datetime.now().isoformat()
        cloned_data["updated_at"] = datetime.now().isoformat()
        cloned_data["mutation_history"] = [
            {
                "mutation_type": "clone",
                "trait_path": "agent_id",
                "old_value": source_agent_id,
                "new_value": target_agent_id,
                "reason": "Personality transfer",
                "trigger": "manual_clone",
            }
        ]

        cloned_dna = AgentPersonalityDNA.model_validate(cloned_data)
        self.save_dna(cloned_dna)

        logger.info(f"Cloned DNA from {source_agent_id} to {target_agent_id}")
        return cloned_dna
