from dataclasses import dataclass

import oxitest
from colorama import Back, Fore, Style

from tests._utils import parse

INVALID_COLOR_MESSAGE = (
    '^Tag "<[^>]*>" does not correspond to any known color directive, '
    r"make sure you have not misspelled it \(or prepend '\\' to escape it\)$"
)


@dataclass(frozen=True)
class MarkupCase:
    text: str
    expected: str


@dataclass(frozen=True)
class HexEquivalenceCase:
    short_code: str
    long_code: str


@dataclass
class ErrorCase:
    text: str
    strip: bool


@dataclass
class LayerHexCase:
    layer: str
    short_code: str
    long_code: str


def _error_cases(*texts: str) -> dict:
    """One partial case per markup snippet, to be crossed with the strip dimension."""
    return {
        "case_%d" % index: oxitest.partial(ErrorCase, text=text)
        for index, text in enumerate(texts)
    }


STRIP_CASES = {
    "stripped": oxitest.partial(ErrorCase, strip=True),
    "colorized": oxitest.partial(ErrorCase, strip=False),
}


@oxitest.parametrize(
    named=MarkupCase(text="<bg red>1</bg red>", expected=Back.RED + "1" + Style.RESET_ALL),
    named_upper=MarkupCase(
        text="<bg BLACK>1</bg BLACK>", expected=Back.BLACK + "1" + Style.RESET_ALL
    ),
    light=MarkupCase(
        text="<bg light-green>1</bg light-green>",
        expected=Back.LIGHTGREEN_EX + "1" + Style.RESET_ALL,
    ),
    light_upper=MarkupCase(
        text="<bg LIGHT-MAGENTA>1</bg LIGHT-MAGENTA>",
        expected=Back.LIGHTMAGENTA_EX + "1" + Style.RESET_ALL,
    ),
)
def test_background_colors(text: str, expected: str) -> None:
    assert parse(text, strip=False) == expected, (
        "the explicit 'bg' form must select the background regardless of tag casing, unlike "
        "the shorthand tags where case is what picks the layer"
    )


@oxitest.parametrize(
    named=MarkupCase(text="<fg yellow>1</fg yellow>", expected=Fore.YELLOW + "1" + Style.RESET_ALL),
    named_upper=MarkupCase(
        text="<fg BLUE>1</fg BLUE>", expected=Fore.BLUE + "1" + Style.RESET_ALL
    ),
    light=MarkupCase(
        text="<fg light-white>1</fg light-white>",
        expected=Fore.LIGHTWHITE_EX + "1" + Style.RESET_ALL,
    ),
    light_upper=MarkupCase(
        text="<fg LIGHT-CYAN>1</fg LIGHT-CYAN>",
        expected=Fore.LIGHTCYAN_EX + "1" + Style.RESET_ALL,
    ),
)
def test_foreground_colors(text: str, expected: str) -> None:
    assert parse(text, strip=False) == expected, (
        "the explicit 'fg' form must select the foreground regardless of tag casing, unlike "
        "the shorthand tags where case is what picks the layer"
    )


@oxitest.parametrize(
    foreground=MarkupCase(
        text="<fg #ff0000>1</fg #ff0000>", expected="\x1b[38;2;255;0;0m" "1" + Style.RESET_ALL
    ),
    background=MarkupCase(
        text="<bg #00A000>1</bg #00A000>", expected="\x1b[48;2;0;160;0m" "1" + Style.RESET_ALL
    ),
    short_form=MarkupCase(
        text="<fg #F12>1</fg #F12>", expected="\x1b[38;2;255;17;34m" "1" + Style.RESET_ALL
    ),
)
def test_8bit_colors(text: str, expected: str) -> None:
    assert parse(text, strip=False) == expected, (
        "a hex color must emit the 24-bit truecolor sequence, since that is the only way to "
        "reproduce an arbitrary RGB value"
    )


@oxitest.parametrize(
    foreground=MarkupCase(
        text="<fg #ff0000>1</fg #ff0000>", expected="\x1b[38;2;255;0;0m" "1" + Style.RESET_ALL
    ),
    background=MarkupCase(
        text="<bg #00A000>1</bg #00A000>", expected="\x1b[48;2;0;160;0m" "1" + Style.RESET_ALL
    ),
    short_foreground=MarkupCase(
        text="<fg #F12>1</fg #F12>", expected="\x1b[38;2;255;17;34m" "1" + Style.RESET_ALL
    ),
    short_background=MarkupCase(
        text="<bg #BEE>1</bg #BEE>", expected="\x1b[48;2;187;238;238m" "1" + Style.RESET_ALL
    ),
)
def test_hex_colors(text: str, expected: str) -> None:
    assert parse(text, strip=False) == expected, (
        "both the three- and six-digit hex forms must be accepted on either layer, matching "
        "the CSS convention users expect"
    )


