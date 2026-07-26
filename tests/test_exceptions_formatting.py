import os
import platform
import re
import subprocess
import sys
import traceback
from dataclasses import dataclass
from typing import Tuple
from unittest.mock import MagicMock

import oxitest
from conftest import Writer
from oxitest import Fixture, helpers

from loguru import logger


@dataclass(frozen=True)
class OutputCase:
    filename: str


@dataclass(frozen=True)
class ModernOutputCase:
    filename: str
    minimum_python_version: Tuple[int, ...]


def _cases(*filenames: str) -> dict:
    return {filename: OutputCase(filename=filename) for filename in filenames}


def normalize(exception):
    """Normalize exception output for reproducible test cases."""
    if os.name == "nt":
        exception = re.sub(
            r'File[^"]+"[^"]+\.py[^"]*"', lambda m: m.group().replace("\\", "/"), exception
        )
        exception = re.sub(r"(\r\n|\r|\n)", "\n", exception)

    def fix_filepath(match):
        filepath = match.group(1)

        # Pattern to check if the filepath contains ANSI escape codes.
        pattern = r'((?:\x1b\[[0-9]*m)+)([^"]+?)((?:\x1b\[[0-9]*m)+)([^"]+?)((?:\x1b\[[0-9]*m)+)'

        match = re.match(pattern, filepath)
        start_directory = os.path.dirname(os.path.dirname(__file__))
        if match:
            # Simplify the path while preserving the color highlighting of the file basename.
            groups = list(match.groups())
            groups[1] = os.path.relpath(os.path.abspath(groups[1]), start_directory) + "/"
            relpath = "".join(groups)
        else:
            # We can straightforwardly convert from absolute to relative path.
            relpath = os.path.relpath(os.path.abspath(filepath), start_directory)
        return 'File "%s"' % relpath.replace("\\", "/")

    exception = re.sub(
        r'File "([^"]+\.py[^"]*)"',
        fix_filepath,
        exception,
    )

    exception = re.sub(
        r'"[^"]*/somelib/__init__.py"', '"/usr/lib/python/somelib/__init__.py"', exception
    )

    exception = re.sub(r"\b0x[0-9a-fA-F]+\b", "0xDEADBEEF", exception)

    if platform.python_implementation() == "PyPy":
        exception = (
            exception.replace(
                "<function str.isdigit at 0xDEADBEEF>", "<method 'isdigit' of 'str' objects>"
            )
            .replace(
                "<function coroutine.send at 0xDEADBEEF>", "<method 'send' of 'coroutine' objects>"
            )
            .replace(
                "<function NoneType.__bool__ at 0xDEADBEEF>",
                "<slot wrapper '__bool__' of 'NoneType' objects>",
            )
        )

    return exception


def generate(output, outpath):
    """Generate new output file if exception formatting is updated."""
    os.makedirs(os.path.dirname(outpath), exist_ok=True)
    with open(outpath, "w") as file:
        file.write(output)
    raise AssertionError("The method 'generate()' was called while running tests.")


def compare_exception(dirname, filename):
    cwd = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    python = sys.executable or "python"
    filepath = os.path.join("tests", "exceptions", "source", dirname, filename + ".py")
    outpath = os.path.join(cwd, "tests", "exceptions", "output", dirname, filename + ".txt")

    with subprocess.Popen(
        [python, filepath],
        shell=False,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        env=dict(os.environ, PYTHONPATH=cwd, PYTHONIOENCODING="utf8"),
    ) as proc:
        stdout, stderr = proc.communicate()
        print(stderr, file=sys.stderr)
        assert proc.returncode == 0, (
            "the sample script must run to completion; a non-zero exit means it crashed "
            "instead of logging the exception it was written to log"
        )
        assert stdout == "", "the sample scripts log to stderr only"
        assert stderr != "", "the sample script must actually produce the traceback under test"

    stderr = normalize(stderr)

    # generate(stderr, outpath)

    with open(outpath, "r") as file:
        assert stderr == file.read(), (
            "the rendered traceback must match the recorded output byte for byte — these "
            "snapshots are the only specification of how loguru formats exceptions"
        )


