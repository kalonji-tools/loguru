import copy
import multiprocessing
import os
import platform
import sys
import threading
import time
from dataclasses import dataclass

import oxitest
from oxitest import StdCapture, TempDir

from loguru import logger
from tests._naming import pin_module_name
from tests._utils import new_event_loop_context

# "spawn" re-imports this module in the child to unpickle the worker functions below, so
# the module has to be reachable under an importable name.
pin_module_name(globals(), "tests.test_multiprocessing")

WINDOWS_HAS_NO_FORK = "Windows does not support forking"


@dataclass
class DeadlockCase:
    enqueue: bool
    deepcopied: bool


@dataclass(frozen=True)
class EnqueueCase:
    enqueue: bool


ENQUEUE_CASES = {
    "enqueued": EnqueueCase(enqueue=True),
    "direct": EnqueueCase(enqueue=False),
}


def do_something(i):
    logger.info("#{}", i)


def set_logger(logger_):
    global logger
    logger = logger_


def subworker(logger_):
    logger_.info("Child")


def subworker_inheritance():
    logger.info("Child")


def subworker_remove(logger_):
    logger_.info("Child")
    logger_.remove()
    logger_.info("Nope")


def subworker_remove_inheritance():
    logger.info("Child")
    logger.remove()
    logger.info("Nope")


def subworker_complete(logger_):
    async def work():
        logger_.info("Child")
        await logger_.complete()

    with new_event_loop_context() as loop:
        loop.run_until_complete(work())


def subworker_complete_inheritance():
    async def work():
        logger.info("Child")
        await logger.complete()

    with new_event_loop_context() as loop:
        loop.run_until_complete(work())


def subworker_barrier(logger_, barrier):
    logger_.info("Child")
    barrier.wait()
    time.sleep(0.5)
    logger_.info("Nope")


def subworker_barrier_inheritance(barrier):
    logger.info("Child")
    barrier.wait()
    time.sleep(0.5)
    logger.info("Nope")


class Writer:
    def __init__(self):
        self._output = ""

    def write(self, message):
        self._output += message

    def read(self):
        return self._output


CHILD_MUST_REACH_PARENT_SINK = (
    "records logged in the child must travel over the queue to the parent's sink, in order, "
    "otherwise logs from worker processes are lost or interleaved"
)

CHILD_MUST_EXIT_CLEANLY = (
    "the child must exit cleanly; a non-zero code means it raised before reaching the "
    "assertions below"
)


def test_apply_spawn() -> None:
    spawn_context = multiprocessing.get_context("spawn")
    writer = Writer()

    logger.add(writer, context=spawn_context, format="{message}", enqueue=True, catch=False)

    with spawn_context.Pool(1, set_logger, [logger]) as pool:
        for i in range(3):
            pool.apply(do_something, (i,))
        pool.close()
        pool.join()

    logger.info("Done!")
    logger.remove()

    assert writer.read() == "#0\n#1\n#2\nDone!\n", CHILD_MUST_REACH_PARENT_SINK


@oxitest.mark.skip(when=os.name == "nt", reason=WINDOWS_HAS_NO_FORK)
def test_apply_fork() -> None:
    fork_context = multiprocessing.get_context("fork")
    writer = Writer()

    logger.add(writer, context=fork_context, format="{message}", enqueue=True, catch=False)

    with fork_context.Pool(1, set_logger, [logger]) as pool:
        for i in range(3):
            pool.apply(do_something, (i,))
        pool.close()
        pool.join()

    logger.info("Done!")
    logger.remove()

    assert writer.read() == "#0\n#1\n#2\nDone!\n", CHILD_MUST_REACH_PARENT_SINK


@oxitest.mark.skip(when=os.name == "nt", reason=WINDOWS_HAS_NO_FORK)
def test_apply_inheritance() -> None:
    fork_context = multiprocessing.get_context("fork")
    writer = Writer()

    logger.add(writer, context=fork_context, format="{message}", enqueue=True, catch=False)

    with fork_context.Pool(1) as pool:
        for i in range(3):
            pool.apply(do_something, (i,))
        pool.close()
        pool.join()

    logger.info("Done!")
    logger.remove()

    assert writer.read() == "#0\n#1\n#2\nDone!\n", (
        "a forked child inherits the configured logger, so it must reach the parent's sink "
        "without the logger being passed explicitly"
    )


