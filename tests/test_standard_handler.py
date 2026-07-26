import sys
from dataclasses import dataclass
from logging import FileHandler, Filter, Formatter, Handler, NullHandler, StreamHandler

import oxitest
from oxitest import StdCapture, TempDir

from loguru import logger

NO_STDERR_EXPECTED = "no handler targets stderr here, so anything there is a leak"


@dataclass(frozen=True)
class DynamicFormatCase:
    dynamic_format: bool


DYNAMIC_FORMAT_CASES = {
    "static": DynamicFormatCase(dynamic_format=False),
    "callable": DynamicFormatCase(dynamic_format=True),
}


class RejectAllFilter(Filter):
    def filter(self, record):
        return False


def test_stream_handler(cap: StdCapture) -> None:
    logger.add(StreamHandler(sys.stderr), format="{level} {message}")
    logger.info("test")
    logger.remove()
    logger.warning("nope")

    captured = cap.readouterr()
    assert captured.out == "", "the handler targets stderr, so stdout must stay empty"
    assert captured.err == "INFO test\n", (
        "a standard Handler must work as a loguru sink and stop receiving records once "
        "removed, like any other sink"
    )


def test_file_handler(tmp: TempDir) -> None:
    file = tmp.path / "test.log"
    logger.add(FileHandler(str(file)), format="{message} {level.name}")
    logger.info("test")
    logger.remove()
    logger.warning("nope")

    assert file.read_text() == "test INFO\n", (
        "a standard FileHandler must receive the loguru-formatted message and be closed on "
        "remove(), otherwise the file would keep growing after the sink is gone"
    )


def test_null_handler(cap: StdCapture) -> None:
    logger.add(NullHandler())
    logger.error("nope")
    logger.remove()

    captured = cap.readouterr()
    assert captured.out == "", "a NullHandler must discard records rather than print them"
    assert captured.err == "", "a NullHandler must discard records rather than print them"


def test_extra_dict(cap: StdCapture) -> None:
    handler = StreamHandler(sys.stdout)
    formatter = Formatter("%(extra)s %(message)s")
    handler.setFormatter(formatter)
    logger.add(handler, format="<{extra[abc]}> {message}", catch=False)
    logger.bind(abc=123).info("Extra!")
    captured = cap.readouterr()
    assert captured.out == "{'abc': 123} <123> Extra!\n", (
        "the bound extra dict must be exposed to the standard formatter as %(extra)s, so "
        "existing logging configurations can reach loguru's structured data"
    )
    assert captured.err == "", NO_STDERR_EXPECTED


def test_no_conflict_with_extra_dict(cap: StdCapture) -> None:
    handler = StreamHandler(sys.stdout)
    logger.add(handler, format="{message}", catch=False)
    logger.bind(args=True, name="foobar", message="Wut?").info("OK!")
    captured = cap.readouterr()
    assert captured.out == "OK!\n", (
        "extra keys that collide with LogRecord attributes must not overwrite them, "
        "otherwise binding a key named 'message' would corrupt the record"
    )
    assert captured.err == "", NO_STDERR_EXPECTED


def test_no_exception() -> None:
    result = None

    class NoExceptionHandler(Handler):
        def emit(self, record):
            nonlocal result
            result = bool(not record.exc_info)

    logger.add(NoExceptionHandler())

    try:
        1 / 0  # noqa: B018
    except ZeroDivisionError:
        logger.exception("Error")

    assert result is False, (
        "exc_info must be populated on the standard record, otherwise handlers that render "
        "tracebacks themselves would show nothing"
    )


def test_exception(cap: StdCapture) -> None:
    result = None

    class ExceptionHandler(Handler):
        def emit(self, record):
            nonlocal result
            result = bool(record.exc_info)

    logger.add(ExceptionHandler())

    try:
        1 / 0  # noqa: B018
    except ZeroDivisionError:
        logger.exception("Error")

    assert result is True, (
        "exc_info must be populated on the standard record, otherwise handlers that render "
        "tracebacks themselves would show nothing"
    )


def test_exception_formatting(tmp: TempDir) -> None:
    file = tmp.path / "test.log"
    logger.add(FileHandler(str(file)), format="{message}")

    try:
        1 / 0  # noqa: B018
    except ZeroDivisionError:
        logger.exception("Error")

    result = file.read_text()
    lines = result.strip().splitlines()

    error = "ZeroDivisionError: division by zero"

    assert lines[1].startswith("Traceback"), "the traceback must follow the message"
    assert lines[-1] == error, "the traceback must end with the exception line"
    assert result.count(error) == 1, (
        "the traceback must be rendered exactly once; twice means both loguru and the "
        "standard handler formatted the same exc_info"
    )


@oxitest.parametrize(**DYNAMIC_FORMAT_CASES)
def test_standard_formatter(cap: StdCapture, dynamic_format: bool) -> None:
    def format_(x):
        return "{level.no} {message} [Not Chopped]"

    if not dynamic_format:
        format_ = format_(None)

    handler = StreamHandler(sys.stdout)
    formatter = Formatter("%(message)s %(levelname)s")
    handler.setFormatter(formatter)
    logger.add(handler, format=format_)
    logger.info("Test")
    captured = cap.readouterr()
    assert captured.out == "20 Test [Not Chopped] INFO\n", (
        "the loguru-formatted text becomes %(message)s for the standard formatter, and must "
        "be passed whole rather than truncated at the message field"
    )
    assert captured.err == "", NO_STDERR_EXPECTED


