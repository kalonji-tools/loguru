import logging
import pathlib
import sys

from oxitest import TempDir

from loguru import logger


def test_no_handler() -> None:
    assert repr(logger) == "<loguru.logger handlers=[]>", (
        "the repr is the quickest way to see how logging is configured, so a logger with no "
        "sink must say so explicitly rather than print a bare object address"
    )


def test_stderr() -> None:
    logger.add(sys.__stderr__)
    assert repr(logger) == "<loguru.logger handlers=[(id=0, level=10, sink=<stderr>)]>", (
        "the standard streams must be named rather than shown as file objects, otherwise "
        "the repr is unreadable for the most common configuration of all"
    )


def test_stdout() -> None:
    logger.add(sys.__stdout__)
    assert repr(logger) == "<loguru.logger handlers=[(id=0, level=10, sink=<stdout>)]>", (
        "the standard streams must be named rather than shown as file objects, otherwise "
        "the repr is unreadable for the most common configuration of all"
    )


def test_file_object(tmp: TempDir) -> None:
    path = str(tmp.path / "test.log")
    with open(path, "w") as file:
        logger.add(file)
        assert repr(logger) == "<loguru.logger handlers=[(id=0, level=10, sink=%s)]>" % path, (
            "an open file must be identified by its path, which is the only part a reader "
            "can act on"
        )


def test_file_str(tmp: TempDir) -> None:
    path = str(tmp.path / "test.log")
    logger.add(path)
    assert repr(logger) == "<loguru.logger handlers=[(id=0, level=10, sink='%s')]>" % path, (
        "a sink given as a path string must be shown quoted, distinguishing it from a file "
        "object opened by the caller"
    )


def test_file_pathlib(tmp: TempDir) -> None:
    path = str(tmp.path / "test.log")
    logger.add(pathlib.Path(path))
    assert repr(logger) == "<loguru.logger handlers=[(id=0, level=10, sink='%s')]>" % path, (
        "a pathlib.Path sink must render like the equivalent string, since the two are "
        "interchangeable at the API level"
    )


def test_stream_object() -> None:
    class MyStream:
        def __init__(self, name):
            self.name = name

        def write(self, m):
            pass

        def __repr__(self):
            return "MyStream()"

    logger.add(MyStream("<foobar>"))
    assert repr(logger) == "<loguru.logger handlers=[(id=0, level=10, sink=<foobar>)]>", (
        "a stream's own 'name' attribute must be preferred over its repr, matching how the "
        "standard streams are identified"
    )


def test_stream_object_without_name_attr() -> None:
    class MyStream:
        def write(self, m):
            pass

        def __repr__(self):
            return "MyStream()"

    logger.add(MyStream())
    assert repr(logger) == "<loguru.logger handlers=[(id=0, level=10, sink=MyStream())]>", (
        "a stream with no 'name' must fall back to its repr rather than raise AttributeError"
    )


def test_stream_object_with_empty_name() -> None:
    class MyStream2:
        def __init__(self):
            self.name = ""

        def write(self, message):
            pass

        def __repr__(self):
            return "MyStream2()"

    logger.add(MyStream2())
    assert repr(logger) == "<loguru.logger handlers=[(id=0, level=10, sink=MyStream2())]>", (
        "an empty 'name' carries no information, so the repr must be used instead"
    )


def test_function() -> None:
    def my_function(message):
        pass

    logger.add(my_function)
    assert repr(logger) == "<loguru.logger handlers=[(id=0, level=10, sink=my_function)]>", (
        "a function sink must be identified by its name, which is what the reader recognises"
    )


def test_callable_without_name() -> None:
    class Function:
        def __call__(self):
            pass

        def __repr__(self):
            return "<FunctionWithout>"

    logger.add(Function())
    assert (
        repr(logger) == "<loguru.logger handlers=[(id=0, level=10, sink=<FunctionWithout>)]>"
    ), "a callable with no __name__ must fall back to its repr rather than raise AttributeError"


def test_callable_with_empty_name() -> None:
    class Function:
        __name__ = ""

        def __call__(self):
            pass

        def __repr__(self):
            return "<FunctionEmpty>"

    logger.add(Function())
    assert repr(logger) == "<loguru.logger handlers=[(id=0, level=10, sink=<FunctionEmpty>)]>", (
        "an empty __name__ carries no information, so the repr must be used instead"
    )


def test_coroutine_function() -> None:
    async def my_async_function(message):
        pass

    logger.add(my_async_function)
    assert (
        repr(logger) == "<loguru.logger handlers=[(id=0, level=10, sink=my_async_function)]>"
    ), "an async sink must be identified the same way as a synchronous one"


def test_coroutine_callable_without_name() -> None:
    class CoroutineFunction:
        async def __call__(self):
            pass

        def __repr__(self):
            return "<AsyncFunctionWithout>"

    logger.add(CoroutineFunction())
    assert (
        repr(logger) == "<loguru.logger handlers=[(id=0, level=10, sink=<AsyncFunctionWithout>)]>"
    ), "an async callable with no __name__ must fall back to its repr, like a sync one"


def test_coroutine_function_with_empty_name() -> None:
    class CoroutineFunction:
        __name__ = ""

        def __call__(self):
            pass

        def __repr__(self):
            return "<AsyncFunctionEmpty>"

    logger.add(CoroutineFunction())
    assert repr(logger) == "<loguru.logger handlers=[(id=0, level=10, sink=<AsyncFunctionEmpty>)]>", (
        "an empty __name__ carries no information, so the repr must be used instead"
    )


def test_standard_handler() -> None:
    handler = logging.StreamHandler(sys.__stderr__)
    logger.add(handler)
    r = "<loguru.logger handlers=[(id=0, level=10, sink=<StreamHandler <stderr> (NOTSET)>)]>"
    assert repr(logger) == r, (
        "a standard logging handler must be shown through its own repr, so its level and "
        "target remain visible"
    )


def test_multiple_handlers() -> None:
    logger.add(sys.__stdout__)
    logger.add(sys.__stderr__)
    r = (
        "<loguru.logger handlers=["
        "(id=0, level=10, sink=<stdout>), "
        "(id=1, level=10, sink=<stderr>)"
        "]>"
    )
    assert repr(logger) == r, (
        "every handler must be listed with its id, since that id is what remove() takes"
    )


def test_handler_removed() -> None:
    i = logger.add(sys.__stdout__)
    logger.add(sys.__stderr__)
    logger.remove(i)
    assert repr(logger) == "<loguru.logger handlers=[(id=1, level=10, sink=<stderr>)]>", (
        "removed handlers must disappear from the repr while the remaining ids keep their "
        "original values, since ids are not renumbered"
    )


def test_handler_level_name() -> None:
    logger.add(sys.__stderr__, level="TRACE")
    assert repr(logger) == "<loguru.logger handlers=[(id=0, level=5, sink=<stderr>)]>", (
        "the repr must show the resolved severity number, so levels given by name and by "
        "number can be compared at a glance"
    )


def test_handler_level_num() -> None:
    logger.add(sys.__stderr__, level=33)
    assert repr(logger) == "<loguru.logger handlers=[(id=0, level=33, sink=<stderr>)]>", (
        "a numeric level must be shown verbatim, including values with no registered name"
    )
