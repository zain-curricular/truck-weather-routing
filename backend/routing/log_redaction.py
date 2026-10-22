import logging
import re

# TomTom authenticates with a `key` query parameter, so any logged URL carries it.
_KEY_PARAM = re.compile(r"(key=)[^&\s'\"]+", re.IGNORECASE)


def redact(text: str) -> str:
    return _KEY_PARAM.sub(r"\1[REDACTED]", text)


class RedactSecretsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        return True
