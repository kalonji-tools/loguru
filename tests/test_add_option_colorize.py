import os
from dataclasses import dataclass
from typing import Any, Callable, Type, Union

import oxitest
import conftest
from conftest import Writer
from oxitest import Fixture

from loguru import logger
from tests._utils import (
    StreamIsattyException,
    StreamIsattyFalse,
    StreamIsattyTrue,
    StubStream,
    parse,
)


@dataclass(frozen=True)
class FormatCase:
    format: Union[str, Callable[[Any], str]]
    message: str
    expected: str


@dataclass(frozen=True)
class StreamCase:
    stream_class: Type[StubStream]


STREAM_CASES = {
    "isatty_true": StreamCase(stream_class=StreamIsattyTrue),
    "isatty_false": StreamCase(stream_class=StreamIsattyFalse),
    "isatty_raising": StreamCase(stream_class=StreamIsattyException),
}


@oxitest.parametrize(
    markup_in_format=FormatCase(
        format="<red>{message}</red>", message="Foo", expected=parse("<red>Foo</red>\n")
    ),
    markup_in_callable_format=FormatCase(
        format=lambda _: "<red>{message}</red>", message="Bar", expected=parse("<red>Bar</red>")
    ),
    markup_in_message=FormatCase(
        format="{message}", message="<red>Baz</red>", expected="<red>Baz</red>\n"
    ),
    escaped_braces=FormatCase(
        format="{{<red>{message:}</red>}}", message="A", expected=parse("{<red>A</red>}\n")
    ),
)
def test_colorized_format(
    format: Union[str, Callable[[Any], str]],
    message: str,
    expected: str,
    writer: Fixture[Writer],
) -> None:
    logger.add(writer, format=format, colorize=True)
    logger.debug(message)
    assert writer.read() == expected, (
        "with colorize=True only markup coming from the format may become ANSI codes; markup "
        "inside the message is data and must stay literal"
    )


@oxitest.parametrize(
    markup_in_format=FormatCase(format="<red>{message}</red>", message="Foo", expected="Foo\n"),
    markup_in_callable_format=FormatCase(
        format=lambda _: "<red>{message}</red>", message="Bar", expected="Bar"
    ),
    markup_in_message=FormatCase(
        format="{message}", message="<red>Baz</red>", expected="<red>Baz</red>\n"
    ),
    escaped_braces=FormatCase(format="{{<red>{message:}</red>}}", message="A", expected="{A}\n"),
)
def test_decolorized_format(
    format: Union[str, Callable[[Any], str]],
    message: str,
    expected: str,
    writer: Fixture[Writer],
) -> None:
    logger.add(writer, format=format, colorize=False)
    logger.debug(message)
    assert writer.read() == expected, (
        "with colorize=False the markup must be stripped from the format and left untouched "
        "in the message, so that log files never contain escape sequences"
    )


@oxitest.parametrize(**STREAM_CASES)
def test_colorize_stream(stream_class: Type[StubStream]) -> None:
    stream = stream_class()
    logger.add(stream, format="<blue>{message}</blue>", colorize=True)
    logger.debug("Message")
    assert stream.getvalue() == parse("<blue>Message</blue>\n"), (
        "an explicit colorize=True must win over stream detection, otherwise the caller "
        "cannot force colors on a stream that does not look like a terminal"
    )


@oxitest.parametrize(**STREAM_CASES)
def test_decolorize_stream(stream_class: Type[StubStream]) -> None:
    stream = stream_class()
    logger.add(stream, format="<blue>{message}</blue>", colorize=False)
    logger.debug("Message")
    assert stream.getvalue() == "Message\n", (
        "an explicit colorize=False must win over stream detection, otherwise a real "
        "terminal would still receive escape sequences the caller opted out of"
    )


def test_automatic_detection_when_stream_is_a_tty() -> None:
    stream = StreamIsattyTrue()
    logger.add(stream, format="<blue>{message}</blue>", colorize=None)
    logger.debug("Message")
    assert stream.getvalue() == parse(
        "<blue>Message</blue>\n"
    ), "colorize=None must colorize a tty, since that is the whole point of auto-detection"


def test_automatic_detection_when_stream_is_not_a_tty() -> None:
    stream = StreamIsattyFalse()
    logger.add(stream, format="<blue>{message}</blue>", colorize=None)
    logger.debug("Message")
    assert stream.getvalue() == "Message\n", (
        "colorize=None must not colorize a non-tty, otherwise redirected output is polluted "
        "with escape sequences"
    )


def test_automatic_detection_when_stream_has_no_isatty() -> None:
    stream = StreamIsattyException()
    logger.add(stream, format="<blue>{message}</blue>", colorize=None)
    logger.debug("Message")
    assert stream.getvalue() == "Message\n", (
        "a stream whose isatty() raises must be treated as a non-tty, otherwise adding an "
        "unusual stream would propagate its error out of logger.add()"
    )


def test_override_no_color() -> None:
    stream = StreamIsattyTrue()
    with conftest.patch_context() as context:
        context.setitem(os.environ, "NO_COLOR", "1")
        logger.add(stream, format="<blue>{message}</blue>", colorize=True)
        logger.debug("Message", colorize=False)
        assert stream.getvalue() == parse("<blue>Message</blue>\n"), (
            "an explicit colorize=True must override NO_COLOR, otherwise the environment "
            "could silently disable colors the application deliberately requested"
        )


def test_override_force_color() -> None:
    stream = StreamIsattyFalse()
    with conftest.patch_context() as context:
        context.setitem(os.environ, "FORCE_COLOR", "1")
        logger.add(stream, format="<blue>{message}</blue>", colorize=False)
        logger.debug("Message", colorize=False)
        assert stream.getvalue() == "Message\n", (
            "an explicit colorize=False must override FORCE_COLOR, otherwise the environment "
            "could silently enable colors the application deliberately refused"
        )
