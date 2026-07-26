import asyncio
import site
import sys
import sysconfig
import threading
import types
from dataclasses import dataclass
from typing import Any

import oxitest
from conftest import Writer
from oxitest import Fixture, StdCapture, TempDir, helpers

from loguru import logger

ENDS_WITH_ZERO_DIVISION = (
    "the traceback must be rendered down to its last line; a truncated or missing one means "
    "the diagnose pass gave up on this environment instead of degrading gracefully"
)


@dataclass(frozen=True)
class DiagnoseCase:
    diagnose: bool


@dataclass(frozen=True)
class EncodingCase:
    encoding: Any


@dataclass(frozen=True)
class ExceptionCase:
    exception: Any


@dataclass
class ExcludeCase:
    exception: Any
    exclude: Any


DIAGNOSE_CASES = {
    "without_diagnose": DiagnoseCase(diagnose=False),
    "with_diagnose": DiagnoseCase(diagnose=True),
}

EXCEPTION_LAYER = {
    "base_exception": oxitest.partial(ExcludeCase, exception=BaseException),
    "specific_exception": oxitest.partial(ExcludeCase, exception=ZeroDivisionError),
}


@oxitest.parametrize(**DIAGNOSE_CASES)
def test_caret_not_masked(writer: Fixture[Writer], diagnose: bool) -> None:
    logger.add(writer, backtrace=True, diagnose=diagnose, colorize=False, format="")

    @logger.catch
    def f(n):
        1 / n
        f(n - 1)

    f(30)

    assert sum(line.startswith("> ") for line in writer.read().splitlines()) == 1, (
        "exactly one frame may be marked as the culprit, otherwise a deep recursion would "
        "highlight every frame and the marker would carry no information"
    )


@oxitest.parametrize(**DIAGNOSE_CASES)
def test_no_caret_if_no_backtrace(writer: Fixture[Writer], diagnose: bool) -> None:
    logger.add(writer, backtrace=False, diagnose=diagnose, colorize=False, format="")

    @logger.catch
    def f(n):
        1 / n
        f(n - 1)

    f(30)

    assert sum(line.startswith("> ") for line in writer.read().splitlines()) == 0, (
        "the culprit marker belongs to the extended backtrace, so backtrace=False must "
        "suppress it regardless of diagnose"
    )


@oxitest.parametrize(
    ascii_encoding=EncodingCase(encoding="ascii"),
    utf8=EncodingCase(encoding="UTF8"),
    none=EncodingCase(encoding=None),
    unknown=EncodingCase(encoding="unknown-encoding"),
    empty=EncodingCase(encoding=""),
    not_a_string=EncodingCase(encoding=object()),
)
def test_sink_encoding(writer: Fixture[Writer], encoding: Any) -> None:
    class Writer:
        def __init__(self, encoding):
            self.encoding = encoding
            self.output = ""

        def write(self, message):
            self.output += message

    writer = Writer(encoding)
    logger.add(writer, backtrace=True, diagnose=True, colorize=False, format="", catch=False)

    def foo(a, b):
        a / b

    def bar(c):
        foo(c, 0)

    try:
        bar(4)
    except ZeroDivisionError:
        logger.exception("")

    assert writer.output.endswith("ZeroDivisionError: division by zero\n"), (
        "the sink's declared encoding decides which decorations are safe to emit, so an "
        "unusable value must fall back to plain ASCII rather than raise"
    )


def test_file_sink_ascii_encoding(tmp: TempDir) -> None:
    file = tmp.path / "test.log"
    logger.add(file, format="", encoding="ascii", errors="backslashreplace", catch=False)
    a = "天"

    try:
        "天" * a
    except Exception:
        logger.exception("")

    logger.remove()
    result = file.read_text("ascii")
    assert result.count('"\\u5929" * a') == 1, (
        "the offending source line must be written once, escaped to fit the sink's encoding"
    )
    assert result.count("-> '\\u5929'") == 1, (
        "the ASCII fallback must use '->' instead of the box-drawing character, since the "
        "latter cannot be encoded"
    )


