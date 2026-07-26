import contextlib
import datetime
import os
import pathlib
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Iterator, List, Tuple, Union
from unittest.mock import Mock

import oxitest
from conftest import FreezeTime
from oxitest import Fixture, StdCapture, TempDir, helpers

import loguru
from loguru import logger
from loguru._ctime_functions import load_ctime_functions

LINUX_SPECIFIC = "Testing implementation specific to Linux"
WINDOWS_SPECIFIC = "Testing implementation specific to Windows"

NO_XATTR_SUPPORT = (
    os.name == "nt"
    or hasattr(os.stat_result, "st_birthtime")
    or not hasattr(os, "setxattr")
    or not hasattr(os, "getxattr")
)


@dataclass(frozen=True)
class SizeCase:
    size: Any


@dataclass(frozen=True)
class TimeRotationCase:
    when: Any
    hours: List[float]


@dataclass(frozen=True)
class OffsetCase:
    offset: int


@dataclass(frozen=True)
class RotationCase:
    rotation: Any


@dataclass(frozen=True)
class TimezoneCase:
    timezone: Tuple[str, int]


@dataclass(frozen=True)
class DelayCase:
    delay: bool


@dataclass(frozen=True)
class ModeCase:
    mode: str


@dataclass(frozen=True)
class ExceptionCase:
    exception: Any


DELAY_CASES = {
    "immediate": DelayCase(delay=False),
    "delayed": DelayCase(delay=True),
}


def _rotation_cases(*rotations: Any) -> dict:
    return {
        "case_%d" % index: RotationCase(rotation=rotation)
        for index, rotation in enumerate(rotations)
    }


@contextlib.contextmanager
def local_temporary_directory() -> Iterator[pathlib.Path]:
    """Create a temp directory inside the project rather than under /tmp.

    The creation-time helpers fall back to extended attributes on Linux, and /tmp is often
    mounted without xattr support, so tests exercising that path need a directory elsewhere.
    """
    with tempfile.TemporaryDirectory(dir=".") as tmp_path:
        try:
            yield pathlib.Path(tmp_path)
        finally:
            logger.remove()  # Deleting file not possible if still in use by Loguru.


def test_renaming(freeze_time: Fixture[FreezeTime], tmp: TempDir) -> None:
    with freeze_time("2020-01-01") as frozen:
        logger.add(tmp.path / "file.log", rotation=0, format="{message}")

        frozen.tick()
        logger.debug("a")

        helpers.common.check_dir(
            tmp.path,
            files=[
                ("file.2020-01-01_00-00-00_000000.log", ""),
                ("file.log", "a\n"),
            ],
        )

        frozen.tick()
        logger.debug("b")

        helpers.common.check_dir(
            tmp.path,
            files=[
                ("file.2020-01-01_00-00-00_000000.log", ""),
                ("file.2020-01-01_00-00-01_000000.log", "a\n"),
                ("file.log", "b\n"),
            ],
        )


def test_no_renaming(freeze_time: Fixture[FreezeTime], tmp: TempDir) -> None:
    with freeze_time("2018-01-01 00:00:00") as frozen:
        logger.add(tmp.path / "file_{time}.log", rotation=0, format="{message}")

        frozen.move_to("2019-01-01 00:00:00")
        logger.debug("a")
        helpers.common.check_dir(
            tmp.path,
            files=[
                ("file_2018-01-01_00-00-00_000000.log", ""),
                ("file_2019-01-01_00-00-00_000000.log", "a\n"),
            ],
        )

        frozen.move_to("2020-01-01 00:00:00")
        logger.debug("b")
        helpers.common.check_dir(
            tmp.path,
            files=[
                ("file_2018-01-01_00-00-00_000000.log", ""),
                ("file_2019-01-01_00-00-00_000000.log", "a\n"),
                ("file_2020-01-01_00-00-00_000000.log", "b\n"),
            ],
        )


@oxitest.parametrize(
    integer=SizeCase(size=8),
    float_value=SizeCase(size=8.0),
    rounded_up=SizeCase(size=7.99),
    bytes_unit=SizeCase(size="8 B"),
    megabytes=SizeCase(size="8e-6MB"),
    kibibytes=SizeCase(size="0.008 kiB"),
    bits=SizeCase(size="64b"),
)
def test_size_rotation(freeze_time: Fixture[FreezeTime], tmp: TempDir, size: Any) -> None:
    with freeze_time("2018-01-01 00:00:00") as frozen:
        i = logger.add(tmp.path / "test_{time}.log", format="{message}", rotation=size, mode="w")

        frozen.tick()
        logger.debug("abcde")

        frozen.tick()
        logger.debug("fghij")

        frozen.tick()
        logger.debug("klmno")

        frozen.tick()
        logger.remove(i)

    helpers.common.check_dir(
        tmp.path,
        files=[
            ("test_2018-01-01_00-00-00_000000.log", "abcde\n"),
            ("test_2018-01-01_00-00-02_000000.log", "fghij\n"),
            ("test_2018-01-01_00-00-03_000000.log", "klmno\n"),
        ],
    )


