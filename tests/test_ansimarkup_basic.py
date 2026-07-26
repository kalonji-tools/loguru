from dataclasses import dataclass

import oxitest
from colorama import Back, Fore, Style

from tests._utils import parse


@dataclass(frozen=True)
class MarkupCase:
    text: str
    expected: str


@dataclass
class ErrorCase:
    text: str
    strip: bool


def _error_cases(*texts: str) -> dict:
    """One partial case per markup snippet, to be crossed with the strip dimension."""
    return {
        "case_%d" % index: oxitest.partial(ErrorCase, text=text) for index, text in enumerate(texts)
    }


STRIP_CASES = {
    "stripped": oxitest.partial(ErrorCase, strip=True),
    "colorized": oxitest.partial(ErrorCase, strip=False),
}


@oxitest.parametrize(
    bold=MarkupCase(text="<bold>1</bold>", expected=Style.BRIGHT + "1" + Style.RESET_ALL),
    dim=MarkupCase(text="<dim>1</dim>", expected=Style.DIM + "1" + Style.RESET_ALL),
    normal=MarkupCase(text="<normal>1</normal>", expected=Style.NORMAL + "1" + Style.RESET_ALL),
    bold_short=MarkupCase(text="<b>1</b>", expected=Style.BRIGHT + "1" + Style.RESET_ALL),
    dim_short=MarkupCase(text="<d>1</d>", expected=Style.DIM + "1" + Style.RESET_ALL),
    normal_short=MarkupCase(text="<n>1</n>", expected=Style.NORMAL + "1" + Style.RESET_ALL),
)
def test_styles(text: str, expected: str) -> None:
    assert parse(text, strip=False) == expected, (
        "each style tag and its short alias must produce the documented escape sequence, "
        "otherwise a format that renders correctly today breaks on the next terminal"
    )


@oxitest.parametrize(
    red=MarkupCase(text="<RED>1</RED>", expected=Back.RED + "1" + Style.RESET_ALL),
    red_short=MarkupCase(text="<R>1</R>", expected=Back.RED + "1" + Style.RESET_ALL),
    light_green=MarkupCase(
        text="<LIGHT-GREEN>1</LIGHT-GREEN>", expected=Back.LIGHTGREEN_EX + "1" + Style.RESET_ALL
    ),
    light_green_short=MarkupCase(
        text="<LG>1</LG>", expected=Back.LIGHTGREEN_EX + "1" + Style.RESET_ALL
    ),
)
def test_background_colors(text: str, expected: str) -> None:
    assert parse(text, strip=False) == expected, (
        "upper-case tags select background colors, so they must map to the Back sequences "
        "rather than to the foreground ones"
    )


@oxitest.parametrize(
    yellow=MarkupCase(text="<yellow>1</yellow>", expected=Fore.YELLOW + "1" + Style.RESET_ALL),
    yellow_short=MarkupCase(text="<y>1</y>", expected=Fore.YELLOW + "1" + Style.RESET_ALL),
    light_white=MarkupCase(
        text="<light-white>1</light-white>", expected=Fore.LIGHTWHITE_EX + "1" + Style.RESET_ALL
    ),
    light_white_short=MarkupCase(
        text="<lw>1</lw>", expected=Fore.LIGHTWHITE_EX + "1" + Style.RESET_ALL
    ),
)
def test_foreground_colors(text: str, expected: str) -> None:
    assert parse(text, strip=False) == expected, (
        "lower-case tags select foreground colors, so they must map to the Fore sequences "
        "rather than to the background ones"
    )


