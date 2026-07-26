import datetime
import os
from dataclasses import dataclass
from typing import Any
from unittest.mock import Mock

import oxitest
from conftest import FreezeTime
from oxitest import Fixture, StdCapture, TempDir, helpers

from loguru import logger

WINDOWS_HAS_NO_GLOB_IN_FILENAME = "Windows does not support '*' in filename"


@dataclass(frozen=True)
class RetentionCase:
    retention: Any


@dataclass(frozen=True)
class CountCase:
    retention: int


@dataclass(frozen=True)
class FilenameCase:
    filename: str


@dataclass(frozen=True)
class ModeCase:
    mode: str


@dataclass(frozen=True)
class DelayCase:
    delay: bool


MODE_CASES = {
    "append": ModeCase(mode="a"),
    "append_and_read": ModeCase(mode="a+"),
    "write": ModeCase(mode="w"),
    "exclusive_create": ModeCase(mode="x"),
}

DELAY_CASES = {
    "delayed": DelayCase(delay=True),
    "immediate": DelayCase(delay=False),
}


@oxitest.parametrize(
    words=RetentionCase(retention="1 hour"),
    compact=RetentionCase(retention="1H"),
    padded=RetentionCase(retention=" 1 h "),
    timedelta=RetentionCase(retention=datetime.timedelta(hours=1)),
)
def test_retention_time(freeze_time: Fixture[FreezeTime], tmp: TempDir, retention: Any) -> None:
    i = logger.add(tmp.path / "test.log.x", retention=retention)
    logger.debug("test")
    logger.remove(i)

    helpers.common.check_dir(tmp.path, size=1)

    future = datetime.datetime.now() + datetime.timedelta(days=1)
    with freeze_time(future):
        i = logger.add(tmp.path / "test.log", retention=retention)
        logger.debug("test")

        helpers.common.check_dir(tmp.path, size=2)
        logger.remove(i)
        helpers.common.check_dir(tmp.path, size=0)


@oxitest.parametrize(
    keep_none=CountCase(retention=0),
    keep_one=CountCase(retention=1),
    keep_ten=CountCase(retention=10),
)
def test_retention_count(tmp: TempDir, retention: int) -> None:
    file = tmp.path / "test.log"

    for i in range(retention):
        tmp.path.joinpath("test.2011-01-01_01-01-%d_000001.log" % i).write_text("test")

    i = logger.add(file, retention=retention)
    logger.debug("test")
    logger.remove(i)

    helpers.common.check_dir(tmp.path, size=retention)


def test_retention_function(tmp: TempDir) -> None:
    def func(logs):
        for log in logs:
            os.rename(log, log + ".xyz")

    tmp.path.joinpath("test.log.1").write_text("A")
    tmp.path.joinpath("test").write_text("B")

    i = logger.add(tmp.path / "test.log", retention=func)
    logger.remove(i)

    helpers.common.check_dir(
        tmp.path,
        files=[
            ("test.log.1.xyz", "A"),
            ("test", "B"),
            ("test.log.xyz", ""),
        ],
    )


def test_managed_files(tmp: TempDir) -> None:
    others = {
        "test.log",
        "test.log.1",
        "test.log.1.gz",
        "test.log.rar",
        "test.2019-11-12_03-22-07_018985.log",
        "test.2019-11-12_03-22-07_018985.log.tar.gz",
        "test.2019-11-12_03-22-07_018985.2.log",
        "test.2019-11-12_03-22-07_018985.2.log.tar.gz",
        "test.foo.log",
        "test.123.log",
        "test.2019-11-12_03-22-07_018985.abc.log",
        "test.2019-11-12_03-22-07_018985.123.abc.log",
        "test.foo.log.bar",
        "test.log.log",
    }

    for other in others:
        tmp.path.joinpath(other).write_text(other)

    i = logger.add(tmp.path / "test.log", retention=0, catch=False)
    logger.remove(i)

    helpers.common.check_dir(tmp.path, size=0)


def test_not_managed_files(tmp: TempDir) -> None:
    others = {
        "test_.log",
        "_test.log",
        "tes.log",
        "te.st.log",
        "testlog",
        "test",
        "test.tar.gz",
        "test.logs",
        "test.foo",
        "test.foo.logs",
        "tests.logs.zip",
        "foo.test.log",
        "foo.test.log.zip",
    }

    if os.name != "nt":
        others.add("test.")

    for other in others:
        tmp.path.joinpath(other).write_text(other)

    i = logger.add(tmp.path / "test.log", retention=0, catch=False)
    logger.remove(i)

    assert set(f.name for f in tmp.path.iterdir()) == others, (
        "retention must only ever delete files it could have created itself; deleting an "
        "unrelated neighbour would be irreversible data loss"
    )


