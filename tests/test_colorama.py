import builtins
import contextlib
import os
import sys
from dataclasses import dataclass
from typing import Any, Iterator, Tuple, Type
from unittest.mock import MagicMock

import oxitest
from oxitest import helpers

from loguru import logger
from loguru._colorama import should_colorize, should_wrap
from tests._utils import (
    StreamFilenoException,
    StreamIsattyException,
    StreamIsattyFalse,
    StreamIsattyTrue,
    StubStream,
)

ONLY_WINDOWS_NEEDS_COLORAMA = "Only Windows requires Colorama"
FIX_IS_WINDOWS_ONLY = "The fix is applied only on Windows"


@dataclass(frozen=True)
class PatchedCase:
    patched: str
    expected: bool


@dataclass(frozen=True)
class EnvValueCase:
    patched: str
    env_value: str
    expected: bool


@dataclass(frozen=True)
class JupyterCase:
    patched: str
    out_class: Type[StubStream]
    expected: bool


@dataclass(frozen=True)
class StandardStreamCase:
    patched: str


STANDARD_STREAM_CASES = {
    "original_stdout": StandardStreamCase(patched="__stdout__"),
    "original_stderr": StandardStreamCase(patched="__stderr__"),
}

# Only the *original* standard streams are eligible for the environment-based fixes;
# a reassigned sys.stdout or an unrelated stream must be left alone.
ORIGINAL_STREAMS_ONLY = {
    "original_stdout": PatchedCase(patched="__stdout__", expected=True),
    "original_stderr": PatchedCase(patched="__stderr__", expected=True),
    "current_stdout": PatchedCase(patched="stdout", expected=False),
    "current_stderr": PatchedCase(patched="stderr", expected=False),
    "unrelated_stream": PatchedCase(patched="", expected=False),
}


@contextlib.contextmanager
def isolated_environment() -> Iterator[Any]:
    """Run with an empty environment and a scoped patcher.

    Colour detection reads NO_COLOR, FORCE_COLOR, TERM, CI and friends, so whatever the
    developer happens to export must not decide the outcome of these tests.
    """
    env = os.environ.copy()
    os.environ.clear()
    try:
        with helpers.common.patch_context() as context:
            yield context
    finally:
        os.environ.clear()
        os.environ.update(env)


@contextlib.contextmanager
def patched_colorama(context: Any) -> Iterator[Any]:
    """Install a fake colorama so the Windows code path can run on any platform."""
    ansi_to_win32_class = MagicMock()
    winapi_test = MagicMock(return_value=True)
    enable_vt_processing = MagicMock(return_value=False)
    win32 = MagicMock(winapi_test=winapi_test)
    winterm = MagicMock(enable_vt_processing=enable_vt_processing)
    colorama = MagicMock(AnsiToWin32=ansi_to_win32_class, win32=win32, winterm=winterm)
    context.setitem(sys.modules, "colorama", colorama)
    context.setitem(sys.modules, "colorama.win32", win32)
    context.setitem(sys.modules, "colorama.winterm", winterm)
    yield colorama


@oxitest.mark.skip(when=os.name != "nt", reason=ONLY_WINDOWS_NEEDS_COLORAMA)
@oxitest.parametrize(**STANDARD_STREAM_CASES)
def test_stream_wrapped_on_windows_if_no_vt_support(patched: str) -> None:
    stream = StreamIsattyTrue()
    with isolated_environment() as context, patched_colorama(context) as colorama:
        context.setattr(sys, patched, stream, raising=False)
        colorama.win32.winapi_test.return_value = True
        colorama.winterm.enable_vt_processing.return_value = False
        logger.add(stream, colorize=True)
        assert colorama.AnsiToWin32.called, (
            "an old Windows console cannot interpret ANSI codes, so the stream must be "
            "wrapped by colorama for colors to appear at all"
        )


@oxitest.mark.skip(when=os.name != "nt", reason=ONLY_WINDOWS_NEEDS_COLORAMA)
@oxitest.parametrize(**STANDARD_STREAM_CASES)
def test_stream_not_wrapped_on_windows_if_vt_support(patched: str) -> None:
    stream = StreamIsattyTrue()
    with isolated_environment() as context, patched_colorama(context) as colorama:
        context.setattr(sys, patched, stream, raising=False)
        colorama.win32.winapi_test.return_value = True
        colorama.winterm.enable_vt_processing.return_value = True
        logger.add(stream, colorize=True)
        assert not colorama.AnsiToWin32.called, (
            "a modern Windows console understands ANSI codes natively, so wrapping would "
            "only add overhead"
        )


