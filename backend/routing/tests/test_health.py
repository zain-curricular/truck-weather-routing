import logging

from django.test import Client

from routing.log_redaction import RedactSecretsFilter, redact


def test_health_returns_ok():
    response = Client().get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_redact_strips_key_query_parameter():
    url = (
        "https://api.tomtom.com/routing/1/calculateRoute/1,2:3,4/json?key=abc123SECRET&traffic=true"
    )

    assert redact(url) == (
        "https://api.tomtom.com/routing/1/calculateRoute/1,2:3,4/json?key=[REDACTED]&traffic=true"
    )


def test_log_filter_redacts_key_passed_as_format_argument():
    record = logging.LogRecord(
        "routing", logging.ERROR, __file__, 1, "upstream failed: %s", ("/x?key=abc123SECRET",), None
    )

    RedactSecretsFilter().filter(record)

    assert record.getMessage() == "upstream failed: /x?key=[REDACTED]"
