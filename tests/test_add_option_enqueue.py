import pickle
import re
import sys
import time
from dataclasses import dataclass
from typing import Any

import oxitest
import conftest
from conftest import Writer
from oxitest import Fixture, StdCapture

from loguru import logger

ERROR_REPORT_SHAPE = (
    "the report must keep its fixed shape — banner, record dump, cause, footer — because "
    "that is what makes a queue failure recognisable in an unrelated log stream"
)


@dataclass(frozen=True)
class ExceptionValueCase:
    exception_value: Any


class NotPicklable:
    def __getstate__(self):
        raise pickle.PicklingError("You shall not serialize me!")

    def __setstate__(self, state):
        pass


class NotPicklableTypeError:
    def __getstate__(self):
        raise TypeError("You shall not serialize me!")

    def __setstate__(self, state):
        pass


class NotUnpicklable:
    def __getstate__(self):
        return "..."

    def __setstate__(self, state):
        raise pickle.UnpicklingError("You shall not de-serialize me!")


class NotUnpicklableTypeError:
    def __getstate__(self):
        return "..."

    def __setstate__(self, state):
        raise TypeError("You shall not de-serialize me!")


class NotWritable:
    def write(self, message):
        if "fail" in message.record["extra"]:
            raise RuntimeError("You asked me to fail...")
        print(message, end="")


def test_enqueue() -> None:
    x = []

    def sink(message):
        time.sleep(0.1)
        x.append(message)

    logger.add(sink, format="{message}", enqueue=True)
    logger.debug("Test")
    assert len(x) == 0, (
        "enqueue must hand the record to another thread and return immediately, otherwise "
        "the caller pays the sink's latency"
    )
    logger.complete()
    assert len(x) == 1, "complete() must block until the queue has been drained"
    assert x[0] == "Test\n", "the message must survive the round trip through the queue"


def test_enqueue_with_exception() -> None:
    x = []

    def sink(message):
        time.sleep(0.1)
        x.append(message)

    logger.add(sink, format="{message}", enqueue=True)

    try:
        1 / 0  # noqa: B018
    except ZeroDivisionError:
        logger.exception("Error")

    assert len(x) == 0, "enqueue must not block the caller, exception records included"
    logger.complete()
    assert len(x) == 1, "complete() must block until the queue has been drained"
    lines = x[0].splitlines()

    assert lines[0] == "Error", "the message must precede the traceback it describes"
    assert (
        lines[-1] == "ZeroDivisionError: division by zero"
    ), "a traceback object cannot be pickled, so it must be rendered before being queued"


def test_caught_exception_queue_put(writer: Fixture[Writer], cap: StdCapture) -> None:
    logger.add(writer, enqueue=True, catch=True, format="{message}")

    logger.info("It's fine")
    logger.bind(broken=NotPicklable()).info("Bye bye...")
    logger.info("It's fine again")
    logger.remove()

    captured = cap.readouterr()
    lines = captured.err.strip().splitlines()
    assert writer.read() == "It's fine\nIt's fine again\n", (
        "one unpicklable record must not disable the sink; the records around it must still "
        "be delivered"
    )
    assert captured.out == "", "the error report goes to stderr, so stdout must stay empty"
    assert lines[0] == "--- Logging error in Loguru Handler #0 ---", ERROR_REPORT_SHAPE
    assert re.match(r"Record was: \{.*Bye bye.*\}", lines[1]), ERROR_REPORT_SHAPE
    assert "PicklingError: You shall not serialize me!" in captured.err, ERROR_REPORT_SHAPE
    assert lines[-1] == "--- End of logging error ---", ERROR_REPORT_SHAPE


def test_caught_exception_queue_get(writer: Fixture[Writer], cap: StdCapture) -> None:
    logger.add(writer, enqueue=True, catch=True, format="{message}")

    logger.info("It's fine")
    logger.bind(broken=NotUnpicklable()).info("Bye bye...")
    logger.info("It's fine again")
    logger.remove()

    captured = cap.readouterr()
    lines = captured.err.strip().splitlines()
    assert writer.read() == "It's fine\nIt's fine again\n", (
        "a record that fails to unpickle must not stop the queue thread, otherwise every "
        "later message would be lost"
    )
    assert captured.out == "", "the error report goes to stderr, so stdout must stay empty"
    assert lines[0] == "--- Logging error in Loguru Handler #0 ---", ERROR_REPORT_SHAPE
    assert lines[1] == "Record was: None", (
        "the record cannot be shown when unpickling is what failed, so the dump must say "
        "None rather than raise again"
    )
    assert "UnpicklingError: You shall not de-serialize me!" in captured.err, ERROR_REPORT_SHAPE
    assert lines[-1] == "--- End of logging error ---", ERROR_REPORT_SHAPE