# hours = [
#   Should not trigger, should trigger, should not trigger, should trigger, should trigger
# ]
@oxitest.parametrize(
    hour_only=TimeRotationCase(when="13", hours=[0, 1, 20, 4, 24]),
    hour_minute=TimeRotationCase(when="13:00", hours=[0.2, 0.9, 23, 1, 48]),
    hour_minute_second=TimeRotationCase(when="13:00:00", hours=[0.5, 1.5, 10, 15, 72]),
    with_microseconds=TimeRotationCase(when="13:00:00.123456", hours=[0.9, 2, 10, 15, 256]),
    earlier_hour=TimeRotationCase(when="11:00", hours=[22.9, 0.2, 23, 1, 24]),
    twelve_hour_clock=TimeRotationCase(when="1:30 PM", hours=[1, 1, 20, 4, 24]),
    weekday_number=TimeRotationCase(when="w0", hours=[11, 1, 24 * 7 - 1, 1, 24 * 7]),
    weekday_at_midnight=TimeRotationCase(
        when="W0 at 00:00", hours=[10, 24 * 7 - 5, 0.1, 24 * 30, 24 * 14]
    ),
    last_weekday=TimeRotationCase(when="W6", hours=[24, 24 * 28, 24 * 5, 24, 364 * 24]),
    weekday_name=TimeRotationCase(when="saturday", hours=[25, 25 * 12, 0, 25 * 12, 24 * 8]),
    weekday_at_hour=TimeRotationCase(when="w6 at 00", hours=[8, 24 * 7, 24 * 6, 24, 24 * 8]),
    weekday_padded=TimeRotationCase(when=" W6 at 13 ", hours=[0.5, 1, 24 * 6, 24 * 6, 365 * 24]),
    weekday_extra_spaces=TimeRotationCase(
        when="w2  at  11:00:00 AM", hours=[48 + 22, 3, 24 * 6, 24, 366 * 24]
    ),
    weekday_mixed_case=TimeRotationCase(
        when="MonDaY at 11:00:30.123", hours=[22, 24, 24, 24 * 7, 24 * 7]
    ),
    sunday=TimeRotationCase(when="sunday", hours=[0.1, 24 * 7 - 10, 24, 24 * 6, 24 * 7]),
    sunday_at_hour=TimeRotationCase(when="SUNDAY at 11:00", hours=[1, 24 * 7, 2, 24 * 7, 30 * 12]),
    sunday_twelve_hour=TimeRotationCase(
        when="sunDAY at 1:0:0.0 pm", hours=[0.9, 0.2, 24 * 7 - 2, 3, 24 * 8]
    ),
    time_object=TimeRotationCase(when=datetime.time(15), hours=[2, 3, 19, 5, 24]),
    time_object_precise=TimeRotationCase(
        when=datetime.time(18, 30, 11, 123), hours=[1, 5.51, 20, 24, 40]
    ),
    hours_compact=TimeRotationCase(when="2 h", hours=[1, 2, 0.9, 0.5, 10]),
    hour_word=TimeRotationCase(when="1 hour", hours=[0.5, 1, 0.1, 100, 1000]),
    days=TimeRotationCase(when="7 days", hours=[24 * 7 - 1, 1, 48, 24 * 10, 24 * 365]),
    mixed_units=TimeRotationCase(when="1h 30 minutes", hours=[1.4, 0.2, 1, 2, 10]),
    weeks_and_days=TimeRotationCase(when="1 w, 2D", hours=[24 * 8, 24 * 2, 24, 24 * 9, 24 * 9]),
    fractional_days=TimeRotationCase(when="1.5d", hours=[30, 10, 0.9, 48, 35]),
    fractional_mixed=TimeRotationCase(when="1.222 hours, 3.44s", hours=[1.222, 0.1, 1, 1.2, 2]),
    timedelta_hour=TimeRotationCase(
        when=datetime.timedelta(hours=1), hours=[0.9, 0.2, 0.7, 0.5, 3]
    ),
    timedelta_minutes=TimeRotationCase(
        when=datetime.timedelta(minutes=30), hours=[0.48, 0.04, 0.07, 0.44, 0.5]
    ),
    hourly=TimeRotationCase(when="hourly", hours=[0.9, 0.2, 0.8, 3, 1]),
    daily=TimeRotationCase(when="daily", hours=[11, 1, 23, 1, 24]),
    weekly=TimeRotationCase(when="WEEKLY", hours=[11, 2, 24 * 6, 24, 24 * 7]),
    monthly_mixed_case=TimeRotationCase(
        when="mOnthLY", hours=[0, 24 * 13, 29 * 24, 60 * 24, 24 * 35]
    ),
    monthly=TimeRotationCase(when="monthly", hours=[10 * 24, 30 * 24 * 6, 24, 24 * 7, 24 * 31]),
    yearly=TimeRotationCase(when="Yearly ", hours=[100, 24 * 7 * 30, 24 * 300, 24 * 100, 24 * 400]),
)
def test_time_rotation(
    freeze_time: Fixture[FreezeTime], tmp: TempDir, when: Any, hours: List[float]
) -> None:
    with freeze_time("2017-06-18 12:00:00") as frozen:  # Sunday
        i = logger.add(
            tmp.path / "test_{time}.log",
            format="{message}",
            rotation=when,
            mode="w",
        )

        for h, m in zip(hours, ["a", "b", "c", "d", "e"]):
            frozen.tick(delta=datetime.timedelta(hours=h))
            logger.debug(m)

        logger.remove(i)

    content = [path.read_text() for path in sorted(tmp.path.iterdir())]
    assert content == ["a\n", "b\nc\n", "d\n", "e\n"], (
        "every accepted spelling of the rotation schedule must produce the same rotation "
        "points; the elapsed hours are chosen so exactly the 2nd, 4th and 5th message rotate"
    )


def test_time_rotation_dst(freeze_time: Fixture[FreezeTime], tmp: TempDir) -> None:
    with freeze_time("2018-10-27 05:00:00", ("CET", 3600)):
        i = logger.add(tmp.path / "test_{time}.log", format="{message}", rotation="1 day")
        logger.debug("First")

        with freeze_time("2018-10-28 05:30:00", ("CEST", 7200)):
            logger.debug("Second")

            with freeze_time("2018-10-29 06:00:00", ("CET", 3600)):
                logger.debug("Third")

    logger.remove(i)

    helpers.common.check_dir(
        tmp.path,
        files=[
            ("test_2018-10-27_05-00-00_000000.log", "First\n"),
            ("test_2018-10-28_05-30-00_000000.log", "Second\n"),
            ("test_2018-10-29_06-00-00_000000.log", "Third\n"),
        ],
    )


def test_time_rotation_with_tzinfo_diff_bigger(
    freeze_time: Fixture[FreezeTime], tmp: TempDir
) -> None:
    with freeze_time("2018-10-27 05:00:00", ("CET", 3600)) as frozen:
        tzinfo = datetime.timezone(datetime.timedelta(seconds=7200))
        rotation = datetime.time(7, 0, 0, tzinfo=tzinfo)

        i = logger.add(tmp.path / "test_{time}.log", format="{message}", rotation=rotation)

        frozen.tick(delta=datetime.timedelta(minutes=30))
        logger.debug("First")
        frozen.tick(delta=datetime.timedelta(hours=1))
        logger.debug("Second")

    logger.remove(i)

    helpers.common.check_dir(
        tmp.path,
        files=[
            ("test_2018-10-27_05-00-00_000000.log", "First\n"),
            ("test_2018-10-27_06-30-00_000000.log", "Second\n"),
        ],
    )


