"""Queen identity profiles -- static queen personas stored as YAML files.

Each queen has a unique identity (Head of Technology, Head of Growth, etc.)
stored in ``~/.hive/agents/queens/{queen_id}/profile.yaml``. Profiles are
initialized with rich defaults and can be edited via the API.

At session start, a lightweight LLM classifier selects the best-matching
queen for the user's request, and the profile is injected into the system
prompt.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from framework.config import QUEENS_DIR, get_aux_max_tokens

if TYPE_CHECKING:
    from framework.llm.provider import LLMProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QueenSelection:
    """Structured selector result for routing diagnostics."""

    queen_id: str
    reason: str


@dataclass(frozen=True)
class ColonySessionSelection:
    """Selector result for creating a colony session directly.

    Adds a ``colony_name`` slug on top of the queen routing decision so a
    colony can be created in a single LLM call instead of a queen DM.
    """

    queen_id: str
    colony_name: str
    reason: str


# ---------------------------------------------------------------------------
# Default queen profiles
# ---------------------------------------------------------------------------
#
# Each default queen is defined in its own file: ``queen_defaults/<queen_id>.yaml``
# (filename stem == queen_id). A file is the single place that queen's
# defaults live: persona (name, traits, examples, ...) plus capability
# defaults:
#   - ``default_tool_categories``: MCP tool categories granted by default.
#     Projected into ``queen_tools_defaults.QUEEN_DEFAULT_CATEGORIES``. A queen
#     with none falls through to "allow every MCP tool".
#   - ``default_preset_skills``: preset-scope skills on by default for the
#     role, enabled in-memory at load time
#     (``SkillsManagerConfig.default_preset_skills``).
#
# (Both are distinct from the persona ``skills`` string, which is prose for
# the prompt / API.) ``_CAPABILITY_KEYS`` are stripped before a profile is
# written to ``profile.yaml`` (see ``_persona_only`` /
# ``_materialize_default_queen``) so persona files stay free of capability
# config.
_CAPABILITY_KEYS = ("default_tool_categories", "default_preset_skills")

_QUEEN_DEFAULTS_DIR = Path(__file__).parent / "queen_defaults"


def _load_default_queens() -> dict[str, dict[str, Any]]:
    """Load every ``queen_defaults/*.yaml`` keyed by filename stem (queen_id)."""
    queens: dict[str, dict[str, Any]] = {}
    for path in sorted(_QUEEN_DEFAULTS_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            logger.exception("Failed to read default queen profile %s; skipping", path)
            continue
        if isinstance(data, dict):
            queens[path.stem] = data
        else:
            # A non-mapping file would silently make this queen vanish from
            # the catalog — surface it instead of dropping on the floor.
            logger.warning("Default queen profile %s is not a mapping; skipping", path)
    return queens


DEFAULT_QUEENS: dict[str, dict[str, Any]] = _load_default_queens()


# ---------------------------------------------------------------------------
# Profile CRUD
# ---------------------------------------------------------------------------


def ensure_default_queens() -> None:
    """No-op in v3.

    Pre-creating every default queen on startup left empty
    ``queens/<id>/`` directories for queens the user never selected.
    Default profiles are now materialized lazily by :func:`load_queen_profile`
    when first requested. Kept as a no-op for back-compat callers.
    """
    return


def _atomic_write_text(path: Path, data: str) -> None:
    """tempfile + os.replace write so concurrent readers never observe a
    half-written profile.yaml.

    Matters because ``initialize-preferences`` distinguishes "user
    customized" from "still default" by content-equality with
    :data:`DEFAULT_QUEENS` — a torn read could be mistaken for a
    customization and cause the user's /me overrides to be skipped.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".profile.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _persona_only(profile: dict[str, Any]) -> dict[str, Any]:
    """Profile minus capability config — the persona half written to profile.yaml."""
    return {k: v for k, v in profile.items() if k not in _CAPABILITY_KEYS}


def default_profile_persona(queen_id: str) -> dict[str, Any] | None:
    """Persona-only form of a default queen — exactly what
    :func:`_materialize_default_queen` writes to ``profile.yaml``. Use this
    (not the raw ``DEFAULT_QUEENS`` entry) when comparing against an on-disk
    profile, since the on-disk copy never carries capability config.
    """
    profile = DEFAULT_QUEENS.get(queen_id)
    return _persona_only(profile) if profile is not None else None


def default_tools_for(queen_id: str) -> list[str] | None:
    """Role-default MCP tool categories for a default queen, else ``None``."""
    profile = DEFAULT_QUEENS.get(queen_id)
    if not profile:
        return None
    tools = profile.get("default_tool_categories")
    return list(tools) if tools else None


def default_skills_for(queen_id: str) -> frozenset[str]:
    """Preset skills on-by-default for a default queen (empty if none/unknown)."""
    profile = DEFAULT_QUEENS.get(queen_id)
    if not profile:
        return frozenset()
    return frozenset(profile.get("default_preset_skills") or ())


def _materialize_default_queen(queen_id: str) -> Path | None:
    """If ``queen_id`` is a known default, write its profile.yaml and
    return the path. Otherwise ``None``."""
    profile = DEFAULT_QUEENS.get(queen_id)
    if profile is None:
        return None
    profile_path = QUEENS_DIR / queen_id / "profile.yaml"
    _atomic_write_text(
        profile_path,
        yaml.safe_dump(_persona_only(profile), sort_keys=False, allow_unicode=True),
    )
    logger.info("Materialized default queen profile lazily: %s", queen_id)
    return profile_path


def list_queens() -> list[dict[str, Any]]:
    """Return the queen catalog: union of materialized on-disk profiles
    plus the built-in DEFAULT_QUEENS catalog.

    Default queens that the user has never selected don't have on-disk
    directories yet, but the catalog should still surface them so the
    UI can offer them as choices.
    """
    results: dict[str, dict[str, Any]] = {}
    # 1. Built-in catalog (always available).
    for queen_id, profile in DEFAULT_QUEENS.items():
        entry: dict[str, Any] = {
            "id": queen_id,
            "name": profile.get("name", ""),
            "title": profile.get("title", ""),
            "has_avatar": _queen_has_avatar(queen_id),
        }
        if profile.get("portrait"):
            entry["portrait"] = profile["portrait"]
        results[queen_id] = entry
    # 2. On-disk profiles (user-customized or non-default).
    if QUEENS_DIR.is_dir():
        for profile_path in sorted(QUEENS_DIR.glob("*/profile.yaml")):
            queen_id = profile_path.parent.name
            try:
                data = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
                entry = {
                    "id": queen_id,
                    "name": data.get("name", ""),
                    "title": _current_title(queen_id, data.get("title", "")),
                    "has_avatar": _queen_has_avatar(queen_id),
                    # Not part of the shipped catalog — created by the user
                    # (UI "New Queen" or a hand-written profile.yaml). The
                    # frontend groups these under "Custom" in the leader
                    # catalog instead of a preset function slot.
                    "custom": queen_id not in DEFAULT_QUEENS,
                }
                if data.get("portrait"):
                    entry["portrait"] = data["portrait"]
                results[queen_id] = entry
            except Exception:
                logger.warning("Failed to read queen profile %s", profile_path)
    return sorted(results.values(), key=lambda q: q["id"])


