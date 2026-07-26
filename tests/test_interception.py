import inspect
import logging

from conftest import Writer
from oxitest import Fixture, helpers

from loguru import logger
from tests._naming import pin_module_name

# Interception rebuilds the record from the standard LogRecord, and several cases below
# assert on the dotted module name that ends up in "{name}".
pin_module_name(globals(), "tests.test_interception")


class InterceptHandler(logging.Handler):
    def emit(self, record):
        # Get corresponding Loguru level if it exists.
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where originated the logged message.
        frame, depth = inspect.currentframe(), 0
        while frame:
            filename = frame.f_code.co_filename
            is_logging = filename == logging.__file__
            is_frozen = "importlib" in filename and "_bootstrap" in filename
            if depth > 0 and not (is_logging or is_frozen):
                break
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def test_formatting(writer: Fixture[Writer]) -> None:
    fmt = (
        "{name} - {file.name} - {function} - {level.name} - "
        "{level.no} - {line} - {module} - {message}"
    )

    with helpers.common.make_logging_logger("tests", InterceptHandler()) as logging_logger:
        logger.add(writer, format=fmt)
        # Read from the call site itself so reformatting this file cannot break the test.
        lineno = inspect.currentframe().f_lineno + 1
        logging_logger.debug("This is the %s", "message")

    expected = (
        "tests.test_interception - test_interception.py - test_formatting - DEBUG - "
        "10 - %d - test_interception - This is the message\n" % lineno
    )

    result = writer.read()
    assert result == expected, (
        "opt(depth=...) must attribute the record to the original caller rather than to the "
        "handler, otherwise every intercepted line points at the interception shim"
    )


def test_intercept(writer: Fixture[Writer]) -> None:
    with helpers.common.make_logging_logger(None, InterceptHandler()) as logging_logger:
        logging_logger.info("Nope")
        logger.add(writer, format="{message}")
        logging_logger.info("Test")

    result = writer.read()
    assert result == "Test\n", (
        "an intercepted record must reach whatever sinks exist at the time it is logged, so "
        "the message emitted before the sink existed must not appear"
    )


def test_add_before_intercept(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message}")

    with helpers.common.make_logging_logger(None, InterceptHandler()) as logging_logger:
        logging_logger.info("Test")

    result = writer.read()
    assert result == "Test\n", (
        "the order of add() and the handler installation must not matter, otherwise "
        "interception only works when set up in one particular sequence"
    )


def test_remove_interception(writer: Fixture[Writer]) -> None:
    h = InterceptHandler()

    with helpers.common.make_logging_logger("foobar", h) as logging_logger:
        logger.add(writer, format="{message}")
        logging_logger.debug("1")
        logging_logger.removeHandler(h)
        logging_logger.debug("2")

    result = writer.read()
    assert result == "1\n", (
        "removing the handler must stop interception immediately, otherwise applications "
        "cannot turn the bridge back off"
    )


def test_intercept_too_low(writer: Fixture[Writer]) -> None:
    with helpers.common.make_logging_logger("tests.test_interception", InterceptHandler()):
        logger.add(writer, format="{message}")
        logging.getLogger("tests").error("Nope 1")
        logging.getLogger("foobar").error("Nope 2")

    result = writer.read()
    assert result == "", (
        "a handler installed on a deeper logger must not receive records from its ancestors "
        "or from unrelated trees — that is standard logging propagation"
    )


def test_multiple_intercept(writer: Fixture[Writer]) -> None:
    with helpers.common.make_logging_logger("test_1", InterceptHandler()) as logging_logger_1:
        with helpers.common.make_logging_logger("test_2", InterceptHandler()) as logging_logger_2:
            logger.add(writer, format="{message}")
            logging_logger_1.info("1")
            logging_logger_2.info("2")

    result = writer.read()
    assert result == "1\n2\n", (
        "several intercept handlers must coexist, so an application can bridge more than "
        "one third-party logger tree at a time"
    )


