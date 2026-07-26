import re

from conftest import Writer
from oxitest import Fixture

import loguru._recattrs as recattrs
from loguru import logger


def test_patch_record_file(writer: Fixture[Writer]) -> None:
    def patch(record):
        record["file"].name = "456"
        record["file"].path = "123/456"

    logger.add(writer, format="{file} {file.name} {file.path}")
    logger.patch(patch).info("Test")

    assert writer.read() == "456 456 123/456\n", (
        "record attributes must stay writable from a patcher, otherwise users cannot rewrite "
        "file paths to hide absolute directories from their logs"
    )


def test_patch_record_thread(writer: Fixture[Writer]) -> None:
    def patch(record):
        record["thread"].id = 111
        record["thread"].name = "Thread-111"

    logger.add(writer, format="{thread} {thread.name} {thread.id}")
    logger.patch(patch).info("Test")

    assert writer.read() == "111 Thread-111 111\n", (
        "record attributes must stay writable from a patcher, otherwise users cannot "
        "normalize thread identity before it reaches the sink"
    )


def test_patch_record_process(writer: Fixture[Writer]) -> None:
    def patch(record):
        record["process"].id = 123
        record["process"].name = "Process-123"

    logger.add(writer, format="{process} {process.name} {process.id}")
    logger.patch(patch).info("Test")

    assert writer.read() == "123 Process-123 123\n", (
        "record attributes must stay writable from a patcher, otherwise users cannot "
        "normalize process identity before it reaches the sink"
    )


def test_patch_record_exception(writer: Fixture[Writer]) -> None:
    def patch(record):
        type_, value, _ = record["exception"]
        record["exception"] = (type_, value, None)

    logger.add(writer, format="")
    try:
        1 / 0  # noqa: B018
    except ZeroDivisionError:
        logger.patch(patch).exception("Error")

    assert writer.read() == "\nZeroDivisionError: division by zero\n", (
        "dropping the traceback from a patched exception must produce the one-line form, "
        "otherwise users cannot strip stack frames they consider sensitive"
    )


def test_level_repr() -> None:
    level = recattrs.RecordLevel("FOO", 123, "!!")
    assert repr(level) == "(name='FOO', no=123, icon='!!')", (
        "the repr is what users see when they format {level} without a field, so it must "
        "name every component rather than fall back to the default object repr"
    )


def test_file_repr() -> None:
    file_ = recattrs.RecordFile("foo.txt", "path/foo.txt")
    assert repr(file_) == "(name='foo.txt', path='path/foo.txt')", (
        "the repr is what users see when they format {file} without a field, so it must "
        "name every component rather than fall back to the default object repr"
    )


def test_thread_repr() -> None:
    thread = recattrs.RecordThread(98765, "thread-1")
    assert repr(thread) == "(id=98765, name='thread-1')", (
        "the repr is what users see when they format {thread} without a field, so it must "
        "name every component rather than fall back to the default object repr"
    )


def test_process_repr() -> None:
    process = recattrs.RecordProcess(12345, "process-1")
    assert repr(process) == "(id=12345, name='process-1')", (
        "the repr is what users see when they format {process} without a field, so it must "
        "name every component rather than fall back to the default object repr"
    )


def test_exception_repr() -> None:
    exception = recattrs.RecordException(ValueError, ValueError("Nope"), None)
    regex = r"\(type=<class 'ValueError'>, value=ValueError\('Nope',?\), traceback=None\)"
    assert re.fullmatch(regex, repr(exception)), (
        "the repr is what users see when they format {exception} without a field, so it must "
        "name every component rather than fall back to the default object repr"
    )
