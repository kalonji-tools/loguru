import asyncio
import sys
import threading
from unittest.mock import MagicMock

from conftest import Writer
from oxitest import Fixture, helpers

from loguru import logger
from loguru._contextvars import load_contextvar_class


def test_contextualize(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message} {extra[foo]} {extra[baz]}")

    with logger.contextualize(foo="bar", baz=123):
        logger.info("Contextualized")

    assert writer.read() == "Contextualized bar 123\n", (
        "contextualize() must add its values to extra for every record logged inside the "
        "block, which is the whole point of ambient context"
    )


def test_contextualize_as_decorator(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message} {extra[foo]} {extra[baz]}")

    @logger.contextualize(foo=123, baz="bar")
    def task():
        logger.info("Contextualized")

    task()

    assert writer.read() == "Contextualized 123 bar\n", (
        "the same object must work as a decorator, so a whole function can be wrapped "
        "without indenting its body"
    )


def test_contextualize_in_function(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message} {extra}")

    def foobar():
        logger.info("Foobar!")

    with logger.contextualize(foobar="baz"):
        foobar()

    assert writer.read() == "Foobar! {'foobar': 'baz'}\n", (
        "the context must reach code called from inside the block, otherwise it could not "
        "annotate logs emitted deep in a call stack"
    )


def test_contextualize_reset() -> None:
    contexts = []
    output = []

    def sink(message):
        contexts.append(message.record["extra"])
        output.append(str(message))

    logger.add(sink, format="{level} {message}")

    logger.info("A")

    with logger.contextualize(abc="def"):
        logger.debug("B")
        logger.warning("C")

    logger.info("D")

    assert contexts == [{}, {"abc": "def"}, {"abc": "def"}, {}], (
        "the context must be restored on exit, otherwise it would leak into every later "
        "record in the process"
    )
    assert output == ["INFO A\n", "DEBUG B\n", "WARNING C\n", "INFO D\n"], (
        "contextualize() must not alter the messages themselves, only the extra dict"
    )


def test_contextualize_async(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message} {extra[i]}", catch=False)

    async def task():
        logger.info("Start")
        await asyncio.sleep(0.1)
        logger.info("End")

    async def worker(i):
        with logger.contextualize(i=i):
            await task()

    async def main():
        workers = [worker(i) for i in range(5)]
        await asyncio.gather(*workers)
        await logger.complete()

    asyncio.run(main())

    assert sorted(writer.read().splitlines()) == ["End %d" % i for i in range(5)] + [
        "Start %d" % i for i in range(5)
    ], (
        "context is stored in a ContextVar, so concurrent tasks must each keep their own "
        "value across an await rather than observe whichever ran last"
    )


def test_contextualize_thread(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message} {extra[i]}")

    def task():
        logger.info("Processing")

    def worker(entry_barrier, exit_barrier, i):
        with logger.contextualize(i=i):
            entry_barrier.wait()
            task()
            exit_barrier.wait()

    entry_barrier = threading.Barrier(5)
    exit_barrier = threading.Barrier(5)

    threads = [
        threading.Thread(target=worker, args=(entry_barrier, exit_barrier, i)) for i in range(5)
    ]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join()

    assert sorted(writer.read().splitlines()) == ["Processing %d" % i for i in range(5)], (
        "the barriers hold every thread inside its own context at once, so a shared context "
        "would show up here as duplicated or missing values"
    )


def test_contextualize_before_bind(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message} {extra[foobar]}")

    logger_2 = logger.bind(foobar="baz")

    with logger.contextualize(foobar="baz_2"):
        logger.info("A")
        logger_2.info("B")

    logger_2.info("C")

    assert writer.read() == "A baz_2\nB baz\nC baz\n", (
        "bind() is explicit and per-logger, so it must take precedence over the ambient "
        "context regardless of which came first"
    )


def test_contextualize_after_bind(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message} {extra[foobar]}")

    with logger.contextualize(foobar="baz"):
        logger_2 = logger.bind(foobar="baz_2")
        logger.info("A")
        logger_2.info("B")

    logger_2.info("C")

    assert writer.read() == "A baz\nB baz_2\nC baz_2\n", (
        "a logger bound inside the block must keep its own value after the block ends, "
        "since bind() copies the value rather than referring to the context"
    )


def test_contextualize_using_bound(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message} {extra[foobar]}")

    logger_2 = logger.bind(foobar="baz")

    with logger_2.contextualize(foobar="baz_2"):
        logger.info("A")
        logger_2.info("B")

    logger_2.info("C")

    assert writer.read() == "A baz_2\nB baz\nC baz\n", (
        "the context is process-wide no matter which logger opened it, but that logger's "
        "own binding still wins for its own records"
    )


def test_contextualize_before_configure(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message} {extra[foobar]}")

    logger.configure(extra={"foobar": "baz"})

    with logger.contextualize(foobar="baz_2"):
        logger.info("A")

    logger.info("B")

    assert writer.read() == "A baz_2\nB baz\n", (
        "the context must override the application-wide extra inside the block and restore "
        "it afterwards"
    )


def test_contextualize_after_configure(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message} {extra[foobar]}")

    with logger.contextualize(foobar="baz"):
        logger.configure(extra={"foobar": "baz_2"})
        logger.info("A")

    logger.info("B")

    assert writer.read() == "A baz\nB baz_2\n", (
        "configure() called inside the block must not disturb the active context, but must "
        "take effect once the block exits"
    )


def test_nested_contextualize(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message} {extra[foobar]}")

    with logger.contextualize(foobar="a"):
        with logger.contextualize(foobar="b"):
            logger.info("B")

        logger.info("A")

        with logger.contextualize(foobar="c"):
            logger.info("C")

    assert writer.read() == "B b\nA a\nC c\n", (
        "each nested block must restore exactly the value it replaced, otherwise leaving an "
        "inner block would reset the context instead of unwinding one level"
    )


def test_context_reset_despite_error(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message} {extra}")

    try:
        with logger.contextualize(foobar=456):
            logger.info("Division")
            1 / 0  # noqa: B018
    except ZeroDivisionError:
        logger.info("Error")

    assert writer.read() == "Division {'foobar': 456}\nError {}\n", (
        "the context must be restored even when the block raises, otherwise one exception "
        "would poison the extra dict for the rest of the process"
    )


# There is not CI runner available for Python 3.5.2. Consequently, we are just
# verifying third-library is properly imported to reach 100% coverage.
def test_contextvars_fallback_352() -> None:
    mock_module = MagicMock()
    with helpers.common.patch_context() as context:
        context.setattr(sys, "version_info", (3, 5, 2))
        context.setitem(sys.modules, "contextvars", mock_module)
        assert load_contextvar_class() == mock_module.ContextVar, (
            "on Python 3.5.2 the stdlib ContextVar does not exist, so loguru must load the "
            "backport package instead of failing to import"
        )