def test_file_sink_utf8_encoding(tmp: TempDir) -> None:
    file = tmp.path / "test.log"
    logger.add(file, format="", encoding="utf8", errors="strict", catch=False)
    a = "天"

    try:
        "天" * a
    except Exception:
        logger.exception("")

    logger.remove()
    result = file.read_text("utf8")
    assert result.count('"天" * a') == 1, (
        "with utf8 the source line must be written verbatim, not escaped"
    )
    assert result.count("└ '天'") == 1, (
        "with utf8 the box-drawing decoration must be used, since the sink can encode it"
    )


def test_has_sys_real_prefix(writer: Fixture[Writer]) -> None:
    with helpers.common.patch_context() as context:
        context.setattr(sys, "real_prefix", "/foo/bar/baz", raising=False)
        logger.add(writer, backtrace=False, diagnose=True, colorize=False, format="")

        try:
            1 / 0  # noqa: B018
        except ZeroDivisionError:
            logger.exception("")

        assert writer.read().endswith("ZeroDivisionError: division by zero\n"), (
            "sys.real_prefix marks an old virtualenv; loguru reads it to tell library frames "
            "from user frames and must cope with it being present"
        )


def test_no_sys_real_prefix(writer: Fixture[Writer]) -> None:
    with helpers.common.patch_context() as context:
        context.delattr(sys, "real_prefix", raising=False)
        logger.add(writer, backtrace=False, diagnose=True, colorize=False, format="")

        try:
            1 / 0  # noqa: B018
        except ZeroDivisionError:
            logger.exception("")

        assert writer.read().endswith("ZeroDivisionError: division by zero\n"), (
            "sys.real_prefix is absent outside an old virtualenv, so its absence must not "
            "raise AttributeError"
        )


def test_has_site_getsitepackages(writer: Fixture[Writer]) -> None:
    with helpers.common.patch_context() as context:
        context.setattr(site, "getsitepackages", lambda: ["foo", "bar", "baz"], raising=False)
        logger.add(writer, backtrace=False, diagnose=True, colorize=False, format="")

        try:
            1 / 0  # noqa: B018
        except ZeroDivisionError:
            logger.exception("")

        assert writer.read().endswith("ZeroDivisionError: division by zero\n"), (
            "site.getsitepackages() is one of the sources loguru uses to locate library "
            "frames, so it must be usable when present"
        )


def test_no_site_getsitepackages(writer: Fixture[Writer]) -> None:
    with helpers.common.patch_context() as context:
        context.delattr(site, "getsitepackages", raising=False)
        logger.add(writer, backtrace=False, diagnose=True, colorize=False, format="")

        try:
            1 / 0  # noqa: B018
        except ZeroDivisionError:
            logger.exception("")

        assert writer.read().endswith("ZeroDivisionError: division by zero\n"), (
            "site.getsitepackages() is missing in some virtualenvs, so its absence must not "
            "raise AttributeError"
        )


def test_user_site_is_path(writer: Fixture[Writer]) -> None:
    with helpers.common.patch_context() as context:
        context.setattr(site, "USER_SITE", "/foo/bar/baz")
        logger.add(writer, backtrace=False, diagnose=True, colorize=False, format="")

        try:
            1 / 0  # noqa: B018
        except ZeroDivisionError:
            logger.exception("")

        assert writer.read().endswith("ZeroDivisionError: division by zero\n"), (
            "site.USER_SITE is one of the sources loguru uses to locate library frames, so "
            "it must be usable when set"
        )


def test_user_site_is_none(writer: Fixture[Writer]) -> None:
    with helpers.common.patch_context() as context:
        context.setattr(site, "USER_SITE", None)
        logger.add(writer, backtrace=False, diagnose=True, colorize=False, format="")

        try:
            1 / 0  # noqa: B018
        except ZeroDivisionError:
            logger.exception("")

        assert writer.read().endswith("ZeroDivisionError: division by zero\n"), (
            "site.USER_SITE is None when user site-packages are disabled, so that value must "
            "not be joined into a path"
        )