def test_stream_is_none() -> None:
    with isolated_environment():
        assert not should_colorize(None), (
            "a missing stream must not be colorized, otherwise detection would raise before "
            "the sink is even added"
        )


def test_is_a_tty() -> None:
    with isolated_environment():
        assert should_colorize(StreamIsattyTrue()), (
            "a terminal is the case colors exist for, so detection must say yes"
        )


def test_is_not_a_tty() -> None:
    with isolated_environment():
        assert not should_colorize(StreamIsattyFalse()), (
            "a redirected stream must not receive escape sequences, otherwise log files "
            "become unreadable"
        )


def test_is_a_tty_exception() -> None:
    with isolated_environment():
        assert not should_colorize(StreamIsattyException()), (
            "a stream whose isatty() raises must be treated as a non-tty rather than "
            "propagate the error out of logger.add()"
        )


@oxitest.parametrize(**ORIGINAL_STREAMS_ONLY)
def test_pycharm_fixed(patched: str, expected: bool) -> None:
    stream = StreamIsattyFalse()
    with isolated_environment() as context:
        context.setattr(sys, patched, stream, raising=False)
        context.setitem(os.environ, "PYCHARM_HOSTED", "1")
        assert should_colorize(stream) is expected, (
            "PyCharm's console renders ANSI but reports isatty() False, so its standard "
            "streams must be colorized anyway — and only those streams"
        )


@oxitest.parametrize(**ORIGINAL_STREAMS_ONLY)
def test_github_actions_fixed(patched: str, expected: bool) -> None:
    stream = StreamIsattyFalse()
    with isolated_environment() as context:
        context.setitem(os.environ, "CI", "1")
        context.setitem(os.environ, "GITHUB_ACTIONS", "1")
        context.setattr(sys, patched, stream, raising=False)
        assert should_colorize(stream) is expected, (
            "the GitHub Actions log viewer renders ANSI but the streams are pipes, so its "
            "standard streams must be colorized anyway — and only those streams"
        )


@oxitest.mark.skip(when=os.name != "nt", reason=FIX_IS_WINDOWS_ONLY)
@oxitest.parametrize(**ORIGINAL_STREAMS_ONLY)
def test_mintty_fixed_windows(patched: str, expected: bool) -> None:
    stream = StreamIsattyFalse()
    with isolated_environment() as context:
        context.setitem(os.environ, "TERM", "xterm")
        context.setattr(sys, patched, stream, raising=False)
        assert should_colorize(stream) is expected, (
            "mintty on Windows reports isatty() False for its pipes, so a TERM value means "
            "the standard streams are really a terminal"
        )


@oxitest.parametrize(
    original_stdout=PatchedCase(patched="__stdout__", expected=False),
    original_stderr=PatchedCase(patched="__stderr__", expected=False),
    current_stdout=PatchedCase(patched="stdout", expected=True),
    current_stderr=PatchedCase(patched="stderr", expected=True),
    unrelated_stream=PatchedCase(patched="", expected=True),
)
def test_dumb_term_not_colored(patched: str, expected: bool) -> None:
    stream = StreamIsattyTrue()
    with isolated_environment() as context:
        context.setitem(os.environ, "TERM", "dumb")
        context.setattr(sys, patched, stream, raising=False)
        assert should_colorize(stream) is expected, (
            'TERM=dumb declares a terminal that cannot render escape sequences, so the '
            "standard streams must not be colorized even though isatty() is True"
        )


