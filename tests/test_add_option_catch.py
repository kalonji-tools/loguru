import re
import sys
import time
from dataclasses import dataclass

import oxitest
import conftest
from conftest import Writer
from oxitest import Fixture, StdCapture

from loguru import logger


@dataclass(frozen=True)
class EnqueueCase:
    enqueue: bool


ENQUEUE_CASES = {
    "direct": EnqueueCase(enqueue=False),
    "enqueued": EnqueueCase(enqueue=True),
}


def broken_sink(m):
    raise ValueError("Error!")


def test_catch_is_true(cap: StdCapture) -> None:
    logger.add(broken_sink, catch=True)
    logger.debug("Fail")
    captured = cap.readouterr()
    assert captured.out == "", "the error report goes to stderr, so stdout must stay empty"
    assert captured.err != "", (
        "catch=True must swallow the sink's exception but still report it, otherwise a "
        "broken sink fails completely silently"
    )


def test_catch_is_false(cap: StdCapture) -> None:
    logger.add(broken_sink, catch=False)
    with oxitest.raises(ValueError, match="Error!"):
        logger.debug("Fail")
    captured = cap.readouterr()
    assert captured.out == captured.err == "", (
        "catch=False must let the exception propagate untouched, so loguru must not also "
        "print a report of its own"
    )


def test_no_sys_stderr(cap: StdCapture) -> None:
    with conftest.patch_context() as context:
        context.setattr(sys, "stderr", None)
        logger.add(broken_sink, catch=True)
        logger.debug("a")

        captured = cap.readouterr()
        assert captured.out == captured.err == "", (
            "with no stderr to report to, the error must be dropped rather than raised — "
            "pythonw and frozen apps run with sys.stderr set to None"
        )


def test_broken_sys_stderr(cap: StdCapture) -> None:
    def broken_write(*args, **kwargs):
        raise OSError

    with conftest.patch_context() as context:
        context.setattr(sys.stderr, "write", broken_write)
        logger.add(broken_sink, catch=True)
        logger.debug("a")

        captured = cap.readouterr()
        assert captured.out == captured.err == "", (
            "a failure while reporting a failure must not escape, otherwise a closed stderr "
            "turns a logging error into an application crash"
        )


def test_encoding_error(cap: StdCapture) -> None:
    def sink(m):
        raise UnicodeEncodeError("utf8", "", 10, 11, "too bad")

    logger.add(sink, catch=True)
    logger.debug("test")

    captured = cap.readouterr()
    lines = captured.err.strip().splitlines()

    why = (
        "the error report must keep its fixed shape — banner, record dump, traceback, "
        "footer — because that is what makes it recognisable in an unrelated log stream"
    )
    assert captured.out == "", "the error report goes to stderr, so stdout must stay empty"
    assert lines[0] == "--- Logging error in Loguru Handler #0 ---", why
    assert lines[1].startswith("Record was: {"), why
    assert lines[1].endswith("}"), why
    assert lines[-2].startswith("UnicodeEncodeError:"), why
    assert lines[-1] == "--- End of logging error ---", why


def test_unprintable_record(writer: Fixture[Writer], cap: StdCapture) -> None:
    class Unprintable:
        def __repr__(self):
            raise ValueError("Failed")

    logger.add(writer, format="{message} {extra[unprintable]}", catch=True)
    logger.bind(unprintable=1).debug("a")
    logger.bind(unprintable=Unprintable()).debug("b")
    logger.bind(unprintable=2).debug("c")

    captured = cap.readouterr()
    lines = captured.err.strip().splitlines()

    assert writer.read() == "a 1\nc 2\n", (
        "one unformattable record must not take the sink down with it; the records around "
        "it must still be delivered"
    )
    assert captured.out == "", "the error report goes to stderr, so stdout must stay empty"
    assert (
        lines[0] == "--- Logging error in Loguru Handler #0 ---"
    ), "the report must keep its banner even when the record itself cannot be shown"
    assert lines[1] == "Record was: /!\\ Unprintable record /!\\", (
        "a record whose repr() raises must degrade to a placeholder, otherwise reporting the "
        "error would raise a second error"
    )
    assert lines[-2] == "ValueError: Failed", "the original failure must still be named"
    assert lines[-1] == "--- End of logging error ---", "the report must be properly closed"


@oxitest.parametrize(**ENQUEUE_CASES)
def test_broken_sink_message(cap: StdCapture, enqueue: bool) -> None:
    logger.add(broken_sink, catch=True, enqueue=enqueue)
    logger.debug("Oops")
    time.sleep(0.1)

    captured = cap.readouterr()
    lines = captured.err.strip().splitlines()

    why = (
        "the report must name the record that failed and the exception that caused it, "
        "whether the sink runs inline or on the queue thread"
    )
    assert captured.out == "", "the error report goes to stderr, so stdout must stay empty"
    assert lines[0] == "--- Logging error in Loguru Handler #0 ---", why
    assert re.match(r"Record was: \{.*Oops.*\}", lines[1]), why
    assert lines[-2].startswith("ValueError: Error!"), why
    assert lines[-1] == "--- End of logging error ---", why


@oxitest.parametrize(**ENQUEUE_CASES)
def test_broken_sink_caught_keep_working(enqueue: bool) -> None:
    output = ""

    def half_broken_sink(m):
        nonlocal output
        if m.startswith("NOK"):
            raise ValueError("Broken!")
        output += m

    logger.add(half_broken_sink, format="{message}", enqueue=enqueue, catch=True)
    logger.info("A")
    logger.info("NOK")
    logger.info("B")

    time.sleep(0.1)
    assert output == "A\nB\n", (
        "one failing record must not disable the sink; with enqueue the queue thread has to "
        "survive the exception too, or every later message is lost"
    )


def test_broken_sink_not_caught_enqueue() -> None:
    called = 0

    def broken_sink(m):
        nonlocal called
        called += 1
        raise ValueError("Nop")

    logger.add(broken_sink, format="{message}", enqueue=True, catch=False)

    with conftest.default_threading_excepthook():
        logger.info("A")
        logger.info("B")
        time.sleep(0.1)

    assert called == 2, (
        "even with catch=False the queue thread must keep consuming, otherwise the first "
        "failure kills the thread and every later message is silently dropped"
    )
