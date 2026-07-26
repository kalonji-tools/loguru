import asyncio
import contextlib
import datetime
import logging
import pickle
from dataclasses import dataclass
from typing import Any, Callable

import oxitest
from conftest import Writer
from oxitest import Fixture, StdCapture, TempDir, helpers

from loguru import logger
from tests._naming import pin_module_name
from tests._utils import parse

# Pickle stores a function by module and qualified name, so the module must be reachable
# under an importable name; some cases below also filter on that dotted name.
pin_module_name(globals(), "tests.test_pickling")

NOT_PICKLABLE_MESSAGE = r"Can't (pickle|get local)"
NO_STDERR_EXPECTED = "the sink writes to stdout, so stderr must stay empty"


@dataclass
class StreamHandlerCase:
    flushable: bool
    stoppable: bool


@dataclass(frozen=True)
class RotationCase:
    rotation: Any


@dataclass(frozen=True)
class RetentionCase:
    retention: Any


@dataclass(frozen=True)
class CompressionCase:
    compression: Any


@dataclass(frozen=True)
class FilterNameCase:
    filter: str


@dataclass(frozen=True)
class ColorizeCase:
    colorize: bool


@dataclass(frozen=True)
class MethodCase:
    method: Callable[..., Any]


COLORIZE_CASES = {
    "colorized": ColorizeCase(colorize=True),
    "plain": ColorizeCase(colorize=False),
}


def print_(message):
    print(message, end="")


async def async_print(msg):
    print_(msg)


@contextlib.contextmanager
def copied_logger_though_pickle(logger):
    pickled = pickle.dumps(logger)
    unpickled = pickle.loads(pickled)
    try:
        yield unpickled
    finally:
        unpickled.remove()


class StreamHandler:
    def __init__(self, flushable=False, stoppable=False):
        if flushable:
            self.flush = self._flush
        if stoppable:
            self.stop = self._stop

        self.wrote = ""
        self.flushed = False
        self.stopped = False

    def write(self, message):
        self.wrote += message

    def _flush(self):
        self.flushed = True

    def _stop(self):
        self.stopped = True


class MockLock:
    def __enter__(self):
        pass

    def __exit__(self, *excinfo):
        pass


class StandardHandler(logging.Handler):
    def __init__(self, level):
        super().__init__(level)
        self.written = ""

    def emit(self, record):
        self.written += record.getMessage()

    def acquire(self):
        pass

    def release(self):
        pass

    def createLock(self):  # noqa: N802
        self.lock = MockLock()


def format_function(record):
    return "-> <red>{message}</red>"


def filter_function(record):
    return "[PASS]" in record["message"]


def patch_function(record):
    record["extra"]["foo"] = "bar"


def rotation_function(message, file):
    pass


def retention_function(files):
    pass


def compression_function(path):
    pass


def test_pickling_function_handler(cap: StdCapture) -> None:
    logger.add(print_, format="{level} - {function} - {message}")
    with copied_logger_though_pickle(logger) as dupe_logger:
        dupe_logger.debug("A message")
    captured = cap.readouterr()
    assert captured.out == "DEBUG - test_pickling_function_handler - A message\n", (
        "a function sink must survive pickling, since that is how handlers reach a process "
        "started with the 'spawn' method"
    )
    assert captured.err == "", NO_STDERR_EXPECTED


def test_pickling_coroutine_function_handler(cap: StdCapture) -> None:
    logger.add(async_print, format="{level} - {function} - {message}")

    with copied_logger_though_pickle(logger) as dupe_logger:

        async def async_debug():
            dupe_logger.debug("A message")
            await dupe_logger.complete()

        asyncio.run(async_debug())

    captured = cap.readouterr()
    assert (
        captured.out == "DEBUG - async_debug - A message\n"
    ), "an async sink must survive pickling and still be awaitable afterwards"
    assert captured.err == "", NO_STDERR_EXPECTED


