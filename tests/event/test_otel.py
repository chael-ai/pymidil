"""Phase 1 OTel foundation: carrier round-trip + span lineage + discontinuity."""

from pymidil.event.otel import (
    DISCONTINUITY_ATTR,
    coerce_header_value,
    consumer_span,
    current_trace_ids,
    inject_headers,
    producer_span,
)

# The TracerProvider + `spans` exporter fixture come from tests/event/conftest.py.


def test_producer_injects_and_consumer_continues_trace(spans):
    carrier: dict = {}
    with producer_span("orders"):
        inject_headers(carrier)
        producer_trace, producer_span_id = current_trace_ids()

    assert "traceparent" in carrier  # W3C header written to the carrier

    with consumer_span(carrier, "orders-svc") as (_span, parent_span_id):
        consumer_trace, consumer_span_id = current_trace_ids()

    assert consumer_trace == producer_trace  # same distributed trace
    assert parent_span_id == producer_span_id  # child of the producer span
    assert consumer_span_id != producer_span_id


def test_empty_carrier_roots_and_flags_discontinuity(spans):
    with consumer_span({}, "orders-svc") as (_span, parent_span_id):
        pass

    assert parent_span_id is None  # no upstream context

    finished = {s.name: s for s in spans.get_finished_spans()}
    consumer = finished["process orders-svc"]
    assert consumer.attributes.get(DISCONTINUITY_ATTR) is True


def test_current_trace_ids_none_outside_span():
    # No active recording span -> invalid context.
    trace_id, span_id = current_trace_ids()
    assert trace_id is None and span_id is None


def test_coerce_header_value_flattens_carrier_shapes():
    # Flat header, SQS MessageAttribute shape, and absent -> normalised to str|None.
    assert coerce_header_value("abc") == "abc"
    assert coerce_header_value({"StringValue": "abc", "DataType": "String"}) == "abc"
    assert coerce_header_value({"Value": "v"}) == "v"
    assert coerce_header_value(None) is None
    assert coerce_header_value({"DataType": "String"}) is None  # no value key
