"""Data-retention janitor for the per-user HIVE_HOME data directory.

Manual-trigger only (CLI ``hive janitor ...`` or
``POST /api/maintenance/janitor/run``); there is no background scheduler.
See ``retention.py`` for the policy engine and ``janitor.py`` for run
orchestration + reporting.
"""
