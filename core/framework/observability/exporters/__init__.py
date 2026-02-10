"""Built-in observability exporters.

All exporters implement ``ObservabilityHooks`` and can be composed via
``CompositeHooks`` to run multiple simultaneously.

Available exporters:
- ``ConsoleExporter``  — pretty-printed real-time output for development
- ``FileExporter``     — JSON Lines for local analysis
"""
