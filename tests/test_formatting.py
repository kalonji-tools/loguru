import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Union

import oxitest
from conftest import Writer
from oxitest import Fixture, StdCapture, TempDir, helpers

from loguru import logger
from tests._naming import pin_module_name

# "{name}" renders the caller's dotted module name, which one of the validators checks.
pin_module_name(globals(), "tests.test_formatting")


@dataclass
class FormatterCase:
    format: str
    validator: Callable[[str], Any]
    use_log_function: bool


@dataclass
class FileFormatterCase:
    format: str
    validator: Callable[[str], Any]
    part: str


@dataclass
class LogFormattingCase:
    message: str
    args: List[Any] = field(default_factory=list)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    expected: str = ""
    use_log_function: bool = False


@dataclass(frozen=True)
class ColorsCase:
    colors: bool


@dataclass
class InvalidKeyCase:
    format_: Union[str, Callable[[Any], str]]
    colorize: bool
    colors: bool


@dataclass(frozen=True)
class IncompleteFrameCase:
    simulate: str


COLORS_CASES = {
    "with_colors": ColorsCase(colors=True),
    "without_colors": ColorsCase(colors=False),
}

INCOMPLETE_FRAME_CASES = {
    "no_globals_name": IncompleteFrameCase(simulate="simulate_f_globals_name_absent"),
    "no_frame": IncompleteFrameCase(simulate="simulate_no_frame_available"),
}

INVALID_KEY_FORMATS = {
    "static_format": oxitest.partial(InvalidKeyCase, format_="{missing}"),
    "callable_format": oxitest.partial(InvalidKeyCase, format_=lambda _: "{missing}\n"),
}

INVALID_KEY_COLORIZE = {
    "colorized": oxitest.partial(InvalidKeyCase, colorize=True),
    "plain": oxitest.partial(InvalidKeyCase, colorize=False),
}

INVALID_KEY_COLORS = {
    "with_colors": oxitest.partial(InvalidKeyCase, colors=True),
    "without_colors": oxitest.partial(InvalidKeyCase, colors=False),
}


@oxitest.parametrize(
    direct_call=oxitest.partial(FormatterCase, use_log_function=False),
    log_function=oxitest.partial(FormatterCase, use_log_function=True),
)
@oxitest.parametrize(
    name=oxitest.partial(
        FormatterCase, format="{name}", validator=lambda r: r == "tests.test_formatting"
    ),
    time=oxitest.partial(
        FormatterCase,
        format="{time}",
        validator=lambda r: re.fullmatch(r"\d+-\d+-\d+T\d+:\d+:\d+[.,]\d+[+-]\d{4}", r),
    ),
    elapsed=oxitest.partial(
        FormatterCase,
        format="{elapsed}",
        validator=lambda r: re.fullmatch(r"\d:\d{2}:\d{2}\.\d{6}", r),
    ),
    elapsed_seconds=oxitest.partial(
        FormatterCase, format="{elapsed.seconds}", validator=lambda r: re.fullmatch(r"\d+", r)
    ),
    line=oxitest.partial(
        FormatterCase, format="{line}", validator=lambda r: re.fullmatch(r"\d+", r)
    ),
    level=oxitest.partial(FormatterCase, format="{level}", validator=lambda r: r == "DEBUG"),
    level_name=oxitest.partial(
        FormatterCase, format="{level.name}", validator=lambda r: r == "DEBUG"
    ),
    level_no=oxitest.partial(FormatterCase, format="{level.no}", validator=lambda r: r == "10"),
    level_icon=oxitest.partial(FormatterCase, format="{level.icon}", validator=lambda r: r == "🐞"),
    file=oxitest.partial(
        FormatterCase, format="{file}", validator=lambda r: r == "test_formatting.py"
    ),
    file_name=oxitest.partial(
        FormatterCase, format="{file.name}", validator=lambda r: r == "test_formatting.py"
    ),
    file_path=oxitest.partial(
        FormatterCase,
        format="{file.path}",
        validator=lambda r: os.path.normcase(r) == os.path.normcase(__file__),
    ),
    function=oxitest.partial(
        FormatterCase, format="{function}", validator=lambda r: r == "test_log_formatters"
    ),
    module=oxitest.partial(
        FormatterCase, format="{module}", validator=lambda r: r == "test_formatting"
    ),
    thread=oxitest.partial(
        FormatterCase, format="{thread}", validator=lambda r: re.fullmatch(r"\d+", r)
    ),
    thread_id=oxitest.partial(
        FormatterCase, format="{thread.id}", validator=lambda r: re.fullmatch(r"\d+", r)
    ),
    thread_name=oxitest.partial(
        FormatterCase,
        format="{thread.name}",
        validator=lambda r: isinstance(r, str) and r != "",
    ),
    process=oxitest.partial(
        FormatterCase, format="{process}", validator=lambda r: re.fullmatch(r"\d+", r)
    ),
    process_id=oxitest.partial(
        FormatterCase, format="{process.id}", validator=lambda r: re.fullmatch(r"\d+", r)
    ),
    process_name=oxitest.partial(
        FormatterCase,
        format="{process.name}",
        validator=lambda r: isinstance(r, str) and r != "",
    ),
    message=oxitest.partial(FormatterCase, format="{message}", validator=lambda r: r == "Message"),
    escaped_specifiers=oxitest.partial(
        FormatterCase,
        format="%s {{a}} 天 {{1}} %d",
        validator=lambda r: r == "%s {a} 天 {1} %d",
    ),
)
def test_log_formatters(
    format: str,
    validator: Callable[[str], Any],
    writer: Fixture[Writer],
    use_log_function: bool,
) -> None:
    message = "Message"

    logger.add(writer, format=format)

    if use_log_function:
        logger.log("DEBUG", message)
    else:
        logger.debug(message)

    result = writer.read().rstrip("\n")
    assert validator(result), (
        "every documented record field must render in the documented shape, and must do so "
        "identically whether the record came from logger.debug() or logger.log()"
    )