def test_apply_async_spawn() -> None:
    spawn_context = multiprocessing.get_context("spawn")
    writer = Writer()

    logger.add(writer, context=spawn_context, format="{message}", enqueue=True, catch=False)

    with spawn_context.Pool(1, set_logger, [logger]) as pool:
        for i in range(3):
            result = pool.apply_async(do_something, (i,))
            result.get()
        pool.close()
        pool.join()

    logger.info("Done!")
    logger.remove()

    assert writer.read() == "#0\n#1\n#2\nDone!\n", CHILD_MUST_REACH_PARENT_SINK


@oxitest.mark.skip(when=os.name == "nt", reason=WINDOWS_HAS_NO_FORK)
def test_apply_async_fork() -> None:
    fork_context = multiprocessing.get_context("fork")
    writer = Writer()

    logger.add(writer, context=fork_context, format="{message}", enqueue=True, catch=False)

    with fork_context.Pool(1, set_logger, [logger]) as pool:
        for i in range(3):
            result = pool.apply_async(do_something, (i,))
            result.get()
        pool.close()
        pool.join()

    logger.info("Done!")
    logger.remove()

    assert writer.read() == "#0\n#1\n#2\nDone!\n", CHILD_MUST_REACH_PARENT_SINK


@oxitest.mark.skip(when=os.name == "nt", reason=WINDOWS_HAS_NO_FORK)
def test_apply_async_inheritance() -> None:
    fork_context = multiprocessing.get_context("fork")
    writer = Writer()

    logger.add(writer, context=fork_context, format="{message}", enqueue=True, catch=False)

    with fork_context.Pool(1) as pool:
        for i in range(3):
            result = pool.apply_async(do_something, (i,))
            result.get()
        pool.close()
        pool.join()

    logger.info("Done!")
    logger.remove()

    assert writer.read() == "#0\n#1\n#2\nDone!\n", (
        "a forked child inherits the configured logger, so it must reach the parent's sink "
        "without the logger being passed explicitly"
    )


def test_process_spawn() -> None:
    spawn_context = multiprocessing.get_context("spawn")
    writer = Writer()

    logger.add(writer, context=spawn_context, format="{message}", enqueue=True, catch=False)

    process = spawn_context.Process(target=subworker, args=(logger,))
    process.start()
    process.join()

    assert process.exitcode == 0, CHILD_MUST_EXIT_CLEANLY

    logger.info("Main")
    logger.remove()

    assert writer.read() == "Child\nMain\n", CHILD_MUST_REACH_PARENT_SINK


@oxitest.mark.skip(when=os.name == "nt", reason=WINDOWS_HAS_NO_FORK)
def test_process_fork() -> None:
    fork_context = multiprocessing.get_context("fork")
    writer = Writer()

    logger.add(writer, context=fork_context, format="{message}", enqueue=True, catch=False)

    process = fork_context.Process(target=subworker, args=(logger,))
    process.start()
    process.join()

    assert process.exitcode == 0, CHILD_MUST_EXIT_CLEANLY

    logger.info("Main")
    logger.remove()

    assert writer.read() == "Child\nMain\n", CHILD_MUST_REACH_PARENT_SINK


@oxitest.mark.skip(when=os.name == "nt", reason=WINDOWS_HAS_NO_FORK)
def test_process_inheritance() -> None:
    fork_context = multiprocessing.get_context("fork")
    writer = Writer()

    logger.add(writer, context=fork_context, format="{message}", enqueue=True, catch=False)

    process = fork_context.Process(target=subworker_inheritance)
    process.start()
    process.join()

    assert process.exitcode == 0, CHILD_MUST_EXIT_CLEANLY

    logger.info("Main")
    logger.remove()

    assert writer.read() == "Child\nMain\n", (
        "a forked child inherits the configured logger, so it must reach the parent's sink "
        "without the logger being passed explicitly"
    )


def test_remove_in_child_process_spawn() -> None:
    spawn_context = multiprocessing.get_context("spawn")
    writer = Writer()

    logger.add(writer, context=spawn_context, format="{message}", enqueue=True, catch=False)

    process = spawn_context.Process(target=subworker_remove, args=(logger,))
    process.start()
    process.join()

    assert process.exitcode == 0, CHILD_MUST_EXIT_CLEANLY

    logger.info("Main")
    logger.remove()

    assert writer.read() == "Child\nMain\n", (
        "remove() in the child must detach only the child's view of the sink, leaving the "
        "parent free to keep logging"
    )


@oxitest.mark.skip(when=os.name == "nt", reason=WINDOWS_HAS_NO_FORK)
def test_remove_in_child_process_fork() -> None:
    fork_context = multiprocessing.get_context("fork")
    writer = Writer()

    logger.add(writer, context=fork_context, format="{message}", enqueue=True, catch=False)

    process = fork_context.Process(target=subworker_remove, args=(logger,))
    process.start()
    process.join()

    assert process.exitcode == 0, CHILD_MUST_EXIT_CLEANLY

    logger.info("Main")
    logger.remove()

    assert writer.read() == "Child\nMain\n", (
        "remove() in the child must detach only the child's view of the sink, leaving the "
        "parent free to keep logging"
    )


