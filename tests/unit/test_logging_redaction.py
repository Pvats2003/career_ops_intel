"""Security-fix tests for the centralized redaction boundary
(`job_agent.logging.setup`), added after the Phase 6A read-only audit
found that `log_event()`'s `error` parameter bypassed redaction entirely,
and that structured redaction only matched dict/list *keys* — never a
secret embedded inside a longer free-text string (exactly the shape a
real leak takes: "request failed: api_key=sk-abc123 ...").

These tests exercise the fix at three levels: the raw `redact_value()`/
`redact_text()` functions, the `log_event()`/`JsonFormatter` logging
boundary, and (in `test_applications_repository.py` /
`test_applications_service.py`) the DB-persisted audit trail and the
Phase 6A batch-isolation error paths that motivated the fix.
"""

from __future__ import annotations

import json
import logging
import sys

from job_agent.logging.setup import JsonFormatter, get_logger, log_event, redact_text, redact_value


# --------------------------------------------------------------------------
# redact_value — dict/list key-based redaction
# --------------------------------------------------------------------------
def test_password_key_redacted():
    assert redact_value({"password": "hunter2"}) == {"password": "***REDACTED***"}


def test_passwd_key_redacted():
    assert redact_value({"passwd": "hunter2"}) == {"passwd": "***REDACTED***"}


def test_access_token_key_redacted():
    assert redact_value({"access_token": "abc123xyz"}) == {"access_token": "***REDACTED***"}


def test_refresh_token_key_redacted():
    assert redact_value({"refresh_token": "abc123xyz"}) == {"refresh_token": "***REDACTED***"}


def test_bearer_token_key_redacted():
    assert redact_value({"bearer_token": "abc123xyz"}) == {"bearer_token": "***REDACTED***"}


def test_client_secret_key_redacted():
    assert redact_value({"client_secret": "abc123xyz"}) == {"client_secret": "***REDACTED***"}


def test_api_key_and_secret_keys_redacted():
    assert redact_value({"api_key": "sk-abc123"}) == {"api_key": "***REDACTED***"}
    assert redact_value({"secret": "topsecret"}) == {"secret": "***REDACTED***"}
    assert redact_value({"apikey": "abc123"}) == {"apikey": "***REDACTED***"}


def test_authorization_header_key_redacted():
    assert redact_value({"Authorization": "Bearer abc.def.ghi"}) == {
        "Authorization": "***REDACTED***"
    }


def test_cookie_and_session_keys_redacted():
    assert redact_value({"cookie": "session=abc123"}) == {"cookie": "***REDACTED***"}
    assert redact_value({"session_token": "xyz"}) == {"session_token": "***REDACTED***"}
    assert redact_value({"session_id": "xyz"}) == {"session_id": "***REDACTED***"}


def test_key_matching_is_case_insensitive():
    assert redact_value({"PASSWORD": "hunter2"}) == {"PASSWORD": "***REDACTED***"}
    assert redact_value({"Api_Key": "sk-abc"}) == {"Api_Key": "***REDACTED***"}


# --------------------------------------------------------------------------
# redact_text — content-pattern redaction of unstructured strings (the
# actual gap the audit found: str(exc) never arrives as a convenient dict)
# --------------------------------------------------------------------------
def test_password_embedded_in_free_text_redacted():
    text = "login failed: password=hunter2 for user bob"
    result = redact_text(text)
    assert "hunter2" not in result
    assert "***REDACTED***" in result


def test_access_token_embedded_in_free_text_redacted():
    text = "oauth refresh failed: access_token=abcDEF123xyz invalid"
    result = redact_text(text)
    assert "abcDEF123xyz" not in result


def test_refresh_token_embedded_in_free_text_redacted():
    text = "oauth error: refresh_token=abcDEF123xyz invalid"
    result = redact_text(text)
    assert "abcDEF123xyz" not in result


def test_api_key_and_secret_embedded_in_free_text_redacted():
    assert "sk-liveSECRET1234567890" not in redact_text(
        "Anthropic call failed: api_key=sk-liveSECRET1234567890"
    )
    assert "topsecretvalue" not in redact_text("config error: secret=topsecretvalue")


def test_authorization_header_embedded_in_free_text_redacted():
    text = "HTTP 401 from provider: Authorization: Bearer abc.def.ghi rejected"
    result = redact_text(text)
    assert "abc.def.ghi" not in result


def test_bearer_token_without_header_prefix_redacted():
    text = "client sent Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature and got 403"
    result = redact_text(text)
    assert "eyJhbGciOiJIUzI1NiJ9" not in result


def test_cookie_header_embedded_in_free_text_redacted():
    text = "response failed; Cookie: session=abc123secret; path=/"
    result = redact_text(text)
    assert "abc123secret" not in result


def test_url_embedded_credential_redacted():
    """A connection-string-shaped credential (scheme://user:password@host)
    — e.g. a non-SQLite DATABASE_URL — has no literal "password=" text, so
    none of the key=value patterns would catch it; this is a distinct
    shape requiring its own pattern."""
    text = "could not connect to postgresql://dbuser:hunter2secret@db.internal:5432/jobs"
    result = redact_text(text)
    assert "hunter2secret" not in result
    assert "dbuser" in result  # username preserved — only the password is secret
    assert "db.internal" in result  # host is diagnostic, not secret


def test_sqlite_url_with_no_credentials_passes_through_unchanged():
    text = "connected to sqlite:///./data/job_agent.db"
    assert redact_text(text) == text