def test_caught_exception_sink_write(cap: StdCapture) -> None:
    logger.add(NotWritable(), enqueue=True, catch=True, format="{message}")

    logger.info("It's fine")
    logger.bind(fail=True).info("Bye bye...")
    logger.info("It's fine again")
    logger.remove()

    captured = cap.readouterr()
    lines = captured.err.strip().splitlines()
    assert captured.out == "It's fine\nIt's fine again\n", (
        "a failure inside the sink must not stop the queue thread, otherwise every later "
        "message would be lost"
    )
    assert lines[0] == "--- Logging error in Loguru Handler #0 ---", ERROR_REPORT_SHAPE
    assert re.match(r"Record was: \{.*Bye bye.*\}", lines[1]), ERROR_REPORT_SHAPE
    assert "RuntimeError: You asked me to fail..." in captured.err, ERROR_REPORT_SHAPE
    assert lines[-1] == "--- End of logging error ---", ERROR_REPORT_SHAPE


def test_not_caught_exception_queue_put(writer: Fixture[Writer], cap: StdCapture) -> None:
    logger.add(writer, enqueue=True, catch=False, format="{message}")

    logger.info("It's fine")

    with oxitest.raises(pickle.PicklingError, match=r"You shall not serialize me!"):
        logger.bind(broken=NotPicklable()).info("Bye bye...")

    logger.remove()

    captured = cap.readouterr()
    assert writer.read() == "It's fine\n", "the earlier record must still have been delivered"
    assert captured.out == "", (
        "with catch=False the exception propagates to the caller, so loguru must not also "
        "print a report"
    )
    assert captured.err == "", (
        "with catch=False the exception propagates to the caller, so loguru must not also "
        "print a report"
    )


def test_not_caught_exception_queue_get(writer: Fixture[Writer], cap: StdCapture) -> None:
    logger.add(writer, enqueue=True, catch=False, format="{message}")

    with conftest.default_threading_excepthook():
        logger.info("It's fine")
        logger.bind(broken=NotUnpicklable()).info("Bye bye...")
        logger.info("It's fine again")
        logger.remove()

    captured = cap.readouterr()
    lines = captured.err.strip().splitlines()
    assert writer.read() == "It's fine\nIt's fine again\n", (
        "catch=False cannot propagate an error raised on the queue thread, so the thread "
        "must report it and carry on rather than die"
    )
    assert captured.out == "", "the error report goes to stderr, so stdout must stay empty"
    assert lines[0] == "--- Logging error in Loguru Handler #0 ---", ERROR_REPORT_SHAPE
    assert lines[1] == "Record was: None", ERROR_REPORT_SHAPE
    assert "UnpicklingError: You shall not de-serialize me!" in captured.err, ERROR_REPORT_SHAPE
    assert lines[-1] == "--- End of logging error ---", ERROR_REPORT_SHAPE


def test_not_caught_exception_sink_write(cap: StdCapture) -> None:
    logger.add(NotWritable(), enqueue=True, catch=False, format="{message}")

    with conftest.default_threading_excepthook():
        logger.info("It's fine")
        logger.bind(fail=True).info("Bye bye...")
        logger.info("It's fine again")
        logger.remove()

    captured = cap.readouterr()
    lines = captured.err.strip().splitlines()
    assert captured.out == "It's fine\nIt's fine again\n", (
        "catch=False cannot propagate an error raised on the queue thread, so the thread "
        "must report it and carry on rather than die"
    )
    assert lines[0] == "--- Logging error in Loguru Handler #0 ---", ERROR_REPORT_SHAPE
    assert re.match(r"Record was: \{.*Bye bye.*\}", lines[1]), ERROR_REPORT_SHAPE
    assert "RuntimeError: You asked me to fail..." in captured.err, ERROR_REPORT_SHAPE
    assert lines[-1] == "--- End of logging error ---", ERROR_REPORT_SHAPE


