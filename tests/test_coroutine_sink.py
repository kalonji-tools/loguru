import asyncio
import logging
import multiprocessing
import re
import sys
import threading
from dataclasses import dataclass

import oxitest
from oxitest import LogCapture, StdCapture, TempDir

from loguru import logger
from tests._naming import pin_module_name
from tests._utils import new_event_loop_context, set_event_loop_context

# "spawn" re-imports this module in the child to unpickle the worker functions below, so
# the module has to be reachable under an importable name.
pin_module_name(globals(), "tests.test_coroutine_sink")

NO_STDERR_EXPECTED = "the sink writes to stdout, so stderr must stay empty"


@dataclass(frozen=True)
class LoopIsNoneCase:
    loop_is_none: bool


async def async_writer(msg):
    await asyncio.sleep(0.01)
    print(msg, end="")


class AsyncWriter:
    async def __call__(self, msg):
        await asyncio.sleep(0.01)
        print(msg, end="")


def test_coroutine_function(cap: StdCapture) -> None:
    async def worker():
        logger.debug("A message")
        await logger.complete()

    logger.add(async_writer, format="{message}")

    asyncio.run(worker())

    captured = cap.readouterr()
    assert captured.err == "", NO_STDERR_EXPECTED
    assert captured.out == "A message\n", (
        "a coroutine function must be usable as a sink, scheduled per record and awaited by "
        "complete()"
    )


def test_async_callable_sink(cap: StdCapture) -> None:
    async def worker():
        logger.debug("A message")
        await logger.complete()

    logger.add(AsyncWriter(), format="{message}")

    asyncio.run(worker())

    captured = cap.readouterr()
    assert captured.err == "", NO_STDERR_EXPECTED
    assert captured.out == "A message\n", (
        "an object with an async __call__ must be accepted like a bare coroutine function"
    )


def test_concurrent_execution(cap: StdCapture) -> None:
    async def task(i):
        logger.debug("=> {}", i)

    async def main():
        tasks = [task(i) for i in range(10)]
        await asyncio.gather(*tasks)
        await logger.complete()

    logger.add(async_writer, format="{message}")

    asyncio.run(main())

    captured = cap.readouterr()
    assert captured.err == "", NO_STDERR_EXPECTED
    assert sorted(captured.out.splitlines()) == sorted("=> %d" % i for i in range(10)), (
        "complete() must await every task scheduled from concurrent callers, so no message "
        "is lost; only their order may vary"
    )


def test_recursive_coroutine(cap: StdCapture) -> None:
    async def task(i):
        if i == 0:
            await logger.complete()
            return
        logger.info("{}!", i)
        await task(i - 1)

    logger.add(async_writer, format="{message}")

    asyncio.run(task(9))

    captured = cap.readouterr()
    assert captured.err == "", NO_STDERR_EXPECTED
    assert sorted(captured.out.splitlines()) == sorted("%d!" % i for i in range(1, 10)), (
        "a single complete() at the bottom of the recursion must await the tasks scheduled "
        "at every level above it"
    )


def test_using_another_event_loop(cap: StdCapture) -> None:
    async def worker():
        logger.debug("A message")
        await logger.complete()

    with new_event_loop_context() as loop:
        logger.add(async_writer, format="{message}", loop=loop)

        loop.run_until_complete(worker())

    captured = cap.readouterr()
    assert captured.err == "", NO_STDERR_EXPECTED
    assert captured.out == "A message\n", (
        "an explicitly supplied loop must be the one the sink is scheduled on"
    )


def test_run_multiple_different_loops(cap: StdCapture) -> None:
    async def worker(i):
        logger.debug("Message {}", i)
        await logger.complete()

    logger.add(async_writer, format="{message}", loop=None)

    asyncio.run(worker(1))
    asyncio.run(worker(2))

    captured = cap.readouterr()
    assert captured.err == "", NO_STDERR_EXPECTED
    assert captured.out == "Message 1\nMessage 2\n", (
        "with loop=None the sink must bind to whichever loop is running at the time, so it "
        "keeps working across successive asyncio.run() calls"
    )


def test_run_multiple_same_loop(cap: StdCapture) -> None:
    async def worker(i):
        logger.debug("Message {}", i)
        await logger.complete()

    with new_event_loop_context() as loop:
        logger.add(async_writer, format="{message}", loop=loop)

        loop.run_until_complete(worker(1))
        loop.run_until_complete(worker(2))

    captured = cap.readouterr()
    assert captured.err == "", NO_STDERR_EXPECTED
    assert captured.out == "Message 1\nMessage 2\n", (
        "a bound loop must stay usable across successive run_until_complete() calls"
    )