@oxitest.parametrize(
    flushable=oxitest.partial(StreamHandlerCase, flushable=True),
    not_flushable=oxitest.partial(StreamHandlerCase, flushable=False),
)
@oxitest.parametrize(
    stoppable=oxitest.partial(StreamHandlerCase, stoppable=True),
    not_stoppable=oxitest.partial(StreamHandlerCase, stoppable=False),
)
def test_pickling_stream_handler(flushable: bool, stoppable: bool) -> None:
    stream = StreamHandler(flushable, stoppable)
    logger.add(stream, format="{level} - {function} - {message}")
    with copied_logger_though_pickle(logger) as dupe_logger:
        dupe_logger.debug("A message")
        stream = next(iter(dupe_logger._core.handlers.values()))._sink._stream
    assert (
        stream.wrote == "DEBUG - test_pickling_stream_handler - A message\n"
    ), "a stream sink must survive pickling and keep receiving records"
    assert (
        stream.flushed == flushable
    ), "whether the sink has a flush() must be re-detected after unpickling, not assumed"
    assert (
        stream.stopped == stoppable
    ), "whether the sink has a stop() must be re-detected after unpickling, not assumed"


def test_pickling_standard_handler() -> None:
    handler = StandardHandler(logging.NOTSET)
    logger.add(handler, format="{level} - {function} - {message}")
    with copied_logger_though_pickle(logger) as dupe_logger:
        dupe_logger.debug("A message")
        handler = next(iter(dupe_logger._core.handlers.values()))._sink._handler
        assert handler.written == "DEBUG - test_pickling_standard_handler - A message", (
            "a standard logging.Handler must survive pickling, which requires its "
            "unpicklable lock to be recreated rather than serialized"
        )


def test_pickling_standard_handler_root_logger_not_picklable(cap: StdCapture) -> None:
    def reduce_protocol():
        raise TypeError("Not picklable")

    with helpers.common.patch_context() as context:
        context.setattr(logging.getLogger(), "__reduce__", reduce_protocol, raising=False)

        handler = StandardHandler(logging.NOTSET)
        logger.add(handler, format="=> {message}", catch=False)

        with copied_logger_though_pickle(logger) as dupe_logger:
            logger.info("Ok")
            dupe_logger.info("Ok")
            captured = cap.readouterr()
            assert captured.out == "", "nothing here writes to stdout"
            assert captured.err == "", (
                "a root logger that refuses to pickle must not break handler pickling, "
                "otherwise a single unpicklable global would make logging unusable"
            )
            assert (
                handler.written == "=> Ok"
            ), "both the original and the unpickled logger must reach the same handler"


def test_pickling_file_handler(tmp: TempDir) -> None:
    file = tmp.path / "test.log"
    logger.add(file, format="{level} - {function} - {message}", delay=True)
    with copied_logger_though_pickle(logger) as dupe_logger:
        dupe_logger.debug("A message")
        assert file.read_text() == "DEBUG - test_pickling_file_handler - A message\n", (
            "a file sink must survive pickling, re-opening the same path in the process "
            "that unpickles it"
        )


@oxitest.parametrize(
    size_in_bytes=RotationCase(rotation=1000),
    named_interval=RotationCase(rotation="daily"),
    timedelta=RotationCase(rotation=datetime.timedelta(minutes=60)),
    time_of_day=RotationCase(rotation=datetime.time(hour=12, minute=00, second=00)),
    human_size=RotationCase(rotation="200 MB"),
    clock_time=RotationCase(rotation="10:00"),
    human_interval=RotationCase(rotation="5 hours"),
    function=RotationCase(rotation=rotation_function),
)
def test_pickling_file_handler_rotation(tmp: TempDir, rotation: Any) -> None:
    file = tmp.path / "test.log"
    logger.add(file, format="{level} - {function} - {message}", delay=True, rotation=rotation)
    with copied_logger_though_pickle(logger) as dupe_logger:
        dupe_logger.debug("A message")
        assert file.read_text() == "DEBUG - test_pickling_file_handler_rotation - A message\n", (
            "every accepted spelling of the rotation option must survive pickling, since "
            "each is parsed into a different internal object"
        )


