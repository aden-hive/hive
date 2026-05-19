"""Unified skill lifecycle manager.

``SkillsManager`` is the single facade that owns skill discovery, loading,
and prompt renderation.  The runtime creates one at startup and downstream
layers read the cached prompt strings.

Typical usage — **config-driven** (runner passes configuration)::

    config = SkillsManagerConfig(
        skills_config=SkillsConfig.from_agent_vars(...),
        project_root=agent_path,
    )
    mgr = SkillsManager(config)
    mgr.load()
    print(mgr.protocols_prompt)       # default skill protocols
    print(mgr.skills_catalog_prompt)  # community skills XML

Typical usage — **bare** (exported agents, SDK users)::

    mgr = SkillsManager()   # default config
    mgr.load()               # loads all 6 default skills, no community discovery
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from framework.skills.config import SkillsConfig

logger = logging.getLogger(__name__)


@dataclass
class SkillsManagerConfig:
    """Everything the runtime needs to configure skills.

    Attributes:
        skills_config: Per-skill enable/disable and overrides.
        project_root: Agent directory for community skill discovery.
            When ``None``, community discovery is skipped.
        skip_community_discovery: Explicitly skip community scanning
            even when ``project_root`` is set.
        interactive: Whether trust gating can prompt the user interactively.
            When ``False``, untrusted project skills are silently skipped.
    """

    skills_config: SkillsConfig = field(default_factory=SkillsConfig)
    project_root: Path | None = None
    skip_community_discovery: bool = False
    interactive: bool = True


class SkillsManager:
    """Unified skill lifecycle: discovery → loading → prompt renderation.

    The runtime creates one instance during init and owns it for the
    lifetime of the process.  Downstream layers (``ExecutionStream``,
    ``GraphExecutor``, ``NodeContext``, ``EventLoopNode``) receive the
    cached prompt strings via property accessors.
    """

    def __init__(self, config: SkillsManagerConfig | None = None) -> None:
        self._config = config or SkillsManagerConfig()
        self._loaded = False
        self._catalog_prompt: str = ""
        self._protocols_prompt: str = ""
        self._allowlisted_dirs: list[str] = []

    # ------------------------------------------------------------------
    # Factory for backwards-compat bridge
    # ------------------------------------------------------------------

    @classmethod
    def from_precomputed(
        cls,
        skills_catalog_prompt: str = "",
        protocols_prompt: str = "",
    ) -> SkillsManager:
        """Wrap pre-rendered prompt strings (legacy callers).

        Returns a manager that skips discovery/loading and just returns
        the provided strings.  Used by the deprecation bridge in
        ``AgentRuntime`` when callers pass raw prompt strings.
        """
        mgr = cls.__new__(cls)
        mgr._config = SkillsManagerConfig()
        mgr._loaded = True  # skip load()
        mgr._catalog_prompt = skills_catalog_prompt
        mgr._protocols_prompt = protocols_prompt
        mgr._allowlisted_dirs = []
        return mgr

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Discover, load, and cache skill prompts.  Idempotent."""
        if self._loaded:
            return
        self._loaded = True

        try:
            self._do_load()
        except Exception:
            logger.warning("Skill system init failed (non-fatal)", exc_info=True)

    def _do_load(self) -> None:
        """Internal load — may raise; caller catches."""
        from framework.skills.catalog import SkillCatalog
        from framework.skills.defaults import DefaultSkillManager
        from framework.skills.discovery import DiscoveryConfig, SkillDiscovery

        skills_config = self._config.skills_config

        # 1. Community skill discovery (when project_root is available)
        catalog_prompt = ""
        if self._config.project_root is not None and not self._config.skip_community_discovery:
            from framework.skills.trust import TrustGate

            discovery = SkillDiscovery(DiscoveryConfig(project_root=self._config.project_root))
            discovered = discovery.discover()

            # Trust-gate project-scope skills (AS-13)
            discovered = TrustGate(interactive=self._config.interactive).filter_and_gate(
                discovered, project_dir=self._config.project_root
            )

            catalog = SkillCatalog(discovered)
            self._allowlisted_dirs = catalog.allowlisted_dirs
            catalog_prompt = catalog.to_prompt()

            # Pre-activated community skills
            if skills_config.skills:
                pre_activated = catalog.build_pre_activated_prompt(skills_config.skills)
                if pre_activated:
                    if catalog_prompt:
                        catalog_prompt = f"{catalog_prompt}\n\n{pre_activated}"
                    else:
                        catalog_prompt = pre_activated

        # 2. Default skills (always loaded unless explicitly disabled)
        default_mgr = DefaultSkillManager(config=skills_config)
        default_mgr.load()
        default_mgr.log_active_skills()
        protocols_prompt = default_mgr.build_protocols_prompt()

        # 3. Cache
        self._catalog_prompt = catalog_prompt
        self._protocols_prompt = protocols_prompt

        if protocols_prompt:
            logger.info(
                "Skill system ready: protocols=%d chars, catalog=%d chars",
                len(protocols_prompt),
                len(catalog_prompt),
            )
        else:
            logger.warning("Skill system produced empty protocols_prompt")

    # ------------------------------------------------------------------
    # Prompt accessors (consumed by downstream layers)
    # ------------------------------------------------------------------

    @property
    def skills_catalog_prompt(self) -> str:
        """Community skills XML catalog for system prompt injection."""
        return self._catalog_prompt

    @property
    def protocols_prompt(self) -> str:
        """Default skill operational protocols for system prompt injection."""
        return self._protocols_prompt

    @property
    def allowlisted_dirs(self) -> list[str]:
        """Skill base directories for Tier 3 resource access (AS-6)."""
        return self._allowlisted_dirs

    @property
    def is_loaded(self) -> bool:
        return self._loaded