_QUEEN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


def _slugify_queen_id(name: str) -> str:
    """Derive a queen id from a display name: ascii-fold to [a-z0-9_-].

    Non-latin names (CJK etc.) can slug to nothing — fall back to a short
    stable suffix so the id is still deterministic-ish and readable.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40]
    if not slug:
        slug = f"custom_{abs(hash(name)) % 100000:05d}"
    return slug if slug.startswith("queen_") else f"queen_{slug}"


def create_queen_profile(
    name: str,
    title: str = "",
    persona: str = "",
    queen_id: str = "",
) -> dict[str, Any]:
    """Create a brand-new custom queen from scratch.

    Writes ``queens/<id>/profile.yaml`` with the persona fields the loader
    understands; :func:`list_queens` picks it up on the next call with
    ``custom: True``. Raises ``ValueError`` for a missing name or malformed
    id, ``FileExistsError`` when the id is already taken (on disk or by the
    built-in catalog — shadowing a shipped default would silently replace
    her persona).
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("name is required")
    qid = (queen_id or "").strip() or _slugify_queen_id(name)
    if not _QUEEN_ID_RE.match(qid):
        raise ValueError("queen_id must match [a-z0-9][a-z0-9_-]{0,62} (lowercase slug)")
    if qid in DEFAULT_QUEENS or (QUEENS_DIR / qid / "profile.yaml").exists():
        raise FileExistsError(qid)
    profile: dict[str, Any] = {"name": name, "title": (title or "").strip()}
    if (persona or "").strip():
        # core_traits is the free-text persona field every shipped profile
        # carries; the system-prompt builder and the API's summary both
        # read it, so a from-scratch queen speaks in her own voice at once.
        profile["core_traits"] = persona.strip()
    _atomic_write_text(
        QUEENS_DIR / qid / "profile.yaml",
        yaml.safe_dump(profile, sort_keys=False, allow_unicode=True),
    )
    logger.info("Created custom queen profile: %s (%s)", qid, name)
    return {
        "id": qid,
        "name": name,
        "title": profile["title"],
        "has_avatar": False,
        "custom": True,
    }


