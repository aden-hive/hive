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
        self._default_mgr: object = None  # DefaultSkillManager, set after load()
        # Hot-reload state
        self._watched_dirs: list[str] = []
        self._watcher_task: object = None  # asyncio.Task, set by start_watching()

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
        mgr._default_mgr = None
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
            self._watched_dirs = discovery.scanned_directories

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
        self._default_mgr = default_mgr
        # DX-3: Community skill startup summary
        if self._config.project_root is not None and not self._config.skip_community_discovery:
            community_count = len(catalog._skills) if catalog_prompt else 0
            pre_activated_count = len(skills_config.skills) if skills_config.skills else 0
            logger.info(
                "Skills: %d community (%d catalog, %d pre-activated)",
                community_count,
                community_count,
                pre_activated_count,
            )

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
    # Hot-reload: watch skill directories for SKILL.md changes.
    # ------------------------------------------------------------------

    async def start_watching(self) -> None:
        """Start a background task watching skill directories for changes.

        When a ``SKILL.md`` file is added/modified/removed, the cached
        ``skills_catalog_prompt`` is rebuilt.  The next node iteration picks
        up the new prompt automatically via the ``dynamic_prompt_provider``.

        Silently no-ops when ``watchfiles`` is not installed or when no
        directories are being watched (e.g. bare mode, no project_root).
        """
        import asyncio

        try:
            import watchfiles  # noqa: F401 -- optional dep check
        except ImportError:
            logger.debug("watchfiles not installed; skill hot-reload disabled")
            return

        if not self._watched_dirs:
            logger.debug("No skill directories to watch; hot-reload skipped")
            return

        if self._watcher_task is not None:
            return  # already watching

        self._watcher_task = asyncio.create_task(
            self._watch_loop(),
            name="skills-hot-reload",
        )
        logger.info(
            "Skill hot-reload enabled (watching %d directories)",
            len(self._watched_dirs),
        )

    async def stop_watching(self) -> None:
        """Cancel the background watcher task (if running)."""
        import asyncio

        task = self._watcher_task
        if task is None:
            return
        self._watcher_task = None
        if not task.done():  # type: ignore[attr-defined]
            task.cancel()  # type: ignore[attr-defined]
            try:
                await task  # type: ignore[misc]
            except asyncio.CancelledError:
                pass

    async def _watch_loop(self) -> None:
        """Background coroutine that watches SKILL.md files and triggers reload."""
        import asyncio

        import watchfiles

        def _filter(_change: object, path: str) -> bool:
            return path.endswith("SKILL.md")

        try:
            async for changes in watchfiles.awatch(
                *self._watched_dirs,
                watch_filter=_filter,
                debounce=1000,
            ):
                paths = [p for _, p in changes]
                logger.info("SKILL.md changes detected: %s", paths)
                try:
                    self._reload()
                except Exception:
                    logger.exception("Skill reload failed; keeping previous prompts")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Skill watcher crashed; hot-reload disabled for this session")

    def _reload(self) -> None:
        """Re-run discovery and rebuild cached prompts."""
        # Reset loaded flag so _do_load actually re-runs.
        self._loaded = False
        self._do_load()
        self._loaded = True
        logger.info("Skills reloaded: protocols=%d chars, catalog=%d chars",
                    len(self._protocols_prompt), len(self._catalog_prompt))

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
    def batch_init_nudge(self) -> str | None:
        """Batch init nudge text for DS-12 auto-detection, or None if disabled."""
        if self._default_mgr is None:
            return None
        return self._default_mgr.batch_init_nudge  # type: ignore[union-attr]

    @property
    def context_warn_ratio(self) -> float | None:
        """Token usage ratio for DS-13 context preservation warning, or None if disabled."""
        if self._default_mgr is None:
            return None
        return self._default_mgr.context_warn_ratio  # type: ignore[union-attr]

    @property
    def is_loaded(self) -> bool:
        return self._loaded