@oxitest.parametrize(
    file_only=oxitest.partial(FileFormatterCase, part="file"),
    dir_only=oxitest.partial(FileFormatterCase, part="dir"),
    file_and_dir=oxitest.partial(FileFormatterCase, part="both"),
)
@oxitest.parametrize(
    time=oxitest.partial(
        FileFormatterCase,
        format="{time}.log",
        validator=lambda r: re.fullmatch(r"\d+-\d+-\d+_\d+-\d+-\d+\_\d+.log", r),
    ),
    escaped_specifiers=oxitest.partial(
        FileFormatterCase,
        format="%s_{{a}}_天_{{1}}_%d",
        validator=lambda r: r == "%s_{a}_天_{1}_%d",
    ),
)
def test_file_formatters(
    tmp: TempDir, format: str, validator: Callable[[str], Any], part: str
) -> None:
    if part == "file":
        file = tmp.path.joinpath(format)
    elif part == "dir":
        file = tmp.path.joinpath(format, "log.log")
    elif part == "both":
        file = tmp.path.joinpath(format, format)

    logger.add(file)
    logger.debug("Message")

    files = [f for f in tmp.path.glob("**/*") if f.is_file()]

    assert len(files) == 1, (
        "exactly one log file must be created, otherwise the placeholder was expanded more "
        "than once and messages would be split across files"
    )

    file = files[0]

    why = (
        "placeholders must be expanded in every path segment, so a log layout can be "
        "described entirely by the sink path"
    )
    if part == "file":
        assert validator(file.name), why
    elif part == "dir":
        assert file.name == "log.log", "a segment without a placeholder must be left alone"
        assert validator(file.parent.name), why
    elif part == "both":
        assert validator(file.name), why
        assert validator(file.parent.name), why