@oxitest.parametrize(
    foreground=oxitest.partial(LayerHexCase, layer="fg"),
    background=oxitest.partial(LayerHexCase, layer="bg"),
)
@oxitest.parametrize(
    abc=oxitest.partial(LayerHexCase, short_code="abc", long_code="aabbcc"),
    f00=oxitest.partial(LayerHexCase, short_code="f00", long_code="ff0000"),
    f12=oxitest.partial(LayerHexCase, short_code="f12", long_code="ff1122"),
    bee=oxitest.partial(LayerHexCase, short_code="bee", long_code="bbeeee"),
    mixed_case=oxitest.partial(LayerHexCase, short_code="Ace", long_code="AAccee"),
)
def test_hex_short_code_equals_long_code(layer: str, short_code: str, long_code: str) -> None:
    short_code_colorized = parse("<%s #%s>_</>" % (layer, short_code))
    long_code_colorized = parse("<%s #%s>_</>" % (layer, long_code))
    assert short_code_colorized == long_code_colorized, (
        "the three-digit form must expand by doubling each digit, so #abc and #aabbcc are "
        "genuinely the same color rather than merely similar"
    )


@oxitest.parametrize(
    foreground=MarkupCase(text="<fg 200>1</fg 200>", expected="\x1b[38;5;200m" "1" + Style.RESET_ALL),
    background=MarkupCase(text="<bg 49>1</bg 49>", expected="\x1b[48;5;49m" "1" + Style.RESET_ALL),
)
def test_rgb_colors(text: str, expected: str) -> None:
    assert parse(text, strip=False) == expected, (
        "a bare number must emit the 256-color palette sequence, which is distinct from the "
        "truecolor sequence used for hex values"
    )


@oxitest.parametrize(
    named_and_hex=MarkupCase(
        text="<red><b><bg #00A000>1</bg #00A000></b></red>",
        expected=Fore.RED + Style.BRIGHT + "\x1b[48;2;0;160;0m"
        "1"
        + Style.RESET_ALL
        + Fore.RED
        + Style.BRIGHT
        + Style.RESET_ALL
        + Fore.RED
        + Style.RESET_ALL,
    ),
    palette_numbers=MarkupCase(
        text="<bg 100><fg 200>1</fg 200></bg 100>",
        expected="\x1b[48;5;100m" "\x1b[38;5;200m" "1" "\x1b[0m" "\x1b[48;5;100m" "\x1b[0m",
    ),
    hex_values=MarkupCase(
        text="<bg #00a000><fg #FF0000>1</fg #FF0000></bg #00a000>",
        expected="\x1b[48;2;0;160;0m" "\x1b[38;2;255;0;0m" "1" "\x1b[0m" "\x1b[48;2;0;160;0m"
        "\x1b[0m",
    ),
    rgb_triplets=MarkupCase(
        text="<bg 0,160,0><fg 255,0,0>1</fg 255,0,0></bg 0,160,0>",
        expected="\x1b[48;2;0;160;0m" "\x1b[38;2;255;0;0m" "1" "\x1b[0m" "\x1b[48;2;0;160;0m"
        "\x1b[0m",
    ),
)
def test_nested(text: str, expected: str) -> None:
    assert parse(text, strip=False) == expected, (
        "ANSI has no 'close one color' code, so leaving a nested tag must reset and then "
        "re-apply the enclosing colors, whatever notation they were written in"
    )


@oxitest.parametrize(
    greater_than=MarkupCase(text="<r>2 > 1</r>", expected=Fore.RED + "2 > 1" + Style.RESET_ALL),
    less_than=MarkupCase(text="<r>1 < 2</r>", expected=Fore.RED + "1 < 2" + Style.RESET_ALL),
    closing_like=MarkupCase(text="<r>1 </ 2</r>", expected=Fore.RED + "1 </ 2" + Style.RESET_ALL),
    align_spec_before=MarkupCase(
        text="{: <10}<r>1</r>", expected="{: <10}" + Fore.RED + "1" + Style.RESET_ALL
    ),
    align_spec_with_slash=MarkupCase(
        text="{: </10}<r>1</r>", expected="{: </10}" + Fore.RED + "1" + Style.RESET_ALL
    ),
    align_spec_after=MarkupCase(
        text="<r>1</r>{: >10}", expected=Fore.RED + "1" + Style.RESET_ALL + "{: >10}"
    ),
    surrounded_by_brackets=MarkupCase(
        text="<1<r>2</r>3>", expected="<1" + Fore.RED + "2" + Style.RESET_ALL + "3>"
    ),
    surrounded_by_closing_brackets=MarkupCase(
        text="</1<r>2</r>3>", expected="</1" + Fore.RED + "2" + Style.RESET_ALL + "3>"
    ),
    brackets_and_less_than=MarkupCase(
        text="<1<r>2 < 3</r>4>", expected="<1" + Fore.RED + "2 < 3" + Style.RESET_ALL + "4>"
    ),
    brackets_and_closing_like=MarkupCase(
        text="<1<r>2 </ 3</r>4>", expected="<1" + Fore.RED + "2 </ 3" + Style.RESET_ALL + "4>"
    ),
    brackets_and_greater_than=MarkupCase(
        text="<1<r>3 > 2</r>4>", expected="<1" + Fore.RED + "3 > 2" + Style.RESET_ALL + "4>"
    ),
)
def test_tricky_parse(text: str, expected: str) -> None:
    assert parse(text, strip=False) == expected, (
        "angle brackets that cannot form a valid tag must be left alone, otherwise comparison "
        "operators and format alignment specs could not appear in a colorized format"
    )


