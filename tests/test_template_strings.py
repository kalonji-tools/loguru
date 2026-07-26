import sys
from unittest.mock import MagicMock

import oxitest
from conftest import Writer
from oxitest import Fixture

from loguru import logger
from tests._utils import parse

if sys.version_info >= (3, 14):
    from string.templatelib import Interpolation, Template

NO_TEMPLATE_STRINGS = "Template Strings not supported"
BEFORE_314 = sys.version_info < (3, 14)


@oxitest.mark.skip(when=BEFORE_314, reason=NO_TEMPLATE_STRINGS)
def test_template_string(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message}", colorize=False)

    # We can't just use t"2**8 = {2**8}", because its a syntax error before python-3.14.
    logger.info(Template("2**8 = ", Interpolation(2**8)))

    result = writer.read()
    assert result == "2**8 = 256\n", (
        "a template string must be rendered by interleaving its literal parts and "
        "interpolations, otherwise t-strings cannot be used as log messages at all"
    )


@oxitest.mark.skip(when=BEFORE_314, reason=NO_TEMPLATE_STRINGS)
def test_template_string_is_lazy(writer: Fixture[Writer]) -> None:
    logger.add(writer, level="INFO", format="{message}", colorize=False)

    debug_tracker = MagicMock()
    debug_tracker.__str__.return_value = "xxx"

    info_tracker = MagicMock()
    info_tracker.__str__.return_value = "xxx"

    logger.debug(Template("debug = ", Interpolation(debug_tracker)))
    logger.info(Template("info = ", Interpolation(info_tracker)))

    result = writer.read()
    assert (
        len(result.strip().split("\n")) == 1
    ), "the message filtered out by level must not be emitted at all"
    assert result == "info = xxx\n", "the message above the level must still be rendered"
    assert not debug_tracker.__str__.called, (
        "interpolations must not be stringified for a record no sink will accept — that "
        "laziness is the main reason to log a t-string rather than an f-string"
    )
    assert (
        info_tracker.__str__.called
    ), "interpolations must be stringified once the record is actually emitted"


@oxitest.mark.skip(when=BEFORE_314, reason=NO_TEMPLATE_STRINGS)
def test_template_string_with_conversion_spec(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message}", colorize=False)

    logger.info(Template("2**8 = ", Interpolation("2**8", "2**8", "r")))

    result = writer.read()
    assert result == "2**8 = '2**8'\n", (
        "the !r conversion carried by the interpolation must be applied, otherwise the "
        "t-string renders differently here than it would with format()"
    )


@oxitest.mark.skip(when=BEFORE_314, reason=NO_TEMPLATE_STRINGS)
def test_template_string_with_format_spec(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message}", colorize=False)

    logger.info(Template("2**8 = ", Interpolation(2**8, "2**8", None, ".2f")))

    result = writer.read()
    assert result == "2**8 = 256.00\n", (
        "the format spec carried by the interpolation must be applied, otherwise the "
        "t-string renders differently here than it would with format()"
    )


@oxitest.mark.skip(when=BEFORE_314, reason=NO_TEMPLATE_STRINGS)
def test_template_string_with_two_consecutive_interpolations(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message}", colorize=False)

    logger.info(Template("2**8 = ", Interpolation(5 * 5), Interpolation(2 * 3)))

    result = writer.read()
    assert result == "2**8 = 256\n", (
        "adjacent interpolations must be concatenated with nothing in between, since the "
        "template carries no literal text to separate them"
    )


@oxitest.mark.skip(when=BEFORE_314, reason=NO_TEMPLATE_STRINGS)
def test_template_string_with_two_consecutive_strings(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message}", colorize=False)

    logger.info(Template("2**8", " = ", Interpolation(2**8)))

    result = writer.read()
    assert (
        result == "2**8 = 256\n"
    ), "adjacent literal parts must be concatenated verbatim, without an implicit separator"


@oxitest.mark.skip(when=BEFORE_314, reason=NO_TEMPLATE_STRINGS)
def test_template_string_without_string(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message}", colorize=False)

    logger.info(Template(Interpolation(2**8)))

    result = writer.read()
    assert (
        result == "256\n"
    ), "a template made only of an interpolation must render to just that value"


@oxitest.mark.skip(when=BEFORE_314, reason=NO_TEMPLATE_STRINGS)
def test_template_string_without_interpolation(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message}", colorize=False)

    logger.info(Template("256"))

    result = writer.read()
    assert (
        result == "256\n"
    ), "a template with no interpolation must behave like the plain string it contains"