def test_sysconfig_get_path_return_path(writer: Fixture[Writer]) -> None:
    with helpers.common.patch_context() as context:
        context.setattr(sysconfig, "get_path", lambda *a, **k: "/foo/bar/baz")
        logger.add(writer, backtrace=False, diagnose=True, colorize=False, format="")

        try:
            1 / 0  # noqa: B018
        except ZeroDivisionError:
            logger.exception("")

        assert writer.read().endswith("ZeroDivisionError: division by zero\n"), (
            "sysconfig.get_path() is one of the sources loguru uses to locate library "
            "frames, so it must be usable when it returns a path"
        )


def test_sysconfig_get_path_return_none(writer: Fixture[Writer]) -> None:
    with helpers.common.patch_context() as context:
        context.setattr(sysconfig, "get_path", lambda *a, **k: None)
        logger.add(writer, backtrace=False, diagnose=True, colorize=False, format="")

        try:
            1 / 0  # noqa: B018
        except ZeroDivisionError:
            logger.exception("")

        assert writer.read().endswith("ZeroDivisionError: division by zero\n"), (
            "sysconfig.get_path() returns None on some installations, so that value must not "
            "be joined into a path"
        )


def test_no_exception(writer: Fixture[Writer]) -> None:
    logger.add(writer, backtrace=False, diagnose=False, colorize=False, format="{message}")

    logger.exception("No Error.")

    assert writer.read() == "No Error.\nNoneType: None\n", (
        "calling exception() with nothing in flight must render the empty exception rather "
        "than raise, so a misplaced call cannot break the application"
    )


def test_exception_is_none() -> None:
    err = object()

    def writer(msg):
        nonlocal err
        err = msg.record["exception"]

    logger.add(writer)

    logger.error("No exception")

    assert err is None, (
        "a record with no exception must carry None, so sinks can test for it directly"
    )


def test_exception_is_tuple() -> None:
    exception = None

    def writer(msg):
        nonlocal exception
        exception = msg.record["exception"]

    logger.add(writer, catch=False)

    try:
        1 / 0  # noqa: B018
    except ZeroDivisionError:
        logger.exception("Exception")
        reference = sys.exc_info()

    t_1, v_1, tb_1 = exception
    t_2, v_2, tb_2 = (x for x in exception)
    t_3, v_3, tb_3 = exception[0], exception[1], exception[2]
    t_4, v_4, tb_4 = exception.type, exception.value, exception.traceback

    why = (
        "the exception field must stay interchangeable with sys.exc_info() while also "
        "offering named attributes, so existing code keeps working either way"
    )
    assert isinstance(exception, tuple), why
    assert len(exception) == 3, why
    assert exception == reference, why
    assert reference == exception, why
    assert not (exception != reference), why
    assert not (reference != exception), why
    assert all(t is ZeroDivisionError for t in (t_1, t_2, t_3, t_4)), why
    assert all(isinstance(v, ZeroDivisionError) for v in (v_1, v_2, v_3, v_4)), why
    assert all(isinstance(tb, types.TracebackType) for tb in (tb_1, tb_2, tb_3, tb_4)), why


@oxitest.parametrize(
    exact_type=ExceptionCase(exception=ZeroDivisionError),
    base_type=ExceptionCase(exception=ArithmeticError),
    tuple_of_types=ExceptionCase(exception=(ValueError, ZeroDivisionError)),
)
def test_exception_not_raising(writer: Fixture[Writer], exception: Any) -> None:
    logger.add(writer)

    @logger.catch(exception)
    def a():
        1 / 0  # noqa: B018

    a()
    assert writer.read().endswith("ZeroDivisionError: division by zero\n"), (
        "catch() must swallow anything matching the declared type, including via a base "
        "class or a tuple member"
    )