def test_using_sink_without_running_loop_not_none(cap: StdCapture) -> None:
    with new_event_loop_context() as loop:
        logger.add(sys.stderr, format="=> {message}")
        logger.add(async_writer, format="{message}", loop=loop)

        logger.info("A message")

        loop.run_until_complete(logger.complete())

    captured = cap.readouterr()
    assert captured.err == "=> A message\n", "the synchronous sink must be written immediately"
    assert captured.out == "A message\n", (
        "logging from outside the loop must still schedule the task on the bound loop, so "
        "the record is delivered once that loop runs"
    )


def test_using_sink_without_running_loop_none(cap: StdCapture) -> None:
    with new_event_loop_context() as loop:
        logger.add(sys.stderr, format="=> {message}")
        logger.add(async_writer, format="{message}", loop=None)

        logger.info("A message")

        loop.run_until_complete(logger.complete())

    captured = cap.readouterr()
    assert captured.err == "=> A message\n", "the synchronous sink must be written immediately"
    assert captured.out == "", (
        "with loop=None and no loop running there is nowhere to schedule the task, so the "
        "record must be dropped rather than raise"
    )


@oxitest.mark.skip(
    when=sys.version_info >= (3, 16), reason="The 'set_event_loop' function is removed"
)
def test_global_loop_not_used(cap: StdCapture) -> None:
    with new_event_loop_context() as loop:
        with set_event_loop_context(loop):
            logger.add(sys.stderr, format="=> {message}")
            logger.add(async_writer, format="{message}", loop=None)

            logger.info("A message")

            loop.run_until_complete(logger.complete())

    captured = cap.readouterr()
    assert captured.err == "=> A message\n", "the synchronous sink must be written immediately"
    assert captured.out == "", (
        "loop=None must mean the *running* loop, not the one merely installed as global; "
        "using the global one would schedule work on a loop nobody is driving"
    )


def test_complete_in_another_run(cap: StdCapture) -> None:
    async def worker_1():
        logger.debug("A")

    async def worker_2():
        logger.debug("B")
        await logger.complete()

    with new_event_loop_context() as loop:
        logger.add(async_writer, format="{message}", loop=loop)

        loop.run_until_complete(worker_1())
        loop.run_until_complete(worker_2())

    captured = cap.readouterr()
    assert captured.out == "A\nB\n", (
        "a task scheduled in an earlier run must still be pending, and complete() in a later "
        "run must await it too"
    )
    assert captured.err == "", NO_STDERR_EXPECTED


def test_tasks_cancelled_on_remove(cap: StdCapture) -> None:
    logger.add(async_writer, format="{message}", catch=False)

    async def foo():
        logger.info("A")
        logger.info("B")
        logger.info("C")
        logger.remove()
        await logger.complete()

    asyncio.run(foo())

    captured = cap.readouterr()
    assert captured.out == captured.err == "", (
        "remove() must cancel the sink's pending tasks, otherwise records would be written "
        "after the caller released the sink"
    )


def test_remove_without_tasks(cap: StdCapture) -> None:
    logger.add(async_writer, format="{message}", catch=False)
    logger.remove()

    async def foo():
        logger.info("!")
        await logger.complete()

    asyncio.run(foo())

    captured = cap.readouterr()
    assert captured.out == captured.err == "", (
        "removing a sink that never ran must be a no-op rather than raise"
    )


def test_complete_without_tasks(cap: StdCapture) -> None:
    logger.add(async_writer, catch=False)

    async def worker():
        await logger.complete()

    asyncio.run(worker())

    captured = cap.readouterr()
    assert captured.out == captured.err == "", (
        "complete() with nothing pending must return immediately rather than raise"
    )


def test_complete_stream_noop(cap: StdCapture) -> None:
    logger.add(sys.stderr, format="{message}", catch=False)
    logger.info("A")

    async def worker():
        logger.info("B")
        await logger.complete()
        logger.info("C")

    asyncio.run(worker())

    logger.info("D")

    captured = cap.readouterr()
    assert captured.out == "", "the sink targets stderr, so stdout must stay empty"
    assert captured.err == "A\nB\nC\nD\n", (
        "complete() must be a no-op for a synchronous sink, leaving it fully usable "
        "afterwards"
    )