@oxitest.mark.skip(when=os.name == "nt", reason=WINDOWS_HAS_NO_FORK)
def test_remove_in_child_process_inheritance() -> None:
    fork_context = multiprocessing.get_context("fork")
    writer = Writer()

    logger.add(writer, context=fork_context, format="{message}", enqueue=True, catch=False)

    process = fork_context.Process(target=subworker_remove_inheritance)
    process.start()
    process.join()

    assert process.exitcode == 0, CHILD_MUST_EXIT_CLEANLY

    logger.info("Main")
    logger.remove()

    assert writer.read() == "Child\nMain\n", (
        "remove() in the child must detach only the child's view of the sink, leaving the "
        "parent free to keep logging"
    )


def test_remove_in_main_process_spawn() -> None:
    # Actually, this test may fail if sleep time in main process is too small (and no barrier used)
    # In such situation, it seems the child process has not enough time to initialize itself
    # It may fail with an "EOFError" during unpickling of the (garbage collected / closed) Queue
    spawn_context = multiprocessing.get_context("spawn")
    writer = Writer()
    barrier = spawn_context.Barrier(2)

    logger.add(writer, context=spawn_context, format="{message}", enqueue=True, catch=False)

    process = spawn_context.Process(target=subworker_barrier, args=(logger, barrier))
    process.start()
    barrier.wait()
    logger.info("Main")
    logger.remove()
    process.join()

    assert process.exitcode == 0, CHILD_MUST_EXIT_CLEANLY

    assert writer.read() == "Child\nMain\n", (
        "remove() in the parent must stop accepting records from the child, and must do so "
        "without the child's later logging call raising"
    )


@oxitest.mark.skip(when=os.name == "nt", reason=WINDOWS_HAS_NO_FORK)
def test_remove_in_main_process_fork() -> None:
    fork_context = multiprocessing.get_context("fork")
    writer = Writer()
    barrier = fork_context.Barrier(2)

    logger.add(writer, context=fork_context, format="{message}", enqueue=True, catch=False)

    process = fork_context.Process(target=subworker_barrier, args=(logger, barrier))
    process.start()
    barrier.wait()
    logger.info("Main")
    logger.remove()
    process.join()

    assert process.exitcode == 0, CHILD_MUST_EXIT_CLEANLY

    assert writer.read() == "Child\nMain\n", (
        "remove() in the parent must stop accepting records from the child, and must do so "
        "without the child's later logging call raising"
    )


@oxitest.mark.skip(when=os.name == "nt", reason=WINDOWS_HAS_NO_FORK)
def test_remove_in_main_process_inheritance() -> None:
    fork_context = multiprocessing.get_context("fork")
    writer = Writer()
    barrier = fork_context.Barrier(2)

    logger.add(writer, context=fork_context, format="{message}", enqueue=True, catch=False)

    process = fork_context.Process(target=subworker_barrier_inheritance, args=(barrier,))
    process.start()
    barrier.wait()
    logger.info("Main")
    logger.remove()
    process.join()

    assert process.exitcode == 0, CHILD_MUST_EXIT_CLEANLY

    assert writer.read() == "Child\nMain\n", (
        "remove() in the parent must stop accepting records from the child, and must do so "
        "without the child's later logging call raising"
    )


def test_await_complete_spawn(cap: StdCapture) -> None:
    spawn_context = multiprocessing.get_context("spawn")

    async def writer(msg):
        print(msg, end="")

    with new_event_loop_context() as loop:
        logger.add(
            writer, context=spawn_context, format="{message}", loop=loop, enqueue=True, catch=False
        )

        process = spawn_context.Process(target=subworker_complete, args=(logger,))
        process.start()
        process.join()

        assert process.exitcode == 0, CHILD_MUST_EXIT_CLEANLY

        async def local():
            await logger.complete()

        loop.run_until_complete(local())

    captured = cap.readouterr()
    assert captured.out == "Child\n", (
        "complete() in the child must not block on the parent's loop; the record still has "
        "to reach the async sink once the parent awaits complete()"
    )
    assert captured.err == "", "the sink writes to stdout, so stderr must stay empty"


