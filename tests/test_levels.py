import functools
from dataclasses import dataclass
from typing import Any

import oxitest
from conftest import Writer
from oxitest import Fixture

from loguru import logger
from tests._utils import parse

UNKNOWN_COLOR_MESSAGE = (
    r'Tag "<[^>]*>" does not correspond to any known color directive, '
    r"make sure you have not misspelled it \(or prepend '\\' to escape it\)"
)


@dataclass(frozen=True)
class ColorizeCase:
    colorize: bool
    expected: str


@dataclass(frozen=True)
class LevelCase:
    level: Any


@dataclass(frozen=True)
class ColorCase:
    color: str


INVALID_LEVEL_REFERENCES = {
    "integer": LevelCase(level=10),
    "object_instance": LevelCase(level=object()),
    "set_instance": LevelCase(level=set()),
}


def test_log_int_level(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{level.name} -> {level.no} -> {message}", colorize=False)
    logger.log(10, "test")

    assert writer.read() == "Level 10 -> 10 -> test\n", (
        "an unregistered severity number must render as 'Level N', so logging by number "
        "never leaves the name field blank"
    )


def test_log_str_level(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{level.name} -> {level.no} -> {message}", colorize=False)
    logger.log("DEBUG", "test")

    assert writer.read() == "DEBUG -> 10 -> test\n", (
        "a level named in log() must resolve to its registered severity number"
    )


def test_add_level(writer: Fixture[Writer]) -> None:
    name = "L3V3L"
    icon = "[o]"
    level = 10

    logger.level(name, level, color="<red>", icon=icon)
    fmt = "{level.icon} <level>{level.name}</level> -> {level.no} -> {message}"
    logger.add(writer, format=fmt, colorize=True)

    logger.log(name, "test")
    expected = parse("%s <red>%s</red> -> %d -> test" % (icon, name, level))
    assert writer.read() == expected + "\n", (
        "a newly registered level must carry its name, number, icon and color, and <level> "
        "must expand to that color"
    )


@oxitest.parametrize(
    plain=ColorizeCase(colorize=False, expected="foo | 10 | a"),
    colorized=ColorizeCase(colorize=True, expected="<red>foo | 10 | a</red>"),
)
def test_add_level_after_add(
    writer: Fixture[Writer], colorize: bool, expected: str
) -> None:
    fmt = "<level>{level.name} | {level.no} | {message}</level>"
    logger.add(writer, level="DEBUG", format=fmt, colorize=colorize)
    logger.level("foo", 10, color="<red>")
    logger.log("foo", "a")
    expected_output = parse(expected) if colorize else expected
    assert writer.read() == expected_output + "\n", (
        "<level> is resolved per record rather than when the handler is added, so a level "
        "registered afterwards must still colorize"
    )


def test_add_level_then_log_with_int_value(writer: Fixture[Writer]) -> None:
    logger.level("foo", 16)
    logger.add(writer, level="foo", format="{level.name} {level.no} {message}", colorize=False)

    logger.log(16, "test")

    assert writer.read() == "Level 16 16 test\n", (
        "logging by number must not adopt the name of a level that happens to share it, "
        "since the caller did not ask for that level"
    )


def test_add_malicious_level(writer: Fixture[Writer]) -> None:
    name = "Level 15"

    logger.level(name, 45, color="<red>")
    fmt = "{level.name} & {level.no} & <level>{message}</level>"
    logger.add(writer, format=fmt, colorize=True)

    logger.log(15, " A ")
    logger.log(name, " B ")

    assert writer.read() == parse(
        "Level 15 & 15 &  A \x1b[0m\nLevel 15 & 45 & <red> B </red>\n"
    ), (
        "a level whose name looks like the generated 'Level N' placeholder must not be "
        "matched by number, so the two records keep their own severities and colors"
    )


def test_add_existing_level(writer: Fixture[Writer]) -> None:
    logger.level("DEBUG", color="<red>")
    fmt = "{level.icon} + <level>{level.name}</level> + {level.no} = {message}"
    logger.add(writer, format=fmt, colorize=True)

    logger.debug("a")
    logger.log("DEBUG", "b")
    logger.log(10, "c")
    logger.log(20, "d")

    assert writer.read() == parse(
        "🐞 + <red>DEBUG</red> + 10 = a\n"
        "🐞 + <red>DEBUG</red> + 10 = b\n"
        "  + Level 10\x1b[0m + 10 = c\n"
        "  + Level 20\x1b[0m + 20 = d\n"
    ), (
        "re-styling an existing level must affect records logged by name but not those "
        "logged by number, which stay anonymous and uncolored"
    )


def test_blank_color(writer: Fixture[Writer]) -> None:
    logger.level("INFO", color=" ")
    logger.add(writer, level="DEBUG", format="<level>{message}</level>", colorize=True)
    logger.info("Test")
    assert writer.read() == parse("Test" "\x1b[0m" "\n"), (
        "a blank color must still emit the reset sequence, so <level> behaves consistently "
        "whether or not a color was configured"
    )


def test_edit_level(writer: Fixture[Writer]) -> None:
    logger.level("info", no=11, color="<bold>", icon="[?]")
    fmt = "<level>->{level.no}, {level.name}, {level.icon}, {message}<-</level>"
    logger.add(writer, format=fmt, colorize=True)

    logger.log("info", "a")

    logger.level("info", icon="[!]")
    logger.log("info", "b")

    logger.level("info", color="<red>")
    logger.log("info", "c")

    assert writer.read() == parse(
        "<bold>->11, info, [?], a<-</bold>\n"
        "<bold>->11, info, [!], b<-</bold>\n"
        "<red>->11, info, [!], c<-</red>\n"
    ), (
        "editing one attribute of a level must leave the others untouched and take effect "
        "from the next record onwards"
    )


def test_edit_existing_level(writer: Fixture[Writer]) -> None:
    logger.level("DEBUG", icon="!")
    fmt = "{level.no}, <level>{level.name}</level>, {level.icon}, {message}"
    logger.add(writer, format=fmt, colorize=False)
    logger.debug("a")
    assert writer.read() == "10, DEBUG, !, a\n", (
        "built-in levels must be editable, so an application can replace the default icons"
    )


def test_get_level() -> None:
    level = ("lvl", 11, "<red>", "[!]")
    logger.level(*level)
    assert logger.level("lvl") == level, (
        "level() must return exactly what was registered, so the call doubles as a way to "
        "read the current configuration back"
    )


def test_get_existing_level() -> None:
    assert logger.level("DEBUG") == ("DEBUG", 10, "<blue><bold>", "🐞"), (
        "the documented defaults for built-in levels are part of the public API and must not "
        "drift silently"
    )


def test_add_custom_level(writer: Fixture[Writer]) -> None:
    logger.level("foo", 17, color="<yellow>")
    logger.add(
        writer,
        level="foo",
        format="<level>{level.name} + {level.no} + {message}</level>",
        colorize=False,
    )

    logger.debug("nope")
    logger.info("yes")

    assert writer.read() == "INFO + 20 + yes\n", (
        "a handler level given by custom name must be resolved to its number and used as an "
        "ordinary threshold: DEBUG (10) is below 17 and INFO (20) is above"
    )


def test_updating_min_level(writer: Fixture[Writer]) -> None:
    logger.debug("Early exit -> no {error}", nope=None)

    a = logger.add(writer, level="DEBUG")

    with oxitest.raises(ValueError, match=r"^The logging message could not be formatted"):
        logger.debug("An {error} will occur!", nope=None)

    logger.trace("Early exit -> no {error}", nope=None)

    logger.add(writer, level="INFO")
    logger.remove(a)

    logger.debug("Early exit -> no {error}", nope=None)


def test_assign_custom_level_method(writer: Fixture[Writer]) -> None:
    logger.level("foobar", no=33, icon="🤖", color="<blue>")

    logger.__class__.foobar = functools.partialmethod(logger.__class__.log, "foobar")
    logger.foobar("Message not logged")
    logger.add(
        writer,
        format="<lvl>{level.name} {level.no} {level.icon} {message} {extra}</lvl>",
        colorize=True,
    )
    logger.foobar("Logged message")
    logger.bind(something="otherthing").foobar("Another message")
    assert writer.read() == parse(
        "<blue>foobar 33 🤖 Logged message {}</blue>\n"
        "<blue>foobar 33 🤖 Another message {'something': 'otherthing'}</blue>\n"
    ), (
        "a custom level method built on log() must behave exactly like the built-in ones, "
        "including through bind()"
    )


def test_updating_level_no_not_allowed_default() -> None:
    with oxitest.raises(
        ValueError, match=r"^Level 'DEBUG' already exists, you can't update its severity no$"
    ):
        logger.level("DEBUG", 100)


def test_updating_level_no_not_allowed_custom() -> None:
    logger.level("foobar", no=33)
    with oxitest.raises(
        ValueError, match=r"^Level 'foobar' already exists, you can't update its severity no$"
    ):
        logger.level("foobar", 100)


@oxitest.parametrize(
    float_value=LevelCase(level=3.4),
    object_instance=LevelCase(level=object()),
    set_instance=LevelCase(level=set()),
)
def test_log_invalid_level_type(writer: Fixture[Writer], level: Any) -> None:
    logger.add(writer)
    with oxitest.raises(
        TypeError, match=r"^Invalid level, it should be an integer or a string, not: '[^']+'$"
    ):
        logger.log(level, "test")


@oxitest.parametrize(
    minus_one=LevelCase(level=-1),
    large_negative=LevelCase(level=-999),
)
def test_log_invalid_level_value(writer: Fixture[Writer], level: Any) -> None:
    logger.add(writer)
    with oxitest.raises(
        ValueError, match=r"^Invalid level value, it should be a positive integer, not: -?[0-9]+"
    ):
        logger.log(level, "test")


@oxitest.parametrize(
    unknown_name=LevelCase(level="foo"),
    wrong_case=LevelCase(level="debug"),
)
def test_log_unknown_level(writer: Fixture[Writer], level: Any) -> None:
    logger.add(writer)
    with oxitest.raises(ValueError, match=r"^Level '[^']+' does not exist$"):
        logger.log(level, "test")


@oxitest.parametrize(**INVALID_LEVEL_REFERENCES)
def test_add_invalid_level_name(level: Any) -> None:
    with oxitest.raises(TypeError):
        logger.level(level, 11)


@oxitest.parametrize(
    string=LevelCase(level="1"),
    object_instance=LevelCase(level=object()),
    float_value=LevelCase(level=3.4),
    set_instance=LevelCase(level=set()),
)
def test_add_invalid_level_type(level: Any) -> None:
    with oxitest.raises(TypeError):
        logger.level("test", level)


@oxitest.parametrize(
    minus_one=LevelCase(level=-1),
    large_negative=LevelCase(level=-999),
)
def test_add_invalid_level_value(level: Any) -> None:
    with oxitest.raises(
        ValueError, match=r"^Invalid level no, it should be a positive integer, not: -?[0-9]+$"
    ):
        logger.level("test", level)


@oxitest.parametrize(**INVALID_LEVEL_REFERENCES)
def test_get_invalid_level(level: Any) -> None:
    with oxitest.raises(TypeError):
        logger.level(level)


def test_get_unknown_level() -> None:
    with oxitest.raises(ValueError, match=r"^Level '[^']+' does not exist$"):
        logger.level("foo")


@oxitest.parametrize(**INVALID_LEVEL_REFERENCES)
def test_edit_invalid_level(level: Any) -> None:
    with oxitest.raises(TypeError):
        logger.level(level, icon="?")


@oxitest.parametrize(
    unknown_name=LevelCase(level="foo"),
    wrong_case=LevelCase(level="debug"),
)
def test_edit_unknown_level(level: Any) -> None:
    with oxitest.raises(
        ValueError,
        match=r"^Level '[^']+' does not exist, you have to create it by specifying a level no$",
    ):
        logger.level(level, icon="?")


@oxitest.parametrize(
    empty_tag=ColorCase(color="<>"),
    unknown_tag=ColorCase(color="<foo>"),
)
def test_add_level_unknown_color(color: str) -> None:
    with oxitest.raises(ValueError, match=UNKNOWN_COLOR_MESSAGE):
        logger.level("foobar", no=20, icon="", color=color)


@oxitest.parametrize(
    autoclose=ColorCase(color="</>"),
    closing_named_tag=ColorCase(color="</red>"),
    closing_unknown_tag=ColorCase(color="</foo>"),
)
def test_add_level_invalid_markup(color: str) -> None:
    with oxitest.raises(
        ValueError, match=r'^Closing tag "</[^>]*>" has no corresponding opening tag$'
    ):
        logger.level("foobar", no=20, icon="", color=color)


@oxitest.parametrize(
    short_alias=ColorCase(color="<lvl>"),
    padded=ColorCase(color=" <level> "),
)
def test_add_level_invalid_name(color: str) -> None:
    with oxitest.raises(
        ValueError,
        match=(
            r"^The '<level>' color tag is not allowed in this context, "
            r"it has not yet been associated to any color value\.$"
        ),
    ):
        logger.level("foobar", no=20, icon="", color=color)