def test_complete_file_noop(tmp: TempDir) -> None:
    filepath = tmp.path / "test.log"

    logger.add(filepath, format="{message}", catch=False)
    logger.info("A")

    async def worker():
        logger.info("B")
        await logger.complete()
        logger.info("C")

    asyncio.run(worker())

    logger.info("D")

    assert filepath.read_text() == "A\nB\nC\nD\n", (
        "complete() must be a no-op for a file sink, leaving it open and usable afterwards"
    )


def test_complete_function_noop() -> None:
    out = ""

    def write(msg):
        nonlocal out
        out += msg

    logger.add(write, format="{message}", catch=False)
    logger.info("A")

    async def worker():
        logger.info("B")
        await logger.complete()
        logger.info("C")

    asyncio.run(worker())

    logger.info("D")

    assert out == "A\nB\nC\nD\n", (
        "complete() must be a no-op for a plain function sink, leaving it usable afterwards"
    )


def test_complete_standard_noop(cap: StdCapture) -> None:
    logger.add(logging.StreamHandler(sys.stderr), format="{message}", catch=False)
    logger.info("A")

    async def worker():
        logger.info("B")
        await logger.complete()
        logger.info("C")

    asyncio.run(worker())

    logger.info("D")

    captured = cap.readouterr()
    assert captured.out == "", "the handler targets stderr, so stdout must stay empty"
    assert captured.err == "A\nB\nC\nD\n", (
        "complete() must be a no-op for a standard logging handler, leaving it usable "
        "afterwards"
    )


def test_exception_in_coroutine_caught(cap: StdCapture) -> None:
    async def sink(msg):
        raise Exception("Oh no")

    async def main():
        logger.add(sink, catch=True)
        logger.info("Hello world")
        await asyncio.sleep(0.1)
        await logger.complete()

    asyncio.run(main())

    captured = cap.readouterr()
    lines = captured.err.strip().splitlines()

    why = (
        "a failure inside an async sink must be reported in the same fixed shape as a "
        "synchronous one, otherwise async errors are harder to recognise"
    )
    assert captured.out == "", "the error report goes to stderr, so stdout must stay empty"
    assert lines[0] == "--- Logging error in Loguru Handler #0 ---", why
    assert re.match(r"Record was: \{.*Hello world.*\}", lines[1]), why
    assert lines[-2] == "Exception: Oh no", why
    assert lines[-1] == "--- End of logging error ---", why


def test_exception_in_coroutine_not_caught(cap: StdCapture, log: LogCapture) -> None:
    async def sink(msg):
        raise ValueError("Oh no")

    async def main():
        logger.add(sink, catch=False)
        logger.info("Hello world")
        await asyncio.sleep(0.1)
        await logger.complete()

    asyncio.run(main())

    captured = cap.readouterr()
    assert captured.out == captured.err == "", (
        "with catch=False loguru must not report the error itself; the task's exception is "
        "the asyncio loop's to handle"
    )

    records = log.records
    assert len(records) == 1, (
        "the loop's exception handler must report the failure exactly once, so the error is "
        "neither lost nor duplicated"
    )
    record = records[0]

    message = record.getMessage()
    assert "Logging error in Loguru Handler" not in message, (
        "the report must come from asyncio, not from loguru's own error handling"
    )
    assert "was never retrieved" not in message, (
        "the task's exception must be retrieved rather than surface later as a "
        "'never retrieved' warning at garbage-collection time"
    )

    exc_type, exc_value, _ = record.exc_info
    assert exc_type is ValueError, "the original exception type must be preserved"
    assert str(exc_value) == "Oh no", "the original exception message must be preserved"


def test_exception_in_coroutine_during_complete_caught(cap: StdCapture) -> None:
    async def sink(msg):
        await asyncio.sleep(0.1)
        raise Exception("Oh no")

    async def main():
        logger.add(sink, catch=True)
        logger.info("Hello world")
        await logger.complete()

    asyncio.run(main())

    captured = cap.readouterr()
    lines = captured.err.strip().splitlines()

    why = (
        "a failure surfacing while complete() awaits the task must be reported in the same "
        "fixed shape as one surfacing during the write itself"
    )
    assert captured.out == "", "the error report goes to stderr, so stdout must stay empty"
    assert lines[0] == "--- Logging error in Loguru Handler #0 ---", why
    assert re.match(r"Record was: \{.*Hello world.*\}", lines[1]), why
    assert lines[-2] == "Exception: Oh no", why
    assert lines[-1] == "--- End of logging error ---", why