def test_not_caught_exception_sink_write_then_complete(cap: StdCapture) -> None:
    logger.add(NotWritable(), enqueue=True, catch=False, format="{message}")

    with conftest.default_threading_excepthook():
        logger.bind(fail=True).info("Bye bye...")
        logger.complete()
        logger.complete()  # Called twice to ensure it's re-usable.
        logger.remove()

    captured = cap.readouterr()
    lines = captured.err.strip().splitlines()
    assert captured.out == "", "the failing record never reaches print(), so stdout stays empty"
    assert lines[0] == "--- Logging error in Loguru Handler #0 ---", ERROR_REPORT_SHAPE
    assert re.match(r"Record was: \{.*Bye bye.*\}", lines[1]), ERROR_REPORT_SHAPE
    assert "RuntimeError: You asked me to fail..." in captured.err, ERROR_REPORT_SHAPE
    assert lines[-1] == "--- End of logging error ---", ERROR_REPORT_SHAPE


def test_not_caught_exception_queue_get_then_complete(
    writer: Fixture[Writer], cap: StdCapture
) -> None:
    logger.add(writer, enqueue=True, catch=False, format="{message}")

    with conftest.default_threading_excepthook():
        logger.bind(broken=NotUnpicklable()).info("Bye bye...")
        logger.complete()
        logger.complete()
        logger.remove()

    captured = cap.readouterr()
    lines = captured.err.strip().splitlines()
    assert writer.read() == "", "the only record failed to unpickle, so nothing may be written"
    assert captured.out == "", "the error report goes to stderr, so stdout must stay empty"
    assert lines[0] == "--- Logging error in Loguru Handler #0 ---", ERROR_REPORT_SHAPE
    assert lines[1] == "Record was: None", ERROR_REPORT_SHAPE
    assert "UnpicklingError: You shall not de-serialize me!" in captured.err, ERROR_REPORT_SHAPE
    assert lines[-1] == "--- End of logging error ---", ERROR_REPORT_SHAPE


def test_wait_for_all_messages_enqueued(cap: StdCapture) -> None:
    def slow_sink(message):
        time.sleep(0.01)
        sys.stderr.write(message)

    logger.add(slow_sink, enqueue=True, catch=False, format="{message}")

    for i in range(10):
        logger.info(i)

    logger.complete()

    captured = cap.readouterr()

    assert captured.out == "", "the sink targets stderr, so stdout must stay empty"
    assert captured.err == "".join("%d\n" % i for i in range(10)), (
        "complete() must wait for every queued record and the queue must preserve order, "
        "otherwise messages would be lost or reordered at shutdown"
    )


@oxitest.parametrize(
    pickling_error=ExceptionValueCase(exception_value=NotPicklable()),
    type_error=ExceptionValueCase(exception_value=NotPicklableTypeError()),
)
def test_logging_not_picklable_exception(exception_value: Any) -> None:
    exception = None

    def sink(message):
        nonlocal exception
        exception = message.record["exception"]

    logger.add(sink, enqueue=True, catch=False)

    try:
        raise ValueError(exception_value)
    except Exception:
        logger.exception("Oups")

    logger.remove()

    type_, value, traceback_ = exception
    assert type_ is ValueError, (
        "the exception type must survive even when the instance cannot be pickled, so the "
        "record still says what went wrong"
    )
    assert value is None, (
        "an unpicklable value must be dropped rather than crash the queue; the already "
        "rendered traceback in the message keeps the detail"
    )
    assert traceback_ is None, "traceback objects are never picklable, so they are dropped"


@oxitest.parametrize(
    unpickling_error=ExceptionValueCase(exception_value=NotUnpicklable()),
    type_error=ExceptionValueCase(exception_value=NotUnpicklableTypeError()),
)
def test_logging_not_unpicklable_exception(exception_value: Any) -> None:
    exception = None

    def sink(message):
        nonlocal exception
        exception = message.record["exception"]

    logger.add(sink, enqueue=True, catch=False)

    try:
        raise ValueError(exception_value)
    except Exception:
        logger.exception("Oups")

    logger.remove()

    type_, value, traceback_ = exception
    assert type_ is ValueError, (
        "the exception type must survive even when the instance cannot be unpickled, so the "
        "record still says what went wrong"
    )
    assert (
        value is None
    ), "a value that fails to unpickle must be dropped rather than crash the queue thread"
    assert traceback_ is None, "traceback objects are never picklable, so they are dropped"
