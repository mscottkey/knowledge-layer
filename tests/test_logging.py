import json
import logging

from core.logging import DevelopmentFormatter, JSONFormatter


def record(**extra) -> logging.LogRecord:
    rec = logging.LogRecord("knowledgelayer.test", logging.INFO, __file__, 1, "something happened", (), None)
    for key, value in extra.items():
        setattr(rec, key, value)
    return rec


def test_json_logs_include_extra_fields():
    out = json.loads(JSONFormatter().format(record(tenant_id="t-1", attempts=2)))
    assert out["message"] == "something happened"
    assert out["tenant_id"] == "t-1"
    assert out["attempts"] == 2


def test_json_logs_do_not_leak_logging_internals():
    out = json.loads(JSONFormatter().format(record()))
    assert set(out) == {"timestamp", "level", "logger", "message"}


def test_json_logs_survive_values_that_are_not_json():
    out = json.loads(JSONFormatter().format(record(thing=object())))
    assert "thing" in out


def test_development_logs_show_extra_fields():
    line = DevelopmentFormatter().format(record(article_id="a-1"))
    assert "something happened" in line
    assert "article_id=a-1" in line