@oxitest.parametrize(
    sequential=MarkupCase(
        text="<b>1</b><d>2</d>",
        expected=Style.BRIGHT + "1" + Style.RESET_ALL + Style.DIM + "2" + Style.RESET_ALL,
    ),
    separated_by_text=MarkupCase(
        text="<b>1</b>2<d>3</d>",
        expected=Style.BRIGHT + "1" + Style.RESET_ALL + "2" + Style.DIM + "3" + Style.RESET_ALL,
    ),
    nested_once=MarkupCase(
        text="0<b>1<d>2</d>3</b>4",
        expected="0"
        + Style.BRIGHT
        + "1"
        + Style.DIM
        + "2"
        + Style.RESET_ALL
        + Style.BRIGHT
        + "3"
        + Style.RESET_ALL
        + "4",
    ),
    nested_twice=MarkupCase(
        text="<d>0<b>1<d>2</d>3</b>4</d>",
        expected=Style.DIM
        + "0"
        + Style.BRIGHT
        + "1"
        + Style.DIM
        + "2"
        + Style.RESET_ALL
        + Style.DIM
        + Style.BRIGHT
        + "3"
        + Style.RESET_ALL
        + Style.DIM
        + "4"
        + Style.RESET_ALL,
    ),
)
def test_nested(text: str, expected: str) -> None:
    assert parse(text, strip=False) == expected, (
        "ANSI has no 'close one style' code, so leaving a nested tag must reset and then "
        "re-apply the enclosing styles"
    )


@oxitest.parametrize(
    unclosed=MarkupCase(text="<b>", expected=""),
    unclosed_outer=MarkupCase(text="<Y><b></b>", expected=""),
    unclosed_duplicate=MarkupCase(text="<b><b></b>", expected=""),
)
def test_strict_parsing(text: str, expected: str) -> None:
    with oxitest.raises(
        ValueError, match=r'^Opening tag "<[^>]*>" has no corresponding closing tag$'
    ):
        parse(text, strip=False)


@oxitest.parametrize(
    unclosed=MarkupCase(text="<b>", expected=Style.BRIGHT),
    unclosed_outer=MarkupCase(
        text="<Y><b></b>", expected=Back.YELLOW + Style.BRIGHT + Style.RESET_ALL + Back.YELLOW
    ),
    unclosed_duplicate=MarkupCase(
        text="<b><b></b>", expected=Style.BRIGHT + Style.BRIGHT + Style.RESET_ALL + Style.BRIGHT
    ),
)
def test_permissive_parsing(text: str, expected: str) -> None:
    assert parse(text, strip=False, strict=False) == expected, (
        "non-strict parsing must render what it can instead of raising, so a partially "
        "written line can still be colorized"
    )


@oxitest.parametrize(
    single=MarkupCase(text="<red>foo</>", expected=Fore.RED + "foo" + Style.RESET_ALL),
    nested=MarkupCase(
        text="<green><bold>bar</></green>",
        expected=Fore.GREEN + Style.BRIGHT + "bar" + Style.RESET_ALL + Fore.GREEN + Style.RESET_ALL,
    ),
    interleaved_with_text=MarkupCase(
        text="a<yellow>b<b>c</>d</>e",
        expected="a"
        + Fore.YELLOW
        + "b"
        + Style.BRIGHT
        + "c"
        + Style.RESET_ALL
        + Fore.YELLOW
        + "d"
        + Style.RESET_ALL
        + "e",
    ),
)
def test_autoclose(text: str, expected: str) -> None:
    assert parse(text, strip=False) == expected, (
        "the '</>' shorthand must close the innermost open tag, so authors do not have to "
        "repeat long tag names"
    )


