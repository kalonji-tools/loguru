import json
import re

from loguru import logger


class JsonSink:
    def __init__(self):
        self.message = None
        self.dict = None
        self.json = None

    def write(self, message):
        self.message = message
        self.dict = message.record
        self.json = json.loads(message)


def test_serialize() -> None:
    sink = JsonSink()
    logger.add(sink, format="{level} {message}", serialize=True)
    logger.debug("Test")
    assert sink.json["text"] == "DEBUG Test\n", (
        'the "text" key must hold the formatted line, so a consumer can render the message '
        "without re-implementing the format"
    )
    assert sink.dict["message"] == sink.json["record"]["message"] == "Test", (
        "the serialized record must carry the same message as the live record, otherwise "
        "JSON consumers and Python sinks disagree about what was logged"
    )
    assert set(sink.dict.keys()) == set(sink.json["record"].keys()), (
        "serialization must not drop or invent record keys, otherwise the JSON schema "
        "silently diverges from the documented record structure"
    )


def test_serialize_non_ascii_characters() -> None:
    sink = JsonSink()
    logger.add(sink, format="{level.icon} {message}", serialize=True)
    logger.debug("天")
    why = (
        "non-ASCII characters must be emitted as-is rather than \\u-escaped, otherwise log "
        "aggregators show mojibake instead of the original text"
    )
    assert re.search(r'"message": "([^\"]+)"', sink.message).group(1) == "天", why
    assert re.search(r'"text": "([^\"]+)"', sink.message).group(1) == "🐞 天\\n", why
    assert re.search(r'"icon": "([^\"]+)"', sink.message).group(1) == "🐞", why
    assert sink.json["text"] == "🐞 天\n", why
    assert sink.dict["message"] == sink.json["record"]["message"] == "天", why


def test_serialize_exception() -> None:
    sink = JsonSink()
    logger.add(sink, format="{message}", serialize=True, catch=False)

    try:
        1 / 0  # noqa: B018
    except ZeroDivisionError:
        logger.exception("Error")

    lines = sink.json["text"].splitlines()
    assert lines[0] == "Error", "the message must precede the traceback it describes"
    assert lines[-1] == "ZeroDivisionError: division by zero", (
        "the rendered traceback must be included in the text, otherwise JSON logs lose the "
        "detail that makes an error actionable"
    )

    assert sink.json["record"]["exception"] == {
        "type": "ZeroDivisionError",
        "value": "division by zero",
        "traceback": True,
    }, (
        "the exception must also be serialized as structured fields, since a traceback "
        "object itself is not JSON-representable"
    )


def test_serialize_exception_without_context() -> None:
    sink = JsonSink()
    logger.add(sink, format="{message}", serialize=True, catch=False)

    logger.exception("No Error")

    lines = sink.json["text"].splitlines()
    assert lines[0] == "No Error", "the message must precede the exception block"
    assert lines[-1] == "NoneType: None", (
        "logging exception() with nothing in flight must render the empty exception rather "
        "than raise, so a misplaced call cannot break the application"
    )

    assert sink.json["record"]["exception"] == {
        "type": None,
        "value": None,
        "traceback": False,
    }, "the structured fields must say explicitly that there was no exception"


def test_serialize_exception_none_tuple() -> None:
    sink = JsonSink()
    logger.add(sink, format="{message}", serialize=True, catch=False)

    logger.opt(exception=(None, None, None)).error("No Error")

    lines = sink.json["text"].splitlines()
    assert lines[0] == "No Error", "the message must precede the exception block"
    assert lines[-1] == "NoneType: None", (
        "an explicit all-None exception tuple must be handled like no exception at all, "
        "otherwise passing sys.exc_info() outside an except block would crash"
    )

    assert sink.json["record"]["exception"] == {
        "type": None,
        "value": None,
        "traceback": False,
    }, "the structured fields must say explicitly that there was no exception"


def test_serialize_exception_instance() -> None:
    sink = JsonSink()
    logger.add(sink, format="{message}", serialize=True, catch=False)

    logger.opt(exception=ZeroDivisionError("Oops")).error("Failure")

    lines = sink.json["text"].splitlines()
    assert lines[0] == "Failure", "the message must precede the exception block"
    assert lines[-1] == "ZeroDivisionError: Oops", (
        "a bare exception instance must still be rendered, so callers can report an error "
        "they caught earlier and no longer have a traceback for"
    )

    assert sink.json["record"]["exception"] == {
        "type": "ZeroDivisionError",
        "value": "Oops",
        "traceback": False,
    }, "traceback must be False here, since an instance alone carries no stack"


def test_serialize_with_catch_decorator() -> None:
    sink = JsonSink()
    logger.add(sink, format="{message}", serialize=True, catch=False)

    @logger.catch
    def foo():
        1 / 0  # noqa: B018

    foo()

    lines = sink.json["text"].splitlines()
    assert lines[0].startswith("An error has been caught"), (
        "the @catch decorator must prepend its own explanatory message, otherwise the log "
        "does not say why an error was recorded instead of raised"
    )
    assert lines[-1] == "ZeroDivisionError: division by zero", (
        "the caught exception must be rendered into the serialized text like any other"
    )
    assert bool(sink.json["record"]["exception"]), (
        "the structured exception fields must be populated for caught errors too"
    )


def test_serialize_with_record_option() -> None:
    sink = JsonSink()
    logger.add(sink, format="{message}", serialize=True, catch=False)

    logger.opt(record=True).info("Test", foo=123)

    assert sink.json["text"] == "Test\n", (
        "opt(record=True) makes kwargs record fields rather than format arguments, so the "
        "message itself must stay unchanged"
    )
    assert sink.dict["extra"] == {"foo": 123}, (
        "the kwarg must land in extra, otherwise opt(record=True) provides no way to attach "
        "structured data to a single call"
    )


def test_serialize_not_serializable() -> None:
    sink = JsonSink()
    logger.add(sink, format="{message}", catch=False, serialize=True)
    not_serializable = object()
    logger.bind(not_serializable=not_serializable).debug("Test")
    assert sink.dict["extra"]["not_serializable"] == not_serializable, (
        "the live record must keep the original object, so Python sinks are not degraded by "
        "the presence of a JSON sink"
    )
    assert bool(sink.json["record"]["extra"]["not_serializable"]), (
        "a value JSON cannot represent must fall back to its string form rather than abort "
        "the whole record"
    )
