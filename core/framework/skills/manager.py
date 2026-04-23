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

import asyncio
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
        queen_id: Optional queen identifier. When set, enables the
            ``queen_ui`` scope and per-queen override file.
        queen_overrides_path: Path to
            ``~/.hive/agents/queens/{queen_id}/skills_overrides.json``.
            When set, the store is loaded and its entries override
            discovery results (disable skills, record provenance).
        colony_name: Optional colony identifier; mirrors ``queen_id`` for
            the ``colony_ui`` scope.
        colony_overrides_path: Per-colony override file path.
        extra_scope_dirs: Extra scope dirs scanned between user and
            project scopes. Typically populated by the caller with the
            queen/colony UI skill directories.
    """

    skills_config: SkillsConfig = field(default_factory=SkillsConfig)
    project_root: Path | None = None
    skip_community_discovery: bool = False
    interactive: bool = True

    # Override support
    queen_id: str | None = None
    queen_overrides_path: Path | None = None
    colony_name: str | None = None
    colony_overrides_path: Path | None = None
    # Typed at the call site as ``list[ExtraScope]`` — not imported here
    # to keep this module free of discovery-layer dependencies.
    extra_scope_dirs: list = field(default_factory=list)


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
        self._catalog: object = None  # SkillCatalog, set after load()
        self._all_skills: list = []  # list[ParsedSkill], pre-override-filter
        self._catalog_prompt: str = ""
        self._protocols_prompt: str = ""
        self._allowlisted_dirs: list[str] = []
        self._default_mgr: object = None  # DefaultSkillManager, set after load()
        # Override stores (loaded lazily in _do_load). Queen-scope and
        # colony-scope are read together; colony entries win on collision.
        self._queen_overrides: object = None  # SkillOverrideStore | None
        self._colony_overrides: object = None  # SkillOverrideStore | None
        # Hot-reload state
        self._watched_dirs: list[str] = []
        self._watched_files: list[str] = []
        self._watcher_task: object = None  # asyncio.Task, set by start_watching()
        # Serializes in-process mutations (HTTP handlers + create_colony).
        self._mutation_lock = asyncio.Lock()

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
        mgr._catalog = None
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
        from framework.skills.overrides import SkillOverrideStore

        skills_config = self._config.skills_config

        # 1. Skill discovery -- always run to pick up framework skills;
        # community/project skills only when project_root is available.
        discovery = SkillDiscovery(
            DiscoveryConfig(
                project_root=self._config.project_root,
                skip_framework_scope=False,
                extra_scopes=list(self._config.extra_scope_dirs or []),
            )
        )
        discovered = discovery.discover()
        self._watched_dirs = discovery.scanned_directories

        # Trust-gate project-scope skills (AS-13). UI scopes bypass.
        if self._config.project_root is not None and not self._config.skip_community_discovery:
            from framework.skills.trust import TrustGate

            discovered = TrustGate(interactive=self._config.interactive).filter_and_gate(
                discovered, project_dir=self._config.project_root
            )

        # 1b. Load per-scope override stores. Missing files → empty stores.
        queen_store = None
        if self._config.queen_overrides_path is not None:
            queen_store = SkillOverrideStore.load(
                self._config.queen_overrides_path,
                scope_label=f"queen:{self._config.queen_id or ''}",
            )
        colony_store = None
        if self._config.colony_overrides_path is not None:
            colony_store = SkillOverrideStore.load(
                self._config.colony_overrides_path,
                scope_label=f"colony:{self._config.colony_name or ''}",
            )
        self._queen_overrides = queen_store
        self._colony_overrides = colony_store
        self._watched_files = [
            str(p) for p in (self._config.queen_overrides_path, self._config.colony_overrides_path) if p is not None
        ]

        # 1c. Apply override filtering. Colony entries take precedence over
        # queen entries on name collision; the store's ``is_disabled`` keeps
        # the resolution rule in one place.
        self._all_skills = list(discovered)
        discovered = self._apply_overrides(discovered, skills_config, queen_store, colony_store)

        catalog = SkillCatalog(discovered)
        self._catalog = catalog
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

        # 2. Default skills -- discovered via _default_skills/ and included
        # in the catalog for progressive disclosure (no longer force-injected
        # as protocols_prompt).  DefaultSkillManager still handles config,
        # logging, and metadata.
        default_mgr = DefaultSkillManager(config=skills_config)
        default_mgr.load()
        default_mgr.log_active_skills()
        self._default_mgr = default_mgr

        # 3. Cache
        self._catalog_prompt = catalog_prompt
        self._protocols_prompt = ""  # all skills use progressive disclosure now

        if catalog_prompt:
            logger.info(
                "Skill system ready: catalog=%d chars",
                len(catalog_prompt),
            )

    # ------------------------------------------------------------------
    # Override application
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_overrides(
        discovered: list,
        skills_config: SkillsConfig,
        queen_store: object,
        colony_store: object,
    ) -> list:
        """Filter ``discovered`` per the queen + colony override stores.

        Resolution rule:
          1. Tombstoned names (``deleted_ui_skills``) drop out.
          2. An explicit ``enabled=False`` override drops the skill.
          3. An explicit ``enabled=True`` override keeps it (wins over
             ``all_defaults_disabled`` for framework defaults AND over the
             preset-scope default-off rule).
          4. Otherwise: preset-scope skills are off by default; everything
             else inherits :meth:`SkillsConfig.is_default_enabled`.
        """
        from framework.skills.overrides import SkillOverrideStore

        stores: list[SkillOverrideStore] = [s for s in (queen_store, colony_store) if s is not None]

        tombstones: set[str] = set()
        for store in stores:
            tombstones |= set(store.deleted_ui_skills)

        out = []
        for skill in discovered:
            if skill.name in tombstones:
                continue
            # Check colony first so colony overrides win over queen's.
            explicit: bool | None = None
            master_disabled = False
            for store in reversed(stores):  # colony, then queen
                entry = store.get(skill.name)
                if entry is not None and entry.enabled is not None:
                    explicit = entry.enabled
                    break
                if store.all_defaults_disabled:
                    master_disabled = True
            if explicit is False:
                continue
            if explicit is True:
                out.append(skill)
                continue
            # Preset-scope capability packs are bundled but ship OFF; the
            # user must explicitly enable them per queen or colony. This
            # runs even when no store is present so bare agents don't
            # silently load x-automation etc.
            if skill.source_scope == "preset":
                continue
            # No explicit entry — master switch takes effect against framework defaults.
            default_enabled = skills_config.is_default_enabled(skill.name)
            if master_disabled and default_enabled and skill.source_scope == "framework":
                continue
            if default_enabled:
                out.append(skill)
        return out

    # ------------------------------------------------------------------
    # Override accessors
    # ------------------------------------------------------------------

    @property
    def queen_overrides(self) -> object:
        """The queen-scope :class:`SkillOverrideStore` or ``None``."""
        return self._queen_overrides

    @property
    def colony_overrides(self) -> object:
        """The colony-scope :class:`SkillOverrideStore` or ``None``."""
        return self._colony_overrides

    @property
    def mutation_lock(self) -> asyncio.Lock:
        """Serializes in-process override mutations (routes + queen tools)."""
        return self._mutation_lock

    def reload(self) -> None:
        """Re-run discovery and rebuild cached prompts. Public wrapper for ``_reload``."""
        self._reload()

    def enumerate_skills_with_source(self) -> list:
        """Return every discovered skill, including ones disabled by overrides.

        The UI relies on this: a disabled framework skill needs to render
        in the list so the user can toggle it back on. The post-filter
        catalog omits those entries.
        """
        return list(self._all_skills)

    # ------------------------------------------------------------------
    # Hot-reload: watch skill directories for SKILL.md changes.
    # ------------------------------------------------------------------

    async def start_watching(self) -> None:
        """Start a background task watching skill directories for changes.

        Triggers a reload when any ``SKILL.md`` changes or an override
        JSON file is modified. The next node iteration picks up the new
        prompt via the ``dynamic_prompt_provider`` / per-worker
        ``dynamic_skills_catalog_provider``.

        Silently no-ops when ``watchfiles`` is not installed or there
        are no paths to watch.
        """

        try:
            import watchfiles  # noqa: F401 -- optional dep check
        except ImportError:
            logger.debug("watchfiles not installed; skill hot-reload disabled")
            return

        if not self._watched_dirs and not self._watched_files:
            logger.debug("No skill directories to watch; hot-reload skipped")
            return

        if self._watcher_task is not None:
            return  # already watching

        self._watcher_task = asyncio.create_task(
            self._watch_loop(),
            name="skills-hot-reload",
        )
        logger.info(
            "Skill hot-reload enabled (watching %d dirs, %d override files)",
            len(self._watched_dirs),
            len(self._watched_files),
        )

    async def stop_watching(self) -> None:
        """Cancel the background watcher task (if running)."""
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
        """Watch SKILL.md + override JSON files and trigger reload on change."""
        import watchfiles

        def _filter(_change: object, path: str) -> bool:
            return path.endswith("SKILL.md") or path.endswith("skills_overrides.json")

        # watchfiles accepts a mix of dirs and files; file watches survive
        # a tmp+rename (the containing dir sees the event).
        watch_targets = list(self._watched_dirs)
        for f in self._watched_files:
            # watchfiles needs the parent dir for file-level events to fire
            # reliably through atomic replace; adding the file path directly
            # works on Linux/macOS inotify/FSEvents but a dir watch is
            # belt-and-braces.
            parent = str(Path(f).parent)
            if parent not in watch_targets:
                watch_targets.append(parent)

        if not watch_targets:
            return

        try:
            async for changes in watchfiles.awatch(
                *watch_targets,
                watch_filter=_filter,
                debounce=1000,
            ):
                paths = [p for _, p in changes]
                logger.info("Skill state changes detected: %s", paths)
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
        logger.info(
            "Skills reloaded: protocols=%d chars, catalog=%d chars",
            len(self._protocols_prompt),
            len(self._catalog_prompt),
        )

    # ------------------------------------------------------------------
    # Prompt accessors (consumed by downstream layers)
    # ------------------------------------------------------------------

    @property
    def skills_catalog_prompt(self) -> str:
        """Community skills XML catalog for system prompt injection."""
        return self._catalog_prompt

    def skills_catalog_prompt_for_phase(self, phase: str | None) -> str:
        """Render the catalog filtered for the given queen phase.

        Skills whose frontmatter ``visibility`` list is present and
        excludes ``phase`` are dropped. Falls back to the cached
        phase-agnostic prompt when no live catalog is available
        (e.g. ``from_precomputed``).
        """
        if self._catalog is None or phase is None:
            return self._catalog_prompt
        return self._catalog.to_prompt(phase=phase)  # type: ignore[attr-defined]

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