def test_opaque_anthropic_style_key_embedded_anywhere_redacted():
    """The original regex was anchored (^sk-...$) and could only match a
    string that was *entirely* the key — never one embedded in a longer
    message, which is the realistic shape of a leak."""
    text = "provider health check failed using key sk-ant-abc123DEF456ghi789 at startup"
    result = redact_text(text)
    assert "sk-ant-abc123DEF456ghi789" not in result


def test_jwt_shaped_token_redacted():
    text = "decoded token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dGVzdHNpZw was invalid"
    result = redact_text(text)
    assert "eyJhbGciOiJIUzI1NiJ9" not in result


def test_ordinary_diagnostic_text_passes_through_unchanged():
    text = "job 42 failed to prepare: provider manual_review timed out after 3 attempts"
    assert redact_text(text) == text


def test_empty_and_none_text_handled_safely():
    assert redact_text("") == ""


# --------------------------------------------------------------------------
# Nested structures and non-sensitive fields
# --------------------------------------------------------------------------
def test_nested_sensitive_structures_are_redacted():
    payload = {
        "request": {
            "headers": {"Authorization": "Bearer abc123", "cookie": "session=xyz"},
            "body": {"password": "hunter2", "items": [{"secret": "s3cr3t"}]},
        },
        "job_id": 42,
    }
    result = redact_value(payload)
    assert result["request"]["headers"]["Authorization"] == "***REDACTED***"
    assert result["request"]["headers"]["cookie"] == "***REDACTED***"
    assert result["request"]["body"]["password"] == "***REDACTED***"
    assert result["request"]["body"]["items"][0]["secret"] == "***REDACTED***"
    assert result["job_id"] == 42  # untouched — see next test


def test_ordinary_non_sensitive_diagnostic_fields_remain_visible():
    payload = {
        "component": "applications.service",
        "action": "submit_applications_batch_item",
        "result": "failure",
        "job_id": 42,
        "application_id": 7,
        "provider": "manual_review",
        "status": "PREPARED",
        "company_name": "Acme",
    }
    assert redact_value(payload) == payload


def test_free_text_error_nested_inside_a_list_is_redacted():
    payload = {"errors": ["auth failed: password=hunter2", "timeout after 3s"]}
    result = redact_value(payload)
    assert "hunter2" not in result["errors"][0]
    assert result["errors"][1] == "timeout after 3s"  # non-sensitive text untouched


# --------------------------------------------------------------------------
# log_event() — the actual logging boundary, not just the helper functions
# --------------------------------------------------------------------------
def test_log_event_redacts_the_error_parameter(caplog):
    """This is precisely the gap the audit found: `error=` used to bypass
    redaction entirely because only `**details` was passed through
    `_redact()`."""
    logger = get_logger("test.redaction.error_param")
    with caplog.at_level(logging.ERROR, logger="test.redaction.error_param"):
        log_event(
            logger, component="test", action="x", result="failure",
            error="auth failed: password=hunter2",
        )
    record = caplog.records[-1]
    assert "hunter2" not in record.event_data["error"]
    assert "***REDACTED***" in record.event_data["error"]


def test_log_event_redacts_sensitive_keys_in_details(caplog):
    logger = get_logger("test.redaction.details")
    with caplog.at_level(logging.INFO, logger="test.redaction.details"):
        log_event(
            logger, component="test", action="x", result="success",
            api_key="sk-liveSECRET1234567890", job_id=42,
        )
    record = caplog.records[-1]
    assert record.event_data["api_key"] == "***REDACTED***"
    assert record.event_data["job_id"] == 42


def test_log_event_none_error_stays_none(caplog):
    """redact_text(None) must not be called / must not crash — error=None
    is the common case (a successful event) and must round-trip as None."""
    logger = get_logger("test.redaction.none_error")
    with caplog.at_level(logging.INFO, logger="test.redaction.none_error"):
        log_event(logger, component="test", action="x", result="success", job_id=1)
    record = caplog.records[-1]
    assert record.event_data["error"] is None


# --------------------------------------------------------------------------
# JsonFormatter — the log line actually written to stdout, including
# formatted exception tracebacks
# --------------------------------------------------------------------------
def _make_record_with_exception(message: str) -> logging.LogRecord:
    try:
        raise ValueError(message)
    except ValueError:
        return logging.LogRecord(
            name="test.formatter", level=logging.ERROR, pathname=__file__, lineno=1,
            msg="boom", args=(), exc_info=sys.exc_info(),
        )


def test_json_formatter_redacts_exception_message_in_traceback():
    formatter = JsonFormatter()
    record = _make_record_with_exception("token=abc123XYZsecretvalue in header")
    payload = json.loads(formatter.format(record))
    assert "abc123XYZsecretvalue" not in payload["exception"]
    assert "***REDACTED***" in payload["exception"]


def test_json_formatter_redacts_event_data():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="test.formatter", level=logging.INFO, pathname=__file__, lineno=1,
        msg="x", args=(), exc_info=None,
    )
    record.event_data = {"password": "hunter2", "job_id": 1}
    payload = json.loads(formatter.format(record))
    assert payload["password"] == "***REDACTED***"
    assert payload["job_id"] == 1


def test_json_formatter_redacts_the_log_message_itself():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="test.formatter", level=logging.INFO, pathname=__file__, lineno=1,
        msg="auth failed: password=hunter2", args=(), exc_info=None,
    )
    payload = json.loads(formatter.format(record))
    assert "hunter2" not in payload["message"]
