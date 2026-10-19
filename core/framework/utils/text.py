"""Small text helpers shared across the framework."""

from __future__ import annotations


def humanize_slug(slug: str) -> str:
    """Turn an on-disk slug into a human-readable display name.

    ``"09_hubspot_parteners"`` -> ``"09 Hubspot Parteners"``. Used for
    browser tab-group labels and UI listings so colony/worker directory
    names render nicely without maintaining a separate stored display name.
    """
    return slug.replace("_", " ").title()