@oxitest.parametrize(**DYNAMIC_FORMAT_CASES)
def test_standard_formatter_with_new_line(cap: StdCapture, dynamic_format: bool) -> None:
    def format_(x):
        return "{level.no} {message}\n"

    if not dynamic_format:
        format_ = format_(None)

    handler = StreamHandler(sys.stdout)
    formatter = Formatter("%(message)s %(levelname)s")
    handler.setFormatter(formatter)
    logger.add(handler, format=format_)
    logger.info("Test")
    captured = cap.readouterr()
    assert captured.out == "20 Test\n INFO\n", (
        "a trailing newline in the loguru format is part of the message text, so the "
        "standard formatter appends after it rather than replacing it"
    )
    assert captured.err == "", NO_STDERR_EXPECTED


@oxitest.parametrize(**DYNAMIC_FORMAT_CASES)
def test_raw_standard_formatter(cap: StdCapture, dynamic_format: bool) -> None:
    def format_(x):
        return "{level.no} {message} [Not Chopped]"

    if not dynamic_format:
        format_ = format_(None)

    handler = StreamHandler(sys.stdout)
    formatter = Formatter("%(message)s %(levelname)s")
    handler.setFormatter(formatter)
    logger.add(handler, format=format_)
    logger.opt(raw=True).info("Test")
    captured = cap.readouterr()
    assert captured.out == "Test INFO\n", (
        "opt(raw=True) skips the loguru format, so the standard formatter must receive the "
        "bare message"
    )
    assert captured.err == "", NO_STDERR_EXPECTED


@oxitest.parametrize(**DYNAMIC_FORMAT_CASES)
def test_raw_standard_formatter_with_new_line(cap: StdCapture, dynamic_format: bool) -> None:
    def format_(x):
        return "{level.no} {message}\n"

    if not dynamic_format:
        format_ = format_(None)

    handler = StreamHandler(sys.stdout)
    formatter = Formatter("%(message)s %(levelname)s")
    handler.setFormatter(formatter)
    logger.add(handler, format=format_)
    logger.opt(raw=True).info("Test")
    captured = cap.readouterr()
    assert captured.out == "Test INFO\n", (
        "in raw mode the loguru format is not applied at all, so its trailing newline must "
        "not appear either"
    )
    assert captured.err == "", NO_STDERR_EXPECTED


def test_standard_formatter_with_non_standard_level_name(cap: StdCapture) -> None:
    handler = StreamHandler(sys.stdout)
    formatter = Formatter("%(levelno)s | %(levelname)s | %(message)s")
    handler.setFormatter(formatter)
    logger.add(handler, format="{message}")
    logger.success("Test")
    captured = cap.readouterr()
    assert captured.out == "25 | SUCCESS | Test\n", (
        "loguru levels with no standard counterpart must still be reported by name and "
        "number, otherwise SUCCESS would show up as an unnamed severity"
    )
    assert captured.err == "", NO_STDERR_EXPECTED


def test_standard_formatter_with_custom_level_name(cap: StdCapture) -> None:
    handler = StreamHandler(sys.stdout)
    formatter = Formatter("%(levelno)s | %(levelname)s | %(message)s")
    handler.setFormatter(formatter)
    logger.add(handler, format="{message}")
    logger.level("CUSTOM", no=35)
    logger.log("CUSTOM", "Test")
    captured = cap.readouterr()
    assert captured.out == "35 | CUSTOM | Test\n", (
        "a level registered by the application must reach the standard formatter by name, "
        "without having to be registered with the logging module as well"
    )
    assert captured.err == "", NO_STDERR_EXPECTED


def test_standard_formatter_with_unregistered_level(cap: StdCapture) -> None:
    handler = StreamHandler(sys.stdout)
    formatter = Formatter("%(levelno)s | %(levelname)s | %(message)s")
    handler.setFormatter(formatter)
    logger.add(handler, format="{message}")
    logger.log(45, "Test")
    captured = cap.readouterr()
    assert captured.out == "45 | Level 45 | Test\n", (
        "a bare severity number with no registered name must fall back to 'Level N' rather "
        "than leave %(levelname)s empty"
    )
    assert captured.err == "", NO_STDERR_EXPECTED


def test_standard_handler_with_configured_filter(cap: StdCapture) -> None:
    handler = StreamHandler(sys.stdout)
    filter_ = RejectAllFilter()
    logger.add(handler, format="{message}")
    logger.info("a")
    handler.addFilter(filter_)
    logger.info("b")
    handler.removeFilter(filter_)
    logger.info("c")
    captured = cap.readouterr()
    assert captured.out == "a\nc\n", (
        "the handler's own filters must be consulted for every record, so a handler can be "
        "reconfigured after it was handed to loguru"
    )
    assert captured.err == "", NO_STDERR_EXPECTED


def test_standard_handler_with_configured_level(cap: StdCapture) -> None:
    handler = StreamHandler(sys.stdout)
    logger.add(handler, format="{message}")
    logger.info("a")
    handler.setLevel("WARNING")
    logger.info("b")
    handler.setLevel("INFO")
    logger.info("c")
    captured = cap.readouterr()
    assert captured.out == "a\nc\n", (
        "the handler's own level must be consulted for every record, so a handler can be "
        "reconfigured after it was handed to loguru"
    )
    assert captured.err == "", NO_STDERR_EXPECTED
