"""
RTA-GUARD Observability — OpenTelemetry Export

Exports guard traces as OpenTelemetry spans and metrics.
Integrates with Jaeger, Datadog, New Relic, and any OTel-compatible backend.

Gracefully degrades if opentelemetry is not installed.
"""
import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("discus.observability.otel")

# Try to import OpenTelemetry
try:
    from opentelemetry import trace, metrics
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    HAS_OTEL = True
except ImportError:
    HAS_OTEL = False
    logger.info("OpenTelemetry not installed — OTel export disabled")


class OTelExporter:
    """
    Exports guard traces as OpenTelemetry spans and metrics.

    Usage:
        exporter = OTelExporter(service_name="rta-guard")
        exporter.record_check(decision="kill", rule="pii", duration_ms=2.5)
    """

    def __init__(self, service_name: str = "rta-guard",
                 endpoint: Optional[str] = None,
                 enabled: bool = True):
        self.enabled = enabled and HAS_OTEL
        self.service_name = service_name

        if not self.enabled:
            return

        # Setup tracer
        resource = Resource.create({"service.name": service_name})
        tracer_provider = TracerProvider(resource=resource)

        if endpoint:
            exporter = OTLPSpanExporter(endpoint=endpoint)
            tracer_provider.add_span_processor(BatchSpanProcessor(exporter))

        trace.set_tracer_provider(tracer_provider)
        self.tracer = trace.get_tracer(__name__)

        # Setup meter
        meter_provider = MeterProvider(resource=resource)
        metrics.set_meter_provider(meter_provider)
        meter = metrics.get_meter(__name__)

        # Create instruments
        self.check_counter = meter.create_counter(
            name="rta_guard.checks",
            description="Total guard checks",
            unit="1",
        )
        self.violation_counter = meter.create_counter(
            name="rta_guard.violations",
            description="Total violations detected",
            unit="1",
        )
        self.duration_histogram = meter.create_histogram(
            name="rta_guard.check_duration",
            description="Guard check duration",
            unit="ms",
        )
        self.token_counter = meter.create_counter(
            name="rta_guard.tokens_saved",
            description="Tokens saved by early termination",
            unit="tokens",
        )

    def record_check(self, decision: str, rule: str = "",
                     duration_ms: float = 0, session_id: str = "",
                     tenant_id: str = "", violation_type: str = "",
                     tokens_saved: int = 0) -> None:
        """Record a guard check as an OTel span + metrics."""
        if not self.enabled:
            return

        try:
            # Create span
            with self.tracer.start_as_current_span("rta_guard.check") as span:
                span.set_attribute("rta_guard.decision", decision)
                span.set_attribute("rta_guard.rule", rule)
                span.set_attribute("rta_guard.session_id", session_id)
                span.set_attribute("rta_guard.tenant_id", tenant_id)
                span.set_attribute("rta_guard.violation_type", violation_type)
                span.set_attribute("rta_guard.duration_ms", duration_ms)

                if decision == "kill":
                    span.set_status(trace.StatusCode.ERROR, "Session killed")
                elif decision == "warn":
                    span.set_status(trace.StatusCode.OK, "Warning issued")
                else:
                    span.set_status(trace.StatusCode.OK, "Passed")

            # Record metrics
            self.check_counter.add(1, {"decision": decision, "rule": rule})
            self.duration_histogram.record(duration_ms, {"rule": rule})

            if decision in ("kill", "warn"):
                self.violation_counter.add(1, {
                    "decision": decision,
                    "violation_type": violation_type,
                })

            if tokens_saved > 0:
                self.token_counter.add(tokens_saved, {"decision": decision})

        except Exception as e:
            logger.debug(f"OTel export error: {e}")

    def is_available(self) -> bool:
        return HAS_OTEL
