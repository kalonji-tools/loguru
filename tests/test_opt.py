import sys
from dataclasses import dataclass
from unittest.mock import MagicMock

import oxitest
from conftest import Writer
from oxitest import Fixture, StdCapture

from loguru import logger
from tests._utils import parse


@dataclass(frozen=True)
class ColorizeCase:
    colorize: bool


@dataclass(frozen=True)
class ColorsCase:
    colors: bool


@dataclass
class InvalidMarkupCase:
    message: str
    colorize: bool


@dataclass
class InvalidIndexingCase:
    message: str
    colorize: bool


@dataclass
class CombinationCase:
    dynamic_format: bool
    colorize: bool
    colors: bool
    raw: bool
    use_log: bool
    use_arg: bool


COLORIZE_CASES = {
    "colorized": ColorizeCase(colorize=True),
    "plain": ColorizeCase(colorize=False),
}

COLORS_CASES = {
    "with_colors": ColorsCase(colors=True),
    "without_colors": ColorsCase(colors=False),
}


def _flag_layer(case_type: type, field: str) -> dict:
    """Two partial cases toggling a single boolean field of *case_type*."""
    return {
        "%s_on" % field: oxitest.partial(case_type, **{field: True}),
        "%s_off" % field: oxitest.partial(case_type, **{field: False}),
    }


def test_record(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message}")

    logger.opt(record=True).debug("1")
    logger.opt(record=True).debug("2 {record[level]}")
    logger.opt(record=True).log(11, "3 {0} {a} {record[level].no}", 4, a=5)

    assert writer.read() == "1\n2 DEBUG\n3 4 5 11\n", (
        "opt(record=True) must expose the record to the message format, alongside the "
        "ordinary positional and keyword arguments"
    )


def test_record_in_kwargs_too(writer: Fixture[Writer]) -> None:
    logger.add(writer, catch=False)

    with oxitest.raises(
        TypeError,
        match=(
            "^The message can't be formatted: 'record' shall not be used as a keyword argument "
            r"while logger has been configured with '\.opt\(record=True\)'$"
        ),
    ):
        logger.opt(record=True).info("Foo {record}", record=123)


def test_record_not_in_extra() -> None:
    extra = None

    def sink(message):
        nonlocal extra
        extra = message.record["extra"]

    logger.add(sink, catch=False)

    logger.opt(record=True).info("Test")

    assert extra == {}, (
        "opt(record=True) only changes what the message can reference; it must not inject "
        "anything into extra"
    )


def test_kwargs_in_extra_of_record() -> None:
    message = None

    def sink(message_):
        nonlocal message
        message = message_

    logger.add(sink, format="{message}", catch=False)

    logger.opt(record=True).info("Test {record[extra][foo]}", foo=123)

    assert message == "Test 123\n", (
        "kwargs must be visible through the record while the message is being formatted, "
        "which requires extra to be populated first"
    )
    assert message.record["extra"] == {"foo": 123}, "the kwarg must still land in extra"