@oxitest.parametrize(
    direct_call=oxitest.partial(LogFormattingCase, use_log_function=False),
    log_function=oxitest.partial(LogFormattingCase, use_log_function=True),
)
@oxitest.parametrize(
    no_arguments=oxitest.partial(
        LogFormattingCase,
        message="{1, 2, 3} - {0} - {",
        args=[],
        kwargs={},
        expected="{1, 2, 3} - {0} - {",
    ),
    positional=oxitest.partial(
        LogFormattingCase, message="{} + {} = {}", args=[1, 2, 3], kwargs={}, expected="1 + 2 = 3"
    ),
    named=oxitest.partial(
        LogFormattingCase,
        message="{a} + {b} = {c}",
        args=[],
        kwargs=dict(a=1, b=2, c=3),
        expected="1 + 2 = 3",
    ),
    mixed=oxitest.partial(
        LogFormattingCase,
        message="{0} + {two} = {1}",
        args=[1, 3],
        kwargs=dict(two=2, nope=4),
        expected="1 + 2 = 3",
    ),
    shadowing_record_keys=oxitest.partial(
        LogFormattingCase,
        message="{self} or {message} or {level}",
        args=[],
        kwargs=dict(self="a", message="b", level="c"),
        expected="a or b or c",
    ),
    format_spec=oxitest.partial(
        LogFormattingCase, message="{:.2f}", args=[1], kwargs={}, expected="1.00"
    ),
    nested_format_spec=oxitest.partial(
        LogFormattingCase,
        message="{0:0{three}d}",
        args=[5],
        kwargs=dict(three=3),
        expected="005",
    ),
    escaped_braces=oxitest.partial(
        LogFormattingCase,
        message="{{nope}} {my_dict} {}",
        args=["{{!}}"],
        kwargs=dict(my_dict={"a": 1}),
        expected="{nope} {'a': 1} {{!}}",
    ),
)
def test_log_formatting(
    writer: Fixture[Writer],
    message: str,
    args: List[Any],
    kwargs: Dict[str, Any],
    expected: str,
    use_log_function: bool,
) -> None:
    logger.add(writer, format="{message}", colorize=False)

    if use_log_function:
        logger.log(10, message, *args, **kwargs)
    else:
        logger.debug(message, *args, **kwargs)

    assert writer.read() == expected + "\n", (
        "the message must be formatted with str.format semantics only when arguments are "
        "supplied, and identically through logger.debug() and logger.log()"
    )


def test_formatting_missing_lineno_frame_context(writer: Fixture[Writer]) -> None:
    with helpers.common.simulate_missing_frame_lineno():
        logger.add(writer, format="{line} {message}", colorize=False)
        logger.info("Foobar")
        result = writer.read()
    assert result == "0 Foobar\n", (
        "a frame without f_lineno must yield line 0 rather than crash, so loguru keeps "
        "working on interpreters that do not expose line numbers"
    )


@oxitest.parametrize(**INCOMPLETE_FRAME_CASES)
def test_formatting_incomplete_frame_context(writer: Fixture[Writer], simulate: str) -> None:
    with getattr(helpers.common, simulate)():
        logger.add(writer, format="{name} {message}", colorize=False)
        logger.info("Foobar")
        result = writer.read()
    assert result == "None Foobar\n", (
        "an unresolvable module name must render as None rather than crash, so loguru keeps "
        "working under Dask and Cython"
    )


def test_extra_formatting(writer: Fixture[Writer]) -> None:
    logger.configure(extra={"test": "my_test", "dict": {"a": 10}})
    logger.add(writer, format="{extra[test]} -> {extra[dict]} -> {message}")
    logger.debug("level: {name}", name="DEBUG")
    assert writer.read() == "my_test -> {'a': 10} -> level: DEBUG\n", (
        "the handler format and the message are formatted separately, so a kwarg named after "
        "a record field must fill the message without disturbing the format"
    )


def test_kwargs_in_extra_dict() -> None:
    extra_dicts = []
    messages = []

    def sink(message):
        extra_dicts.append(message.record["extra"])
        messages.append(str(message))

    logger.add(sink, format="{message}")
    logger.info("A")
    logger.info("B", foo=123)
    logger.bind(merge=True).info("C", other=False)
    logger.bind(override=False).info("D", override=True)
    logger.info("Formatted kwargs: {foobar}", foobar=123)
    logger.info("Ignored args: {}", 456)
    logger.info("Both: {foobar} {}", 456, foobar=123)
    logger.opt(lazy=True).info("Lazy: {lazy}", lazy=lambda: 789)

    assert messages == [
        "A\n",
        "B\n",
        "C\n",
        "D\n",
        "Formatted kwargs: 123\n",
        "Ignored args: 456\n",
        "Both: 123 456\n",
        "Lazy: 789\n",
    ], "kwargs must fill the message when it references them, and be ignored otherwise"

    assert extra_dicts == [
        {},
        {"foo": 123},
        {"merge": True, "other": False},
        {"override": True},
        {"foobar": 123},
        {},
        {"foobar": 123},
        {"lazy": 789},
    ], (
        "kwargs must also land in extra, merging with (and overriding) bound values, so "
        "structured sinks see the same data the message was formatted from"
    )


def test_non_string_message(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message}")

    logger.info(1)
    logger.info({})
    logger.info(b"test")

    assert writer.read() == "1\n{}\nb'test'\n", (
        "a non-string message must be converted with str(), so logging an arbitrary object "
        "never raises"
    )