@oxitest.parametrize(**STRIP_CASES)
@oxitest.parametrize(
    **_error_cases(
        "<fg light-blue2>1</fg light-blue2>",
        "<bg ,red>1</bg ,red>",
        "<bg red,>1</bg red,>",
        "<bg a,z>1</bg a,z>",
        "<bg blue,yelllow>1</bg blue,yelllow>",
        "<>1</>",
        "<,>1</,>",
        "<z,z>1</z,z>",
        "<z,z,z>1</z,z,z>",
        "<fg>1</fg>",
    )
)
def test_invalid_color(text: str, strip: bool) -> None:
    with oxitest.raises(ValueError, match=INVALID_COLOR_MESSAGE):
        parse(text, strip=strip)


@oxitest.parametrize(**STRIP_CASES)
@oxitest.parametrize(
    **_error_cases(
        "<fg #>1</fg #>",
        "<bg #12>1</bg #12>",
        "<fg #1234567>1</fg #1234567>",
        "<bg #E7G>1</bg #E7G>",
        "<fg #F2D1GZ>1</fg #F2D1GZ>",
    )
)
def test_invalid_hex(text: str, strip: bool) -> None:
    with oxitest.raises(ValueError, match=INVALID_COLOR_MESSAGE):
        parse(text, strip=strip)


@oxitest.parametrize(**STRIP_CASES)
@oxitest.parametrize(
    **_error_cases("<fg 256>1</fg 256>", "<bg 2222>1</bg 2222>", "<bg -1>1</bg -1>")
)
def test_invalid_8bit(text: str, strip: bool) -> None:
    with oxitest.raises(ValueError, match=INVALID_COLOR_MESSAGE):
        parse(text, strip=strip)


@oxitest.parametrize(**STRIP_CASES)
@oxitest.parametrize(
    **_error_cases(
        "<fg 1,2,>1</fg 1,2,>",
        "<bg ,>1</bg ,>",
        "<fg ,,>1</fg ,,>",
        "<fg 256,120,120>1</fg 256,120,120>",
        "<bg 1,2,3,4>1</bg 1,2,3,4>",
    )
)
def test_invalid_rgb(text: str, strip: bool) -> None:
    with oxitest.raises(ValueError, match=INVALID_COLOR_MESSAGE):
        parse(text, strip=strip)


@oxitest.parametrize(
    hex_value=MarkupCase(text="<fg #ff0000>foobar</fg #ff0000>", expected="foobar"),
    palette_number=MarkupCase(text="<fg 55>baz</fg 55>", expected="baz"),
    rgb_triplet=MarkupCase(text="<bg 23,12,12>bar</bg 23,12,12>", expected="bar"),
)
def test_strip(text: str, expected: str) -> None:
    assert parse(text, strip=True) == expected, (
        "stripping must remove extended tags as completely as basic ones, otherwise a log "
        "file would keep fragments of the color notation"
    )


@oxitest.parametrize(
    greater_than=MarkupCase(text="<r>2 > 1</r>", expected="2 > 1"),
    less_than=MarkupCase(text="<r>1 < 2</r>", expected="1 < 2"),
    closing_like=MarkupCase(text="<r>1 </ 2</r>", expected="1 </ 2"),
    align_spec_before=MarkupCase(text="{: <10}<r>1</r>", expected="{: <10}1"),
    align_spec_with_slash=MarkupCase(text="{: </10}<r>1</r>", expected="{: </10}1"),
    align_spec_after=MarkupCase(text="<r>1</r>{: >10}", expected="1{: >10}"),
    surrounded_by_brackets=MarkupCase(text="<1<r>2</r>3>", expected="<123>"),
    surrounded_by_closing_brackets=MarkupCase(text="</1<r>2</r>3>", expected="</123>"),
    brackets_and_less_than=MarkupCase(text="<1<r>2 < 3</r>4>", expected="<12 < 34>"),
    brackets_and_closing_like=MarkupCase(text="<1<r>2 </ 3</r>4>", expected="<12 </ 34>"),
    brackets_and_greater_than=MarkupCase(text="<1<r>3 > 2</r>4>", expected="<13 > 24>"),
)
def test_tricky_strip(text: str, expected: str) -> None:
    assert parse(text, strip=True) == expected, (
        "stripping must recognise exactly the same tags as colorizing, otherwise the same "
        "format would render differently to a file than to a terminal"
    )
