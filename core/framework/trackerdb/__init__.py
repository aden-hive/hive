"""Shared plumbing for Hive's terminal CLIs.

* :mod:`~framework.trackerdb.errors` — exit-code taxonomy + dispatch harness, used by
  ``hive-cred`` (:mod:`framework.credentials.cli`).

The path matches hive-desktop-runtime, where this package also holds the
``hive-tracker`` CLI, so code moves between the two unchanged.
"""

from __future__ import annotations