@oxitest.parametrize(
    **_cases(
        "chained_expression_direct",
        "chained_expression_indirect",
        "chaining_first",
        "chaining_second",
        "chaining_third",
        "enqueue",
        "enqueue_with_others_handlers",
        "frame_values_backward",
        "frame_values_forward",
        "function",
        "head_recursion",
        "missing_attributes_traceback_objects",
        "missing_lineno_frame_objects",
        "nested",
        "nested_chained_catch_up",
        "nested_decorator_catch_up",
        "nested_explicit_catch_up",
        "nested_wrapping",
        "no_tb",
        "not_enough_arguments",
        "raising_recursion",
        "suppressed_expression_direct",
        "suppressed_expression_indirect",
        "tail_recursion",
        "too_many_arguments",
    )
)
def test_backtrace(filename: str) -> None:
    compare_exception("backtrace", filename)


@oxitest.parametrize(
    **_cases(
        "assertion_error",
        "assertion_error_custom",
        "assertion_error_in_string",
        "attributes",
        "chained_both",
        "encoding",
        "global_variable",
        "indentation_error",
        "keyword_argument",
        "multilines_repr",
        "no_error_message",
        "parenthesis",
        "source_multilines",
        "source_strings",
        "syntax_error",
        "syntax_highlighting",
        "truncating",
        "unprintable_object",
    )
)
def test_diagnose(filename: str) -> None:
    compare_exception("diagnose", filename)


@oxitest.parametrize(
    **_cases(
        "assertion_from_lib",
        "assertion_from_local",
        "callback",
        "catch_decorator",
        "catch_decorator_from_lib",
        "decorated_callback",
        "direct",
        "indirect",
        "string_lib",
        "string_source",
        "syntaxerror",
    )
)
def test_exception_ownership(filename: str) -> None:
    compare_exception("ownership", filename)


@oxitest.parametrize(
    **_cases(
        "assertionerror_without_traceback",
        "broken_but_decorated_repr",
        "catch_as_context_manager",
        "catch_as_decorator_with_parentheses",
        "catch_as_decorator_without_parentheses",
        "catch_as_function",
        "catch_message",
        "exception_formatting_coroutine",
        "exception_formatting_function",
        "exception_formatting_generator",
        "exception_in_property",
        "handler_formatting_with_context_manager",
        "handler_formatting_with_decorator",
        "level_name",
        "level_number",
        "message_formatting_with_context_manager",
        "message_formatting_with_decorator",
        "nested_with_reraise",
        "one_liner_recursion",
        "recursion_error",
        "repeated_lines",
        "syntaxerror_without_traceback",
        "sys_tracebacklimit",
        "sys_tracebacklimit_negative",
        "sys_tracebacklimit_none",
        "sys_tracebacklimit_unset",
        "zerodivisionerror_without_traceback",
    )
)
def test_exception_others(filename: str) -> None:
    if filename == "recursion_error" and platform.python_implementation() == "PyPy":
        oxitest.skip("RecursionError is not reliable on PyPy")

    compare_exception("others", filename)


