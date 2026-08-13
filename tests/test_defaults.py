from dataclasses import dataclass

import conftest
import oxitest

from loguru._defaults import env


@dataclass(frozen=True)
class ValueCase:
    value: str


@oxitest.parametrize(
    non_empty=ValueCase(value="test"),
    empty=ValueCase(value=""),
)
def test_string(value: str) -> None:
    with conftest.patch_context() as context:
        key = "VALID_STRING"
        context.setenv(key, value)
        assert env(key, str) == value, (
            "a string variable must be forwarded verbatim, otherwise user-supplied formats "
            "and levels get mangled before loguru ever sees them"
        )


@oxitest.parametrize(
    letter=ValueCase(value="y"),
    digit=ValueCase(value="1"),
    word=ValueCase(value="TRUE"),
)
def test_bool_positive(value: str) -> None:
    with conftest.patch_context() as context:
        key = "VALID_BOOL_POS"
        context.setenv(key, value)
        assert env(key, bool) is True, (
            "every documented spelling of "
            "true must parse as True, otherwise the variable silently means its opposite"
        )


@oxitest.parametrize(
    word=ValueCase(value="NO"),
    digit=ValueCase(value="0"),
    lowercase_word=ValueCase(value="false"),
)
def test_bool_negative(value: str) -> None:
    with conftest.patch_context() as context:
        key = "VALID_BOOL_NEG"
        context.setenv(key, value)
        assert env(key, bool) is False, (
            "every documented spelling of "
            "false must parse as False, otherwise the variable silently means its opposite"
        )


def test_int() -> None:
    with conftest.patch_context() as context:
        key = "VALID_INT"
        context.setenv(key, "42")
        assert env(key, int) == 42, (
            "an integer variable must be converted from its string form, otherwise level "
            "thresholds would be compared as text"
        )


@oxitest.parametrize(
    empty=ValueCase(value=""),
    letter=ValueCase(value="a"),
)
def test_invalid_int(value: str) -> None:
    with conftest.patch_context() as context:
        key = "INVALID_INT"
        context.setenv(key, value)
        with oxitest.raises(
            ValueError,
            match=r"^Invalid environment variable 'INVALID_INT' \(expected an integer\): '[^']*'$",
        ):
            env(key, int)


@oxitest.parametrize(
    empty=ValueCase(value=""),
    letter=ValueCase(value="a"),
)
def test_invalid_bool(value: str) -> None:
    with conftest.patch_context() as context:
        key = "INVALID_BOOL"
        context.setenv(key, value)
        with oxitest.raises(
            ValueError,
            match=r"^Invalid environment variable 'INVALID_BOOL' \(expected a boolean\): '[^']*'$",
        ):
            env(key, bool)


def test_invalid_type() -> None:
    with conftest.patch_context() as context:
        key = "INVALID_TYPE"
        context.setenv(key, "42.0")
        with oxitest.raises(ValueError, match=r"^The requested type '[^']+' is not supported"):
            env(key, float)