@oxitest.parametrize(
    count=RetentionCase(retention=1000),
    timedelta=RetentionCase(retention=datetime.timedelta(hours=13)),
    human_interval=RetentionCase(retention="10 days"),
    function=RetentionCase(retention=retention_function),
)
def test_pickling_file_handler_retention(tmp: TempDir, retention: Any) -> None:
    file = tmp.path / "test.log"
    logger.add(file, format="{level} - {function} - {message}", delay=True, retention=retention)
    with copied_logger_though_pickle(logger) as dupe_logger:
        dupe_logger.debug("A message")
        assert file.read_text() == "DEBUG - test_pickling_file_handler_retention - A message\n", (
            "every accepted spelling of the retention option must survive pickling, since "
            "each is parsed into a different internal object"
        )


@oxitest.parametrize(
    zip_archive=CompressionCase(compression="zip"),
    gzip=CompressionCase(compression="gz"),
    tarball=CompressionCase(compression="tar"),
    function=CompressionCase(compression=compression_function),
)
def test_pickling_file_handler_compression(tmp: TempDir, compression: Any) -> None:
    file = tmp.path / "test.log"
    logger.add(file, format="{level} - {function} - {message}", delay=True, compression=compression)
    with copied_logger_though_pickle(logger) as dupe_logger:
        dupe_logger.debug("A message")
        assert file.read_text() == "DEBUG - test_pickling_file_handler_compression - A message\n", (
            "every accepted spelling of the compression option must survive pickling, since "
            "each is parsed into a different internal object"
        )


def test_pickling_no_handler(writer: Fixture[Writer]) -> None:
    with copied_logger_though_pickle(logger) as dupe_logger:
        dupe_logger.add(writer, format="{level} - {function} - {message}")
        dupe_logger.debug("A message")
        assert (
            writer.read() == "DEBUG - test_pickling_no_handler - A message\n"
        ), "a logger with no handler must pickle to a usable logger, not to a broken shell"


def test_pickling_handler_not_serializable() -> None:
    logger.add(lambda m: None)
    with oxitest.raises((pickle.PicklingError, AttributeError), match=NOT_PICKLABLE_MESSAGE):
        pickle.dumps(logger)


def test_pickling_filter_function(cap: StdCapture) -> None:
    logger.add(print_, format="{message}", filter=filter_function)
    with copied_logger_though_pickle(logger) as dupe_logger:
        dupe_logger.info("Nope")
        dupe_logger.info("[PASS] Yes")
    captured = cap.readouterr()
    assert captured.out == "[PASS] Yes\n", (
        "a filter function must survive pickling and still be applied, otherwise the copy "
        "would log records the original filtered out"
    )
    assert captured.err == "", NO_STDERR_EXPECTED


@oxitest.parametrize(
    root=FilterNameCase(filter=""),
    package=FilterNameCase(filter="tests"),
)
def test_pickling_filter_name(cap: StdCapture, filter: str) -> None:
    logger.add(print_, format="{message}", filter=filter)
    with copied_logger_though_pickle(logger) as dupe_logger:
        dupe_logger.info("A message")
    captured = cap.readouterr()
    assert captured.out == "A message\n", (
        "a filter given as a module name must survive pickling and keep matching the same "
        "records"
    )
    assert captured.err == "", NO_STDERR_EXPECTED


@oxitest.parametrize(**COLORIZE_CASES)
def test_pickling_format_string(cap: StdCapture, colorize: bool) -> None:
    logger.add(print_, format="-> <red>{message}</red>", colorize=colorize)
    with copied_logger_though_pickle(logger) as dupe_logger:
        dupe_logger.info("The message")
    captured = cap.readouterr()
    assert captured.out == parse("-> <red>The message</red>\n", strip=not colorize), (
        "the format string and the colorize decision must both survive pickling, otherwise "
        "the copy renders differently from the original"
    )
    assert captured.err == "", NO_STDERR_EXPECTED


@oxitest.parametrize(**COLORIZE_CASES)
def test_pickling_format_function(cap: StdCapture, colorize: bool) -> None:
    logger.add(print_, format=format_function, colorize=colorize)
    with copied_logger_though_pickle(logger) as dupe_logger:
        dupe_logger.info("The message")
    captured = cap.readouterr()
    assert captured.out == parse("-> <red>The message</red>", strip=not colorize), (
        "a callable format must survive pickling and be re-evaluated in the copy, colorize "
        "decision included"
    )
    assert captured.err == "", NO_STDERR_EXPECTED