def test_time_rotation_with_tzinfo_diff_lower(
    freeze_time: Fixture[FreezeTime], tmp: TempDir
) -> None:
    with freeze_time("2018-10-27 06:00:00", ("CEST", 7200)) as frozen:
        tzinfo = datetime.timezone(datetime.timedelta(seconds=3600))
        rotation = datetime.time(6, 0, 0, tzinfo=tzinfo)

        i = logger.add(tmp.path / "test_{time}.log", format="{message}", rotation=rotation)

        frozen.tick(delta=datetime.timedelta(minutes=30))
        logger.debug("First")
        frozen.tick(delta=datetime.timedelta(hours=1))
        logger.debug("Second")

    logger.remove(i)

    helpers.common.check_dir(
        tmp.path,
        files=[
            ("test_2018-10-27_06-00-00_000000.log", "First\n"),
            ("test_2018-10-27_07-30-00_000000.log", "Second\n"),
        ],
    )


def test_time_rotation_with_tzinfo_utc(freeze_time: Fixture[FreezeTime], tmp: TempDir) -> None:
    with freeze_time("2018-10-27 05:00:00", ("CET", 3600)) as frozen:
        rotation = datetime.time(5, 0, 0, tzinfo=datetime.timezone.utc)

        i = logger.add(
            tmp.path / "test_{time:YYYY-MM-DD_HH-mm-ss!UTC}.log",
            format="{message}",
            rotation=rotation,
        )

        frozen.tick(delta=datetime.timedelta(minutes=30))
        logger.debug("First")
        frozen.tick(delta=datetime.timedelta(hours=1))
        logger.debug("Second")

    logger.remove(i)

    helpers.common.check_dir(
        tmp.path,
        files=[
            ("test_2018-10-27_04-00-00.log", "First\n"),
            ("test_2018-10-27_05-30-00.log", "Second\n"),
        ],
    )


def test_time_rotation_multiple_days_at_midnight_utc(
    freeze_time: Fixture[FreezeTime], tmp: TempDir
) -> None:
    with freeze_time("2018-10-27 10:00:00", ("CET", 3600)) as frozen:
        rotation = datetime.time(0, 0, 0, tzinfo=datetime.timezone.utc)

        i = logger.add(
            tmp.path / "test_{time:YYYY-MM-DD!UTC}.log",
            format="{message}",
            rotation=rotation,
        )

        frozen.tick(delta=datetime.timedelta(hours=13, minutes=30))
        logger.debug("First")
        frozen.tick(delta=datetime.timedelta(hours=1))
        logger.debug("Second")
        frozen.tick(delta=datetime.timedelta(hours=1))
        logger.debug("Third")
        frozen.tick(delta=datetime.timedelta(hours=24))
        logger.debug("Fourth")

    logger.remove(i)

    helpers.common.check_dir(
        tmp.path,
        files=[
            ("test_2018-10-27.log", "First\nSecond\n"),
            ("test_2018-10-28.log", "Third\n"),
            ("test_2018-10-29.log", "Fourth\n"),
        ],
    )


@oxitest.parametrize(
    behind_utc=OffsetCase(offset=-3600),
    utc=OffsetCase(offset=0),
    ahead_of_utc=OffsetCase(offset=3600),
)
def test_daily_rotation_with_different_timezone(
    freeze_time: Fixture[FreezeTime], tmp: TempDir, offset: int
) -> None:
    with freeze_time("2018-10-27 00:00:00", ("A", offset)) as frozen:
        i = logger.add(
            tmp.path / "test_{time:YYYY-MM-DD}.log",
            format="{message}",
            rotation="daily",
        )

        logger.debug("First")
        frozen.tick(delta=datetime.timedelta(hours=23, minutes=30))
        logger.debug("Second")
        frozen.tick(delta=datetime.timedelta(hours=1))
        logger.debug("Third")
        frozen.tick(delta=datetime.timedelta(hours=24))
        logger.debug("Fourth")

    logger.remove(i)

    helpers.common.check_dir(
        tmp.path,
        files=[
            ("test_2018-10-27.log", "First\nSecond\n"),
            ("test_2018-10-28.log", "Third\n"),
            ("test_2018-10-29.log", "Fourth\n"),
        ],
    )


@oxitest.parametrize(
    **_rotation_cases(
        datetime.time(1, 30, 0, tzinfo=datetime.timezone.utc),
        datetime.time(2, 30, 0, tzinfo=datetime.timezone(datetime.timedelta(seconds=3600))),
        datetime.time(0, 30, 0, tzinfo=datetime.timezone(datetime.timedelta(seconds=-3600))),
        datetime.time(3, 30, 0),
        "03:30:00",
    )
)
def test_time_rotation_after_positive_timezone_changes_forward(
    freeze_time: Fixture[FreezeTime], tmp: TempDir, rotation: Any
) -> None:
    with freeze_time("2018-10-27 02:00:00", ("CET", 3600)):
        i = logger.add(
            tmp.path / "test_{time:YYYY-MM-DD_HH-mm-ss!UTC}.log",
            format="{message}",
            rotation=rotation,
        )

        logger.debug("First")

        with freeze_time("2018-10-27 03:00:00", ("CET", 7200)) as frozen:
            logger.debug("Second")
            frozen.tick(delta=datetime.timedelta(hours=1))
            logger.debug("Third")

    logger.remove(i)

    helpers.common.check_dir(
        tmp.path,
        files=[
            ("test_2018-10-27_01-00-00.log", "First\nSecond\n"),
            ("test_2018-10-27_02-00-00.log", "Third\n"),
        ],
    )


@oxitest.parametrize(**_rotation_cases(datetime.time(2, 30, 0), "02:30:00"))
def test_time_rotation_when_positive_timezone_changes_forward(
    freeze_time: Fixture[FreezeTime], tmp: TempDir, rotation: Any
) -> None:
    with freeze_time("2018-10-27 02:00:00", ("CET", 3600)):
        i = logger.add(
            tmp.path / "test_{time:YYYY-MM-DD_HH-mm-ss}.log",
            format="{message}",
            rotation=rotation,
        )

        logger.debug("First")

        with freeze_time("2018-10-27 03:00:00", ("CET", 7200)) as frozen:
            logger.debug("Second")
            frozen.tick(delta=datetime.timedelta(hours=1))
            logger.debug("Third")

    logger.remove(i)

    helpers.common.check_dir(
        tmp.path,
        files=[
            ("test_2018-10-27_02-00-00.log", "First\n"),
            ("test_2018-10-27_03-00-00.log", "Second\nThird\n"),
        ],
    )


