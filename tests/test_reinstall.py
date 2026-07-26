import multiprocessing
import os

import oxitest

from loguru import logger
from tests._naming import pin_module_name

# "spawn" re-imports this module in the child to unpickle the worker functions below, so
# the module has to be reachable under an importable name.
pin_module_name(globals(), "tests.test_reinstall")

WINDOWS_HAS_NO_FORK = "Windows does not support forking"


class Writer:
    def __init__(self):
        self._output = ""

    def write(self, message):
        self._output += message

    def read(self):
        return self._output


def subworker(logger):
    logger.reinstall()
    logger.info("Child")
    deeper_subworker()


def poolworker(_):
    logger.info("Child")
    deeper_subworker()


def deeper_subworker():
    logger.info("Grandchild")


@oxitest.mark.skip(when=os.name == "nt", reason=WINDOWS_HAS_NO_FORK)
def test_process_fork() -> None:
    fork_context = multiprocessing.get_context("fork")
    writer = Writer()

    logger.add(writer, context=fork_context, format="{message}", enqueue=True, catch=False)

    process = fork_context.Process(target=subworker, args=(logger,))
    process.start()
    process.join()

    assert process.exitcode == 0, (
        "the child must exit cleanly; a non-zero code means reinstall() raised and the "
        "messages below would be missing for that reason rather than a queueing bug"
    )

    logger.info("Main")
    logger.remove()

    assert writer.read() == "Child\nGrandchild\nMain\n", (
        "after reinstall() the forked child must reach the parent's sink from any call "
        "depth, otherwise logs from subprocesses are silently dropped"
    )


def test_process_spawn() -> None:
    spawn_context = multiprocessing.get_context("spawn")
    writer = Writer()

    logger.add(writer, context=spawn_context, format="{message}", enqueue=True, catch=False)

    process = spawn_context.Process(target=subworker, args=(logger,))
    process.start()
    process.join()

    assert process.exitcode == 0, (
        "the child must exit cleanly; a non-zero code means reinstall() raised and the "
        "messages below would be missing for that reason rather than a queueing bug"
    )

    logger.info("Main")
    logger.remove()

    assert writer.read() == "Child\nGrandchild\nMain\n", (
        "after reinstall() the spawned child must reach the parent's sink from any call "
        "depth, otherwise logs from subprocesses are silently dropped"
    )


@oxitest.mark.skip(when=os.name == "nt", reason=WINDOWS_HAS_NO_FORK)
def test_pool_fork() -> None:
    fork_context = multiprocessing.get_context("fork")
    writer = Writer()

    logger.add(writer, context=fork_context, format="{message}", enqueue=True, catch=False)

    with fork_context.Pool(1, initializer=logger.reinstall) as pool:
        pool.map(poolworker, [None])

    logger.info("Main")
    logger.remove()

    assert writer.read() == "Child\nGrandchild\nMain\n", (
        "reinstall() must work as a Pool initializer, since that is the only hook a pool "
        "worker has to reconnect to the parent's sinks"
    )


def test_pool_spawn() -> None:
    spawn_context = multiprocessing.get_context("spawn")
    writer = Writer()

    logger.add(writer, context=spawn_context, format="{message}", enqueue=True, catch=False)

    with spawn_context.Pool(1, initializer=logger.reinstall) as pool:
        pool.map(poolworker, [None])

    logger.info("Main")
    logger.remove()

    assert writer.read() == "Child\nGrandchild\nMain\n", (
        "reinstall() must work as a Pool initializer, since that is the only hook a pool "
        "worker has to reconnect to the parent's sinks"
    )