def test_exception_in_coroutine_during_complete_not_caught(
    cap: StdCapture, log: LogCapture
) -> None:
    async def sink(msg):
        await asyncio.sleep(0.1)
        raise ValueError("Oh no")

    async def main():
        logger.add(sink, catch=False)
        logger.info("Hello world")
        await logger.complete()

    asyncio.run(main())

    captured = cap.readouterr()
    assert captured.out == captured.err == "", (
        "with catch=False loguru must not report the error itself; the task's exception is "
        "the asyncio loop's to handle"
    )

    records = log.records
    assert len(records) == 1, (
        "the loop's exception handler must report the failure exactly once, so the error is "
        "neither lost nor duplicated"
    )
    record = records[0]

    message = record.getMessage()
    assert "Logging error in Loguru Handler" not in message, (
        "the report must come from asyncio, not from loguru's own error handling"
    )
    assert "was never retrieved" not in message, (
        "the task's exception must be retrieved rather than surface later as a "
        "'never retrieved' warning at garbage-collection time"
    )

    exc_type, exc_value, _ = record.exc_info
    assert exc_type is ValueError, "the original exception type must be preserved"
    assert str(exc_value) == "Oh no", "the original exception message must be preserved"


def test_enqueue_coroutine_loop(cap: StdCapture) -> None:
    with new_event_loop_context() as loop:
        logger.add(async_writer, enqueue=True, loop=loop, format="{message}", catch=False)

        async def worker():
            logger.info("A")
            await logger.complete()

        loop.run_until_complete(worker())

    captured = cap.readouterr()
    assert captured.out == "A\n", (
        "enqueue and an async sink must compose: the queue thread has to schedule the "
        "coroutine on the bound loop"
    )
    assert captured.err == "", NO_STDERR_EXPECTED


def test_enqueue_coroutine_from_inside_coroutine_without_loop(cap: StdCapture) -> None:
    with new_event_loop_context() as loop:

        async def worker():
            logger.add(async_writer, enqueue=True, loop=None, format="{message}", catch=False)
            logger.info("A")
            await logger.complete()

        loop.run_until_complete(worker())

    captured = cap.readouterr()
    assert captured.out == "A\n", (
        "adding the sink from inside a running loop must capture that loop, so loop=None is "
        "usable in the common async setup"
    )
    assert captured.err == "", NO_STDERR_EXPECTED


def test_custom_complete_function(cap: StdCapture) -> None:
    awaited = False

    class Handler:
        def write(self, message):
            print(message, end="")

        async def complete(self):
            nonlocal awaited
            awaited = True

    async def worker():
        logger.info("A")
        await logger.complete()

    logger.add(Handler(), catch=False, format="{message}")

    asyncio.run(worker())

    captured = cap.readouterr()
    assert captured.out == "A\n", "the synchronous write() must still be used for records"
    assert captured.err == "", NO_STDERR_EXPECTED
    assert awaited, (
        "a sink's own async complete() must be awaited, which is how a custom sink flushes "
        "whatever it buffers"
    )


@oxitest.parametrize(
    loop_is_none=LoopIsNoneCase(loop_is_none=True),
    loop_is_bound=LoopIsNoneCase(loop_is_none=False),
)
def test_complete_from_another_loop(cap: StdCapture, loop_is_none: bool) -> None:
    with new_event_loop_context() as main_loop, new_event_loop_context() as second_loop:
        loop = None if loop_is_none else main_loop
        logger.add(async_writer, loop=loop, format="{message}")

        async def worker_1():
            logger.info("A")

        async def worker_2():
            await logger.complete()

        main_loop.run_until_complete(worker_1())
        second_loop.run_until_complete(worker_2())

        captured = cap.readouterr()
        assert captured.out == captured.err == "", (
            "complete() must only await tasks belonging to the loop it runs on; awaiting "
            "another loop's task would block or raise"
        )

        main_loop.run_until_complete(worker_2())

    captured = cap.readouterr()
    assert captured.out == "A\n", (
        "the pending task must still be there and must be awaited once complete() runs on "
        "its own loop"
    )
    assert captured.err == "", NO_STDERR_EXPECTED


