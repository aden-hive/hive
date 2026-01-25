"""OpenTelemetry tracing setup."""

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
import logging


def setup_tracing(
    service_name: str,
    service_version: str = "1.0.0",
    otlp_endpoint: str = "http://localhost:4317",
    enable_console_export: bool = False
) -> trace.Tracer:
    """Initialize OpenTelemetry tracing."""
    # Create resource
    resource = Resource(attributes={
        SERVICE_NAME: service_name,
        SERVICE_VERSION: service_version,
    })

    # Create tracer provider
    provider = TracerProvider(resource=resource)

    # Add OTLP exporter
    otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

    # Add console exporter for debugging
    if enable_console_export:
        console_exporter = ConsoleSpanExporter()
        provider.add_span_processor(BatchSpanProcessor(console_exporter))

    # Set global tracer provider
    trace.set_tracer_provider(provider)

    return trace.get_tracer(__name__)


def instrument_fastapi(app):
    """Instrument FastAPI app for tracing."""
    FastAPIInstrumentor.instrument_app(app)


def instrument_httpx():
    """Instrument HTTPX client for tracing."""
    HTTPXClientInstrumentor().instrument()