# Titles this build has RETIRED, per queen id. A queen's display name is defined
# once — the `title` in her shipped profile — but each install keeps a
# materialized copy under ``queens/<id>/profile.yaml``, and that copy is written
# once and never refreshed. So renaming a queen in the catalog reached new
# installs only: everyone who had already opened her kept seeing the old name in
# the org chart, the sidebar and her own greeting.
#
# This is the cache invalidation, kept deliberately narrow: only a title that
# EXACTLY matches a name we used to ship is replaced. A user who edited the
# title themselves (profile panel → "Edit name & title") wrote something else,
# and their choice survives untouched.
_SUPERSEDED_TITLES: dict[str, set[str]] = {
    # queen_sales is displayed as Head of RevOps; the id is unchanged so no
    # preference, session or profile keyed on it needs migrating.
    "queen_sales": {"Head of Sales"},
}


def _current_title(queen_id: str, on_disk_title: Any) -> Any:
    """The title to show: the shipped one when the stored copy is a retired default."""
    retired = _SUPERSEDED_TITLES.get(queen_id)
    if not retired or on_disk_title not in retired:
        return on_disk_title
    shipped = DEFAULT_QUEENS.get(queen_id, {}).get("title")
    return shipped or on_disk_title


def _queen_has_avatar(queen_id: str) -> bool:
    """True iff an avatar.* file exists in the queen's profile directory."""
    queen_dir = QUEENS_DIR / queen_id
    if not queen_dir.is_dir():
        return False
    return any(queen_dir.glob("avatar.*"))


def load_queen_profile(queen_id: str) -> dict[str, Any]:
    """Load a queen's full profile, materializing the default lazily
    if the user hasn't customized it yet.

    Raises ``FileNotFoundError`` only when ``queen_id`` is neither on
    disk nor a known default in :data:`DEFAULT_QUEENS`.
    """
    profile_path = QUEENS_DIR / queen_id / "profile.yaml"
    if not profile_path.exists():
        materialized = _materialize_default_queen(queen_id)
        if materialized is None:
            raise FileNotFoundError(f"Queen profile not found: {queen_id}")
        profile_path = materialized
    data = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    # The agent bakes its own title into its system prompt, so a stale copy would
    # have her introduce herself by a name the UI no longer shows.
    if isinstance(data, dict) and "title" in data:
        data["title"] = _current_title(queen_id, data["title"])
    return data