@oxitest.parametrize(
    original_stdout_set=EnvValueCase(patched="__stdout__", env_value="1", expected=False),
    original_stderr_set=EnvValueCase(patched="__stderr__", env_value="1", expected=False),
    current_stdout_set=EnvValueCase(patched="stdout", env_value="1", expected=False),
    current_stderr_set=EnvValueCase(patched="stderr", env_value="1", expected=False),
    # Only standard out and err should be affected.
    unrelated_stream_set=EnvValueCase(patched="", env_value="1", expected=True),
    # An empty value for NO_COLOR should not be applied:
    original_stdout_empty=EnvValueCase(patched="__stdout__", env_value="", expected=True),
    original_stderr_empty=EnvValueCase(patched="__stderr__", env_value="", expected=True),
    current_stdout_empty=EnvValueCase(patched="stdout", env_value="", expected=True),
    current_stderr_empty=EnvValueCase(patched="stderr", env_value="", expected=True),
    unrelated_stream_empty=EnvValueCase(patched="", env_value="", expected=True),
)
def test_honor_no_color_standard(patched: str, env_value: str, expected: bool) -> None:
    stream = StreamIsattyTrue()
    with isolated_environment() as context:
        context.setitem(os.environ, "NO_COLOR", env_value)
        context.setattr(sys, patched, stream, raising=False)
        assert should_colorize(stream) is expected, (
            "the NO_COLOR standard applies to the standard streams and only when the "
            "variable is non-empty"
        )


@oxitest.parametrize(
    original_stdout_set=EnvValueCase(patched="__stdout__", env_value="1", expected=True),
    original_stderr_set=EnvValueCase(patched="__stderr__", env_value="1", expected=True),
    current_stdout_set=EnvValueCase(patched="stdout", env_value="1", expected=True),
    current_stderr_set=EnvValueCase(patched="stderr", env_value="1", expected=True),
    # Only standard out and err should be affected.
    unrelated_stream_set=EnvValueCase(patched="", env_value="1", expected=False),
    # An empty value for FORCE_COLOR should not be applied:
    original_stdout_empty=EnvValueCase(patched="__stdout__", env_value="", expected=False),
    original_stderr_empty=EnvValueCase(patched="__stderr__", env_value="", expected=False),
    current_stdout_empty=EnvValueCase(patched="stdout", env_value="", expected=False),
    current_stderr_empty=EnvValueCase(patched="stderr", env_value="", expected=False),
    unrelated_stream_empty=EnvValueCase(patched="", env_value="", expected=False),
)
def test_honor_force_color_standard(patched: str, env_value: str, expected: bool) -> None:
    stream = StreamIsattyFalse()
    with isolated_environment() as context:
        context.setitem(os.environ, "FORCE_COLOR", env_value)
        context.setattr(sys, patched, stream, raising=False)
        assert should_colorize(stream) is expected, (
            "the FORCE_COLOR convention applies to the standard streams and only when the "
            "variable is non-empty"
        )


def test_no_color_takes_precedence_over_force_color() -> None:
    stream_tty = StreamIsattyTrue()
    stream_not_tty = StreamIsattyFalse()

    with isolated_environment() as context:
        context.setitem(os.environ, "NO_COLOR", "1")
        context.setitem(os.environ, "FORCE_COLOR", "1")

        why = (
            "when both variables are set the safe choice is no color, since emitting escape "
            "sequences somewhere they cannot be rendered corrupts the output"
        )

        context.setattr(sys, "__stderr__", stream_tty, raising=False)
        assert not should_colorize(stream_tty), why

        context.setattr(sys, "__stderr__", stream_not_tty, raising=False)
        assert not should_colorize(stream_not_tty), why


@oxitest.mark.skip(when=os.name == "nt", reason="The fix will be applied on Windows")
@oxitest.parametrize(
    original_stdout=PatchedCase(patched="__stdout__", expected=False),
    original_stderr=PatchedCase(patched="__stderr__", expected=False),
    current_stdout=PatchedCase(patched="stdout", expected=False),
    current_stderr=PatchedCase(patched="stderr", expected=False),
    unrelated_stream=PatchedCase(patched="", expected=False),
)
def test_mintty_not_fixed_linux(patched: str, expected: bool) -> None:
    stream = StreamIsattyFalse()
    with isolated_environment() as context:
        context.setitem(os.environ, "TERM", "xterm")
        context.setattr(sys, patched, stream, raising=False)
        assert should_colorize(stream) is expected, (
            "the mintty workaround is Windows-specific: on Linux a non-tty is a non-tty, "
            "whatever TERM says"
        )


