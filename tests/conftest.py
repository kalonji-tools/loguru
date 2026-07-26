import builtins
import contextlib
import datetime
import logging
import multiprocessing
import os
import sys
import threading
import time
import traceback
import warnings
from typing import Any, Callable, Iterator, List, NamedTuple, Type

import freezegun
from oxitest import Fixtures, Helpers, Yields

import loguru

fx = Fixtures()
common = Helpers()


# ── Scoped patching ─────────────────────────────────────────────────────────
# oxitest's built-in "Patcher" reverts at the end of a test, but several helpers
# below need patches scoped to an inner "with" block instead. This is the
# equivalent of pytest's "monkeypatch.context()".


class _PatchContext:
    def __init__(self) -> None:
        self._undos: List[Callable[[], None]] = []

    def setattr(self, obj: Any, name: str, value: Any, *, raising: bool = True) -> None:
        if hasattr(obj, name):
            old = getattr(obj, name)
            self._undos.append(lambda: setattr(obj, name, old))
        elif raising:
            raise AttributeError("%r has no attribute %r" % (obj, name))
        else:
            self._undos.append(lambda: delattr(obj, name))
        setattr(obj, name, value)

    def delattr(self, obj: Any, name: str, *, raising: bool = True) -> None:
        if not hasattr(obj, name):
            if raising:
                raise AttributeError("%r has no attribute %r" % (obj, name))
            return
        old = getattr(obj, name)
        self._undos.append(lambda: setattr(obj, name, old))
        delattr(obj, name)

    def setenv(self, name: str, value: str) -> None:
        self.setitem(os.environ, name, value)

    def delenv(self, name: str) -> None:
        if name in os.environ:
            self.delitem(os.environ, name)

    def delitem(self, mapping: Any, key: Any) -> None:
        old = mapping[key]
        self._undos.append(lambda: mapping.__setitem__(key, old))
        del mapping[key]

    def setitem(self, mapping: Any, key: Any, value: Any) -> None:
        if key in mapping:
            old = mapping[key]
            self._undos.append(lambda: mapping.__setitem__(key, old))
        else:
            self._undos.append(lambda: mapping.pop(key, None))
        mapping[key] = value

    def undo(self) -> None:
        for undo in reversed(self._undos):
            undo()
        self._undos.clear()


@common.helper
@contextlib.contextmanager
def patch_context() -> Iterator[_PatchContext]:
    context = _PatchContext()
    try:
        yield context
    finally:
        context.undo()


# ── Test doubles ────────────────────────────────────────────────────────────


class Writer:
    """Callable sink recording every message written to it."""

    def __init__(self) -> None:
        self.written: List[Any] = []

    def __call__(self, message: Any) -> None:
        self.written.append(message)

    def read(self) -> str:
        return "".join(self.written)

    def clear(self) -> None:
        self.written.clear()


class SinkWithLogger:
    def __init__(self, logger: Any) -> None:
        self.logger = logger
        self.out = ""

    def write(self, message: str) -> None:
        self.logger.info(message)
        self.out += message