def test_pickling_filter_function_not_serializable() -> None:
    logger.add(print, filter=lambda r: True)
    with oxitest.raises((pickle.PicklingError, AttributeError), match=NOT_PICKLABLE_MESSAGE):
        pickle.dumps(logger)


def test_pickling_format_function_not_serializable() -> None:
    logger.add(print, format=lambda r: "{message}")
    with oxitest.raises((pickle.PicklingError, AttributeError), match=NOT_PICKLABLE_MESSAGE):
        pickle.dumps(logger)


def test_pickling_bound_logger(writer: Fixture[Writer]) -> None:
    bound_logger = logger.bind(foo="bar")
    with copied_logger_though_pickle(bound_logger) as dupe_logger:
        dupe_logger.add(writer, format="{extra[foo]}")
        dupe_logger.info("Test")
        assert writer.read() == "bar\n", (
            "bound context must survive pickling, otherwise a logger sent to a subprocess "
            "would silently lose the values it was bound with"
        )


def test_pickling_patched_logger(writer: Fixture[Writer]) -> None:
    patched_logger = logger.patch(patch_function)
    with copied_logger_though_pickle(patched_logger) as dupe_logger:
        dupe_logger.add(writer, format="{extra[foo]}")
        dupe_logger.info("Test")
        assert writer.read() == "bar\n", (
            "an attached patcher must survive pickling, otherwise a logger sent to a "
            "subprocess would silently stop enriching its records"
        )


def test_remove_after_pickling(cap: StdCapture) -> None:
    i = logger.add(print_, format="{message}")
    logger.info("A")
    with copied_logger_though_pickle(logger) as dupe_logger:
        dupe_logger.remove(i)
        dupe_logger.info("B")
    captured = cap.readouterr()
    assert (
        captured.out == "A\n"
    ), "handler ids must survive pickling, so the copy can remove a handler it inherited"
    assert captured.err == "", NO_STDERR_EXPECTED


def test_pickling_logging_method(cap: StdCapture) -> None:
    logger.add(print_, format="{level} - {function} - {message}")
    pickled = pickle.dumps(logger.critical)
    func = pickle.loads(pickled)
    func("A message")
    captured = cap.readouterr()
    assert captured.out == "CRITICAL - test_pickling_logging_method - A message\n", (
        "a bound logging method must be picklable on its own, so it can be handed directly "
        "to multiprocessing as a callback"
    )
    assert captured.err == "", NO_STDERR_EXPECTED


def test_pickling_log_method(cap: StdCapture) -> None:
    logger.add(print_, format="{level} - {function} - {message}")
    pickled = pickle.dumps(logger.log)
    func = pickle.loads(pickled)
    func(19, "A message")
    captured = cap.readouterr()
    assert (
        captured.out == "Level 19 - test_pickling_log_method - A message\n"
    ), "the generic log() method must be picklable on its own, like the level shortcuts"
    assert captured.err == "", NO_STDERR_EXPECTED


@oxitest.parametrize(
    add=MethodCase(method=logger.add),
    remove=MethodCase(method=logger.remove),
    catch=MethodCase(method=logger.catch),
    opt=MethodCase(method=logger.opt),
    bind=MethodCase(method=logger.bind),
    patch=MethodCase(method=logger.patch),
    level=MethodCase(method=logger.level),
    disable=MethodCase(method=logger.disable),
    enable=MethodCase(method=logger.enable),
    configure=MethodCase(method=logger.configure),
    parse=MethodCase(method=logger.parse),
    exception=MethodCase(method=logger.exception),
)
def test_pickling_no_error(method: Callable[..., Any]) -> None:
    pickled = pickle.dumps(method)
    unpickled = pickle.loads(pickled)
    assert unpickled, (
        "every public method must be picklable, so any of them can be passed across a "
        "process boundary without special handling"
    )