def test_complete_from_multiple_threads_loop_is_none(cap: StdCapture) -> None:
    async def worker(i):
        for _ in range(100):
            await asyncio.sleep(0)
            logger.info("{:03}", i)
        await logger.complete()

    async def sink(msg):
        print(msg, end="")

    def worker_(i):
        asyncio.run(worker(i))

    logger.add(sink, catch=False, format="{message}")

    threads = [threading.Thread(target=worker_, args=(i,)) for i in range(10)]

    for t in threads:
        t.start()

    for t in threads:
        t.join()

    captured = cap.readouterr()
    assert sorted(captured.out.splitlines()) == [
        "{:03}".format(i) for i in range(10) for _ in range(100)
    ], (
        "each thread runs its own loop, so complete() must track tasks per loop for every "
        "message to be delivered exactly once"
    )
    assert captured.err == "", NO_STDERR_EXPECTED


def test_complete_from_multiple_threads_loop_is_not_none(cap: StdCapture) -> None:
    async def worker(i):
        for _ in range(100):
            await asyncio.sleep(0)
            logger.info("{:03}", i)
        await logger.complete()

    async def sink(msg):
        print(msg, end="")

    def worker_(i):
        asyncio.run(worker(i))

    with new_event_loop_context() as loop:
        logger.add(sink, catch=False, format="{message}", loop=loop)

        threads = [threading.Thread(target=worker_, args=(i,)) for i in range(10)]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        async def complete():
            await logger.complete()

        loop.run_until_complete(complete())

    captured = cap.readouterr()
    assert sorted(captured.out.splitlines()) == [
        "{:03}".format(i) for i in range(10) for _ in range(100)
    ], (
        "with a bound loop every thread must schedule onto it, and one final complete() on "
        "that loop must deliver every message exactly once"
    )
    assert captured.err == "", NO_STDERR_EXPECTED


def test_complete_and_sink_write_concurrency() -> None:
    count = 1000
    n = 0

    async def sink(message):
        nonlocal n
        n += 1

    async def some_task():
        for _ in range(count):
            logger.info("Message")
            await asyncio.sleep(0)

    async def another_task():
        for _ in range(count):
            await logger.complete()
            await asyncio.sleep(0)

    async def main():
        logger.remove()
        logger.add(sink, catch=False)

        await asyncio.gather(some_task(), another_task())

    asyncio.run(main())

    assert n == count, (
        "complete() running concurrently with logging must not drop or duplicate tasks, "
        "which a naive 'clear the pending set' implementation would do"
    )


def test_complete_and_contextualize_concurrency() -> None:
    called = False

    async def main():
        logging_event = asyncio.Event()
        contextualize_event = asyncio.Event()

        async def sink(message):
            nonlocal called
            logging_event.set()
            await contextualize_event.wait()
            called = True

        async def logging_task():
            logger.info("Message")
            await logger.complete()

        async def contextualize_task():
            with logger.contextualize():
                contextualize_event.set()
                await logging_event.wait()

        logger.remove()
        logger.add(sink, catch=False)

        await asyncio.gather(logging_task(), contextualize_task())

    asyncio.run(main())

    assert called, (
        "contextualize() and an in-flight async sink must not share a lock, otherwise these "
        "two tasks would wait on each other forever"
    )


async def async_subworker(logger_):
    logger_.info("Child")
    await logger_.complete()


async def async_mainworker(logger_):
    logger_.info("Main")
    await logger_.complete()


def subworker(logger_):
    with new_event_loop_context() as loop:
        loop.run_until_complete(async_subworker(logger_))


class Writer:
    def __init__(self):
        self.output = ""

    async def write(self, message):
        self.output += message


def test_complete_with_sub_processes(cap: StdCapture) -> None:
    spawn_context = multiprocessing.get_context("spawn")

    with new_event_loop_context() as loop:
        writer = Writer()
        logger.add(writer.write, context=spawn_context, format="{message}", enqueue=True, loop=loop)

        process = spawn_context.Process(target=subworker, args=[logger])
        process.start()
        process.join()

        async def complete():
            await logger.complete()

        loop.run_until_complete(complete())

    captured = cap.readouterr()
    assert captured.out == captured.err == "", "the sink collects messages rather than printing"
    assert writer.output == "Child\n", (
        "complete() in the child must not block waiting for the parent's loop, and the "
        "record must still reach the parent's async sink"
    )


def test_invalid_coroutine_sink_if_no_loop_with_enqueue() -> None:
    with oxitest.raises(
        ValueError,
        match=(
            r"^An event loop is required to add a coroutine sink with `enqueue=True`, "
            r"but none has been passed as argument and none is currently running.$"
        ),
    ):
        logger.add(async_writer, enqueue=True, loop=None)
