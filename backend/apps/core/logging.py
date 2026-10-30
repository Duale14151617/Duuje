import re
import logging

from .middleware import get_correlation_id


class CorrelationFilter(logging.Filter):
    def filter(self, record):
        record.correlation_id = get_correlation_id() or "-"
        return True


_SENSITIVE = re.compile(
    r"(?i)(password|passwd|temporary_password|new_password|current_password|otp|token|secret|authorization|cookie|csrf|session)"
    r"(\"?'?\s*[:=]\s*)(\"?'?)[^\s,\"'&}]+")


_AUTH_HEADER = re.compile(r"(?i)(authorization\s*[:=]\s*)(?:(?:bearer|basic)\s+)?\S+")


def redact(text):
    text = _AUTH_HEADER.sub(r"\1[redacted]", text)
    return _SENSITIVE.sub(r"\1\2\3[redacted]", text)


class RedactingFilter(logging.Filter):
    """Last line of defence: scrub secrets that might be interpolated into a log message."""

    def filter(self, record):
        try:
            message = record.getMessage()
        except Exception:
            return True
        cleaned = redact(message)
        if cleaned != message:
            record.msg, record.args = cleaned, ()
        return True