@oxitest.parametrize(
    stdout_is_outstream=JupyterCase(patched="stdout", out_class=StreamIsattyFalse, expected=True),
    stderr_is_outstream=JupyterCase(patched="stderr", out_class=StreamIsattyFalse, expected=True),
    original_stdout=JupyterCase(
        patched="__stdout__", out_class=StreamIsattyFalse, expected=False
    ),
    original_stderr=JupyterCase(
        patched="__stderr__", out_class=StreamIsattyFalse, expected=False
    ),
    stdout_not_outstream=JupyterCase(
        patched="stdout", out_class=StreamIsattyTrue, expected=False
    ),
    stderr_not_outstream=JupyterCase(
        patched="stderr", out_class=StreamIsattyTrue, expected=False
    ),
    unrelated_stream=JupyterCase(patched="", out_class=StreamIsattyFalse, expected=False),
)
def test_jupyter_fixed(patched: str, out_class: Type[StubStream], expected: bool) -> None:
    stream = StreamIsattyFalse()

    class Shell:
        pass

    ipython = MagicMock()
    ipykernel = MagicMock()
    instance = MagicMock()
    instance.__class__ = Shell
    ipython.get_ipython.return_value = instance
    ipykernel.zmqshell.ZMQInteractiveShell = Shell
    ipykernel.iostream.OutStream = out_class

    with isolated_environment() as context:
        context.setattr(sys, patched, stream, raising=False)
        context.setattr(builtins, "__IPYTHON__", True, raising=False)
        context.setitem(sys.modules, "IPython", ipython)
        context.setitem(sys.modules, "ipykernel", ipykernel)
        assert should_colorize(stream) is expected, (
            "a notebook renders ANSI through ipykernel's OutStream, so exactly the current "
            "sys.stdout/sys.stderr of that type must be colorized — nothing else"
        )


def test_jupyter_missing_lib() -> None:
    # Missing ipykernal so jupyter block will err, should handle gracefully
    stream = StreamIsattyFalse()
    with isolated_environment() as context:
        context.setattr(sys, "stdout", stream, raising=False)
        context.setattr(builtins, "__IPYTHON__", True, raising=False)
        assert should_colorize(stream) is False, (
            "IPython without ipykernel is a plain terminal session, so the missing import "
            "must be handled rather than propagated"
        )


@oxitest.mark.skip(when=os.name == "nt", reason="Colorama is required on Windows")
@oxitest.parametrize(**STANDARD_STREAM_CASES)
def test_dont_wrap_on_linux(patched: str) -> None:
    stream = StreamIsattyTrue()
    with isolated_environment() as context, patched_colorama(context) as colorama:
        context.setattr(sys, patched, stream, raising=False)
        assert not should_wrap(stream), "colorama is only needed on Windows"
        assert not colorama.win32.winapi_test.called, (
            "the Windows API must not even be consulted on other platforms"
        )


@oxitest.mark.skip(when=os.name != "nt", reason=ONLY_WINDOWS_NEEDS_COLORAMA)
@oxitest.parametrize(
    current_stdout=StandardStreamCase(patched="stdout"),
    current_stderr=StandardStreamCase(patched="stderr"),
    unrelated_stream=StandardStreamCase(patched=""),
)
def test_dont_wrap_if_not_original_stdout_or_stderr(patched: str) -> None:
    stream = StreamIsattyTrue()
    with isolated_environment() as context, patched_colorama(context) as colorama:
        context.setattr(sys, patched, stream, raising=False)
        assert not should_wrap(stream), (
            "only the console attached to the process needs wrapping; a redirected stream "
            "is not a Windows console"
        )
        assert not colorama.win32.winapi_test.called, (
            "the Windows API must not be consulted for a stream that cannot be a console"
        )


@oxitest.mark.skip(when=os.name != "nt", reason=ONLY_WINDOWS_NEEDS_COLORAMA)
@oxitest.parametrize(**STANDARD_STREAM_CASES)
def test_dont_wrap_if_terminal_has_vt_support(patched: str) -> None:
    stream = StreamIsattyTrue()
    with isolated_environment() as context, patched_colorama(context) as colorama:
        context.setattr(sys, patched, stream, raising=False)
        colorama.win32.winapi_test.return_value = True
        colorama.winterm.enable_vt_processing.return_value = True
        assert not should_wrap(stream), (
            "a console with VT processing enabled renders ANSI itself, so wrapping would "
            "only add overhead"
        )
        assert colorama.winterm.enable_vt_processing.called, (
            "VT support must actually be probed rather than assumed"
        )


