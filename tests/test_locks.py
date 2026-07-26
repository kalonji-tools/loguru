import contextlib
import gc
import pickle
import sys
import threading
import time
from typing import Iterator

import oxitest
from oxitest import StdCapture

from loguru import logger


class CyclicReference:
    """A minimal cyclic reference.

    Cyclical references are garbage collected using the generational collector rather than
    via reference counting. This is important here, because the generational collector runs
    periodically, meaning that it is hard to predict when the stack will be overtaken by a
    garbage collection process - but it will almost always be when allocating memory of some
    kind.

    When this object is garbage-collected, a log will be emitted.
    """

    def __init__(self, _other: "CyclicReference" = None):
        self.other = _other or CyclicReference(_other=self)

    def __del__(self):
        logger.info("tearing down")


@contextlib.contextmanager
def removed_cyclic_references() -> Iterator[None]:
    """Prevent cyclic isolate finalizers bleeding into other tests."""
    try:
        yield
    finally:
        gc.collect()


def test_no_deadlock_on_generational_garbage_collection() -> None:
    """Regression test for https://github.com/Delgan/loguru/issues/712.

    Assert that deadlocks do not occur when a cyclic isolate containing log output in
    finalizers is collected by generational GC, during the output of another log message.
    """
    with removed_cyclic_references():
        # GIVEN a sink which assigns some memory
        output = []

        def sink(message):
            # The generational GC could be triggered here by any memory assignment, but we
            # trigger it explicitly to avoid a flaky test.
            # See https://github.com/Delgan/loguru/issues/712
            gc.collect()

            # Actually write the message somewhere
            output.append(message)

        logger.add(sink, colorize=False)

        # WHEN there are cyclic isolates in memory which log on GC
        # AND logs are produced long enough to trigger generational GC
        for _ in range(10):
            CyclicReference()
            logger.info("test")

    # THEN deadlock should not be reached
    assert len(output) >= 10, (
        "reaching this line at all is the real assertion — a re-entrant lock would have "
        "deadlocked above — and every emitted message must have made it to the sink"
    )


def test_no_deadlock_if_logger_used_inside_sink_with_catch(cap: StdCapture) -> None:
    def sink(message):
        logger.info(message)

    logger.add(sink, colorize=False, catch=True)

    logger.info("Test")

    captured = cap.readouterr()
    assert captured.out == "", "the error report goes to stderr, so stdout must stay empty"
    assert "deadlock avoided" in captured.err, (
        "logging from inside a sink must be reported rather than blocking forever on the "
        "handler lock the caller already holds"
    )


def test_no_deadlock_if_logger_used_inside_sink_without_catch() -> None:
    def sink(message):
        logger.info(message)

    logger.add(sink, colorize=False, catch=False)

    with oxitest.raises(RuntimeError, match=r".*deadlock avoided.*"):
        logger.info("Test")


def test_no_error_if_multithreading(cap: StdCapture) -> None:
    barrier = threading.Barrier(2)

    def sink(message):
        barrier.wait()
        sys.stderr.write(message)
        time.sleep(0.5)  # Give time to the other thread to try to acquire the lock.

    def worker():
        logger.info("Thread message")
        barrier.wait()  # Release main thread.

    logger.add(sink, colorize=False, catch=False, format="{message}")
    thread = threading.Thread(target=worker)
    thread.start()

    barrier.wait()
    logger.info("Main message")

    captured = cap.readouterr()
    assert captured.out == "", "the sink writes to stderr, so stdout must stay empty"
    assert captured.err == "Thread message\nMain message\n", (
        "the handler lock must serialize concurrent writers, otherwise messages from two "
        "threads interleave into corrupted lines"
    )


def _pickle_sink(message):
    sys.stderr.write(message)

    if message.record["extra"].get("clone", False):
        new_logger = pickle.loads(pickle.dumps(logger))
        new_logger.bind(clone=False).info("From clone")
        new_logger.remove()


def test_pickled_logger_does_not_inherit_acquired_local(cap: StdCapture) -> None:
    logger.add(_pickle_sink, colorize=False, catch=False, format="{message}")

    logger.bind(clone=True).info("From main")

    captured = cap.readouterr()
    assert captured.out == "", "the sink writes to stderr, so stdout must stay empty"
    assert captured.err == "From main\nFrom clone\n", (
        "an unpickled logger must start with its re-entrancy flag cleared, otherwise it "
        "inherits the 'lock already held' state and refuses to log"
    )