@oxitest.parametrize(
    type_hints=ModernOutputCase(filename="type_hints", minimum_python_version=(3, 6)),
    exception_formatting_async_generator=ModernOutputCase(
        filename="exception_formatting_async_generator", minimum_python_version=(3, 6)
    ),
    decorate_async_generator=ModernOutputCase(
        filename="decorate_async_generator", minimum_python_version=(3, 7)
    ),
    positional_only_argument=ModernOutputCase(
        filename="positional_only_argument", minimum_python_version=(3, 8)
    ),
    walrus_operator=ModernOutputCase(filename="walrus_operator", minimum_python_version=(3, 8)),
    match_statement=ModernOutputCase(filename="match_statement", minimum_python_version=(3, 10)),
    exception_group_catch=ModernOutputCase(
        filename="exception_group_catch", minimum_python_version=(3, 11)
    ),
    notes=ModernOutputCase(filename="notes", minimum_python_version=(3, 11)),
    grouped_simple=ModernOutputCase(filename="grouped_simple", minimum_python_version=(3, 11)),
    grouped_nested=ModernOutputCase(filename="grouped_nested", minimum_python_version=(3, 11)),
    grouped_with_cause_and_context=ModernOutputCase(
        filename="grouped_with_cause_and_context", minimum_python_version=(3, 11)
    ),
    grouped_as_cause_and_context=ModernOutputCase(
        filename="grouped_as_cause_and_context", minimum_python_version=(3, 11)
    ),
    grouped_max_length=ModernOutputCase(
        filename="grouped_max_length", minimum_python_version=(3, 11)
    ),
    grouped_max_depth=ModernOutputCase(
        filename="grouped_max_depth", minimum_python_version=(3, 11)
    ),
    # Available since 3.6 but in 3.12 the lexer for f-string changed.
    f_string=ModernOutputCase(filename="f_string", minimum_python_version=(3, 12)),
    t_string=ModernOutputCase(filename="t_string", minimum_python_version=(3, 14)),
)
def test_exception_modern(filename: str, minimum_python_version: Tuple[int, ...]) -> None:
    if sys.version_info < minimum_python_version:
        oxitest.skip("Feature not supported in this Python version")

    if filename == "exception_group_catch" and platform.python_implementation() == "PyPy":
        oxitest.skip("Incorrect traceback formatting on PyPy")  #  Issue #5338.

    compare_exception("modern", filename)


@oxitest.mark.skip(
    when=not (3, 7) <= sys.version_info < (3, 11), reason="No backport available or needed"
)
def test_group_exception_using_backport(writer: Fixture[Writer]) -> None:
    from exceptiongroup import ExceptionGroup

    logger.add(writer, backtrace=True, diagnose=True, colorize=False, format="")

    try:
        raise ExceptionGroup("Test", [ValueError(1), ValueError(2)])
    except Exception:
        logger.exception("")

    assert (
        writer.read().strip().startswith("+ Exception Group Traceback (most recent call last):")
    ), (
        "the backported ExceptionGroup must be rendered with the same grouped layout as the "
        "built-in one, so output does not depend on the Python version"
    )


def test_invalid_format_exception_only_no_output(writer: Fixture[Writer]) -> None:
    logger.add(writer, backtrace=True, diagnose=True, colorize=False, format="")

    with helpers.common.patch_context() as context:
        context.setattr(traceback, "format_exception_only", lambda _e, _v: [])
        error = ValueError(0)
        logger.opt(exception=error).error("Error")

        assert writer.read() == "\n", (
            "a formatter returning nothing must produce an empty traceback rather than an "
            "IndexError while loguru inspects the result"
        )


def test_invalid_format_exception_only_indented_error_message(
    writer: Fixture[Writer],
) -> None:
    logger.add(writer, backtrace=True, diagnose=True, colorize=False, format="")

    with helpers.common.patch_context() as context:
        context.setattr(traceback, "format_exception_only", lambda _e, _v: ["    ValueError: 0\n"])
        error = ValueError(0)
        logger.opt(exception=error).error("Error")

        assert writer.read() == "\n    ValueError: 0\n", (
            "an unexpectedly indented line must be passed through rather than confuse the "
            "logic that decides where the exception message starts"
        )


@oxitest.mark.skip(when=sys.version_info < (3, 11), reason="No builtin GroupedException")
def test_invalid_grouped_exception_no_exceptions(writer: Fixture[Writer]) -> None:
    error = MagicMock(spec=ExceptionGroup)  # noqa: F821
    error.__cause__ = None
    error.__context__ = None
    error.__traceback__ = None

    logger.add(writer, backtrace=True, diagnose=True, colorize=False, format="")
    logger.opt(exception=error).error("Error")

    assert writer.read().strip().startswith("| unittest.mock.MagicMock:"), (
        "an object that merely looks like an ExceptionGroup but holds no sub-exceptions "
        "must still be rendered instead of crashing the formatter"
    )