@oxitest.parametrize(
    without_extension=FilenameCase(filename="test"),
    with_extension=FilenameCase(filename="test.log"),
)
def test_no_duplicates_in_listed_files(tmp: TempDir, filename: str) -> None:
    others = [
        "test.log",
        "test.log.log",
        "test.log.log.log",
        "test",
        "test..",
        "test.log..",
        "test..log",
        "test...log",
        "test.log..",
        "test.log.a.log.b",
    ]

    for other in others:
        tmp.path.joinpath(other).write_text(other)

    retention = Mock()
    i = logger.add(tmp.path / filename, retention=retention, catch=False)
    logger.remove(i)

    assert retention.call_count == 1, "the retention function must be invoked exactly once"
    assert len(retention.call_args.args[0]) == len(set(retention.call_args.args[0])), (
        "the candidate list is built from several glob patterns, so a file matching more "
        "than one must not be handed to the function twice"
    )


def test_directories_ignored(tmp: TempDir) -> None:
    others = ["test.log.2", "test.123.log", "test.log.tar.gz", "test.archive"]

    for other in others:
        tmp.path.joinpath(other).mkdir()

    i = logger.add(tmp.path / "test.log", retention=0, catch=False)
    logger.remove(i)

    helpers.common.check_dir(tmp.path, size=len(others))


def test_manage_formatted_files(freeze_time: Fixture[FreezeTime], tmp: TempDir) -> None:
    with freeze_time("2018-01-01 00:00:00"):
        f1 = tmp.path / "temp/2018/file.log"
        f2 = tmp.path / "temp/file2018.log"
        f3 = tmp.path / "temp/d2018/f2018.2018.log"

        a = logger.add(tmp.path / "temp/{time:YYYY}/file.log", retention=0)
        b = logger.add(tmp.path / "temp/file{time:YYYY}.log", retention=0)
        c = logger.add(tmp.path / "temp/d{time:YYYY}/f{time:YYYY}.{time:YYYY}.log", retention=0)

        logger.debug("test")

        why_created = "the placeholder must be expanded when the file is created"
        assert f1.exists(), why_created
        assert f2.exists(), why_created
        assert f3.exists(), why_created

        logger.remove(a)
        logger.remove(b)
        logger.remove(c)

        why_removed = (
            "retention must recognise files whose name came from a placeholder, in any path "
            "segment, otherwise those logs would accumulate forever"
        )
        assert not f1.exists(), why_removed
        assert not f2.exists(), why_removed
        assert not f3.exists(), why_removed


@oxitest.mark.skip(when=os.name == "nt", reason=WINDOWS_HAS_NO_GLOB_IN_FILENAME)
def test_date_with_dot_after_extension(tmp: TempDir) -> None:
    file = tmp.path / "file.{time:YYYY.MM}_log"

    i = logger.add(tmp.path / "file*.log", retention=0, catch=False)
    logger.remove(i)

    assert not file.exists(), (
        "a literal '*' in the sink path must be treated as part of the name, not as a glob "
        "that could match and delete unrelated files"
    )


@oxitest.mark.skip(when=os.name == "nt", reason=WINDOWS_HAS_NO_GLOB_IN_FILENAME)
def test_symbol_in_filename(tmp: TempDir) -> None:
    file = tmp.path / "file123.log"
    file.touch()

    i = logger.add(tmp.path / "file*.log", retention=0, catch=False)
    logger.remove(i)

    assert file.exists(), (
        "the '*' must be escaped before globbing, otherwise retention would delete every "
        "file that happens to match the pattern"
    )


def test_manage_file_without_extension(tmp: TempDir) -> None:
    file = tmp.path / "file"

    i = logger.add(file, retention=0)
    logger.debug("?")
    helpers.common.check_dir(tmp.path, files=[("file", None)])
    logger.remove(i)
    helpers.common.check_dir(tmp.path, files=[])


def test_manage_formatted_files_without_extension(tmp: TempDir) -> None:
    tmp.path.joinpath("file_8").touch()
    tmp.path.joinpath("file_7").touch()
    tmp.path.joinpath("file_6").touch()

    i = logger.add(tmp.path / "file_{time}", retention=0)
    logger.debug("1")
    logger.remove(i)

    helpers.common.check_dir(tmp.path, size=0)


@oxitest.parametrize(**MODE_CASES)
def test_retention_at_rotation(tmp: TempDir, mode: str) -> None:
    tmp.path.joinpath("test.log.1").touch()
    tmp.path.joinpath("test.log.2").touch()
    tmp.path.joinpath("test.log.3").touch()

    logger.add(tmp.path / "test.log", retention=1, rotation=0, mode=mode)
    logger.debug("test")

    helpers.common.check_dir(tmp.path, size=2)


@oxitest.parametrize(**MODE_CASES)
def test_retention_at_remove_without_rotation(tmp: TempDir, mode: str) -> None:
    i = logger.add(tmp.path / "file.log", retention=0, mode=mode)
    logger.debug("1")
    helpers.common.check_dir(tmp.path, size=1)
    logger.remove(i)
    helpers.common.check_dir(tmp.path, size=0)


