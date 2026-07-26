import asyncio
import logging
import os
import pathlib
import sys
from dataclasses import dataclass
from typing import Any, Callable, Type

import oxitest
from conftest import SinkWithLogger, Writer
from oxitest import Fixture, StdCapture, TempDir

from loguru import logger

message = "test message"
expected = message + "\n"

NO_STDERR_EXPECTED = "no sink targets stderr here, so anything there is a leak"


@dataclass(frozen=True)
class RepetitionCase:
    rep: int


@dataclass
class PathTypeCase:
    rep: int
    path_type: Callable[[str], Any]


@dataclass(frozen=True)
class AttributeCase:
    value: Any


@dataclass(frozen=True)
class SinkCase:
    sink: Any


REPETITIONS = {
    "none": RepetitionCase(rep=0),
    "once": RepetitionCase(rep=1),
    "twice": RepetitionCase(rep=2),
}

PATH_REPETITIONS = {
    "none": oxitest.partial(PathTypeCase, rep=0),
    "once": oxitest.partial(PathTypeCase, rep=1),
    "twice": oxitest.partial(PathTypeCase, rep=2),
}


def log(sink, rep=1):
    logger.debug("This shouldn't be printed.")
    i = logger.add(sink, format="{message}")
    for _ in range(rep):
        logger.debug(message)
    logger.remove(i)
    logger.debug("This shouldn't be printed neither.")


async def async_log(sink, rep=1):
    logger.debug("This shouldn't be printed.")
    i = logger.add(sink, format="{message}")
    for _ in range(rep):
        logger.debug(message)
    await logger.complete()
    logger.remove(i)
    logger.debug("This shouldn't be printed neither.")


@oxitest.parametrize(**REPETITIONS)
def test_stdout_sink(rep: int, cap: StdCapture) -> None:
    log(sys.stdout, rep)
    captured = cap.readouterr()
    assert captured.out == expected * rep, (
        "sys.stdout must be usable as a sink, receiving exactly the messages logged while "
        "it was attached and none of those logged outside that window"
    )
    assert captured.err == "", NO_STDERR_EXPECTED


@oxitest.parametrize(**REPETITIONS)
def test_stderr_sink(rep: int, cap: StdCapture) -> None:
    log(sys.stderr, rep)
    captured = cap.readouterr()
    assert captured.out == "", "the sink targets stderr, so stdout must stay empty"
    assert captured.err == expected * rep, (
        "sys.stderr must be usable as a sink, receiving exactly the messages logged while "
        "it was attached and none of those logged outside that window"
    )


@oxitest.parametrize(**REPETITIONS)
def test_devnull(rep: int) -> None:
    log(os.devnull, rep)


@oxitest.parametrize(**PATH_REPETITIONS)
@oxitest.parametrize(
    string=oxitest.partial(PathTypeCase, path_type=str),
    pathlib_path=oxitest.partial(PathTypeCase, path_type=pathlib.Path),
)
def test_file_path_sink(rep: int, path_type: Callable[[str], Any], tmp: TempDir) -> None:
    file = tmp.path / "test.log"
    sink = path_type(str(file))
    log(sink, rep)
    assert file.read_text() == expected * rep, (
        "a path given as either a string or a Path must open the same file, since the two "
        "are documented as interchangeable"
    )


@oxitest.parametrize(**REPETITIONS)
def test_file_opened_sink(rep: int, tmp: TempDir) -> None:
    file = tmp.path / "test.log"
    with open(str(file), "w") as sink:
        log(sink, rep)
    assert file.read_text() == expected * rep, (
        "an already-open file must be written to without loguru taking ownership of it, so "
        "the caller's 'with' block still controls when it closes"
    )


@oxitest.parametrize(**REPETITIONS)
def test_file_sink_folder_creation(rep: int, tmp: TempDir) -> None:
    file = tmp.path.joinpath("some", "sub", "folder", "not", "existing", "test.log")
    log(file, rep)
    assert file.read_text() == expected * rep, (
        "missing parent directories must be created, otherwise every application would have "
        "to mkdir its log directory before configuring logging"
    )


@oxitest.parametrize(**REPETITIONS)
def test_function_sink(rep: int) -> None:
    a = []

    def func(log_message):
        a.append(log_message)

    log(func, rep)
    assert a == [expected] * rep, (
        "a plain callable must be usable as a sink, called once per record with the "
        "formatted message"
    )


@oxitest.parametrize(**REPETITIONS)
def test_coroutine_sink(cap: StdCapture, rep: int) -> None:
    async def async_print(msg):
        await asyncio.sleep(0.01)
        print(msg, end="")
        await asyncio.sleep(0.01)

    asyncio.run(async_log(async_print, rep))

    captured = cap.readouterr()
    assert captured.err == "", NO_STDERR_EXPECTED
    assert captured.out == expected * rep, (
        "an async sink must be scheduled per record and awaited by complete(), otherwise "
        "messages would still be pending when the loop closes"
    )


@oxitest.parametrize(**REPETITIONS)
def test_file_object_sink(rep: int) -> None:
    class A:
        def __init__(self):
            self.out = ""

        def write(self, m):
            self.out += m

    a = A()
    log(a, rep)
    assert a.out == expected * rep, (
        "any object with write() must be usable as a sink, so custom file-likes need no " "adapter"
    )