@oxitest.parametrize(
    unrelated_type=ExceptionCase(exception=ValueError),
    unrelated_tuple=ExceptionCase(exception=((SyntaxError, TypeError))),
)
def test_exception_raising(writer: Fixture[Writer], exception: Any) -> None:
    logger.add(writer)

    @logger.catch(exception=exception)
    def a():
        1 / 0  # noqa: B018

    with oxitest.raises(ZeroDivisionError):
        a()

    assert writer.read() == "", (
        "an exception outside the declared type must propagate untouched and must not be "
        "logged either"
    )


@oxitest.parametrize(**EXCEPTION_LAYER)
@oxitest.parametrize(
    exact_type=oxitest.partial(ExcludeCase, exclude=ZeroDivisionError),
    base_type=oxitest.partial(ExcludeCase, exclude=ArithmeticError),
    tuple_of_types=oxitest.partial(ExcludeCase, exclude=(ValueError, ZeroDivisionError)),
)
def test_exclude_exception_raising(
    writer: Fixture[Writer], exclude: Any, exception: Any
) -> None:
    logger.add(writer)

    @logger.catch(exception, exclude=exclude)
    def a():
        1 / 0  # noqa: B018

    with oxitest.raises(ZeroDivisionError):
        a()

    assert writer.read() == "", (
        "exclude must win over the caught type, so an excluded error propagates untouched "
        "and is not logged either"
    )


@oxitest.parametrize(**EXCEPTION_LAYER)
@oxitest.parametrize(
    unrelated_type=oxitest.partial(ExcludeCase, exclude=ValueError),
    unrelated_tuple=oxitest.partial(ExcludeCase, exclude=((SyntaxError, TypeError))),
)
def test_exclude_exception_not_raising(
    writer: Fixture[Writer], exclude: Any, exception: Any
) -> None:
    logger.add(writer)

    @logger.catch(exception, exclude=exclude)
    def a():
        1 / 0  # noqa: B018

    a()
    assert writer.read().endswith("ZeroDivisionError: division by zero\n"), (
        "an exclude that does not match must leave the caught type in effect"
    )


def test_reraise(writer: Fixture[Writer]) -> None:
    logger.add(writer)

    @logger.catch(reraise=True)
    def a():
        1 / 0  # noqa: B018

    with oxitest.raises(ZeroDivisionError):
        a()

    assert writer.read().endswith("ZeroDivisionError: division by zero\n"), (
        "reraise must log the error and then let it propagate, so catch() can be used purely "
        "for reporting"
    )


def test_onerror(writer: Fixture[Writer]) -> None:
    is_error_valid = False
    logger.add(writer, format="{message}")

    def onerror(error):
        nonlocal is_error_valid
        logger.info("Called after logged message")
        _, exception, _ = sys.exc_info()
        is_error_valid = (error == exception) and isinstance(error, ZeroDivisionError)

    @logger.catch(onerror=onerror)
    def a():
        1 / 0  # noqa: B018

    a()

    assert is_error_valid, (
        "the callback must receive the actual exception and run while it is still the one "
        "being handled, so sys.exc_info() agrees with the argument"
    )
    assert writer.read().endswith(
        "ZeroDivisionError: division by zero\n" "Called after logged message\n"
    ), "the callback must run after the error has been logged, not before"


def test_onerror_with_reraise(writer: Fixture[Writer]) -> None:
    called = False
    logger.add(writer, format="{message}")

    def onerror(_):
        nonlocal called
        called = True

    with oxitest.raises(ZeroDivisionError):
        with logger.catch(onerror=onerror, reraise=True):
            1 / 0  # noqa: B018

    assert called, (
        "the callback must run before the exception is re-raised, otherwise reraise would "
        "silently skip it"
    )


def test_decorate_function(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message}", diagnose=False, backtrace=False, colorize=False)

    @logger.catch
    def a(x):
        return 100 / x

    assert a(50) == 2, "the decorator must return the function's value unchanged"
    assert writer.read() == "", "nothing may be logged when the function succeeds"