@oxitest.mark.skip(when=os.name == "nt", reason=WINDOWS_HAS_NO_FORK)
def test_await_complete_fork(cap: StdCapture) -> None:
    fork_context = multiprocessing.get_context("fork")

    async def writer(msg):
        print(msg, end="")

    with new_event_loop_context() as loop:
        logger.add(
            writer, context=fork_context, format="{message}", loop=loop, enqueue=True, catch=False
        )

        process = fork_context.Process(target=subworker_complete, args=(logger,))
        process.start()
        process.join()

        assert process.exitcode == 0, CHILD_MUST_EXIT_CLEANLY

        async def local():
            await logger.complete()

        loop.run_until_complete(local())

    captured = cap.readouterr()
    assert captured.out == "Child\n", (
        "complete() in the child must not block on the parent's loop; the record still has "
        "to reach the async sink once the parent awaits complete()"
    )
    assert captured.err == "", "the sink writes to stdout, so stderr must stay empty"


@oxitest.mark.skip(when=os.name == "nt", reason=WINDOWS_HAS_NO_FORK)
def test_await_complete_inheritance(cap: StdCapture) -> None:
    fork_context = multiprocessing.get_context("fork")

    async def writer(msg):
        print(msg, end="")

    with new_event_loop_context() as loop:
        logger.add(
            writer, context=fork_context, format="{message}", loop=loop, enqueue=True, catch=False
        )

        process = fork_context.Process(target=subworker_complete_inheritance)
        process.start()
        process.join()

        assert process.exitcode == 0, CHILD_MUST_EXIT_CLEANLY

        async def local():
            await logger.complete()

        loop.run_until_complete(local())

    captured = cap.readouterr()
    assert captured.out == "Child\n", (
        "complete() in the child must not block on the parent's loop; the record still has "
        "to reach the async sink once the parent awaits complete()"
    )
    assert captured.err == "", "the sink writes to stdout, so stderr must stay empty"


def test_not_picklable_sinks_spawn(tmp: TempDir, cap: StdCapture) -> None:
    spawn_context = multiprocessing.get_context("spawn")
    filepath = tmp.path / "test.log"
    stream = sys.stderr
    output = []

    logger.add(filepath, context=spawn_context, format="{message}", enqueue=True, catch=False)
    logger.add(stream, context=spawn_context, format="{message}", enqueue=True)
    logger.add(lambda m: output.append(m), context=spawn_context, format="{message}", enqueue=True)

    process = spawn_context.Process(target=subworker, args=[logger])
    process.start()
    process.join()

    assert process.exitcode == 0, CHILD_MUST_EXIT_CLEANLY

    logger.info("Main")
    logger.remove()

    captured = cap.readouterr()

    why = (
        "with enqueue the sink itself stays in the parent and only the record is pickled, so "
        "even an unpicklable sink must keep working across processes"
    )
    assert filepath.read_text() == "Child\nMain\n", why
    assert captured.out == "", "no sink targets stdout here"
    assert captured.err == "Child\nMain\n", why
    assert output == ["Child\n", "Main\n"], why


@oxitest.mark.skip(when=os.name == "nt", reason=WINDOWS_HAS_NO_FORK)
def test_not_picklable_sinks_fork(tmp: TempDir, cap: StdCapture) -> None:
    fork_context = multiprocessing.get_context("fork")
    filepath = tmp.path / "test.log"
    stream = sys.stderr
    output = []

    logger.add(filepath, context=fork_context, format="{message}", enqueue=True, catch=False)
    logger.add(stream, context=fork_context, format="{message}", enqueue=True, catch=False)
    logger.add(
        lambda m: output.append(m),
        context=fork_context,
        format="{message}",
        enqueue=True,
        catch=False,
    )

    process = fork_context.Process(target=subworker, args=[logger])
    process.start()
    process.join()

    assert process.exitcode == 0, CHILD_MUST_EXIT_CLEANLY

    logger.info("Main")
    logger.remove()

    captured = cap.readouterr()

    why = (
        "with enqueue the sink itself stays in the parent and only the record is pickled, so "
        "even an unpicklable sink must keep working across processes"
    )
    assert filepath.read_text() == "Child\nMain\n", why
    assert captured.out == "", "no sink targets stdout here"
    assert captured.err == "Child\nMain\n", why
    assert output == ["Child\n", "Main\n"], why


