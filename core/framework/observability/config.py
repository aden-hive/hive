"""
Configuration for the observability framework.

This module provides configuration dataclasses for setting up
observability hooks, exporters, and telemetry options.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ObservabilityConfig:
    """
    Configuration for the observability framework.

    This configuration controls how observability hooks are set up
    and what exporters are enabled.

    Attributes:
        enabled: Whether observability is enabled. When False, all hooks
            are no-ops with zero overhead.
        exporters: List of exporter instances to use. Exporters implement
            the ObservabilityHooks protocol and receive all events.
        sample_rate: Fraction of events to sample (0.0 to 1.0). Useful for
            reducing overhead in high-throughput production environments.
        trace_enabled: Whether to enable distributed tracing via OpenTelemetry.
        metrics_enabled: Whether to enable metrics collection.
        log_sensitive_data: Whether to include potentially sensitive data
            (like input/output content) in traces and logs.
        service_name: Service name for OpenTelemetry resource identification.
        service_version: Service version for OpenTelemetry resource identification.
        otlp_endpoint: OTLP endpoint URL for exporting traces/metrics.
            Example: "http://localhost:4317" for Jaeger with OTLP.
        prometheus_port: Port for Prometheus metrics endpoint. Set to 0 to disable.
        file_export_path: Path for file-based JSON Lines export. Set to None to disable.

    Example:
        config = ObservabilityConfig(
            enabled=True,
            exporters=[ConsoleExporter(verbose=True)],
            sample_rate=1.0,
        )
    """

    enabled: bool = True
    exporters: list[Any] = field(default_factory=list)
    sample_rate: float = 1.0
    trace_enabled: bool = True
    metrics_enabled: bool = True
    log_sensitive_data: bool = False
    service_name: str = "hive-agent"
    service_version: str = "0.1.0"
    otlp_endpoint: str | None = None
    prometheus_port: int = 0
    file_export_path: Path | str | None = None

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if not 0.0 <= self.sample_rate <= 1.0:
            raise ValueError(f"sample_rate must be between 0.0 and 1.0, got {self.sample_rate}")

        if isinstance(self.file_export_path, str):
            self.file_export_path = Path(self.file_export_path)

    @classmethod
    def dev(cls) -> "ObservabilityConfig":
        """
        Create a development configuration with console output.

        Returns:
            ObservabilityConfig configured for local development.
        """
        return cls(
            enabled=True,
            exporters=[],
            sample_rate=1.0,
            log_sensitive_data=True,
        )

    @classmethod
    def production(
        cls,
        otlp_endpoint: str | None = None,
        prometheus_port: int = 9090,
        sample_rate: float = 0.1,
    ) -> "ObservabilityConfig":
        """
        Create a production configuration.

        Args:
            otlp_endpoint: OTLP endpoint for traces/metrics export.
            prometheus_port: Port for Prometheus metrics scraping.
            sample_rate: Sampling rate for events (lower for high throughput).

        Returns:
            ObservabilityConfig configured for production use.
        """
        return cls(
            enabled=True,
            exporters=[],
            sample_rate=sample_rate,
            log_sensitive_data=False,
            otlp_endpoint=otlp_endpoint,
            prometheus_port=prometheus_port,
            trace_enabled=True,
            metrics_enabled=True,
        )

    @classmethod
    def disabled(cls) -> "ObservabilityConfig":
        """
        Create a disabled configuration with zero overhead.

        Returns:
            ObservabilityConfig with all observability disabled.
        """
        return cls(
            enabled=False,
            exporters=[],
            sample_rate=0.0,
        )


@dataclass
class TelemetryConfig:
    """
    Configuration for OpenTelemetry telemetry.

    This configuration controls how telemetry (traces, metrics, logs)
    is collected and exported via OpenTelemetry.

    Attributes:
        tracer_name: Name of the tracer to use.
        meter_name: Name of the meter to use.
        resource_attributes: Additional resource attributes for telemetry.
        span_processor: Type of span processor ("batch" or "simple").
        export_timeout_ms: Timeout for OTLP exports in milliseconds.
        max_export_batch_size: Maximum batch size for exports.
        schedule_delay_ms: Delay between batch exports.
    """

    tracer_name: str = "hive.agent"
    meter_name: str = "hive.agent"
    resource_attributes: dict[str, str] = field(default_factory=dict)
    span_processor: str = "batch"
    export_timeout_ms: int = 30000
    max_export_batch_size: int = 512
    schedule_delay_ms: int = 5000