@oxitest.parametrize(
    **_rotation_cases(
        datetime.time(4, 30, 0, tzinfo=datetime.timezone.utc),
        datetime.time(5, 30, 0, tzinfo=datetime.timezone(datetime.timedelta(seconds=3600))),
        datetime.time(3, 30, 0, tzinfo=datetime.timezone(datetime.timedelta(seconds=-3600))),
        datetime.time(3, 30, 0),
        "03:30:00",
    )
)
def test_time_rotation_after_negative_timezone_changes_forward(
    freeze_time: Fixture[FreezeTime], tmp: TempDir, rotation: Any
) -> None:
    with freeze_time("2018-10-27 02:00:00", ("CET", -7200)):
        i = logger.add(
            tmp.path / "test_{time:YYYY-MM-DD_HH-mm-ss!UTC}.log",
            format="{message}",
            rotation=rotation,
        )

        logger.debug("First")

        with freeze_time("2018-10-27 03:00:00", ("CET", -3600)) as frozen:
            logger.debug("Second")
            frozen.tick(delta=datetime.timedelta(hours=1))
            logger.debug("Third")

    logger.remove(i)

    helpers.common.check_dir(
        tmp.path,
        files=[
            ("test_2018-10-27_04-00-00.log", "First\nSecond\n"),
            ("test_2018-10-27_05-00-00.log", "Third\n"),
        ],
    )


@oxitest.parametrize(**_rotation_cases(datetime.time(2, 30, 0), "02:30:00"))
def test_time_rotation_when_negative_timezone_changes_forward(
    freeze_time: Fixture[FreezeTime], tmp: TempDir, rotation: Any
) -> None:
    with freeze_time("2018-10-27 02:00:00", ("CET", -7200)):
        i = logger.add(
            tmp.path / "test_{time:YYYY-MM-DD_HH-mm-ss}.log",
            format="{message}",
            rotation=rotation,
        )

        logger.debug("First")

        with freeze_time("2018-10-27 03:00:00", ("CET", -3600)) as frozen:
            logger.debug("Second")
            frozen.tick(delta=datetime.timedelta(hours=1))
            logger.debug("Third")

    logger.remove(i)

    helpers.common.check_dir(
        tmp.path,
        files=[
            ("test_2018-10-27_02-00-00.log", "First\n"),
            ("test_2018-10-27_03-00-00.log", "Second\nThird\n"),
        ],
    )


@oxitest.parametrize(
    **_rotation_cases(
        datetime.time(1, 30, 0, tzinfo=datetime.timezone.utc),
        datetime.time(2, 30, 0, tzinfo=datetime.timezone(datetime.timedelta(seconds=3600))),
        datetime.time(0, 30, 0, tzinfo=datetime.timezone(datetime.timedelta(seconds=-3600))),
    )
)
def test_time_rotation_after_positive_timezone_changes_backward_aware(
    freeze_time: Fixture[FreezeTime], tmp: TempDir, rotation: Any
) -> None:
    with freeze_time("2018-10-27 03:00:00", ("CET", 7200)):
        i = logger.add(
            tmp.path / "test_{time:YYYY-MM-DD_HH-mm-ss!UTC}.log",
            format="{message}",
            rotation=rotation,
        )

        logger.debug("First")

        with freeze_time("2018-10-27 02:00:00", ("CET", 3600)) as frozen:
            logger.debug("Second")
            frozen.tick(delta=datetime.timedelta(hours=1))
            logger.debug("Third")

    logger.remove(i)

    helpers.common.check_dir(
        tmp.path,
        files=[
            ("test_2018-10-27_01-00-00.log", "First\nSecond\n"),
            ("test_2018-10-27_02-00-00.log", "Third\n"),
        ],
    )


@oxitest.parametrize(**_rotation_cases(datetime.time(2, 30, 0), "02:30:00"))
def test_time_rotation_after_positive_timezone_changes_backward_naive(
    freeze_time: Fixture[FreezeTime], tmp: TempDir, rotation: Any
) -> None:
    with freeze_time("2018-10-27 03:00:00", ("CET", 7200)):
        i = logger.add(
            tmp.path / "test_{time:YYYY-MM-DD_HH-mm-ss!UTC}.log",
            format="{message}",
            rotation=rotation,
        )

        logger.debug("First")

        with freeze_time("2018-10-27 02:00:00", ("CET", 3600)) as frozen:
            logger.debug("Second")
            frozen.tick(delta=datetime.timedelta(hours=1))
            logger.debug("Third")
            frozen.tick(delta=datetime.timedelta(days=1))
            logger.debug("Fourth")

    logger.remove(i)

    helpers.common.check_dir(
        tmp.path,
        files=[
            ("test_2018-10-27_01-00-00.log", "First\nSecond\nThird\n"),
            ("test_2018-10-28_02-00-00.log", "Fourth\n"),
        ],
    )


@oxitest.parametrize(
    **_rotation_cases(
        datetime.time(4, 30, 0, tzinfo=datetime.timezone.utc),
        datetime.time(5, 30, 0, tzinfo=datetime.timezone(datetime.timedelta(seconds=3600))),
        datetime.time(3, 30, 0, tzinfo=datetime.timezone(datetime.timedelta(seconds=-3600))),
    )
)
def test_time_rotation_after_negative_timezone_changes_backward_aware(
    freeze_time: Fixture[FreezeTime], tmp: TempDir, rotation: Any
) -> None:
    with freeze_time("2018-10-27 03:00:00", ("CET", -3600)):
        i = logger.add(
            tmp.path / "test_{time:YYYY-MM-DD_HH-mm-ss!UTC}.log",
            format="{message}",
            rotation=rotation,
        )

        logger.debug("First")

        with freeze_time("2018-10-27 02:00:00", ("CET", -7200)) as frozen:
            logger.debug("Second")
            frozen.tick(delta=datetime.timedelta(hours=1))
            logger.debug("Third")

    logger.remove(i)

    helpers.common.check_dir(
        tmp.path,
        files=[
            ("test_2018-10-27_04-00-00.log", "First\nSecond\n"),
            ("test_2018-10-27_05-00-00.log", "Third\n"),
        ],
    )