def test_exception_boolean(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{level.name}: {message}")

    try:
        1 / 0  # noqa: B018
    except Exception:
        logger.opt(exception=True).debug("Error {0} {record}", 1, record="test")

    lines = writer.read().strip().splitlines()

    assert lines[0] == "DEBUG: Error 1 test", (
        "opt(exception=True) must not disturb message formatting, 'record' as a plain kwarg "
        "included"
    )
    assert lines[-1] == "ZeroDivisionError: division by zero", (
        "opt(exception=True) must attach the exception currently being handled"
    )


def test_exception_exc_info(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message}")

    try:
        1 / 0  # noqa: B018
    except Exception:
        exc_info = sys.exc_info()

    logger.opt(exception=exc_info).debug("test")

    lines = writer.read().strip().splitlines()

    assert lines[0] == "test", "the message must come first"
    assert lines[-1] == "ZeroDivisionError: division by zero", (
        "an explicit exc_info tuple must be accepted, so an exception caught earlier can "
        "still be reported"
    )


def test_exception_class(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message}")

    try:
        1 / 0  # noqa: B018
    except Exception:
        _, exc_class, _ = sys.exc_info()

    logger.opt(exception=exc_class).debug("test")

    lines = writer.read().strip().splitlines()

    assert lines[0] == "test", "the message must come first"
    assert lines[-1] == "ZeroDivisionError: division by zero", (
        "a bare exception value must be accepted too, rendering without a traceback"
    )


def test_exception_log_function(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{level.no} {message}")

    try:
        1 / 0  # noqa: B018
    except Exception:
        logger.opt(exception=True).log(50, "Error")

    lines = writer.read().strip().splitlines()

    assert lines[0] == "50 Error", "the message must come first"
    assert lines[-1] == "ZeroDivisionError: division by zero", (
        "opt() must apply to log() exactly as it does to the level shortcuts"
    )


def test_lazy(writer: Fixture[Writer]) -> None:
    counter = 0

    def laziness():
        nonlocal counter
        counter += 1
        return counter

    logger.add(writer, level=10, format="{level.no} => {message}")

    logger.opt(lazy=True).log(10, "1: {lazy}", lazy=laziness)
    logger.opt(lazy=True).log(5, "2: {0}", laziness)

    logger.remove()

    logger.opt(lazy=True).log(20, "3: {}", laziness)

    i = logger.add(writer, level=15, format="{level.no} => {message}")
    logger.add(writer, level=20, format="{level.no} => {message}")

    logger.log(17, "4: {}", counter)
    logger.opt(lazy=True).log(14, "5: {lazy}", lazy=lambda: counter)

    logger.remove(i)

    logger.opt(lazy=True).log(16, "6: {0}", lambda: counter)

    logger.opt(lazy=True).info("7: {}", laziness)
    logger.debug("7: {}", counter)

    assert writer.read() == "10 => 1: 1\n17 => 4: 1\n20 => 7: 2\n", (
        "lazy arguments must only be evaluated when at least one sink will accept the "
        "record — the counter reaching 2 proves the calls below the threshold were skipped"
    )


def test_lazy_function_executed_only_once(writer: Fixture[Writer]) -> None:
    counter = 0

    def laziness():
        nonlocal counter
        counter += 1
        return counter

    logger.add(writer, level=10, format="{level.name} => {message}")

    logger.opt(lazy=True).info("1: {lazy} {lazy}", lazy=laziness)
    logger.opt(lazy=True).info("2: {0} {0}", laziness)

    assert writer.read() == "INFO => 1: 1 1\nINFO => 2: 2 2\n", (
        "a lazy argument referenced twice must be evaluated once, otherwise a side-effecting "
        "callable would run more times than the message suggests"
    )


def test_logging_within_lazy_function(writer: Fixture[Writer]) -> None:
    logger.add(writer, level=20, format="{message}")

    def laziness():
        logger.trace("Nope")
        logger.warning("Yes Warn")

    logger.opt(lazy=True).trace("No", laziness)

    assert writer.read() == "", (
        "a lazy callable must not run at all when the record is filtered out, so its own "
        "logging calls do not happen either"
    )

    logger.opt(lazy=True).info("Yes", laziness)

    assert writer.read() == "Yes Warn\nYes\n", (
        "a lazy callable runs before the message is emitted, so records it logs itself "
        "appear first"
    )


def test_depth(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{function} : {message}")

    def a():
        logger.opt(depth=1).debug("Test 1")
        logger.opt(depth=0).debug("Test 2")
        logger.opt(depth=1).log(10, "Test 3")

    a()

    logger.remove()

    assert writer.read() == "test_depth : Test 1\na : Test 2\ntest_depth : Test 3\n", (
        "opt(depth=...) must attribute the record to a caller further up the stack, which is "
        "what lets logging wrappers report their own caller"
    )


def test_depth_with_unreachable_frame(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{name} : {function} : {file} : {line} : {message}")
    logger.opt(depth=1000).debug("Test")
    logger.remove()
    assert writer.read() == "None : <unknown> : <unknown> : 0 : Test\n", (
        "a depth beyond the top of the stack must produce placeholder values rather than "
        "raise, so an over-deep wrapper cannot break logging"
    )


def test_capture(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message} {extra}")
    logger.opt(capture=False).info("No {}", 123, no=False)
    logger.opt(capture=False).info("Formatted: {fmt}", fmt=456)
    logger.opt(capture=False).info("Formatted bis: {} {fmt}", 123, fmt=456)
    assert writer.read() == "No 123 {}\nFormatted: 456 {}\nFormatted bis: 123 456 {}\n", (
        "opt(capture=False) must keep kwargs out of extra while still using them to format "
        "the message"
    )


def test_colors(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="<red>a</red> {message}", colorize=True)
    logger.opt(colors=True).debug("<blue>b</blue>")
    logger.opt(colors=True).log(20, "<y>c</y>")

    assert writer.read() == parse(
        "<red>a</red> <blue>b</blue>\n" "<red>a</red> <y>c</y>\n", strip=False
    ), "opt(colors=True) must make markup in the message meaningful, like markup in the format"


def test_colors_not_colorize(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="<red>a</red> {message}", colorize=False)
    logger.opt(colors=True).debug("<blue>b</blue>")
    assert writer.read() == parse("<red>a</red> <blue>b</blue>\n", strip=True), (
        "with colorize=False the markup must be stripped rather than left in the output"
    )


def test_colors_doesnt_color_unrelated(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message} {extra[trap]}", colorize=True)
    logger.bind(trap="<red>B</red>").opt(colors=True).debug("<red>A</red>")
    assert writer.read() == parse("<red>A</red>", strip=False) + " <red>B</red>\n", (
        "only the message is scanned for markup; a bound value is data and must be emitted "
        "literally, otherwise logged data could inject colors"
    )


def test_colors_doesnt_strip_unrelated(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message} {extra[trap]}", colorize=False)
    logger.bind(trap="<red>B</red>").opt(colors=True).debug("<red>A</red>")
    assert writer.read() == parse("<red>A</red>", strip=True) + " <red>B</red>\n", (
        "stripping must apply to the message only; a bound value must survive unchanged"
    )


def test_colors_doesnt_raise_unrelated_colorize(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message} {extra[trap]}", colorize=True, catch=False)
    logger.bind(trap="</red>").opt(colors=True).debug("A")
    assert writer.read() == "A </red>\n", (
        "invalid markup in a bound value must not be parsed at all, otherwise arbitrary "
        "logged data could raise a formatting error"
    )


def test_colors_doesnt_raise_unrelated_not_colorize(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message} {extra[trap]}", colorize=False, catch=False)
    logger.bind(trap="</red>").opt(colors=True).debug("A")
    assert writer.read() == "A </red>\n", (
        "invalid markup in a bound value must not be parsed at all, otherwise arbitrary "
        "logged data could raise a formatting error"
    )


def test_colors_doesnt_raise_unrelated_colorize_dynamic(writer: Fixture[Writer]) -> None:
    logger.add(writer, format=lambda x: "{message} {extra[trap]}", colorize=True, catch=False)
    logger.bind(trap="</red>").opt(colors=True).debug("A")
    assert writer.read() == "A </red>", (
        "the same protection must hold with a callable format, which is resolved per record"
    )


def test_colors_doesnt_raise_unrelated_not_colorize_dynamic(writer: Fixture[Writer]) -> None:
    logger.add(writer, format=lambda x: "{message} {extra[trap]}", colorize=False, catch=False)
    logger.bind(trap="</red>").opt(colors=True).debug("A")
    assert writer.read() == "A </red>", (
        "the same protection must hold with a callable format, which is resolved per record"
    )


@oxitest.parametrize(**COLORIZE_CASES)
def test_colors_within_record(writer: Fixture[Writer], colorize: bool) -> None:
    logger.add(writer, format="{message}", colorize=colorize)
    logger_ = logger.bind(start="<red>", end="</red>")
    logger_.opt(colors=True, record=True).debug("{record[extra][start]}B{record[extra][end]}")
    assert writer.read() == "<red>B</red>\n", (
        "markup is resolved before record fields are substituted, so tags arriving through "
        "the record stay literal and cannot colorize anything"
    )


@oxitest.parametrize(**COLORIZE_CASES)
def test_colors_nested(writer: Fixture[Writer], colorize: bool) -> None:
    logger.add(writer, format="(<red>[{message}]</red>)", colorize=colorize)
    logger.opt(colors=True).debug("A<green>B</green>C<blue>D</blue>E")
    assert writer.read() == parse(
        "(<red>[A<green>B</green>C<blue>D</blue>E]</red>)\n", strip=not colorize
    ), (
        "message markup must nest inside the format's markup, so leaving an inner tag "
        "restores the enclosing color"
    )


@oxitest.parametrize(**COLORIZE_CASES)
def test_colors_stripped_in_message_record(colorize: bool) -> None:
    message = None

    def sink(msg):
        nonlocal message
        message = msg.record["message"]

    logger.add(sink, colorize=colorize)
    logger.opt(colors=True).debug("<red>Test</red>")
    assert message == "Test", (
        "the record must carry the plain message, so structured sinks never see markup "
        "regardless of how the handler renders it"
    )


@oxitest.parametrize(**_flag_layer(InvalidMarkupCase, "colorize"))
@oxitest.parametrize(
    unclosed=oxitest.partial(InvalidMarkupCase, message="<red>"),
    unopened=oxitest.partial(InvalidMarkupCase, message="</red>"),
    crossed=oxitest.partial(InvalidMarkupCase, message="X </red> <red> Y"),
)
def test_invalid_markup_in_message(
    writer: Fixture[Writer], message: str, colorize: bool
) -> None:
    logger.add(writer, format="<red>{message}</red>", colorize=colorize, catch=False)
    with oxitest.raises(
        ValueError,
        match=r'(Closing|Opening) tag "[^"]*" has no corresponding (opening|closing) tag',
    ):
        logger.opt(colors=True).debug(message)


@oxitest.parametrize(**COLORIZE_CASES)
def test_colors_with_args(writer: Fixture[Writer], colorize: bool) -> None:
    logger.add(writer, format="=> {message} <=", colorize=colorize)
    logger.opt(colors=True).debug("the {0}test{end}", "<red>", end="</red>")
    assert writer.read() == "=> the <red>test</red> <=\n", (
        "markup is resolved before arguments are substituted, so tags arriving as arguments "
        "stay literal and cannot colorize anything"
    )


@oxitest.parametrize(**COLORIZE_CASES)
def test_colors_with_level(writer: Fixture[Writer], colorize: bool) -> None:
    logger.add(writer, format="{message}", colorize=colorize)
    logger.level("DEBUG", color="<green>")
    logger.opt(colors=True).debug("a <level>level</level> b")
    assert writer.read() == parse("a <green>level</green> b\n", strip=not colorize), (
        "<level> must resolve to the record's own level color in the message too, not only "
        "in the handler format"
    )


@oxitest.parametrize(**COLORIZE_CASES)
def test_colors_double_message(writer: Fixture[Writer], colorize: bool) -> None:
    logger.add(
        writer, format="<red><b>{message}...</b> - <c>...{message}</c></red>", colorize=colorize
    )
    logger.opt(colors=True).debug("<g>foo</g> bar <g>baz</g>")

    assert writer.read() == parse(
        "<red><b><g>foo</g> bar <g>baz</g>...</b> - <c>...<g>foo</g> bar <g>baz</g></c></red>\n",
        strip=not colorize,
    ), (
        "a format referencing {message} twice must colorize both occurrences correctly, each "
        "within its own enclosing tags"
    )


@oxitest.parametrize(**COLORIZE_CASES)
def test_colors_multiple_calls(writer: Fixture[Writer], colorize: bool) -> None:
    logger.add(writer, format="{message}", colorize=colorize)
    logger.opt(colors=True).debug("a <red>foo</red> b")
    logger.opt(colors=True).debug("a <red>foo</red> b")
    assert writer.read() == parse("a <red>foo</red> b\na <red>foo</red> b\n", strip=not colorize), (
        "colorizing must be stateless across calls, otherwise a cached parse would make the "
        "second record differ from the first"
    )


@oxitest.parametrize(**COLORIZE_CASES)
def test_colors_multiple_calls_level_color_changed(
    writer: Fixture[Writer], colorize: bool
) -> None:
    logger.add(writer, format="{message}", colorize=colorize)
    logger.level("INFO", color="<blue>")
    logger.opt(colors=True).info("a <level>foo</level> b")
    logger.level("INFO", color="<red>")
    logger.opt(colors=True).info("a <level>foo</level> b")
    assert writer.read() == parse(
        "a <blue>foo</blue> b\na <red>foo</red> b\n", strip=not colorize
    ), "<level> must be resolved per record, so re-styling a level takes effect immediately"


@oxitest.parametrize(**COLORIZE_CASES)
def test_colors_with_dynamic_formatter(writer: Fixture[Writer], colorize: bool) -> None:
    logger.add(writer, format=lambda r: "<red>{message}</red>", colorize=colorize)
    logger.opt(colors=True).debug("<b>a</b> <y>b</y>")
    assert writer.read() == parse("<red><b>a</b> <y>b</y></red>", strip=not colorize), (
        "markup returned by a callable format must be honoured like a static one"
    )


@oxitest.parametrize(**COLORIZE_CASES)
def test_colors_with_format_specs(writer: Fixture[Writer], colorize: bool) -> None:
    fmt = "<g>{level.no:03d} {message:} {message!s:} {{nope}} {extra[a][b]!r}</g>"
    logger.add(writer, colorize=colorize, format=fmt)
    logger.bind(a={"b": "c"}).opt(colors=True).debug("<g>{X}</g>")
    assert writer.read() == parse("<g>010 <g>{X}</g> {X} {nope} 'c'</g>\n", strip=not colorize), (
        "format specs, conversions and escaped braces must all keep working when the format "
        "also carries markup"
    )


@oxitest.parametrize(**COLORIZE_CASES)
def test_colors_with_message_specs(writer: Fixture[Writer], colorize: bool) -> None:
    logger.add(writer, colorize=colorize, format="<g>{message}</g>")
    logger.opt(colors=True).debug("{} <b>A</b> {{nope}} {key:03d} {let!r}", 1, key=10, let="c")
    logger.opt(colors=True).debug("<b>{0:0{1}d}</b>", 2, 4)
    assert writer.read() == parse(
        "<g>1 <b>A</b> {nope} 010 'c'</g>\n<g><b>0002</b></g>\n", strip=not colorize
    ), (
        "format specs, conversions and escaped braces must all keep working inside a "
        "colorized message, nested specs included"
    )


@oxitest.parametrize(**COLORIZE_CASES)
def test_colored_string_used_as_spec(writer: Fixture[Writer], colorize: bool) -> None:
    logger.add(writer, colorize=colorize, format="{level.no:{message}} <red>{message}</red>")
    logger.opt(colors=True).log(30, "03d")
    assert writer.read() == parse("030 <red>03d</red>\n", strip=not colorize), (
        "the colorized message must still behave as a plain string when used as a format "
        "spec, otherwise the escape sequences would leak into the spec"
    )


@oxitest.parametrize(**COLORIZE_CASES)
def test_colored_string_getitem(writer: Fixture[Writer], colorize: bool) -> None:
    logger.add(writer, colorize=colorize, format="<red>{message[0]}</red>")
    logger.opt(colors=True).info("ABC")
    assert writer.read() == parse("<red>A</red>\n", strip=not colorize), (
        "indexing the message must operate on the visible characters, not on a string that "
        "already contains escape sequences"
    )


@oxitest.parametrize(**COLORIZE_CASES)
def test_colors_without_formatting_args(writer: Fixture[Writer], colorize: bool) -> None:
    string = "{} This { should } not } raise {"
    logger.add(writer, colorize=colorize, format="{message}")
    logger.opt(colors=True).info(string)
    assert writer.read() == string + "\n", (
        "with no arguments the message must not be run through str.format at all, so stray "
        "braces cannot raise"
    )


@oxitest.parametrize(**COLORIZE_CASES)
def test_colors_with_recursion_depth_exceeded_in_format(
    writer: Fixture[Writer], colorize: bool
) -> None:
    with oxitest.raises(
        ValueError, match=r"^Invalid format, color markups could not be parsed correctly$"
    ):
        logger.add(writer, format="{message:{message:{message:}}}", colorize=colorize)


@oxitest.parametrize(**COLORIZE_CASES)
def test_colors_with_recursion_depth_exceeded_in_message(
    writer: Fixture[Writer], colorize: bool
) -> None:
    logger.add(writer, format="{message}", colorize=colorize)

    with oxitest.raises(ValueError, match="Max string recursion exceeded"):
        logger.opt(colors=True).info("{foo:{foo:{foo:}}}", foo=123)


@oxitest.parametrize(**COLORIZE_CASES)
def test_colors_with_auto_indexing(writer: Fixture[Writer], colorize: bool) -> None:
    logger.add(writer, format="{message}", colorize=colorize)
    logger.opt(colors=True).info("<red>{}</red> <green>{}</green>", "foo", "bar")
    assert writer.read() == parse("<red>foo</red> <green>bar</green>\n", strip=not colorize), (
        "automatic field numbering must keep counting across markup boundaries"
    )


@oxitest.parametrize(**COLORIZE_CASES)
def test_colors_with_manual_indexing(writer: Fixture[Writer], colorize: bool) -> None:
    logger.add(writer, format="{message}", colorize=colorize)
    logger.opt(colors=True).info("<red>{1}</red> <green>{0}</green>", "foo", "bar")
    assert writer.read() == parse("<red>bar</red> <green>foo</green>\n", strip=not colorize), (
        "manual field numbering must keep working across markup boundaries"
    )


@oxitest.parametrize(**_flag_layer(InvalidIndexingCase, "colorize"))
@oxitest.parametrize(
    auto_then_manual=oxitest.partial(InvalidIndexingCase, message="{} {0}"),
    manual_then_auto=oxitest.partial(InvalidIndexingCase, message="{1} {}"),
)
def test_colors_with_invalid_indexing(
    writer: Fixture[Writer], colorize: bool, message: str
) -> None:
    logger.add(writer, format="{message}", colorize=colorize)

    with oxitest.raises(
        ValueError,
        match="cannot switch from manual field specification to automatic field numbering",
    ):
        logger.opt(colors=True).debug(message, 1, 2, 3)


def test_raw(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="", colorize=True)
    logger.opt(raw=True).info("Raw {}", "message")
    logger.opt(raw=True).log(30, " + The end")
    assert writer.read() == "Raw message + The end", (
        "opt(raw=True) must bypass the handler format entirely, newline included, so the "
        "caller controls the exact bytes written"
    )


def test_raw_with_format_function(writer: Fixture[Writer]) -> None:
    logger.add(writer, format=lambda _: "{time} \n")
    logger.opt(raw=True).debug("Raw {message} bis", message="message")
    assert writer.read() == "Raw message bis", (
        "raw mode must bypass a callable format too, not only a static one"
    )


@oxitest.parametrize(**COLORIZE_CASES)
def test_raw_with_colors(writer: Fixture[Writer], colorize: bool) -> None:
    logger.add(writer, format="XYZ", colorize=colorize)
    logger.opt(raw=True, colors=True).info("Raw <red>colors</red> and <lvl>level</lvl>")
    assert writer.read() == parse(
        "Raw <red>colors</red> and <b>level</b>", strip=not colorize
    ), "raw and colors must compose: the format is skipped but the message is still colorized"


def test_args_with_colors_not_formatted_twice(cap: StdCapture) -> None:
    logger.add(sys.stdout, format="{message}", colorize=True)
    logger.add(sys.stderr, format="{message}", colorize=False)
    a = MagicMock(__format__=MagicMock(return_value="a"))
    b = MagicMock(__format__=MagicMock(return_value="b"))

    logger.opt(colors=True).info("{} <red>{foo}</red>", a, foo=b)
    captured = cap.readouterr()
    assert captured.out == parse("a <red>b</red>\n"), "the colorized sink must see the colors"
    assert captured.err == "a b\n", "the plain sink must see the message stripped"
    assert a.__format__.call_count == 1, (
        "arguments must be formatted once for the record, not once per handler, otherwise a "
        "side-effecting __format__ would run several times"
    )
    assert b.__format__.call_count == 1, (
        "arguments must be formatted once for the record, not once per handler, otherwise a "
        "side-effecting __format__ would run several times"
    )


@oxitest.parametrize(**COLORIZE_CASES)
def test_level_tag_wrapping_with_colors(writer: Fixture[Writer], colorize: bool) -> None:
    logger.add(writer, format="<level>FOO {message} BAR</level>", colorize=colorize)
    logger.opt(colors=True).info("> foo <red>{}</> bar <lvl>{}</> baz <green>{}</green> <", 1, 2, 3)
    logger.opt(colors=True).log(33, "<lvl> {} <red>{}</red> {} </lvl>", 1, 2, 3)

    assert writer.read() == parse(
        "<b>FOO > foo <red>1</red> bar <b>2</b> baz <green>3</green> < BAR</b>\n"
        "<level>FOO <level> 1 <red>2</red> 3 </level> BAR</level>\n",
        strip=not colorize,
    ), (
        "a message wrapped in the format's <level> tag must still resolve its own <level> "
        "tags, and a level with no color must leave them inert"
    )


@oxitest.parametrize(**_flag_layer(CombinationCase, "dynamic_format"))
@oxitest.parametrize(**_flag_layer(CombinationCase, "colorize"))
@oxitest.parametrize(**_flag_layer(CombinationCase, "colors"))
@oxitest.parametrize(**_flag_layer(CombinationCase, "raw"))
@oxitest.parametrize(**_flag_layer(CombinationCase, "use_log"))
@oxitest.parametrize(**_flag_layer(CombinationCase, "use_arg"))
def test_all_colors_combinations(
    writer: Fixture[Writer],
    dynamic_format: bool,
    colorize: bool,
    colors: bool,
    raw: bool,
    use_log: bool,
    use_arg: bool,
) -> None:
    format_ = "<level>{level.no:03}</level> <red>{message}</red>"
    message = "<green>The</green> <lvl>{}</lvl>"
    arg = "message"

    def formatter(_):
        return format_ + "\n"

    logger.add(writer, format=formatter if dynamic_format else format_, colorize=colorize)

    logger_ = logger.opt(colors=colors, raw=raw)

    if use_log:
        if use_arg:
            logger_.log(20, message, arg)
        else:
            logger_.log(20, message.format(arg))
    else:
        if use_arg:
            logger_.info(message, arg)
        else:
            logger_.info(message.format(arg))

    if use_log:
        if raw:
            if colors:
                expected = parse("<green>The</green> <level>message</level>", strip=not colorize)
            else:
                expected = "<green>The</green> <lvl>message</lvl>"
        else:
            if colors:
                expected = parse(
                    "<level>020</level> <red><green>The</green> <level>message</level></red>\n",
                    strip=not colorize,
                )
            else:
                expected = (
                    parse("<level>020</level> <red>%s</red>\n", strip=not colorize)
                    % "<green>The</green> <lvl>message</lvl>"
                )

    else:
        if raw:
            if colors:
                expected = parse("<green>The</green> <b>message</b>", strip=not colorize)
            else:
                expected = "<green>The</green> <lvl>message</lvl>"
        else:
            if colors:
                expected = parse(
                    "<b>020</b> <red><green>The</green> <b>message</b></red>\n", strip=not colorize
                )
            else:
                expected = (
                    parse("<b>020</b> <red>%s</red>\n", strip=not colorize)
                    % "<green>The</green> <lvl>message</lvl>"
                )

    assert writer.read() == expected, (
        "the six options interact, so every combination must render exactly as documented; a "
        "single wrong pairing means one option silently overrides another"
    )


def test_raw_with_record(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="Nope\n")
    logger.opt(raw=True, record=True).debug("Raw in '{record[function]}'\n")
    assert writer.read() == "Raw in 'test_raw_with_record'\n", (
        "raw and record must compose: the format is skipped but the record is still "
        "available to the message"
    )


def test_keep_extra(writer: Fixture[Writer]) -> None:
    logger.configure(extra=dict(test=123))
    logger.add(writer, format="{extra[test]}")
    logger.opt().debug("")
    logger.opt().log(50, "")

    assert writer.read() == "123\n123\n", (
        "opt() must return a logger that still carries the configured extra, otherwise using "
        "any option would discard the application's context"
    )


def test_before_bind(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message}")
    logger.opt(record=True).bind(key="value").info("{record[level]}")
    assert writer.read() == "INFO\n", (
        "bind() called after opt() must preserve the options, otherwise the two could not be "
        "chained in either order"
    )


def test_deprecated_ansi_argument(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message}", colorize=True)
    with oxitest.warns(DeprecationWarning, match=r"The 'ansi' parameter is deprecated"):
        logger.opt(ansi=True).info("Foo <red>bar</red> baz")
    assert writer.read() == parse("Foo <red>bar</red> baz\n"), (
        "the deprecated alias must still behave like colors=True, otherwise the warning "
        "would be a breaking change rather than a deprecation"
    )


@oxitest.parametrize(**COLORS_CASES)
def test_message_update_not_overridden_by_patch(
    writer: Fixture[Writer], colors: bool
) -> None:
    def patcher(record):
        record["message"] += " [Patched]"

    logger.add(writer, format="{level} {message}", colorize=True)
    logger.patch(patcher).opt(colors=colors).info("Message")

    assert writer.read() == "INFO Message [Patched]\n", (
        "a patcher rewriting the message must win over the colorized copy loguru keeps, "
        "otherwise its edit would be silently discarded"
    )


@oxitest.parametrize(**COLORS_CASES)
def test_message_update_not_overridden_by_format(
    writer: Fixture[Writer], colors: bool
) -> None:
    def formatter(record):
        record["message"] += " [Formatted]"
        return "{level} {message}\n"

    logger.add(writer, format=formatter, colorize=True)
    logger.opt(colors=colors).info("Message")

    assert writer.read() == "INFO Message [Formatted]\n", (
        "a callable format rewriting the message must win over the colorized copy loguru "
        "keeps, otherwise its edit would be silently discarded"
    )


@oxitest.parametrize(**COLORS_CASES)
def test_message_update_not_overridden_by_filter(
    writer: Fixture[Writer], colors: bool
) -> None:
    def filter(record):
        record["message"] += " [Filtered]"
        return True

    logger.add(writer, format="{level} {message}", filter=filter, colorize=True)
    logger.opt(colors=colors).info("Message")

    assert writer.read() == "INFO Message [Filtered]\n", (
        "a filter rewriting the message must win over the colorized copy loguru keeps, "
        "otherwise its edit would be silently discarded"
    )


@oxitest.parametrize(**COLORS_CASES)
def test_message_update_not_overridden_by_raw(writer: Fixture[Writer], colors: bool) -> None:
    logger.add(writer, colorize=True)
    logger.patch(lambda r: r.update(message="Updated!")).opt(raw=True, colors=colors).info("Raw!")
    assert writer.read() == "Updated!", (
        "in raw mode the record's message is what gets written, so a patcher's rewrite must "
        "be what appears"
    )


def test_overridden_message_ignore_colors(writer: Fixture[Writer]) -> None:
    def formatter(record):
        record["message"] += " <blue>[Ignored]</blue> </xyz>"
        return "{message}\n"

    logger.add(writer, format=formatter, colorize=True)
    logger.opt(colors=True).info("<red>Message</red>")

    assert writer.read() == "Message <blue>[Ignored]</blue> </xyz>\n", (
        "once the message has been rewritten it is treated as data, so markup added by the "
        "formatter must stay literal — even markup that would not parse"
    )
