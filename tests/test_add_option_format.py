from dataclasses import dataclass
from typing import Any, Callable, Union

import oxitest
from conftest import Writer
from oxitest import Fixture

from loguru import logger


@dataclass(frozen=True)
class FormatCase:
    message: str
    format: Union[str, Callable[[Any], str]]
    expected: str


@dataclass(frozen=True)
class InvalidFormatCase:
    format: Any


@dataclass(frozen=True)
class ColorizeCase:
    colorize: bool


@oxitest.parametrize(
    literal_prefix=FormatCase(message="a", format="Message: {message}", expected="Message: a\n"),
    without_message=FormatCase(message="b", format="Nope", expected="Nope\n"),
    repeated_field=FormatCase(
        message="c", format="{level} {message} {level}", expected="DEBUG c DEBUG\n"
    ),
    level_attributes=FormatCase(
        message="d",
        format="{message} {level} {level.no} {level.name}",
        expected="d DEBUG 10 DEBUG\n",
    ),
    callable_constant=FormatCase(message="e", format=lambda _: "{message}", expected="e"),
    callable_using_record=FormatCase(
        message="f", format=lambda r: "{message} " + r["level"].name, expected="f DEBUG"
    ),
)
def test_format(
    message: str,
    format: Union[str, Callable[[Any], str]],
    expected: str,
    writer: Fixture[Writer],
) -> None:
    logger.add(writer, format=format)
    logger.debug(message)
    assert writer.read() == expected, (
        "the format must be applied exactly as given, otherwise sinks emit something other "
        "than the layout the user configured"
    )


def test_progressive_format(writer: Fixture[Writer]) -> None:
    def formatter(record):
        fmt = "[{level.name}] {message}"
        if "noend" not in record["extra"]:
            fmt += "\n"
        return fmt

    logger.add(writer, format=formatter)
    logger.bind(noend=True).debug("Start: ")
    for _ in range(5):
        logger.opt(raw=True).debug(".")
    logger.opt(raw=True).debug("\n")
    logger.debug("End")
    assert writer.read() == ("[DEBUG] Start: .....\n" "[DEBUG] End\n"), (
        "a callable format must be re-evaluated per record, otherwise it could not decide "
        "per message whether to terminate the line"
    )


def test_function_format_without_exception(writer: Fixture[Writer]) -> None:
    logger.add(writer, format=lambda _: "{message}\n")
    try:
        1 / 0  # noqa: B018
    except ZeroDivisionError:
        logger.exception("Error!")
    assert writer.read() == "Error!\n", (
        "a callable format that omits {exception} must suppress the traceback, otherwise the "
        "format cannot control what the sink emits"
    )


def test_function_format_with_exception(writer: Fixture[Writer]) -> None:
    logger.add(writer, format=lambda _: "{message}\n{exception}")
    try:
        1 / 0  # noqa: B018
    except ZeroDivisionError:
        logger.exception("Error!")
    lines = writer.read().splitlines()
    assert (
        lines[0] == "Error!"
    ), "the message must come first, matching the order the callable format declares"
    assert lines[-1] == "ZeroDivisionError: division by zero", (
        "a callable format including {exception} must append the traceback, otherwise the "
        "error detail the user asked for is dropped"
    )


@oxitest.parametrize(
    integer=InvalidFormatCase(format=-1),
    float_value=InvalidFormatCase(format=3.4),
    object_instance=InvalidFormatCase(format=object()),
)
def test_invalid_format(writer: Fixture[Writer], format: Any) -> None:
    with oxitest.raises(TypeError):
        logger.add(writer, format=format)


@oxitest.parametrize(
    unclosed_tag=InvalidFormatCase(format="<red>"),
    unopened_tag=InvalidFormatCase(format="</red>"),
    crossed_tags=InvalidFormatCase(format="</level><level>"),
    dangling_closing_tag=InvalidFormatCase(format="</>"),
    unknown_tag=InvalidFormatCase(format="<foobar>"),
)
def test_invalid_markups(writer: Fixture[Writer], format: Any) -> None:
    with oxitest.raises(
        ValueError, match=r"^Invalid format, color markups could not be parsed correctly$"
    ):
        logger.add(writer, format=format)


@oxitest.parametrize(
    colorized=ColorizeCase(colorize=True),
    plain=ColorizeCase(colorize=False),
)
def test_markup_in_field(writer: Fixture[Writer], colorize: bool) -> None:
    class F:
        def __format__(self, spec):
            return spec

    logger.add(writer, format="{extra[f]:</>} {extra[f]: <blue> } {message}", colorize=colorize)
    logger.bind(f=F()).info("Test")

    assert writer.read() == "</>  <blue>  Test\n", (
        "markup produced by a field value must be emitted literally, otherwise logged data "
        "could inject color tags into the output"
    )


def test_invalid_format_builtin(writer: Fixture[Writer]) -> None:
    with oxitest.raises(ValueError, match=r".* most likely a mistake"):
        logger.add(writer, format=format)