@oxitest.parametrize(**_rotation_cases(datetime.time(2, 30, 0), "02:30:00"))
def test_time_rotation_after_negative_timezone_changes_backward_naive(
    freeze_time: Fixture[FreezeTime], tmp: TempDir, rotation: Any
) -> None:
    with freeze_time("2018-10-27 03:00:00", ("CET", -3600)):
        i = logger.add(
            tmp.path / "test_{time:YYYY-MM-DD_HH-mm-ss!UTC}.log",
            format="{message}",
            rotation=rotation,
        )

        logger.debug("First")

        with freeze_time("2018-10-27 02:00:00", ("CET", -7200)) as frozen:
            logger.debug("Second")
            frozen.tick(delta=datetime.timedelta(hours=1))
            logger.debug("Third")
            frozen.tick(delta=datetime.timedelta(days=1))
            logger.debug("Fourth")

    logger.remove(i)

    helpers.common.check_dir(
        tmp.path,
        files=[
            ("test_2018-10-27_04-00-00.log", "First\nSecond\nThird\n"),
            ("test_2018-10-28_05-00-00.log", "Fourth\n"),
        ],
    )


def test_time_rotation_when_timezone_changes_backward_rename_file(
    freeze_time: Fixture[FreezeTime], tmp: TempDir
) -> None:
    with freeze_time("2018-10-27 02:00:00", ("CET", 3600)):
        i = logger.add(
            tmp.path / "test_{time:YYYY-MM-DD_HH-mm-ss!UTC}.log",
            format="{message}",
            rotation="02:30:00",
        )

        logger.debug("First")

        with freeze_time("2018-10-27 03:00:00", ("CET", 7200)) as frozen:
            logger.debug("Second")
            frozen.tick(delta=datetime.timedelta(hours=1))
            logger.debug("Third")

    logger.remove(i)

    helpers.common.check_dir(
        tmp.path,
        files=[
            ("test_2018-10-27_01-00-00.2018-10-27_03-00-00_000000.log", "First\n"),
            ("test_2018-10-27_01-00-00.log", "Second\nThird\n"),
        ],
    )


@oxitest.parametrize(
    **_rotation_cases(
        "00:15",
        datetime.time(0, 15, 0),
        datetime.time(23, 15, 0, tzinfo=datetime.timezone.utc),
        datetime.time(0, 15, 0, tzinfo=datetime.timezone(datetime.timedelta(seconds=+3600))),
        datetime.time(22, 15, 0, tzinfo=datetime.timezone(datetime.timedelta(seconds=-3600))),
    )
)
def test_dont_rotate_earlier_when_utc_is_one_day_before(
    freeze_time: Fixture[FreezeTime], tmp: TempDir, rotation: Any
) -> None:
    with freeze_time("2018-10-24 00:30:00", ("CET", +3600)) as frozen:
        logger.add(tmp.path / "test.log", format="{message}", rotation=rotation)
        logger.info("First")
        logger.remove()

        frozen.tick(delta=datetime.timedelta(hours=1))
        logger.add(tmp.path / "test.log", format="{message}", rotation=rotation)
        logger.info("Second")
        logger.remove()

        frozen.tick(delta=datetime.timedelta(hours=23))
        logger.add(tmp.path / "test.log", format="{message}", rotation=rotation)
        logger.info("Third")
        logger.remove()

    helpers.common.check_dir(
        tmp.path,
        files=[
            ("test.2018-10-24_00-30-00_000000.log", "First\nSecond\n"),
            ("test.log", "Third\n"),
        ],
    )


@oxitest.parametrize(
    **_rotation_cases(
        "23:45",
        datetime.time(23, 45, 0),
        datetime.time(0, 45, 0, tzinfo=datetime.timezone.utc),
        datetime.time(1, 45, 0, tzinfo=datetime.timezone(datetime.timedelta(seconds=+3600))),
        datetime.time(23, 45, 0, tzinfo=datetime.timezone(datetime.timedelta(seconds=-3600))),
    )
)
def test_dont_rotate_later_when_utc_is_one_day_after(
    freeze_time: Fixture[FreezeTime], tmp: TempDir, rotation: Any
) -> None:
    with freeze_time("2018-10-23 23:30:00", ("CET", -3600)) as frozen:
        logger.add(tmp.path / "test.log", format="{message}", rotation=rotation)
        logger.info("First")
        logger.remove()

        frozen.tick(delta=datetime.timedelta(hours=1))
        logger.add(tmp.path / "test.log", format="{message}", rotation=rotation)
        logger.info("Second")
        logger.remove()

        frozen.tick(delta=datetime.timedelta(hours=23))
        logger.add(tmp.path / "test.log", format="{message}", rotation=rotation)
        logger.info("Third")
        logger.remove()

    helpers.common.check_dir(
        tmp.path,
        files=[
            ("test.2018-10-23_23-30-00_000000.log", "First\n"),
            ("test.log", "Second\nThird\n"),
        ],
    )


@oxitest.parametrize(
    ahead_of_utc=TimezoneCase(timezone=("CET", +3600)),
    behind_utc=TimezoneCase(timezone=("CET", -3600)),
    utc=TimezoneCase(timezone=("UTC", 0)),
)
def test_rotation_at_midnight_with_date_in_filename(
    freeze_time: Fixture[FreezeTime], tmp: TempDir, timezone: Tuple[str, int]
) -> None:
    with freeze_time("2018-10-23 23:55:00", timezone) as frozen:
        logger.add(tmp.path / "test.{time:YYYY-MM-DD}.log", format="{message}", rotation="00:00")
        logger.info("First")
        logger.remove()

        frozen.tick(delta=datetime.timedelta(minutes=10))

        logger.add(tmp.path / "test.{time:YYYY-MM-DD}.log", format="{message}", rotation="00:00")
        logger.info("Second")
        logger.remove()

    helpers.common.check_dir(
        tmp.path,
        files=[
            ("test.2018-10-23.log", "First\n"),
            ("test.2018-10-24.log", "Second\n"),
        ],
    )