class FreezeTime:
    """Freezegun wrapper also faking the local timezone name and UTC offset."""

    def __init__(self) -> None:
        self._ctimes: dict = {}
        self._builtins_open = builtins.open
        self._fakes: dict = {
            "zone": "UTC",
            "offset": 0,
            "include_tm_zone": True,
            "tm_gmtoff_override": None,
        }

    def _fake_localtime(self, t: Any = None) -> Any:
        struct_time_attributes = [
            ("tm_year", int),
            ("tm_mon", int),
            ("tm_mday", int),
            ("tm_hour", int),
            ("tm_min", int),
            ("tm_sec", int),
            ("tm_wday", int),
            ("tm_yday", int),
            ("tm_isdst", int),
            ("tm_zone", str),
            ("tm_gmtoff", int),
        ]

        if self._fakes["include_tm_zone"]:
            struct_time = time.struct_time
        else:
            struct_time_attributes = struct_time_attributes[:-2]
            struct_time = NamedTuple("struct_time", struct_time_attributes)._make

        struct = self._freezegun_localtime(t)
        override = {"tm_zone": self._fakes["zone"], "tm_gmtoff": self._fakes["offset"]}
        attributes = []

        if self._fakes["tm_gmtoff_override"] is not None:
            override["tm_gmtoff"] = self._fakes["tm_gmtoff_override"]

        for attribute, _ in struct_time_attributes:
            if attribute in override:
                value = override[attribute]
            else:
                value = getattr(struct, attribute)
            attributes.append(value)

        return struct_time(attributes)

    def _patched_open(self, filepath: Any, *args: Any, **kwargs: Any) -> Any:
        if not os.path.exists(filepath):
            tz = datetime.timezone(
                datetime.timedelta(seconds=self._fakes["offset"]), name=self._fakes["zone"]
            )
            self._ctimes[filepath] = datetime.datetime.now().replace(tzinfo=tz).timestamp()
        return self._builtins_open(filepath, *args, **kwargs)

    @contextlib.contextmanager
    def __call__(
        self,
        date: Any,
        timezone: Any = ("UTC", 0),
        *,
        include_tm_zone: bool = True,
        tm_gmtoff_override: Any = None,
    ) -> Iterator[Any]:
        # Freezegun does not behave very well with UTC and timezones, see spulec/freezegun#348.
        # In particular, "now(tz=utc)" does not return the converted datetime.
        # For this reason, we re-implement date parsing here to properly handle aware date using
        # the optional "tz_offset" argument.
        if isinstance(date, str):
            for accepted_format in ["%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"]:
                try:
                    date = datetime.datetime.strptime(date, accepted_format)
                    break
                except ValueError:
                    pass

        if not isinstance(date, datetime.datetime) or date.tzinfo is not None:
            raise ValueError("Unsupported date provided")

        zone, offset = timezone
        tz_offset = datetime.timedelta(seconds=offset)
        tzinfo = datetime.timezone(tz_offset, zone)
        date = date.replace(tzinfo=tzinfo)

        self._builtins_open = builtins.open
        self._freezegun_localtime = freezegun.api.fake_localtime

        with patch_context() as context:
            context.setitem(self._fakes, "zone", zone)
            context.setitem(self._fakes, "offset", offset)
            context.setitem(self._fakes, "include_tm_zone", include_tm_zone)
            context.setitem(self._fakes, "tm_gmtoff_override", tm_gmtoff_override)

            context.setattr(loguru._file_sink, "get_ctime", self._ctimes.__getitem__)
            context.setattr(loguru._file_sink, "set_ctime", self._ctimes.__setitem__)
            context.setattr(builtins, "open", self._patched_open)

            # Freezegun does not permit to override timezone name.
            context.setattr(freezegun.api, "fake_localtime", self._fake_localtime)

            with freezegun.freeze_time(date, tz_offset=tz_offset) as frozen:
                yield frozen


# ── Helpers ─────────────────────────────────────────────────────────────────


@common.helper
def check_dir(dir: Any, *, files: Any = None, size: Any = None) -> None:
    actual_files = set(dir.iterdir())
    seen = set()
    if size is not None:
        assert len(actual_files) == size, (
            "the sink must leave exactly this many files behind, otherwise rotation or "
            "retention created or deleted more files than it was configured to"
        )
    if files is not None:
        assert len(actual_files) == len(files), (
            "the sink must leave exactly this many files behind, otherwise rotation or "
            "retention created or deleted more files than it was configured to"
        )
        for name, content in files:
            filepath = dir / name
            assert filepath in actual_files, (
                "the sink must have created this file, otherwise its naming or rotation "
                "scheme resolved to an unexpected path"
            )
            assert filepath not in seen, (
                "the same file is expected twice, so the expectation itself is malformed"
            )
            if content is not None:
                assert filepath.read_text() == content, (
                    "the file must hold exactly these messages, otherwise records were lost, "
                    "duplicated, or written to the wrong file during rotation"
                )
            seen.add(filepath)


@common.helper
@contextlib.contextmanager
def default_threading_excepthook() -> Iterator[None]:
    if not hasattr(threading, "excepthook"):
        yield
        return

    # Test runners install their own thread excepthook to surface unhandled thread
    # exceptions. Restore a plain one for tests asserting on what a failing thread prints.

    def excepthook(args: Any) -> None:
        print("Exception in thread:", file=sys.stderr, flush=True)
        traceback.print_exception(
            args.exc_type, args.exc_value, args.exc_traceback, file=sys.stderr
        )

    old_excepthook = threading.excepthook
    threading.excepthook = excepthook
    yield
    threading.excepthook = old_excepthook