@oxitest.mark.skip(when=BEFORE_314, reason=NO_TEMPLATE_STRINGS)
def test_template_string_nested(writer: Fixture[Writer]) -> None:
    inner = Template(Interpolation(2**8))
    template = Template("2**8 = ", Interpolation(inner))

    logger.add(writer, format="{message}", colorize=False)

    logger.info(template)

    result = writer.read()
    assert result == "2**8 = 256\n", (
        "a template interpolated into another must be rendered recursively, not shown as "
        "its repr"
    )


@oxitest.mark.skip(when=BEFORE_314, reason=NO_TEMPLATE_STRINGS)
def test_template_string_with_colors(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message}", colorize=True)

    logger.opt(colors=True).info(Template("<red>2**8 = ", Interpolation(2**8), "</red>"))

    result = writer.read()
    assert result == parse("<red>2**8 = 256</red>\n"), (
        "markup in the literal parts of a template must be honoured under opt(colors=True), "
        "so t-strings are as expressive as plain ones"
    )


@oxitest.mark.skip(when=BEFORE_314, reason=NO_TEMPLATE_STRINGS)
def test_template_string_with_colors_and_args(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message}", colorize=True)

    logger.opt(colors=True).info(
        Template("<red>{calc} = ", Interpolation(2**8), "</red>"),
        calc="2**8",
    )

    result = writer.read()
    assert result == parse("<red>2**8 = 256</red>\n"), (
        "braces in a template's literal parts must still be filled from the logging kwargs, "
        "so both substitution mechanisms can be combined"
    )


@oxitest.mark.skip(when=BEFORE_314, reason=NO_TEMPLATE_STRINGS)
def test_template_string_with_raw(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{time} {message}", colorize=True)

    logger.opt(raw=True).info(Template("2**8 = ", Interpolation(2**8)))

    result = writer.read()
    assert result == parse("2**8 = 256"), (
        "opt(raw=True) must bypass the handler format for a template exactly as it does for "
        "a string, emitting the rendered message alone"
    )


@oxitest.mark.skip(when=BEFORE_314, reason=NO_TEMPLATE_STRINGS)
def test_template_string_with_raw_and_args(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{time} {message}", colorize=True)

    logger.opt(raw=True).info(
        Template("{calc} = ", Interpolation(2**8)),
        calc="2**8",
    )

    result = writer.read()
    assert result == parse(
        "2**8 = 256"
    ), "raw mode must still apply the logging kwargs to the template's literal parts"


@oxitest.mark.skip(when=BEFORE_314, reason=NO_TEMPLATE_STRINGS)
def test_template_string_with_raw_and_colors(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{time} {message}", colorize=True)

    logger.opt(raw=True, colors=True).info(Template("<red>2**8 = ", Interpolation(2**8), "</red>"))

    result = writer.read()
    assert result == parse(
        "<red>2**8 = 256</red>"
    ), "raw and colors must compose for templates as they do for strings"


@oxitest.mark.skip(when=BEFORE_314, reason=NO_TEMPLATE_STRINGS)
def test_template_string_with_raw_and_colors_and_args(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{time} {message}", colorize=True)

    logger.opt(raw=True, colors=True).info(
        Template("<red>{calc} = ", Interpolation(2**8), "</red>"),
        calc="2**8",
    )

    result = writer.read()
    assert result == parse(
        "<red>2**8 = 256</red>"
    ), "raw, colors and kwargs must all compose for templates as they do for strings"


@oxitest.mark.skip(when=BEFORE_314, reason=NO_TEMPLATE_STRINGS)
def test_template_string_with_interpolated_colors(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message}", colorize=True)

    logger.opt(colors=True).info(
        Template(Interpolation("<red>"), "2**8 = 256", Interpolation("</red>"))
    )

    result = writer.read()
    assert result == parse("<red>2**8 = 256</red>\n"), (
        "markup is resolved after the template is rendered, so tags produced by an "
        "interpolation take effect just like tags written literally"
    )


@oxitest.mark.skip(when=BEFORE_314, reason=NO_TEMPLATE_STRINGS)
def test_template_string_in_catch_message(writer: Fixture[Writer]) -> None:
    logger.add(writer, format=lambda _: "{level}: {message}\n", colorize=False)

    with logger.catch(message=Template("2**8 = ", Interpolation(2**8))):
        raise ValueError("An error occurred")

    result = writer.read()
    assert result == "ERROR: 2**8 = 256\n", (
        "catch(message=...) must accept a template too, otherwise t-strings work everywhere "
        "except the one place errors are reported"
    )