@oxitest.mark.skip(when=os.name != "nt", reason=ONLY_WINDOWS_NEEDS_COLORAMA)
@oxitest.parametrize(**STANDARD_STREAM_CASES)
def test_dont_wrap_if_winapi_false(patched: str) -> None:
    stream = StreamIsattyTrue()
    with isolated_environment() as context, patched_colorama(context) as colorama:
        context.setattr(sys, patched, stream, raising=False)
        colorama.win32.winapi_test.return_value = False
        colorama.winterm.enable_vt_processing.return_value = False
        assert not should_wrap(stream), (
            "without the Windows console API there is nothing for colorama to wrap"
        )
        assert colorama.win32.winapi_test.called, (
            "availability of the console API must actually be probed rather than assumed"
        )


@oxitest.mark.skip(when=os.name != "nt", reason=ONLY_WINDOWS_NEEDS_COLORAMA)
@oxitest.parametrize(**STANDARD_STREAM_CASES)
def test_wrap_if_winapi_true_and_no_vt_support(patched: str) -> None:
    stream = StreamIsattyTrue()
    with isolated_environment() as context, patched_colorama(context) as colorama:
        context.setattr(sys, patched, stream, raising=False)
        colorama.win32.winapi_test.return_value = True
        colorama.winterm.enable_vt_processing.return_value = False
        assert should_wrap(stream), (
            "a legacy console needs colorama to translate ANSI into console API calls"
        )
        assert colorama.winterm.enable_vt_processing.called, "VT support must be probed"
        assert colorama.win32.winapi_test.called, "the console API must be probed"


@oxitest.mark.skip(when=os.name != "nt", reason=ONLY_WINDOWS_NEEDS_COLORAMA)
@oxitest.parametrize(**STANDARD_STREAM_CASES)
def test_wrap_if_winapi_true_and_vt_check_fails(patched: str) -> None:
    stream = StreamIsattyTrue()
    with isolated_environment() as context, patched_colorama(context) as colorama:
        context.setattr(sys, patched, stream, raising=False)
        colorama.win32.winapi_test.return_value = True
        colorama.winterm.enable_vt_processing.side_effect = RuntimeError
        assert should_wrap(stream), (
            "a failing VT probe must be treated as no VT support, so colors still work "
            "instead of the error escaping"
        )
        assert colorama.winterm.enable_vt_processing.called, "VT support must be probed"
        assert colorama.win32.winapi_test.called, "the console API must be probed"


@oxitest.mark.skip(when=os.name != "nt", reason=ONLY_WINDOWS_NEEDS_COLORAMA)
@oxitest.parametrize(**STANDARD_STREAM_CASES)
def test_wrap_if_winapi_true_and_stream_has_no_fileno(patched: str) -> None:
    stream = StreamFilenoException()
    with isolated_environment() as context, patched_colorama(context) as colorama:
        context.setattr(sys, patched, stream, raising=False)
        colorama.win32.winapi_test.return_value = True
        assert should_wrap(stream), (
            "without a file descriptor VT support cannot be probed, so wrapping is the safe "
            "choice"
        )
        assert not colorama.winterm.enable_vt_processing.called, (
            "the VT probe needs a file descriptor, so it must be skipped rather than called "
            "with a broken one"
        )
        assert colorama.win32.winapi_test.called, "the console API must still be probed"


@oxitest.mark.skip(when=os.name != "nt", reason=ONLY_WINDOWS_NEEDS_COLORAMA)
@oxitest.parametrize(**STANDARD_STREAM_CASES)
def test_wrap_if_winapi_true_and_old_colorama_version(patched: str) -> None:
    stream = StreamIsattyTrue()
    with isolated_environment() as context, patched_colorama(context) as colorama:
        context.setattr(sys, patched, stream, raising=False)
        colorama.win32.winapi_test.return_value = True
        del colorama.winterm.enable_vt_processing
        assert should_wrap(stream), (
            "an older colorama has no VT probe at all, so the missing attribute must be "
            "handled by falling back to wrapping"
        )
        assert colorama.win32.winapi_test.called, "the console API must still be probed"