@oxitest.parametrize(**MODE_CASES)
def test_no_retention_at_remove_with_rotation(tmp: TempDir, mode: str) -> None:
    i = logger.add(tmp.path / "file.log", retention=0, rotation="100 MB", mode=mode)
    logger.debug("1")
    helpers.common.check_dir(tmp.path, size=1)
    logger.remove(i)
    helpers.common.check_dir(tmp.path, size=1)


def test_no_renaming(tmp: TempDir) -> None:
    i = logger.add(tmp.path / "test.log", format="{message}", retention=10)
    logger.debug("test")
    logger.remove(i)

    helpers.common.check_dir(tmp.path, files=[("test.log", "test\n")])


@oxitest.parametrize(**DELAY_CASES)
def test_exception_during_retention_at_rotation(
    freeze_time: Fixture[FreezeTime], tmp: TempDir, cap: StdCapture, delay: bool
) -> None:
    with freeze_time("2022-02-22") as frozen:
        logger.add(
            tmp.path / "test.log",
            format="{message}",
            retention=Mock(side_effect=[Exception("Retention error"), None]),
            rotation=0,
            catch=True,
            delay=delay,
        )
        logger.debug("AAA")
        frozen.tick()
        logger.debug("BBB")

    helpers.common.check_dir(
        tmp.path,
        files=[
            ("test.2022-02-22_00-00-00_000000.log", ""),
            ("test.2022-02-22_00-00-01_000000.log", ""),
            ("test.log", "BBB\n"),
        ],
    )

    captured = cap.readouterr()
    assert captured.out == "", "the error report goes to stderr, so stdout must stay empty"
    assert captured.err.count("Logging error in Loguru Handler") == 1, (
        "a failing retention must be reported once and must not prevent the following "
        "rotation from succeeding"
    )
    assert (
        captured.err.count("Exception: Retention error") == 1
    ), "the report must name the original error so the user knows why old logs remain"


@oxitest.parametrize(**DELAY_CASES)
def test_exception_during_retention_at_rotation_not_caught(
    freeze_time: Fixture[FreezeTime], tmp: TempDir, cap: StdCapture, delay: bool
) -> None:
    with freeze_time("2022-02-22") as frozen:
        logger.add(
            tmp.path / "test.log",
            format="{message}",
            retention=Mock(side_effect=[OSError("Retention error"), None]),
            rotation=0,
            catch=False,
            delay=delay,
        )
        with oxitest.raises(OSError, match=r"^Retention error$"):
            logger.debug("AAA")
        frozen.tick()
        logger.debug("BBB")

    helpers.common.check_dir(
        tmp.path,
        files=[
            ("test.2022-02-22_00-00-00_000000.log", ""),
            ("test.2022-02-22_00-00-01_000000.log", ""),
            ("test.log", "BBB\n"),
        ],
    )

    captured = cap.readouterr()
    assert captured.out == captured.err == "", (
        "with catch=False the error propagates to the caller, so loguru must not also print "
        "a report of its own"
    )


@oxitest.parametrize(**DELAY_CASES)
def test_exception_during_retention_at_remove(tmp: TempDir, cap: StdCapture, delay: bool) -> None:
    i = logger.add(
        tmp.path / "test.log",
        format="{message}",
        retention=Mock(side_effect=[OSError("Retention error"), None]),
        catch=False,
        delay=delay,
    )
    logger.debug("AAA")

    with oxitest.raises(OSError, match=r"^Retention error$"):
        logger.remove(i)

    logger.debug("Nope")

    helpers.common.check_dir(tmp.path, files=[("test.log", "AAA\n")])

    captured = cap.readouterr()
    assert (
        captured.out == captured.err == ""
    ), "the error reaches the caller through remove(), so nothing may be printed as well"


@oxitest.parametrize(
    time_of_day=RetentionCase(retention=datetime.time(12, 12, 12)),
    module=RetentionCase(retention=os),
    object_instance=RetentionCase(retention=object()),
)
def test_invalid_retention_type(retention: Any) -> None:
    with oxitest.raises(TypeError):
        logger.add("test.log", retention=retention)


@oxitest.parametrize(
    week_number=RetentionCase(retention="W5"),
    weekday_at_time=RetentionCase(retention="monday at 14:00"),
    weekday=RetentionCase(retention="sunday"),
    nonsense=RetentionCase(retention="nope"),
    unit_only_lower=RetentionCase(retention="d"),
    unit_only_upper=RetentionCase(retention="H"),
    dunder=RetentionCase(retention="__dict__"),
)
def test_unparsable_retention(retention: str) -> None:
    with oxitest.raises(ValueError, match=r"^Cannot parse retention from: '[^']+'$"):
        logger.add("test.log", retention=retention)


@oxitest.parametrize(
    size_unit=RetentionCase(retention="5 MB"),
    misspelled_unit=RetentionCase(retention="3 hours 2 dayz"),
)
def test_invalid_value_retention_duration(retention: str) -> None:
    with oxitest.raises(ValueError, match=r"^Invalid unit value while parsing duration: '[^']+'$"):
        logger.add("test.log", retention=retention)