def update_queen_profile(queen_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    """Merge partial updates into an existing queen profile and persist.

    Performs a shallow merge at the top level, but deep-merges dict values
    (e.g. world_lore, hidden_background) so partial sub-field updates don't
    clobber sibling keys.

    Returns the full updated profile.
    Raises FileNotFoundError if the profile doesn't exist.
    """
    profile_path = QUEENS_DIR / queen_id / "profile.yaml"
    if not profile_path.exists():
        # Defense-in-depth: the eager init path (Electron main calling
        # /api/queen/initialize-preferences before broadcasting "ready")
        # is responsible for materializing preferenced queens up front.
        # This branch handles any caller that still PATCHes a queen
        # whose profile.yaml hasn't been materialized yet (e.g. a
        # direct-edit flow on a queen the user never opened, or
        # cloud_sync pulling a cloud-side profile for the first time).
        # Without it, those PATCHes 404 silently and the queen stays on
        # its default.
        materialized = _materialize_default_queen(queen_id)
        if materialized is None:
            raise FileNotFoundError(f"Queen profile not found: {queen_id}")
        profile_path = materialized
    data = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(data.get(key), dict):
            data[key].update(value)
        else:
            data[key] = value
    _atomic_write_text(
        profile_path,
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
    )
    return data


# ---------------------------------------------------------------------------
# Prompt formatting
# ---------------------------------------------------------------------------


def _as_clean_text(value: Any) -> str:
    """Return a stripped string, or an empty string for non-string values."""
    return value.strip() if isinstance(value, str) else ""


def _sentence(value: Any) -> str:
    text = _as_clean_text(value)
    if not text:
        return ""
    return text if text.endswith((".", "!", "?")) else f"{text}."


def _profile_text_to_instruction(text: Any) -> str:
    instruction = _sentence(text)
    replacements = {
        "She thrives": "You thrive",
        "she thrives": "you thrive",
        "She's ": "You are ",
        "she's ": "you are ",
        "She is ": "You are ",
        "she is ": "you are ",
        "She ": "You ",
        "she ": "you ",
        "Her ": "Your ",
        "her ": "your ",
    }
    for old, new in replacements.items():
        instruction = instruction.replace(old, new)
    return instruction


def format_queen_identity_prompt(profile: dict[str, Any], *, max_examples: int | None = None) -> str:
    """Convert a queen profile into a high-dimensional character prompt.

    Uses the 5-pillar character construction system: core identity,
    hidden background (behavioral engine), psychological profile,
    behavior rules, and world lore.  The hidden background and
    psychological profile are never shown to the user but shape
    every response.

    ``max_examples`` caps the roleplay_examples block — profiles ship
    four worked examples (~2.4 KB) but one is enough at runtime to show
    the internal-then-external pattern. Full rendering stays available
    for profile authoring / eval playback by leaving ``max_examples=None``.
    """
    name = profile.get("name", "the Queen")
    title = profile.get("title", "Senior Advisor")
    core = profile.get("core_traits", "")
    bg = profile.get("hidden_background", {})
    psych = profile.get("psychological_profile", {})
    triggers = profile.get("behavior_triggers", [])
    lore = profile.get("world_lore", {})
    skills = profile.get("skills", "")

    sections: list[str] = []

    # Pillar 1: Core identity
    sections.append(f"<core_identity>\nYou are a queen agent, your name is {name}, {title}.\n{core}\n</core_identity>")

    # Pillar 2: Hidden background (behavioral engine, never surfaced)
    if bg:
        sections.append(
            "<hidden_background>\n"
            "(Strictly hidden from users -- acts as your underlying "
            "behavioral engine)\n"
            f"- Past Wound: {bg.get('past_wound', '')}\n"
            f"- Deep Motive: {bg.get('deep_motive', '')}\n"
            f"- Behavioral Mapping: {bg.get('behavioral_mapping', '')}\n"
            "</hidden_background>"
        )

    # Pillar 3: Psychological profile. Each line is optional — a profile that
    # omits one must not render a dangling label with nothing after it.
    if psych:
        psych_lines = []
        if _as_clean_text(psych.get("social_masks")):
            psych_lines.append(f"- Social Masks & Boundaries: {psych['social_masks']}")
        anti_stereotype = _profile_text_to_instruction(psych.get("anti_stereotype"))
        if anti_stereotype:
            psych_lines.append(f"- Anti-Stereotype Rules: {anti_stereotype}")
        if psych_lines:
            sections.append("<psychological_profile>\n" + "\n".join(psych_lines) + "\n</psychological_profile>")

    # Pillar 4: Behavior rules
    trigger_lines = []
    for t in triggers:
        trigger_lines.append(f"  - [{t.get('trigger', '')}]: {_profile_text_to_instruction(t.get('reaction'))}")
    sections.append(
        "<behavior_rules>\n"
        "- Before each response, internally assess:\n"
        "  1. Relationship with the person (founder, engineer, "
        "executive, stranger)\n"
        "  2. Current context (urgency, stakes, emotional state)\n"
        "  3. Filter through your hidden background and motives\n"
        "  4. Select the right register and depth\n"
        "- Interaction triggers:\n" + "\n".join(trigger_lines) + "\n"
        "</behavior_rules>"
    )

    # Pillar 5: Negative constraints
    sections.append(
        "<negative_constraints>\n"
        "- NEVER use corporate filler ('leverage', 'synergy', "
        "'circle back', 'at the end of the day').\n"
        "- NEVER break character to explain your thought process "
        "or reference your hidden background.\n"
        "</negative_constraints>"
    )

    # World lore
    if lore:
        sections.append(f"<world_lore>\n- Habitat: {lore.get('habitat', '')}\n- Lexicon: {lore.get('lexicon', '')}\n</world_lore>")

    # Skills (functional, for tool selection context)
    if skills:
        sections.append(f"<core_skills>\n{skills}\n</core_skills>")

    # Few-shot examples showing the full internal process
    examples = profile.get("examples", [])
    if examples and max_examples is not None:
        examples = examples[:max_examples]
    if examples:
        example_parts: list[str] = []
        for ex in examples:
            example_parts.append(f"User: {ex['user']}\n\nAssistant:\n{ex['internal']}\n{ex['response']}")
        sections.append("<roleplay_examples>\n" + "\n\n---\n\n".join(example_parts) + "\n</roleplay_examples>")

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Queen selection (lightweight LLM classifier)
# ---------------------------------------------------------------------------

# One-line domain blurb per default queen, used to build the selector prompt.
# Only queens actually offered to the classifier appear in the prompt (see
# ``_allowed_queen_ids``), so a decommissioned queen can never win the routing.
_QUEEN_SELECTOR_DESCRIPTIONS: dict[str, str] = {
    "queen_technology": "Technical architecture, software engineering, infrastructure, DevOps, system design",
    "queen_growth": "User acquisition, retention, growth experiments, PLG, marketing funnels, analytics, brand and demand",
    "queen_market_research": "Market sizing (TAM/SAM), competitive analysis, customer interviews, surveys, trend forecasting, positioning research",
    "queen_content_creation": "Content strategy, copywriting, short-form video, social media, brand storytelling, editorial calendars",
    "queen_lead_gen": "Lead generation, offer design, paid acquisition, list building, inbound/demand capture, ICP, lead qualification",
    "queen_outbound": "Outbound prospecting on LinkedIn/Twitter/email, cold sequences, ICP definition, deliverability, reply-rate optimization",
    "queen_product_strategy": "Product vision, roadmapping, user research, feature prioritization, go-to-market",
    "queen_finance_fundraising": "Financial modeling, fundraising, investor relations, cap tables, unit economics, budgeting",
    "queen_legal": "Contracts, IP, compliance, corporate governance, employment law, regulatory matters",
    "queen_brand_design": "Brand identity, visual design, UX, design systems, creative direction, messaging",
    "queen_sales": "The CRM itself — pipeline stages, fields, the shape of the sales process — plus pipeline and forecast ownership, deal qualification, enterprise/mid-market selling, sales coaching, comp design, channel and partnership sales",  # noqa: E501
    "queen_talent": "Hiring, recruiting, team building, culture, compensation, organizational design",
    "queen_operations": "Founder coaching, strategic decisions, leadership challenges, company growth, pivots",
}


def _allowed_queen_ids(active_queen_ids: list[str] | None) -> list[str]:
    """Queens the selector may pick from: the caller's active set, restricted
    to known defaults. Empty/None (prefs not loaded, older client) falls back
    to the full catalog rather than refusing to route."""
    allowed = [qid for qid in (active_queen_ids or []) if qid in DEFAULT_QUEENS]
    return allowed or list(DEFAULT_QUEENS)


def _queen_selector_system_prompt(allowed_ids: list[str]) -> str:
    queen_lines = "\n".join(f"- {qid}: {_QUEEN_SELECTOR_DESCRIPTIONS.get(qid) or DEFAULT_QUEENS[qid].get('title') or qid}" for qid in allowed_ids)
    return f"""\
You are a routing classifier acting as the CEO of the company.

Treat the incoming request as something you personally want to accomplish.
Select the single best-matching queen identity from the list below to take on that goal.

Queens:
{queen_lines}

Reply with ONLY a valid JSON object — no markdown, no prose:
{{"reason": "<reason and thinking of selecting who will take the request>", "queen_id": "<one of the IDs above>"}}

Rules:
- Think about the request from the CEO's perspective: this is your goal and you need the best queen to own it.
- Pick the queen whose domain most directly applies to the goal.
- If the request spans multiple domains, pick the one most central to the ask.
- The reason must briefly explain why that queen should take this request.
"""


_DEFAULT_QUEEN_ID = "queen_growth"


def _fallback_queen_id(allowed_ids: list[str]) -> str:
    """Failure-path queen: the static default when it's allowed, else the
    first allowed queen — never a decommissioned one."""
    return _DEFAULT_QUEEN_ID if _DEFAULT_QUEEN_ID in allowed_ids else allowed_ids[0]


async def select_queen_with_reason(user_message: str, llm: LLMProvider) -> QueenSelection:
    """Classify a user message into the best-matching queen ID and reason.

    Makes a single non-streaming LLM call. Returns the queen_id and selector
    reason so routing decisions can be logged explicitly.
    Falls back to head-of-technology on any failure.
    """
    if not user_message.strip():
        reason = "User message was empty, so routing defaulted to queen_technology."
        logger.info(
            "Queen selector: %s takes the task. reason=%s",
            _DEFAULT_QUEEN_ID,
            reason,
        )
        return QueenSelection(queen_id=_DEFAULT_QUEEN_ID, reason=reason)

    try:
        response = await llm.acomplete(
            messages=[{"role": "user", "content": user_message}],
            system=_queen_selector_system_prompt(list(DEFAULT_QUEENS)),
            max_tokens=get_aux_max_tokens(),
            json_mode=True,
        )
    except Exception as exc:
        logger.exception(
            "Queen selector failed during LLM classification; defaulting to %s. error=%s",
            _DEFAULT_QUEEN_ID,
            exc,
        )
        return QueenSelection(
            queen_id=_DEFAULT_QUEEN_ID,
            reason=f"Selection failed because the classifier errored: {exc}",
        )

    raw = response.content.strip()
    # Extract JSON object if the response has extra text before/after it
    if raw.startswith("{"):
        json_str = raw
    else:
        # Find the first '{' and last '}' to extract the JSON object
        start = raw.find("{")
        end = raw.rfind("}")
        json_str = raw[start : end + 1] if start != -1 and end != -1 and end > start else raw
    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError as exc:
        logger.error(
            "Queen selector failed to parse JSON; defaulting to %s. error=%s raw=%r",
            _DEFAULT_QUEEN_ID,
            exc,
            raw,
        )
        return QueenSelection(
            queen_id=_DEFAULT_QUEEN_ID,
            reason=f"Selection failed because the classifier returned invalid JSON: {exc.msg}",
        )

    queen_id = str(parsed.get("queen_id", "")).strip()
    reason = str(parsed.get("reason", "")).strip()
    if queen_id not in DEFAULT_QUEENS:
        logger.error(
            "Queen selector returned an unknown queen_id; defaulting to %s. queen_id=%r reason=%r raw=%r",
            _DEFAULT_QUEEN_ID,
            queen_id,
            reason,
            raw,
        )
        fallback_reason = reason or f"Selection failed because the classifier returned unknown queen_id {queen_id!r}."
        return QueenSelection(queen_id=_DEFAULT_QUEEN_ID, reason=fallback_reason)

    if not reason:
        reason = f"Classifier selected {queen_id} but did not provide an explicit reason."
        logger.warning(
            "Queen selector response omitted reason for queen_id=%s; using synthesized reason.",
            queen_id,
        )

    logger.info("Queen selector: %s takes the task. reason=%s", queen_id, reason)
    return QueenSelection(queen_id=queen_id, reason=reason)


async def select_queen(user_message: str, llm: LLMProvider) -> str:
    """Classify a user message into the best-matching queen ID."""

    selection = await select_queen_with_reason(user_message, llm)
    return selection.queen_id


# ---------------------------------------------------------------------------
# Colony session selection (queen + colony name in one LLM call)
# ---------------------------------------------------------------------------

# On-disk colony names must match this everywhere (see routes_colonies.py).
_COLONY_NAME_RE = re.compile(r"^[a-z0-9_]+$")
_COLONY_NAME_MAX_LEN = 64
_DEFAULT_COLONY_NAME = "new_colony"


def _colony_selector_system_prompt(allowed_ids: list[str]) -> str:
    return (
        _queen_selector_system_prompt(allowed_ids).replace(
            "Reply with ONLY a valid JSON object — no markdown, no prose:\n"
            '{"reason": "<reason and thinking of selecting who will take the request>", "queen_id": "<one of the IDs above>"}',
            "You are also spinning up a dedicated colony (a project workspace) to own this goal.\n"
            "Give the colony a short, human-friendly name that captures the goal.\n\n"
            "Reply with ONLY a valid JSON object — no markdown, no prose:\n"
            '{"reason": "<why this queen and colony name>", "queen_id": "<one of the IDs above>", '
            '"colony_name": "<lowercase_snake_case slug, e.g. fintech_competitor_research>"}',
        )
        + "\n- colony_name must be lowercase letters, digits, and underscores only "
        "(e.g. 'morning_hn_digest'), max 64 characters, derived from the goal."
    )


def _sanitize_colony_name(raw: str, *, fallback: str = _DEFAULT_COLONY_NAME) -> str:
    """Coerce an LLM-proposed colony name into a valid on-disk slug.

    Lowercases, replaces any run of disallowed characters with a single
    underscore, trims leading/trailing underscores, and clamps length.
    Returns ``fallback`` if nothing usable remains.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", (raw or "").strip().lower()).strip("_")
    slug = slug[:_COLONY_NAME_MAX_LEN].strip("_")
    if not slug or not _COLONY_NAME_RE.match(slug):
        return fallback
    return slug


async def select_queen_and_colony(
    user_message: str,
    llm: LLMProvider,
    active_queen_ids: list[str] | None = None,
) -> ColonySessionSelection:
    """Pick the best queen AND a colony name for a colony session.

    Single non-streaming LLM call. Mirrors ``select_queen_with_reason`` but
    additionally extracts a sanitized ``colony_name`` slug. Only queens in
    ``active_queen_ids`` (the user's active roster) are offered to the
    classifier; None/empty means the full default catalog. Falls back to an
    allowed queen and a derived/default colony name on any failure.
    """
    allowed_ids = _allowed_queen_ids(active_queen_ids)
    fallback_id = _fallback_queen_id(allowed_ids)

    if not user_message.strip():
        reason = "User message was empty, so routing defaulted to the default queen."
        return ColonySessionSelection(
            queen_id=fallback_id,
            colony_name=_DEFAULT_COLONY_NAME,
            reason=reason,
        )

    try:
        response = await llm.acomplete(
            messages=[{"role": "user", "content": user_message}],
            system=_colony_selector_system_prompt(allowed_ids),
            max_tokens=get_aux_max_tokens(),
            json_mode=True,
        )
    except Exception as exc:
        logger.exception(
            "Colony selector failed during LLM classification; defaulting to %s. error=%s",
            fallback_id,
            exc,
        )
        return ColonySessionSelection(
            queen_id=fallback_id,
            colony_name=_DEFAULT_COLONY_NAME,
            reason=f"Selection failed because the classifier errored: {exc}",
        )

    raw = response.content.strip()
    # Extract JSON object if the response has extra text before/after it
    if raw.startswith("{"):
        json_str = raw
    else:
        start = raw.find("{")
        end = raw.rfind("}")
        json_str = raw[start : end + 1] if start != -1 and end != -1 and end > start else raw
    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError as exc:
        logger.error(
            "Colony selector failed to parse JSON; defaulting to %s. error=%s raw=%r",
            fallback_id,
            exc,
            raw,
        )
        return ColonySessionSelection(
            queen_id=fallback_id,
            colony_name=_DEFAULT_COLONY_NAME,
            reason=f"Selection failed because the classifier returned invalid JSON: {exc.msg}",
        )

    queen_id = str(parsed.get("queen_id", "")).strip()
    reason = str(parsed.get("reason", "")).strip()
    colony_name = _sanitize_colony_name(str(parsed.get("colony_name", "")))

    if queen_id not in allowed_ids:
        logger.error(
            "Colony selector returned a queen_id outside the allowed set; defaulting to %s. queen_id=%r raw=%r",
            fallback_id,
            queen_id,
            raw,
        )
        fallback_reason = reason or f"Selection failed because the classifier returned disallowed queen_id {queen_id!r}."
        return ColonySessionSelection(
            queen_id=fallback_id,
            colony_name=colony_name,
            reason=fallback_reason,
        )

    if not reason:
        reason = f"Classifier selected {queen_id} but did not provide an explicit reason."
        logger.warning(
            "Colony selector response omitted reason for queen_id=%s; using synthesized reason.",
            queen_id,
        )

    logger.info(
        "Colony selector: %s takes the task in colony %r. reason=%s",
        queen_id,
        colony_name,
        reason,
    )
    return ColonySessionSelection(queen_id=queen_id, colony_name=colony_name, reason=reason)