def test_exception(writer: Fixture[Writer]) -> None:
    with helpers.common.make_logging_logger(
        "tests.test_interception", InterceptHandler()
    ) as logging_logger:
        logger.add(writer, format="{message}")

        try:
            1 / 0  # noqa: B018
        except Exception:
            logging_logger.exception("Oops...")

    lines = writer.read().strip().splitlines()
    assert lines[0] == "Oops...", "the message must precede the traceback it describes"
    assert lines[-1] == "ZeroDivisionError: division by zero", (
        "exc_info from the standard record must be carried over, otherwise intercepted "
        "errors lose their traceback"
    )
    assert sum(line.startswith("> ") for line in lines) == 1, (
        "exactly one frame may be marked as the culprit; more than one means the depth "
        "passed to opt() pointed at a frame inside the logging machinery"
    )


def test_level_is_no(writer: Fixture[Writer]) -> None:
    with helpers.common.make_logging_logger("tests", InterceptHandler()) as logging_logger:
        logger.add(writer, format="<lvl>{level.no} - {level.name} - {message}</lvl>", colorize=True)
        logging_logger.log(12, "Hop")

    result = writer.read()
    assert result == "12 - Level 12 - Hop\x1b[0m\n", (
        "a numeric level with no loguru counterpart must be rendered as 'Level N' with no "
        "color, otherwise unknown severities break formatting"
    )


def test_level_does_not_exist(writer: Fixture[Writer]) -> None:
    logging.addLevelName(152, "FANCY_LEVEL")

    with helpers.common.make_logging_logger("tests", InterceptHandler()) as logging_logger:
        logger.add(writer, format="<lvl>{level.no} - {level.name} - {message}</lvl>", colorize=True)
        logging_logger.log(152, "Nop")

    result = writer.read()
    assert result == "152 - Level 152 - Nop\x1b[0m\n", (
        "a level name known only to the standard library must not be adopted by loguru, "
        "since it has no registered color or icon here"
    )


def test_level_exist_builtin(writer: Fixture[Writer]) -> None:
    with helpers.common.make_logging_logger("tests", InterceptHandler()) as logging_logger:
        logger.add(writer, format="<lvl>{level.no} - {level.name} - {message}</lvl>", colorize=True)
        logging_logger.error("Error...")

    result = writer.read()
    assert result == "\x1b[31m\x1b[1m40 - ERROR - Error...\x1b[0m\n", (
        "a standard level that also exists in loguru must be mapped by name, so intercepted "
        "records get the same color as native ones"
    )


def test_level_exists_custom(writer: Fixture[Writer]) -> None:
    logging.addLevelName(99, "ANOTHER_FANCY_LEVEL")
    logger.level("ANOTHER_FANCY_LEVEL", no=99, color="<green>", icon="")

    with helpers.common.make_logging_logger("tests", InterceptHandler()) as logging_logger:
        logger.add(writer, format="<lvl>{level.no} - {level.name} - {message}</lvl>", colorize=True)
        logging_logger.log(99, "Yep!")

    result = writer.read()
    assert result == "\x1b[32m99 - ANOTHER_FANCY_LEVEL - Yep!\x1b[0m\n", (
        "a custom level registered in both libraries must be mapped by name, so the "
        "application's own colors apply to intercepted records too"
    )


def test_using_logging_function(writer: Fixture[Writer]) -> None:
    with helpers.common.make_logging_logger(None, InterceptHandler()):
        logger.add(writer, format="{function} {line} {module} {file.name} {message}")
        # Read from the call site itself so reformatting this file cannot break the test.
        lineno = inspect.currentframe().f_lineno + 1
        logging.warning("ABC")

    result = writer.read()
    expected = (
        "test_using_logging_function %d test_interception test_interception.py ABC\n" % lineno
    )
    assert result == expected, (
        "the module-level logging.warning() shortcut must be attributed to its caller too, "
        "not to the logging module that implements it"
    )