def test_decorate_coroutine(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message}", diagnose=False, backtrace=False, colorize=False)

    @logger.catch
    async def foo(a, b):
        return a + b

    result = asyncio.run(foo(100, 5))

    assert result == 105, (
        "decorating a coroutine must return an awaitable yielding the original value, not "
        "wrap it into something else"
    )
    assert writer.read() == "", "nothing may be logged when the coroutine succeeds"


def test_decorate_generator(writer: Fixture[Writer]) -> None:
    @logger.catch
    def foo(x, y, z):
        yield x
        yield y
        return z

    f = foo(1, 2, 3)
    assert next(f) == 1, "the wrapper must forward yielded values unchanged"
    assert next(f) == 2, "the wrapper must forward yielded values unchanged"

    with oxitest.raises(StopIteration, match=r"3"):
        next(f)


def test_decorate_generator_with_error() -> None:
    @logger.catch
    def foo():
        yield 0
        yield 1
        raise ValueError

    assert list(foo()) == [0, 1], (
        "an error raised after the last yield must be caught and end the iteration cleanly, "
        "rather than escape to the consumer"
    )


def test_default_with_function() -> None:
    @logger.catch(default=42)
    def foo():
        1 / 0  # noqa: B018

    assert foo() == 42, (
        "the default must be returned when the call fails, which is what makes catch() "
        "usable on a function whose value the caller needs"
    )


def test_default_with_generator() -> None:
    @logger.catch(default=42)
    def foo():
        yield 1 / 0

    with oxitest.raises(StopIteration, match=r"42"):
        next(foo())


def test_default_with_coroutine() -> None:
    @logger.catch(default=42)
    async def foo():
        return 1 / 0

    assert asyncio.run(foo()) == 42, "the default must apply to a coroutine as well"


def test_async_context_manager() -> None:
    async def coro():
        async with logger.catch():
            return 1 / 0
        return 1

    assert asyncio.run(coro()) == 1, (
        "catch() must work as an async context manager, swallowing the error so execution "
        "continues after the block"
    )


def test_error_when_decorating_class_without_parentheses() -> None:
    with oxitest.raises(TypeError):

        @logger.catch
        class Foo:
            pass


def test_error_when_decorating_class_with_parentheses() -> None:
    with oxitest.raises(TypeError):

        @logger.catch()
        class Foo:
            pass


def test_unprintable_but_decorated_repr(writer: Fixture[Writer]) -> None:

    class Foo:
        @logger.catch(reraise=True)
        def __repr__(self):
            raise ValueError("Something went wrong")

    logger.add(writer, backtrace=True, diagnose=True, colorize=False, format="", catch=False)

    foo = Foo()

    with oxitest.raises(ValueError, match=r"^Something went wrong$"):
        repr(foo)

    assert writer.read().endswith("ValueError: Something went wrong\n"), (
        "diagnose calls repr() on locals, so an object whose repr() itself fails inside "
        "catch() must not send the formatter into infinite recursion"
    )


def test_unprintable_but_decorated_repr_without_reraise(writer: Fixture[Writer]) -> None:
    class Foo:
        @logger.catch(reraise=False, default="?")
        def __repr__(self):
            raise ValueError("Something went wrong")

    logger.add(writer, backtrace=True, diagnose=True, colorize=False, format="", catch=False)

    foo = Foo()

    repr(foo)

    assert writer.read().endswith("ValueError: Something went wrong\n"), (
        "the same protection must hold when the failing repr() returns a default instead of "
        "re-raising"
    )


def test_unprintable_but_decorated_multiple_sinks(cap: StdCapture) -> None:
    class Foo:
        @logger.catch(reraise=True)
        def __repr__(self):
            raise ValueError("Something went wrong")

    logger.add(sys.stderr, backtrace=True, diagnose=True, colorize=False, format="", catch=False)
    logger.add(sys.stdout, backtrace=True, diagnose=True, colorize=False, format="", catch=False)

    foo = Foo()

    with oxitest.raises(ValueError, match=r"^Something went wrong$"):
        repr(foo)

    captured = cap.readouterr()
    why = "each sink must receive the report, and the second must not re-trigger the failing repr"
    assert captured.out.endswith("ValueError: Something went wrong\n"), why
    assert captured.err.endswith("ValueError: Something went wrong\n"), why


