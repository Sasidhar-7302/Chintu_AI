import logging

from chintu_backend.telemetry.trace import SecretRedactionFilter, setup_json_logging


def test_secret_filter_redacts_telegram_token_in_url() -> None:
    token = "8511065473:AAEwx8di3x8o8XYmE21XPS98x3s6cRaRnho"
    record = logging.LogRecord(
        name="httpx",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg=f'HTTP Request: POST https://api.telegram.org/bot{token}/getMe "HTTP/1.1 200 OK"',
        args=(),
        exc_info=None,
    )

    redactor = SecretRedactionFilter()
    redactor.filter(record)

    assert token not in record.msg
    assert "[REDACTED_TELEGRAM_TOKEN]" in record.msg


def test_secret_filter_redacts_literal_env_secret(monkeypatch) -> None:
    secret = "custom_secret_value_123"
    monkeypatch.setenv("DEEPSEEK_API_KEY", secret)

    redactor = SecretRedactionFilter()
    record = logging.LogRecord(
        name="chintu",
        level=logging.INFO,
        pathname=__file__,
        lineno=28,
        msg=f"Provider key loaded: {secret}",
        args=(),
        exc_info=None,
    )

    redactor.filter(record)

    assert secret not in record.msg
    assert "[REDACTED_SECRET]" in record.msg


def test_setup_json_logging_quiets_httpx() -> None:
    setup_json_logging(level=logging.INFO, log_file=None)
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING
    assert logging.getLogger("telegram").level == logging.WARNING