@oxitest.parametrize(**COLORS_CASES)
def test_non_string_message_is_str_in_record(writer: Fixture[Writer], colors: bool) -> None:
    output = ""

    def sink(message):
        nonlocal output
        assert isinstance(message.record["message"], str), (
            "the record must expose the message as a string, otherwise sinks would each have "
            "to convert it themselves"
        )
        output += message

    def format(record):
        assert isinstance(record["message"], str), (
            "a callable format receives the same record, so the message must already be a "
            "string there too"
        )
        return "[{message}]\n"

    logger.add(sink, format=format, catch=False)
    logger.opt(colors=colors).info(123)
    assert output == "[123]\n", "the converted message must be what the format sees"


@oxitest.parametrize(**COLORS_CASES)
def test_missing_positional_field_during_formatting(writer: Fixture[Writer], colors: bool) -> None:
    logger.add(writer)

    with oxitest.raises(ValueError, match=r"^The logging message could not be formatted") as e:
        logger.opt(colors=colors).info("Foo {} {}", 123)

    assert isinstance(e.value.__cause__, IndexError), (
        "the original error must be chained, otherwise the user cannot tell which kind of "
        "formatting mistake they made"
    )


@oxitest.parametrize(**COLORS_CASES)
def test_missing_named_field_during_formatting(writer: Fixture[Writer], colors: bool) -> None:
    logger.add(writer)

    with oxitest.raises(ValueError, match=r"^The logging message could not be formatted") as e:
        logger.opt(colors=colors).info("Foo {bar}", baz=123)

    assert isinstance(e.value.__cause__, KeyError), (
        "the original error must be chained, otherwise the user cannot tell which kind of "
        "formatting mistake they made"
    )


@oxitest.parametrize(**COLORS_CASES)
def test_malformed_curly_braces_during_formatting(writer: Fixture[Writer], colors: bool) -> None:
    logger.add(writer)

    with oxitest.raises(ValueError, match=r"^The logging message could not be formatted") as e:
        logger.opt(colors=colors).info("This is a curly bracket: {", foo="bar")

    assert isinstance(e.value.__cause__, ValueError), (
        "the original error must be chained, otherwise the user cannot tell which kind of "
        "formatting mistake they made"
    )


@oxitest.parametrize(**COLORS_CASES)
def test_not_formattable_message(writer: Fixture[Writer], colors: bool) -> None:
    logger.add(writer)

    with oxitest.raises(ValueError, match=r"^The logging message could not be formatted") as e:
        logger.opt(colors=colors).info(123, baz=456)

    assert isinstance(e.value.__cause__, TypeError if colors else AttributeError), (
        "the original error must be chained; the colors path fails while parsing markup and "
        "the plain path while calling format(), so the two causes legitimately differ"
    )


def test_invalid_color_markup(writer: Fixture[Writer]) -> None:
    with oxitest.raises(
        ValueError, match=r"^Invalid format, color markups could not be parsed correctly$"
    ):
        logger.add(writer, format="<red>Not closed tag", colorize=True)


@oxitest.parametrize(**INVALID_KEY_FORMATS)
@oxitest.parametrize(**INVALID_KEY_COLORIZE)
@oxitest.parametrize(**INVALID_KEY_COLORS)
def test_invalid_format_key_emits_helpful_error_with_catch(
    cap: StdCapture,
    format_: Union[str, Callable[[Any], str]],
    colorize: bool,
    colors: bool,
) -> None:
    logger.add(lambda msg: None, format=format_, catch=True, colorize=colorize)
    logger.opt(colors=colors).info("Hello")
    captured = cap.readouterr()
    assert captured.out == "", "the error report goes to stderr, so stdout must stay empty"
    assert "ValueError: Failed to format log record: key 'missing' not found" in captured.err, (
        "the report must name the offending key on every code path, since a bare KeyError "
        "would not say which format was wrong"
    )


@oxitest.parametrize(**INVALID_KEY_FORMATS)
@oxitest.parametrize(**INVALID_KEY_COLORIZE)
@oxitest.parametrize(**INVALID_KEY_COLORS)
def test_invalid_format_key_raises_enhanced_error_without_catch(
    format_: Union[str, Callable[[Any], str]], colorize: bool, colors: bool
) -> None:
    logger.add(lambda msg: None, format=format_, catch=False, colorize=colorize)
    with oxitest.raises(ValueError, match=r"Failed to format log record: key 'missing' not found."):
        logger.opt(colors=colors).info("Hello")