@oxitest.parametrize(**DELAY_CASES)
def test_time_rotation_reopening_native(delay: bool) -> None:
    with local_temporary_directory() as tmp_path_local:
        with tempfile.TemporaryDirectory(dir=str(tmp_path_local)) as test_dir:
            get_ctime, set_ctime = load_ctime_functions()
            test_file = pathlib.Path(test_dir) / "test.txt"
            test_file.touch()
            timestamp_in = 946681200
            set_ctime(str(test_file), timestamp_in)
            timestamp_out = get_ctime(str(test_file))
            if timestamp_in != timestamp_out:
                oxitest.skip(
                    "The current system does not support getting and setting file creation "
                    "dates, the test can't be run."
                )

        filepath = tmp_path_local / "test.log"
        i = logger.add(filepath, format="{message}", delay=delay, rotation="2 s")
        logger.info("1")
        time.sleep(1.5)
        logger.info("2")
        logger.remove(i)
        i = logger.add(filepath, format="{message}", delay=delay, rotation="2 s")
        logger.info("3")

        helpers.common.check_dir(tmp_path_local, size=1)
        assert filepath.read_text() == "1\n2\n3\n", (
            "re-opening the file must recover its original creation time, so the rotation "
            "clock is not reset by a restart"
        )

        time.sleep(1)
        logger.info("4")

        helpers.common.check_dir(tmp_path_local, size=2)
        assert (
            filepath.read_text() == "4\n"
        ), "the elapsed time since the *original* creation must trigger the rotation"

        logger.remove(i)
        time.sleep(1)
        i = logger.add(filepath, format="{message}", delay=delay, rotation="2 s")
        logger.info("5")

        helpers.common.check_dir(tmp_path_local, size=2)
        assert (
            filepath.read_text() == "4\n5\n"
        ), "the creation time recorded at rotation must survive the next re-open too"

        time.sleep(1.5)
        logger.info("6")
        logger.remove(i)

        helpers.common.check_dir(tmp_path_local, size=3)
        assert (
            filepath.read_text() == "6\n"
        ), "the rotation clock must keep running across re-opens rather than restart"


@oxitest.mark.skip(when=NO_XATTR_SUPPORT, reason=LINUX_SPECIFIC)
@oxitest.parametrize(**DELAY_CASES)
def test_time_rotation_reopening_xattr_attributeerror(delay: bool) -> None:
    with local_temporary_directory() as tmp_path_local:
        with helpers.common.patch_context() as context:
            context.delattr(os, "setxattr")
            context.delattr(os, "getxattr")
            get_ctime, set_ctime = load_ctime_functions()

            context.setattr(loguru._file_sink, "get_ctime", get_ctime)
            context.setattr(loguru._file_sink, "set_ctime", set_ctime)

            filepath = tmp_path_local / "test.log"
            i = logger.add(filepath, format="{message}", delay=delay, rotation="2 s")
            time.sleep(1)
            logger.info("1")
            logger.remove(i)
            time.sleep(1.5)
            i = logger.add(filepath, format="{message}", delay=delay, rotation="2 s")
            logger.info("2")
            logger.remove(i)
            helpers.common.check_dir(tmp_path_local, size=1)
            assert filepath.read_text() == "1\n2\n", (
                "without xattr the creation time falls back to mtime, which must still give "
                "a usable rotation clock rather than raise"
            )
            time.sleep(2.5)
            i = logger.add(filepath, format="{message}", delay=delay, rotation="2 s")
            logger.info("3")
            logger.remove(i)
            helpers.common.check_dir(tmp_path_local, size=2)
            assert (
                filepath.read_text() == "3\n"
            ), "the fallback clock must still trigger rotation once the interval elapses"


@oxitest.mark.skip(when=NO_XATTR_SUPPORT, reason=LINUX_SPECIFIC)
@oxitest.parametrize(**DELAY_CASES)
def test_time_rotation_reopening_xattr_oserror(delay: bool) -> None:
    with local_temporary_directory() as tmp_path_local:
        with helpers.common.patch_context() as context:
            context.setattr(os, "setxattr", Mock(side_effect=OSError))
            context.setattr(os, "getxattr", Mock(side_effect=OSError))
            get_ctime, set_ctime = load_ctime_functions()

            context.setattr(loguru._file_sink, "get_ctime", get_ctime)
            context.setattr(loguru._file_sink, "set_ctime", set_ctime)

            filepath = tmp_path_local / "test.log"
            i = logger.add(filepath, format="{message}", delay=delay, rotation="2 s")
            time.sleep(1)
            logger.info("1")
            logger.remove(i)
            time.sleep(1.5)
            i = logger.add(filepath, format="{message}", delay=delay, rotation="2 s")
            logger.info("2")
            logger.remove(i)
            helpers.common.check_dir(tmp_path_local, size=1)
            assert filepath.read_text() == "1\n2\n", (
                "a filesystem that rejects xattr at run time must be handled like one that "
                "has no xattr at all, rather than propagate the OSError"
            )
            time.sleep(2.5)
            i = logger.add(filepath, format="{message}", delay=delay, rotation="2 s")
            logger.info("3")
            logger.remove(i)
            helpers.common.check_dir(tmp_path_local, size=2)
            assert (
                filepath.read_text() == "3\n"
            ), "the fallback clock must still trigger rotation once the interval elapses"


@oxitest.mark.skip(when=os.name != "nt", reason=WINDOWS_SPECIFIC)
def test_time_rotation_windows_no_setctime(tmp: TempDir) -> None:
    import win32_setctime

    with helpers.common.patch_context() as context:
        context.setattr(win32_setctime, "SUPPORTED", False)
        context.setattr(win32_setctime, "setctime", Mock())

        filepath = tmp.path / "test.log"
        logger.add(filepath, format="{message}", rotation="2 s")
        logger.info("1")
        time.sleep(1.5)
        logger.info("2")
        helpers.common.check_dir(tmp.path, size=1)
        assert (
            filepath.read_text() == "1\n2\n"
        ), "on an unsupported Windows filesystem the rotation clock must still work"
        time.sleep(1)
        logger.info("3")
        helpers.common.check_dir(tmp.path, size=2)
        assert filepath.read_text() == "3\n", "the rotation must still trigger on time"

        assert not win32_setctime.setctime.called, (
            "the unsupported API must not be called at all, otherwise every file open would "
            "pay for a call that is known to fail"
        )