def test_unprintable_but_decorated_repr_with_enqueue(writer: Fixture[Writer]) -> None:
    class Foo:
        @logger.catch(reraise=True)
        def __repr__(self):
            raise ValueError("Something went wrong")

    logger.add(
        writer, backtrace=True, diagnose=True, colorize=False, format="", catch=False, enqueue=True
    )

    foo = Foo()

    with oxitest.raises(ValueError, match=r"^Something went wrong$"):
        repr(foo)

    logger.complete()

    assert writer.read().endswith("ValueError: Something went wrong\n"), (
        "the same protection must hold when the record is rendered on the queue thread"
    )


def test_unprintable_but_decorated_repr_twice(writer: Fixture[Writer]) -> None:
    class Foo:
        @logger.catch(reraise=True)
        @logger.catch(reraise=True)
        def __repr__(self):
            raise ValueError("Something went wrong")

    logger.add(writer, backtrace=True, diagnose=True, colorize=False, format="", catch=False)

    foo = Foo()

    with oxitest.raises(ValueError, match=r"^Something went wrong$"):
        repr(foo)

    assert writer.read().endswith("ValueError: Something went wrong\n"), (
        "nesting two catchers must not double the recursion guard's work or defeat it"
    )


def test_unprintable_with_catch_context_manager(writer: Fixture[Writer]) -> None:
    class Foo:
        def __repr__(self):
            with logger.catch(reraise=True):
                raise ValueError("Something went wrong")

    logger.add(writer, backtrace=True, diagnose=True, colorize=False, format="", catch=False)

    foo = Foo()

    with oxitest.raises(ValueError, match=r"^Something went wrong$"):
        repr(foo)

    assert writer.read().endswith("ValueError: Something went wrong\n"), (
        "the recursion guard must cover the context-manager form as well as the decorator"
    )


def test_unprintable_with_catch_context_manager_reused(writer: Fixture[Writer]) -> None:
    def sink(_):
        raise ValueError("Sink error")

    logger.remove()
    logger.add(sink, catch=False)

    catcher = logger.catch(reraise=False)

    class Foo:
        def __repr__(self):
            with catcher:
                raise ValueError("Something went wrong")

    foo = Foo()

    with oxitest.raises(ValueError, match=r"^Sink error$"):
        repr(foo)

    logger.remove()
    logger.add(writer)

    with catcher:
        raise ValueError("Error")

    assert writer.read().endswith("ValueError: Error\n"), (
        "a catcher object must be reusable after a failed use, so its recursion guard has to "
        "be reset even when the sink itself raised"
    )


def test_unprintable_but_decorated_repr_multiple_threads(writer: Fixture[Writer]) -> None:
    wait_for_repr_block = threading.Event()
    wait_for_worker_finish = threading.Event()

    recursive = False

    class Foo:
        @logger.catch(reraise=True)
        def __repr__(self):
            nonlocal recursive
            if not recursive:
                recursive = True
            else:
                wait_for_repr_block.set()
                wait_for_worker_finish.wait()
            raise ValueError("Something went wrong")

    def worker():
        wait_for_repr_block.wait()
        with logger.catch(reraise=False):
            raise ValueError("Worker error")
        wait_for_worker_finish.set()

    logger.add(writer, backtrace=True, diagnose=True, colorize=False, format="", catch=False)

    thread = threading.Thread(target=worker)
    thread.start()

    foo = Foo()

    with oxitest.raises(ValueError, match=r"^Something went wrong$"):
        repr(foo)

    thread.join()

    assert "ValueError: Worker error\n" in writer.read(), (
        "the recursion guard must be per-thread: a thread blocked mid-repr must not stop "
        "another thread from logging its own error"
    )
    assert writer.read().endswith("ValueError: Something went wrong\n"), (
        "the blocked thread must still finish reporting once it is released"
    )