@oxitest.parametrize(
    escaped_tags=MarkupCase(text=r"\<red>foobar\</red>", expected="<red>foobar</red>"),
    escaped_backslash=MarkupCase(
        text=r"\\<red>foobar\\</red>", expected="\\" + Fore.RED + "foobar\\" + Style.RESET_ALL
    ),
    escaped_backslash_then_tag=MarkupCase(
        text=r"\\\<red>foobar\\\</red>", expected="\\<red>foobar\\</red>"
    ),
    two_escaped_backslashes=MarkupCase(
        text=r"\\\\<red>foobar\\\\</red>",
        expected="\\\\" + Fore.RED + "foobar\\\\" + Style.RESET_ALL,
    ),
    escaped_closing_inside=MarkupCase(
        text=r"<red>foo\</red>bar</red>", expected=Fore.RED + "foo</red>bar" + Style.RESET_ALL
    ),
    escaped_opening_inside=MarkupCase(
        text=r"<red>foo\<red>bar</red>", expected=Fore.RED + "foo<red>bar" + Style.RESET_ALL
    ),
    escaped_empty_pair=MarkupCase(text=r"\<red>\</red>", expected="<red></red>"),
    escaped_autoclose=MarkupCase(text=r"foo\</>bar\</>baz", expected="foo</>bar</>baz"),
    backslashes_before_letters=MarkupCase(
        text=r"\a \\b \\\c \\\\d", expected="\\a \\\\b \\\\\\c \\\\\\\\d"
    ),
)
def test_escaping(text: str, expected: str) -> None:
    assert parse(text, strip=False) == expected, (
        "a backslash must escape the tag that follows it and nothing else, so log messages "
        "containing angle brackets survive unchanged"
    )


@oxitest.parametrize(**STRIP_CASES)
@oxitest.parametrize(
    **_error_cases(
        "<b>1</d>",
        "</b>",
        "<b>1</b></b>",
        "<red><b>1</b></b></red>",
        "<green>1</b>",
        "<green>foo</bar>",
        "</>",
        "<red><green>X</></green>",
    )
)
def test_mismatched_error(text: str, strip: bool) -> None:
    with oxitest.raises(
        ValueError, match=r'^Closing tag "<[^>]*>" has no corresponding opening tag$'
    ):
        parse(text, strip=strip)


@oxitest.parametrize(**STRIP_CASES)
@oxitest.parametrize(
    **_error_cases("<r><Y>1</r>2</Y>", "<r><r><Y>1</r>2</Y></r>", "<r><Y><r></r></r></Y>")
)
def test_unbalanced_error(text: str, strip: bool) -> None:
    with oxitest.raises(ValueError, match=r'^Closing tag "<[^>]*>" violates nesting rules$'):
        parse(text, strip=strip)


@oxitest.parametrize(**STRIP_CASES)
@oxitest.parametrize(**_error_cases("<b>", "<Y><b></b>", "<b><b></b>", "<fg red>1<fg red>"))
def test_unclosed_error(text: str, strip: bool) -> None:
    with oxitest.raises(
        ValueError, match=r'^Opening tag "<[^>]*>" has no corresponding closing tag$'
    ):
        parse(text, strip=strip)


@oxitest.parametrize(**STRIP_CASES)
@oxitest.parametrize(
    **_error_cases(
        "<foo>bar</foo>",
        "<Green>foobar</Green>",
        "<bar>foo</green>",
        "<b>1</b><tag>2</tag>",
        "<tag>1</tag><b>2</b>",
        "<b>1</b><tag>2</tag><b>3</b>",
        "<tag>1</tag><b>2</b><tag>3</tag>",
        "<b><tag>1</tag></b>",
        "<tag><b>1</b></tag>",
        "<tag>1</b>",
        "<b></b><tag>1</tag>",
        "<tag>1</tag><b></b>",
    )
)
def test_invalid_color(text: str, strip: bool) -> None:
    with oxitest.raises(
        ValueError,
        match=(
            '^Tag "<[^>]*>" does not correspond to any known color directive, '
            r"make sure you have not misspelled it \(or prepend '\\' to escape it\)$"
        ),
    ):
        parse(text, strip=strip)


@oxitest.parametrize(
    foreground=MarkupCase(text="<red>foo</red>", expected="foo"),
    background=MarkupCase(text="<BLACK>bar</BLACK>", expected="bar"),
    style=MarkupCase(text="<b>baz</b>", expected="baz"),
    several_tags=MarkupCase(text="<b>1</b>2<d>3</d>", expected="123"),
    autoclose=MarkupCase(text="<red>foo</>", expected="foo"),
)
def test_strip(text: str, expected: str) -> None:
    assert parse(text, strip=True) == expected, (
        "stripping must remove the tags and emit no escape sequences at all, which is what "
        "makes the same format usable for both a terminal and a log file"
    )
