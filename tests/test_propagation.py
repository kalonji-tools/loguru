import logging
import sys
from dataclasses import dataclass
from logging import StreamHandler

import oxitest
from oxitest import StdCapture, helpers

from loguru import logger
from tests._naming import pin_module_name

# Propagated records carry the caller's dotted module name into the standard "logging"
# hierarchy, and these tests assert on both the name and the handler that receives it.
pin_module_name(globals(), "tests.test_propagation")


@dataclass(frozen=True)
class ExceptionCase:
    use_opt: bool


class PropagateHandler(logging.Handler):
    def emit(self, record):
        logging.getLogger(record.name).handle(record)


def test_formatting(cap: StdCapture) -> None:
    fmt = (
        "%(name)s - %(filename)s - %(funcName)s - %(levelname)s - "
        "%(levelno)s - %(lineno)d - %(module)s - %(message)s"
    )

    expected = (
        "tests.test_propagation - test_propagation.py - test_formatting - DEBUG - "
        "10 - 42 - test_propagation - This is my message\n"
    )

    with helpers.common.make_logging_logger(
        "tests.test_propagation", StreamHandler(sys.stderr), fmt
    ):
        logger.add(PropagateHandler(), format="{message}")
        logger.debug("This {verb} my {}", "message", verb="is")

    captured = cap.readouterr()
    assert captured.out == "", "propagation targets stderr only, so stdout must stay empty"
    assert captured.err == expected, (
        "every standard LogRecord attribute must be reconstructed from the loguru record, "
        "otherwise existing logging formats break when records arrive through propagation"
    )


def test_propagate(cap: StdCapture) -> None:
    with helpers.common.make_logging_logger(
        "tests", StreamHandler(sys.stderr)
    ) as logging_logger:
        logging_logger.debug("1")
        logger.debug("2")

        logger.add(PropagateHandler(), format="{message}")

        logger.debug("3")
        logger.trace("4")

    captured = cap.readouterr()
    assert captured.out == "", "propagation targets stderr only, so stdout must stay empty"
    assert captured.err == "1\n3\n", (
        "only records logged while the propagating handler is installed may reach the "
        "standard logger, and TRACE stays below its DEBUG threshold"
    )


def test_remove_propagation(cap: StdCapture) -> None:
    with helpers.common.make_logging_logger(
        "tests", StreamHandler(sys.stderr)
    ) as logging_logger:
        i = logger.add(PropagateHandler(), format="{message}")

        logger.debug("1")
        logging_logger.debug("2")

        logger.remove(i)

        logger.debug("3")
        logging_logger.debug("4")

    captured = cap.readouterr()
    assert captured.out == "", "propagation targets stderr only, so stdout must stay empty"
    assert captured.err == "1\n2\n4\n", (
        "removing the propagating handler must stop loguru records from reaching the "
        "standard logger while leaving that logger otherwise working"
    )


def test_propagate_too_high(cap: StdCapture) -> None:
    with helpers.common.make_logging_logger(
        "tests.test_propagation.deep", StreamHandler(sys.stderr)
    ) as logging_logger:
        logger.add(PropagateHandler(), format="{message}")
        logger.debug("1")
        logging_logger.debug("2")

    captured = cap.readouterr()
    assert captured.out == "", "propagation targets stderr only, so stdout must stay empty"
    assert captured.err == "2\n", (
        "records propagate to the logger named after the calling module, so a handler "
        "installed on a deeper name must not receive them"
    )


@oxitest.parametrize(
    via_exception=ExceptionCase(use_opt=False),
    via_opt=ExceptionCase(use_opt=True),
)
def test_exception(cap: StdCapture, use_opt: bool) -> None:
    with helpers.common.make_logging_logger("tests", StreamHandler(sys.stderr)):
        logger.add(PropagateHandler(), format="{message}")

        try:
            1 / 0  # noqa: B018
        except Exception:
            if use_opt:
                logger.opt(exception=True).error("Oops...")
            else:
                logger.exception("Oops...")

    captured = cap.readouterr()
    lines = captured.err.strip().splitlines()

    error = "ZeroDivisionError: division by zero"

    assert captured.out == "", "propagation targets stderr only, so stdout must stay empty"
    assert lines[0] == "Oops...", "the message must precede the traceback it describes"
    assert lines[-1] == error, (
        "exception info must survive propagation, otherwise standard handlers lose the "
        "traceback that makes the record actionable"
    )
    assert captured.err.count(error) == 1, (
        "the traceback must be attached exactly once; a second copy means both loguru and "
        "the standard handler are formatting it"
    )