@common.helper
@contextlib.contextmanager
def make_logging_logger(
    name: Any, handler: Any, fmt: str = "%(message)s", level: str = "DEBUG"
) -> Iterator[logging.Logger]:
    original_logging_level = logging.getLogger().getEffectiveLevel()
    logging_logger = logging.getLogger(name)
    logging_logger.setLevel(level)
    formatter = logging.Formatter(fmt)

    handler.setLevel(level)
    handler.setFormatter(formatter)
    logging_logger.addHandler(handler)

    try:
        yield logging_logger
    finally:
        logging_logger.setLevel(original_logging_level)
        logging_logger.removeHandler(handler)


@common.helper
@contextlib.contextmanager
def simulate_f_globals_name_absent() -> Iterator[None]:
    """Simulate execution in Dask environment, where "__name__" is not available in globals."""
    getframe_ = loguru._get_frame.load_get_frame_function()

    def patched_getframe(*args: Any, **kwargs: Any) -> Any:
        frame = getframe_(*args, **kwargs)
        frame.f_globals.pop("__name__", None)
        return frame

    with patch_context() as context:
        context.setattr(loguru._logger, "get_frame", patched_getframe)
        yield


@common.helper
@contextlib.contextmanager
def simulate_no_frame_available() -> Iterator[None]:
    """Simulate execution in Cython, where there is no stack frame to retrieve."""

    def patched_getframe(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("Call stack is not deep enough (dummy)")

    with patch_context() as context:
        context.setattr(loguru._logger, "get_frame", patched_getframe)
        yield


@common.helper
@contextlib.contextmanager
def simulate_missing_frame_lineno() -> Iterator[None]:
    """Simulate corner case where the "f_lineno" value is not available in stack frames."""
    getframe_ = loguru._get_frame.load_get_frame_function()

    class MockedFrame:
        def __init__(self, frame: Any) -> None:
            self._frame = frame

        def __getattribute__(self, name: str) -> Any:
            if name == "f_lineno":
                return None
            frame = object.__getattribute__(self, "_frame")
            return getattr(frame, name)

    def patched_getframe(*args: Any, **kwargs: Any) -> Any:
        frame = getframe_(*args, **kwargs)
        return MockedFrame(frame)

    with patch_context() as context:
        context.setattr(loguru._logger, "get_frame", patched_getframe)
        yield


# ── Fixtures ────────────────────────────────────────────────────────────────


@fx.fixture(autouse=True, shared=True)
def check_env_variables() -> None:
    for var in os.environ:
        if var.startswith("LOGURU_"):
            warnings.warn(
                "A Loguru environment variable has been detected "
                "and may interfere with the tests: '%s'" % var,
                RuntimeWarning,
                stacklevel=1,
            )


@fx.fixture(autouse=True)
def strict_warnings() -> Yields[None]:
    """Turn warnings into errors, replacing the former "filterwarnings" pytest config."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        # Mixing threads and "fork()" is deprecated, but we need to test it anyway.
        warnings.filterwarnings(
            "ignore",
            message=r".*use of fork\(\) may lead to deadlocks in the child.*",
            category=DeprecationWarning,
        )
        # Using "set_event_loop()" is deprecated, but no alternative is provided.
        warnings.filterwarnings(
            "ignore",
            message=r".*'asyncio.set_event_loop' is deprecated.*",
            category=DeprecationWarning,
        )
        yield


@fx.fixture(autouse=True)
def reset_logger() -> Yields[None]:
    def reset() -> None:
        loguru.logger.remove()
        loguru.logger.__init__(
            loguru._logger.Core(), None, 0, False, False, False, False, True, [], {}
        )
        loguru._logger.context.set({})

    reset()
    yield
    reset()


@fx.fixture(autouse=True)
def reset_multiprocessing_start_method() -> Yields[None]:
    multiprocessing.set_start_method(None, force=True)
    yield
    multiprocessing.set_start_method(None, force=True)


@fx.fixture
def writer() -> Writer:
    return Writer()


@fx.fixture
def sink_with_logger() -> Type[SinkWithLogger]:
    return SinkWithLogger


@fx.fixture
def freeze_time() -> FreezeTime:
    return FreezeTime()
