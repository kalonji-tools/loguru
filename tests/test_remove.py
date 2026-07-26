import sys
import time
from dataclasses import dataclass
from typing import Any

import oxitest
from conftest import Writer
from oxitest import Fixture, StdCapture, TempDir

from loguru import logger


@dataclass(frozen=True)
class HandlerIdCase:
    handler_id: Any


class StopSinkError:
    def write(self, message):
        print(message, end="")

    def stop(self):
        raise OSError("Stop error")


def test_remove_all(tmp: TempDir, writer: Fixture[Writer], cap: StdCapture) -> None:
    file = tmp.path / "test.log"

    logger.debug("This shouldn't be printed.")

    logger.add(file, format="{message}")
    logger.add(sys.stdout, format="{message}")
    logger.add(sys.stderr, format="{message}")
    logger.add(writer, format="{message}")

    message = "some message"
    expected = message + "\n"

    logger.debug(message)

    logger.remove()

    logger.debug("This shouldn't be printed neither.")

    captured = cap.readouterr()

    why = (
        "remove() without an id must detach every sink at once, and only the message logged "
        "while they were attached may appear — one sink surviving means the loop over "
        "handlers is incomplete"
    )
    assert file.read_text() == expected, why
    assert captured.out == expected, why
    assert captured.err == expected, why
    assert writer.read() == expected, why


def test_remove_simple(writer: Fixture[Writer]) -> None:
    i = logger.add(writer, format="{message}")
    logger.debug("1")
    logger.remove(i)
    logger.debug("2")
    assert writer.read() == "1\n", (
        "removing a sink by id must take effect immediately, otherwise records keep reaching "
        "a sink the caller has already released"
    )


def test_remove_enqueue(writer: Fixture[Writer]) -> None:
    i = logger.add(writer, format="{message}", enqueue=True)
    logger.debug("1")
    time.sleep(0.1)
    logger.remove(i)
    logger.debug("2")
    assert writer.read() == "1\n", (
        "removing an enqueued sink must drain what is pending and then stop, otherwise "
        "messages are either lost on shutdown or delivered after release"
    )


def test_remove_enqueue_filesink(tmp: TempDir) -> None:
    file = tmp.path / "test.log"
    i = logger.add(file, format="{message}", enqueue=True)
    logger.debug("1")
    logger.remove(i)
    assert file.read_text() == "1\n", (
        "remove() must wait for the queue thread to flush to disk, otherwise a message "
        "logged just before shutdown never reaches the file"
    )


def test_exception_in_stop_during_remove_one(cap: StdCapture) -> None:
    i = logger.add(StopSinkError(), catch=False, format="{message}")
    logger.info("A")
    with oxitest.raises(OSError, match=r"Stop error"):
        logger.remove(i)
    logger.info("Nope")

    captured = cap.readouterr()

    assert captured.out == "A\n", (
        "the sink must still be detached even though its stop() raised, otherwise a failing "
        "teardown would leave the handler permanently attached"
    )
    assert captured.err == "", "nothing writes to stderr here, so anything there is a leak"


def test_exception_in_stop_not_caught_during_remove_all(cap: StdCapture) -> None:
    logger.add(StopSinkError(), catch=False, format="{message}")
    logger.add(StopSinkError(), catch=False, format="{message}")

    with oxitest.raises(OSError, match=r"Stop error"):
        logger.remove()

    logger.info("A")

    with oxitest.raises(OSError, match=r"Stop error"):
        logger.remove()

    logger.info("Nope")

    captured = cap.readouterr()

    assert captured.out == "A\n", (
        "a failing stop() must abort remove() while leaving the remaining sink attached, so "
        "the second remove() has something left to detach and the message in between prints"
    )
    assert captured.err == "", "nothing writes to stderr here, so anything there is a leak"


def test_invalid_handler_id_value(writer: Fixture[Writer]) -> None:
    logger.add(writer)

    with oxitest.raises(ValueError, match=r"^There is no existing handler.*"):
        logger.remove(42)


@oxitest.parametrize(
    stream=HandlerIdCase(handler_id=sys.stderr),
    module=HandlerIdCase(handler_id=sys),
    object_instance=HandlerIdCase(handler_id=object()),
    type_object=HandlerIdCase(handler_id=int),
)
def test_invalid_handler_id_type(handler_id: Any) -> None:
    with oxitest.raises(TypeError, match=r"^Invalid handler id.*"):
        logger.remove(handler_id)