@oxitest.mark.skip(when=os.name == "nt", reason=WINDOWS_HAS_NO_FORK)
def test_not_picklable_sinks_inheritance(tmp: TempDir, cap: StdCapture) -> None:
    fork_context = multiprocessing.get_context("fork")
    filepath = tmp.path / "test.log"
    stream = sys.stderr
    output = []

    logger.add(filepath, context=fork_context, format="{message}", enqueue=True, catch=False)
    logger.add(stream, context=fork_context, format="{message}", enqueue=True, catch=False)
    logger.add(
        lambda m: output.append(m),
        context=fork_context,
        format="{message}",
        enqueue=True,
        catch=False,
    )

    process = fork_context.Process(target=subworker_inheritance)
    process.start()
    process.join()

    assert process.exitcode == 0, CHILD_MUST_EXIT_CLEANLY

    logger.info("Main")
    logger.remove()

    captured = cap.readouterr()

    why = (
        "with enqueue the sink itself stays in the parent and only the record is pickled, so "
        "even an unpicklable sink must keep working across processes"
    )
    assert filepath.read_text() == "Child\nMain\n", why
    assert captured.out == "", "no sink targets stdout here"
    assert captured.err == "Child\nMain\n", why
    assert output == ["Child\n", "Main\n"], why


@oxitest.mark.skip(when=os.name == "nt", reason=WINDOWS_HAS_NO_FORK)
@oxitest.parametrize(
    enqueued=oxitest.partial(DeadlockCase, enqueue=True),
    direct=oxitest.partial(DeadlockCase, enqueue=False),
)
@oxitest.parametrize(
    deepcopied=oxitest.partial(DeadlockCase, deepcopied=True),
    original=oxitest.partial(DeadlockCase, deepcopied=False),
)
def test_no_deadlock_if_internal_lock_in_use(tmp: TempDir, enqueue: bool, deepcopied: bool) -> None:
    fork_context = multiprocessing.get_context("fork")
    if deepcopied:
        logger_ = copy.deepcopy(logger)
    else:
        logger_ = logger

    output = tmp.path / "stdout.txt"

    with output.open("w") as stdout:

        def slow_sink(msg):
            time.sleep(0.5)
            stdout.write(msg)
            stdout.flush()

        def main():
            logger_.info("Main")

        def worker():
            logger_.info("Child")

        logger_.add(
            slow_sink, context=fork_context, format="{message}", enqueue=enqueue, catch=False
        )

        thread = threading.Thread(target=main)
        thread.start()

        process = fork_context.Process(target=worker)
        process.start()

        thread.join()
        process.join(2)

        assert process.exitcode == 0, (
            "forking while another thread holds the handler lock must not leave the child "
            "with a lock nobody will ever release — a non-zero exit code here means deadlock"
        )

        logger_.remove()

    assert output.read_text() in (
        "Main\nChild\n",
        "Child\nMain\n",
    ), "both messages must be written; only their order may vary"


@oxitest.mark.skip(when=os.name == "nt", reason=WINDOWS_HAS_NO_FORK)
@oxitest.parametrize(**ENQUEUE_CASES)
def test_no_deadlock_if_external_lock_in_use(enqueue: bool, cap: StdCapture) -> None:
    fork_context = multiprocessing.get_context("fork")
    # Can't reproduce the bug on the test runner (even if stderr is not wrapped), but let it anyway
    logger.add(sys.stderr, context=fork_context, enqueue=enqueue, catch=True, format="{message}")
    num = 100

    for i in range(num):
        logger.info("This is a message: {}", i)
        process = fork_context.Process(target=lambda: None)
        process.start()
        process.join(1)
        assert process.exitcode == 0, (
            "forking right after a logging call must not inherit a held stream lock; a "
            "non-zero exit code here means the child deadlocked"
        )

    logger.remove()

    captured = cap.readouterr()
    assert captured.out == "", "the sink targets stderr, so stdout must stay empty"
    assert captured.err == "".join(
        "This is a message: %d\n" % i for i in range(num)
    ), "every message must be written exactly once and in order despite the interleaved forks"


@oxitest.mark.skip(when=os.name == "nt", reason=WINDOWS_HAS_NO_FORK)
@oxitest.mark.skip(when=platform.python_implementation() == "PyPy", reason="PyPy is too slow")
def test_complete_from_multiple_child_processes(cap: StdCapture) -> None:
    fork_context = multiprocessing.get_context("fork")
    logger.add(lambda _: None, context=fork_context, enqueue=True, catch=False)
    num = 100

    barrier = fork_context.Barrier(num)

    def worker(barrier):
        barrier.wait()
        logger.complete()

    processes = []

    for _ in range(num):
        process = fork_context.Process(target=worker, args=(barrier,))
        process.start()
        processes.append(process)

    for process in processes:
        process.join(5)
        assert process.exitcode == 0, (
            "many children calling complete() at once must not contend for a shared lock; a "
            "non-zero exit code here means one of them deadlocked or timed out"
        )

    captured = cap.readouterr()
    assert (
        captured.out == captured.err == ""
    ), "with catch=False any failure in a child would surface on the standard streams"