@oxitest.mark.skip(when=os.name != "nt", reason=WINDOWS_SPECIFIC)
@oxitest.parametrize(
    value_error=ExceptionCase(exception=ValueError),
    os_error=ExceptionCase(exception=OSError),
)
def test_time_rotation_windows_setctime_exception(tmp: TempDir, exception: Any) -> None:
    import win32_setctime

    with helpers.common.patch_context() as context:
        context.setattr(win32_setctime, "setctime", Mock(side_effect=exception))

        filepath = tmp.path / "test.log"
        logger.add(filepath, format="{message}", rotation="2 s")
        logger.info("1")
        time.sleep(1.5)
        logger.info("2")
        helpers.common.check_dir(tmp.path, size=1)
        assert (
            filepath.read_text() == "1\n2\n"
        ), "a failure while stamping the creation time must not break logging"
        time.sleep(1)
        logger.info("3")
        helpers.common.check_dir(tmp.path, size=2)
        assert filepath.read_text() == "3\n", "the rotation must still trigger on time"

        assert win32_setctime.setctime.called, (
            "the API must have been attempted; otherwise the test proves nothing about how "
            "its failure is handled"
        )


def test_function_rotation(freeze_time: Fixture[FreezeTime], tmp: TempDir) -> None:
    with freeze_time("2018-01-01 00:00:00") as frozen:
        logger.add(
            tmp.path / "test_{time}.log",
            rotation=Mock(side_effect=[False, True, False]),
            format="{message}",
        )
        logger.debug("a")
        helpers.common.check_dir(tmp.path, files=[("test_2018-01-01_00-00-00_000000.log", "a\n")])

        frozen.move_to("2019-01-01 00:00:00")
        logger.debug("b")
        helpers.common.check_dir(
            tmp.path,
            files=[
                ("test_2018-01-01_00-00-00_000000.log", "a\n"),
                ("test_2019-01-01_00-00-00_000000.log", "b\n"),
            ],
        )

        frozen.move_to("2020-01-01 00:00:00")
        logger.debug("c")
        helpers.common.check_dir(
            tmp.path,
            files=[
                ("test_2018-01-01_00-00-00_000000.log", "a\n"),
                ("test_2019-01-01_00-00-00_000000.log", "b\nc\n"),
            ],
        )


@oxitest.parametrize(
    write=ModeCase(mode="w"),
    exclusive_create=ModeCase(mode="x"),
)
def test_rotation_at_remove(freeze_time: Fixture[FreezeTime], tmp: TempDir, mode: str) -> None:
    with freeze_time("2018-01-01"):
        i = logger.add(
            tmp.path / "test_{time:YYYY}.log",
            rotation="10 MB",
            mode=mode,
            format="{message}",
        )
        logger.debug("test")
        logger.remove(i)

    helpers.common.check_dir(tmp.path, files=[("test_2018.log", "test\n")])


@oxitest.parametrize(
    append=ModeCase(mode="a"),
    append_and_read=ModeCase(mode="a+"),
)
def test_no_rotation_at_remove(tmp: TempDir, mode: str) -> None:
    i = logger.add(tmp.path / "test.log", rotation="10 MB", mode=mode, format="{message}")
    logger.debug("test")
    logger.remove(i)

    helpers.common.check_dir(tmp.path, files=[("test.log", "test\n")])


def test_rename_existing_with_creation_time(freeze_time: Fixture[FreezeTime], tmp: TempDir) -> None:
    with freeze_time("2018-01-01") as frozen:
        logger.add(tmp.path / "test.log", rotation=10, format="{message}")
        logger.debug("X")
        frozen.tick()
        logger.debug("Y" * 20)

    helpers.common.check_dir(
        tmp.path,
        files=[
            ("test.2018-01-01_00-00-00_000000.log", "X\n"),
            ("test.log", "Y" * 20 + "\n"),
        ],
    )


def test_renaming_rotation_dest_exists(freeze_time: Fixture[FreezeTime], tmp: TempDir) -> None:
    with freeze_time("2019-01-02 03:04:05.000006"):
        logger.add(tmp.path / "rotate.log", rotation=Mock(return_value=True), format="{message}")
        logger.info("A")
        logger.info("B")
        logger.info("C")

    helpers.common.check_dir(
        tmp.path,
        files=[
            ("rotate.2019-01-02_03-04-05_000006.log", ""),
            ("rotate.2019-01-02_03-04-05_000006.2.log", "A\n"),
            ("rotate.2019-01-02_03-04-05_000006.3.log", "B\n"),
            ("rotate.log", "C\n"),
        ],
    )


def test_renaming_rotation_dest_exists_with_time(
    freeze_time: Fixture[FreezeTime], tmp: TempDir
) -> None:
    with freeze_time("2019-01-02 03:04:05.000006"):
        logger.add(
            tmp.path / "rotate.{time}.log", rotation=Mock(return_value=True), format="{message}"
        )
        logger.info("A")
        logger.info("B")
        logger.info("C")

    helpers.common.check_dir(
        tmp.path,
        files=[
            ("rotate.2019-01-02_03-04-05_000006.2019-01-02_03-04-05_000006.log", ""),
            ("rotate.2019-01-02_03-04-05_000006.2019-01-02_03-04-05_000006.2.log", "A\n"),
            ("rotate.2019-01-02_03-04-05_000006.2019-01-02_03-04-05_000006.3.log", "B\n"),
            ("rotate.2019-01-02_03-04-05_000006.log", "C\n"),
        ],
    )


def test_exception_during_rotation(tmp: TempDir, cap: StdCapture) -> None:
    logger.add(
        tmp.path / "test.log",
        rotation=Mock(side_effect=[Exception("Rotation error"), False]),
        format="{message}",
        catch=True,
    )

    logger.info("A")
    logger.info("B")

    helpers.common.check_dir(tmp.path, files=[("test.log", "B\n")])

    captured = cap.readouterr()
    assert captured.out == "", "the error report goes to stderr, so stdout must stay empty"
    assert captured.err.count("Logging error in Loguru Handler") == 1, (
        "a failing rotation check must be reported once and must not stop the sink from "
        "handling the next record"
    )
    assert (
        captured.err.count("Exception: Rotation error") == 1
    ), "the report must name the original error so the user knows why nothing rotated"