@oxitest.parametrize(**REPETITIONS)
def test_standard_handler_sink(rep: int) -> None:
    out = []

    class H(logging.Handler):
        def emit(self, record):
            out.append(record.getMessage() + "\n")

    h = H()
    log(h, rep)
    assert out == [expected] * rep, (
        "a standard logging.Handler must be usable as a sink, which is what lets loguru "
        "feed an existing logging setup"
    )


@oxitest.parametrize(**REPETITIONS)
def test_flush(rep: int) -> None:
    flushed = []
    out = []

    class A:
        def write(self, m):
            out.append(m)

        def flush(self):
            flushed.append(out[-1])

    log(A(), rep)
    assert flushed == [expected] * rep, (
        "flush() must be called after every record, otherwise a crash would lose whatever "
        "the sink had buffered"
    )


def test_file_sink_ascii_encoding(tmp: TempDir) -> None:
    file = tmp.path / "test.log"
    logger.add(file, encoding="ascii", format="{message}", errors="backslashreplace", catch=False)
    logger.info("天")
    logger.remove()
    assert file.read_text("ascii") == "\\u5929\n", (
        "the encoding and errors arguments must reach open(), so a restricted encoding "
        "degrades the character instead of raising"
    )


def test_file_sink_utf8_encoding(tmp: TempDir) -> None:
    file = tmp.path / "test.log"
    logger.add(file, encoding="utf8", format="{message}", errors="strict", catch=False)
    logger.info("天")
    logger.remove()
    assert file.read_text("utf8") == "天\n", (
        "an explicit utf8 encoding must write the character as-is even under strict error "
        "handling"
    )


def test_file_sink_default_encoding(tmp: TempDir) -> None:
    file = tmp.path / "test.log"
    logger.add(file, format="{message}", errors="strict", catch=False)
    logger.info("天")
    logger.remove()
    assert file.read_text("utf8") == "天\n", (
        "the default encoding must be utf8 rather than the platform's, otherwise the same "
        "code would produce different files on different machines"
    )


def test_disabled_logger_in_sink(sink_with_logger: Fixture[Type[SinkWithLogger]]) -> None:
    sink = sink_with_logger(logger)
    logger.disable(SinkWithLogger.__module__)
    logger.add(sink, format="{message}")
    logger.info("Disabled test")
    assert sink.out == "Disabled test\n", (
        "a sink that logs from a disabled module must still receive records; only the "
        "records it emits itself are suppressed, which is what avoids infinite recursion"
    )


@oxitest.parametrize(
    integer=AttributeCase(value=123),
    none=AttributeCase(value=None),
)
def test_custom_sink_invalid_flush(cap: StdCapture, value: Any) -> None:
    class Sink:
        def __init__(self):
            self.flush = value

        def write(self, message):
            print(message, end="")

    logger.add(Sink(), format="{message}")
    logger.info("Test")

    captured = cap.readouterr()
    assert captured.out == "Test\n", (
        "a non-callable 'flush' attribute must be ignored rather than called, otherwise an "
        "unrelated attribute name would break the sink"
    )
    assert captured.err == "", NO_STDERR_EXPECTED


@oxitest.parametrize(
    integer=AttributeCase(value=123),
    none=AttributeCase(value=None),
)
def test_custom_sink_invalid_stop(cap: StdCapture, value: Any) -> None:
    class Sink:
        def __init__(self):
            self.stop = value

        def write(self, message):
            print(message, end="")

    logger.add(Sink(), format="{message}")
    logger.info("Test")
    logger.remove()

    captured = cap.readouterr()
    assert captured.out == "Test\n", (
        "a non-callable 'stop' attribute must be ignored rather than called, otherwise "
        "remove() would fail on an unrelated attribute name"
    )
    assert captured.err == "", NO_STDERR_EXPECTED


@oxitest.parametrize(
    integer=AttributeCase(value=123),
    none=AttributeCase(value=None),
    zero_argument_callable=AttributeCase(value=lambda: None),
)
def test_custom_sink_invalid_complete(cap: StdCapture, value: Any) -> None:
    class Sink:
        def __init__(self):
            self.complete = value

        def write(self, message):
            print(message, end="")

    async def worker():
        logger.info("Test")
        await logger.complete()

    logger.add(Sink(), format="{message}")
    asyncio.run(worker())

    captured = cap.readouterr()
    assert captured.out == "Test\n", (
        "a 'complete' attribute that is not an awaitable-returning callable must be ignored, "
        "otherwise complete() would fail on an unrelated attribute name"
    )
    assert captured.err == "", NO_STDERR_EXPECTED


@oxitest.parametrize(
    integer=SinkCase(sink=123),
    module=SinkCase(sink=sys),
    object_instance=SinkCase(sink=object()),
    type_object=SinkCase(sink=int),
)
def test_invalid_sink(sink: Any) -> None:
    with oxitest.raises(TypeError):
        log(sink, "")


def test_deprecated_start_and_stop(writer: Fixture[Writer]) -> None:
    with oxitest.warns(DeprecationWarning, match=r"The 'start\(\)' method is deprecated"):
        i = logger.start(writer, format="{message}")
    logger.debug("Test")
    assert writer.read() == "Test\n", (
        "the deprecated alias must keep working, otherwise the warning would be a breaking "
        "change rather than a deprecation"
    )
    writer.clear()
    with oxitest.warns(DeprecationWarning, match=r"The 'stop\(\)' method is deprecated"):
        logger.stop(i)
    logger.debug("Test")
    assert writer.read() == "", (
        "the deprecated alias must keep working, otherwise the warning would be a breaking "
        "change rather than a deprecation"
    )