def test_exception_during_rotation_not_caught(tmp: TempDir, cap: StdCapture) -> None:
    logger.add(
        tmp.path / "test.log",
        rotation=Mock(side_effect=[OSError("Rotation error"), False]),
        format="{message}",
        catch=False,
    )

    with oxitest.raises(OSError, match=r"^Rotation error$"):
        logger.info("A")

    logger.info("B")

    helpers.common.check_dir(tmp.path, files=[("test.log", "B\n")])

    captured = cap.readouterr()
    assert captured.out == captured.err == "", (
        "with catch=False the error propagates to the caller, so loguru must not also print "
        "a report of its own"
    )


def test_recipe_rotation_both_size_and_time(freeze_time: Fixture[FreezeTime], tmp: TempDir) -> None:
    class Rotator:
        def __init__(self, *, size, at):
            now = datetime.datetime.now()

            self._size_limit = size
            self._time_limit = now.replace(hour=at.hour, minute=at.minute, second=at.second)

            if now >= self._time_limit:
                # The current time is already past the target time so it would rotate already.
                # Add one day to prevent an immediate rotation.
                self._time_limit += datetime.timedelta(days=1)

        def should_rotate(self, message, file):
            file.seek(0, 2)
            if file.tell() + len(message) > self._size_limit:
                return True
            excess = message.record["time"].timestamp() - self._time_limit.timestamp()
            if excess >= 0:
                elapsed_days = datetime.timedelta(seconds=excess).days
                self._time_limit += datetime.timedelta(days=elapsed_days + 1)
                return True
            return False

    with freeze_time("2020-01-01 20:00:00") as frozen:
        rotator = Rotator(size=20, at=datetime.time(12, 0, 0))
        logger.add(tmp.path / "file.log", rotation=rotator.should_rotate, format="{message}")
        logger.info("A" * 15)
        frozen.tick()
        logger.info("B" * 10)
        frozen.move_to("2020-01-02 13:00:00")
        logger.info("C")
        frozen.move_to("2020-01-10 13:10:00")
        logger.info("D")
        logger.info("E")

    helpers.common.check_dir(
        tmp.path,
        files=[
            ("file.2020-01-01_20-00-00_000000.log", "A" * 15 + "\n"),
            ("file.2020-01-01_20-00-01_000000.log", "B" * 10 + "\n"),
            ("file.2020-01-02_13-00-00_000000.log", "C\n"),
            ("file.log", "D\nE\n"),
        ],
    )


def test_multiple_rotation_conditions(freeze_time: Fixture[FreezeTime], tmp: TempDir) -> None:
    with freeze_time("2020-01-01 20:00:00") as frozen:
        logger.add(tmp.path / "file.log", rotation=["8 B", "1 min"], format="{message}")
        logger.info("abcde")
        frozen.tick()

        logger.info("fghij")
        frozen.tick()

        logger.info("klm")
        frozen.move_to("2020-01-01 20:01:01")

        logger.info("no")

    helpers.common.check_dir(
        tmp.path,
        files=[
            ("file.2020-01-01_20-00-00_000000.log", "abcde\n"),
            ("file.2020-01-01_20-00-01_000000.log", "fghij\n"),
            ("file.2020-01-01_20-00-02_000000.log", "klm\n"),
            ("file.log", "no\n"),
        ],
    )


def test_empty_rotation_condition_list() -> None:
    with oxitest.raises(ValueError, match=r"^Must provide at least one rotation condition$"):
        logger.add("test.log", rotation=[])


@oxitest.parametrize(
    **_rotation_cases(object(), os, datetime.date(2017, 11, 11), datetime.datetime.now(), 1j)
)
def test_invalid_rotation_type(rotation: Any) -> None:
    with oxitest.raises(TypeError):
        logger.add("test.log", rotation=rotation)


@oxitest.parametrize(
    **_rotation_cases(
        "w-1",
        "h",
        "M",
        "w1at13",
        "www",
        "w",
        "K",
        "foobar MB",
        "01:00:00!UTC",
        "foobar",
        "__dict__",
    )
)
def test_unparsable_rotation(rotation: Union[str, Any]) -> None:
    with oxitest.raises(ValueError, match=r"^Cannot parse rotation from: '[^']+'$"):
        logger.add("test.log", rotation=rotation)


@oxitest.parametrize(**_rotation_cases("w7", "w10", "13 at w2", "[not|a|day] at 12:00"))
def test_invalid_day_rotation(rotation: str) -> None:
    with oxitest.raises(ValueError, match=r"^Invalid day while parsing daytime: '[^']+'$"):
        logger.add("test.log", rotation=rotation)


@oxitest.parametrize(
    **_rotation_cases("2017.11.12", "11:99", "monday at 2017", "w5 at [not|a|time]")
)
def test_invalid_time_rotation(rotation: str) -> None:
    with oxitest.raises(ValueError, match=r"^Invalid time while parsing daytime: '[^']+'$"):
        logger.add("test.log", rotation=rotation)


@oxitest.parametrize(**_rotation_cases("111.111.111 kb", "e KB"))
def test_invalid_value_size_rotation(rotation: str) -> None:
    with oxitest.raises(ValueError, match=r"^Invalid float value while parsing size: '[^']+'$"):
        logger.add("test.log", rotation=rotation)


@oxitest.parametrize(**_rotation_cases("2 days 8 foobar", "1 foobar 3 days", "3 Ki"))
def test_invalid_unit_rotation_duration(rotation: str) -> None:
    with oxitest.raises(ValueError, match=r"^Invalid unit value while parsing duration: '[^']+'$"):
        logger.add("test.log", rotation=rotation)


@oxitest.parametrize(**_rotation_cases("e days", "1.2.3 days"))
def test_invalid_value_rotation_duration(rotation: str) -> None:
    with oxitest.raises(ValueError, match=r"^Invalid float value while parsing duration: '[^']+'$"):
        logger.add("test.log", rotation=rotation)
