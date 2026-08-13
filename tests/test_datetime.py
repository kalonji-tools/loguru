import datetime
import os
import sys
from dataclasses import dataclass
from time import strftime
from typing import Any, Tuple, Type
from unittest.mock import Mock

import freezegun
import oxitest
import conftest
from conftest import FreezeTime, Writer
from oxitest import Fixture, StdCapture, TempDir

import loguru
from loguru import logger

UTC_NAME = "UTC"


@dataclass(frozen=True)
class FormatCase:
    time_format: str
    date: Any
    timezone: Tuple[str, float]
    expected: str


@dataclass(frozen=True)
class OffsetCase:
    time_format: str
    offset: float
    expected: str


@dataclass(frozen=True)
class GmtoffCase:
    tm_gmtoff: int


@dataclass(frozen=True)
class ExceptionCase:
    exception: Type[Exception]


@dataclass(frozen=True)
class ZoneInfoCase:
    date: str
    expected_result: str


@dataclass(frozen=True)
class InvalidFormatCase:
    time_format: str


def _expected_fallback_time_zone():
    # For some reason, Python versions and interpreters return different time zones here.
    return strftime("%Z")


@oxitest.parametrize(
    strftime_utc=FormatCase(
        time_format="%Y-%m-%d %H-%M-%S %f %Z %z",
        date="2018-06-09 01:02:03.000045",
        timezone=("UTC", 0),
        expected="2018-06-09 01-02-03 000045 UTC +0000",
    ),
    tokens_utc=FormatCase(
        time_format="YYYY-MM-DD HH-mm-ss SSSSSS zz ZZ",
        date="2018-06-09 01:02:03.000045",
        timezone=("UTC", 0),
        expected="2018-06-09 01-02-03 000045 UTC +0000",
    ),
    strftime_est=FormatCase(
        time_format="%Y-%m-%d %H-%M-%S %f %Z %z",
        date="2018-06-09 01:02:03.000045",
        timezone=("EST", -18000),
        expected="2018-06-09 01-02-03 000045 EST -0500",
    ),
    tokens_est=FormatCase(
        time_format="YYYY-MM-DD HH-mm-ss SSSSSS zz ZZ",
        date="2018-06-09 01:02:03.000045",
        timezone=("EST", -18000),
        expected="2018-06-09 01-02-03 000045 EST -0500",
    ),
    strftime_forced_utc=FormatCase(
        time_format="%Y-%m-%d %H-%M-%S %f %Z!UTC",
        date="2018-06-09 01:02:03.000045",
        timezone=("UTC", 0),
        expected="2018-06-09 01-02-03 000045 %s" % UTC_NAME,
    ),
    tokens_forced_utc=FormatCase(
        time_format="YYYY-MM-DD HH-mm-ss SSSSSS zz!UTC",
        date="2018-06-09 01:02:03.000045",
        timezone=("UTC", 0),
        expected="2018-06-09 01-02-03 000045 %s" % UTC_NAME,
    ),
    strftime_converted_to_utc=FormatCase(
        time_format="%Y-%m-%d %H-%M-%S %f %Z %z!UTC",
        date="2018-06-09 01:02:03.000045",
        timezone=("EST", -18000),
        expected="2018-06-09 06-02-03 000045 %s +0000" % UTC_NAME,
    ),
    tokens_converted_to_utc=FormatCase(
        time_format="YYYY-MM-DD HH-mm-ss SSSSSS zz ZZ!UTC",
        date="2018-06-09 01:02:03.000045",
        timezone=("UTC", -18000),
        expected="2018-06-09 06-02-03 000045 %s +0000" % UTC_NAME,
    ),
    short_tokens=FormatCase(
        time_format="YY-M-D H-m-s SSS Z",
        date="2005-04-07 09:03:08.002320",
        timezone=("A", 3600),
        expected="05-4-7 9-3-8 002 +01:00",
    ),
    exotic_tokens=FormatCase(
        time_format="Q_DDDD_DDD d_E h_hh A SS ZZ",
        date="2000-01-01 14:00:00.9",
        timezone=("B", -1800),
        expected="1_001_1 5_6 2_02 PM 90 -0030",
    ),
    midnight_is_12_am=FormatCase(
        time_format="hh A",
        date="2018-01-01 00:01:02.000003",
        timezone=("UTC", 0),
        expected="12 AM",
    ),
    noon_is_12_pm=FormatCase(
        time_format="hh A", date="2018-01-01 12:00:00.0", timezone=("UTC", 0), expected="12 PM"
    ),
    eleven_pm=FormatCase(
        time_format="hh A", date="2018-01-01 23:00:00.0", timezone=("UTC", 0), expected="11 PM"
    ),
    escaped_tokens=FormatCase(
        time_format="[YYYY] MM [DD]",
        date="2018-02-03 11:09:00.000002",
        timezone=("UTC", 0),
        expected="YYYY 02 DD",
    ),
    escaped_brackets=FormatCase(
        time_format="[YYYY MM DD]",
        date="2018-01-03 11:03:04.000002",
        timezone=("UTC", 0),
        expected="[2018 01 03]",
    ),
    nested_brackets=FormatCase(
        time_format="[[YY]]",
        date="2018-01-03 11:03:04.000002",
        timezone=("UTC", 0),
        expected="[YY]",
    ),
    empty_brackets=FormatCase(
        time_format="[]", date="2018-01-03 11:03:04.000002", timezone=("UTC", 0), expected=""
    ),
    empty_nested_brackets=FormatCase(
        time_format="[[]]", date="2018-01-03 11:03:04.000002", timezone=("UTC", 0), expected="[]"
    ),
    tokens_around_brackets=FormatCase(
        time_format="SSSSSS[]SSS[]SSSSSS",
        date="2018-01-03 11:03:04.100002",
        timezone=("UTC", 0),
        expected="100002100100002",
    ),
    unclosed_bracket=FormatCase(
        time_format="[HHmmss",
        date="2018-01-03 11:03:04.000002",
        timezone=("UTC", 0),
        expected="[110304",
    ),
    unopened_bracket=FormatCase(
        time_format="HHmmss]",
        date="2018-01-03 11:03:04.000002",
        timezone=("UTC", 0),
        expected="110304]",
    ),
    utc_suffix=FormatCase(
        time_format="HH:mm:ss!UTC",
        date="2018-01-01 11:30:00.0",
        timezone=("A", 7200),
        expected="09:30:00",
    ),
    utc_prefix_is_literal=FormatCase(
        time_format="UTC! HH:mm:ss",
        date="2018-01-01 11:30:00.0",
        timezone=("A", 7200),
        expected="UTC! 11:30:00",
    ),
    leading_utc_marker_is_literal=FormatCase(
        time_format="!UTC HH:mm:ss",
        date="2018-01-01 11:30:00.0",
        timezone=("A", 7200),
        expected="!UTC 11:30:00",
    ),
    utc_marker_after_space=FormatCase(
        time_format="hh:mm:ss A - Z ZZ !UTC",
        date="2018-01-01 12:30:00.0",
        timezone=("A", 5400),
        expected="11:00:00 AM - +00:00 +0000 ",
    ),
    escaped_z_with_utc_marker=FormatCase(
        time_format="YYYY-MM-DD HH:mm:ss[Z]!UTC",
        date="2018-01-03 11:03:04.2",
        timezone=("XYZ", -7200),
        expected="2018-01-03 13:03:04Z",
    ),
    escaped_utc_marker=FormatCase(
        time_format="HH:mm:ss[!UTC]",
        date="2018-01-01 11:30:00.0",
        timezone=("A", 7200),
        expected="11:30:00!UTC",
    ),
    empty_format=FormatCase(
        time_format="",
        date="2018-02-03 11:09:00.000002",
        timezone=("Z", 1800),
        expected="2018-02-03T11:09:00.000002+0030",
    ),
    only_utc_marker=FormatCase(
        time_format="!UTC",
        date="2018-02-03 11:09:00.000002",
        timezone=("Z", 1800),
        expected="2018-02-03T10:39:00.000002+0000",
    ),
    timestamps=FormatCase(
        time_format="X x",
        date="2023-01-01 00:00:00.000500",
        timezone=("UTC", 0),
        expected="1672531200 1672531200000500",
    ),
    year_2242=FormatCase(
        time_format="YYYY-MM-DD HH:mm:ss.SSSSSS x",
        date=datetime.datetime(2242, 3, 16, 12, 56, 32, 999999),  # The year 2242 bug!
        timezone=("UTC", 0),
        expected="2242-03-16 12:56:32.999999 8589934592999999",
    ),
)
def test_formatting(
    writer: Fixture[Writer],
    freeze_time: Fixture[FreezeTime],
    time_format: str,
    date: Any,
    timezone: Tuple[str, float],
    expected: str,
) -> None:
    with freeze_time(date, timezone):
        logger.add(writer, format="{time:%s}" % time_format)
        logger.debug("X")
        result = writer.read()
        assert result == expected + "\n", (
            "the time format must render exactly as documented; both the strftime and the "
            "token syntax are public API and users depend on their precise output"
        )


@oxitest.parametrize(
    strftime_with_fractional_seconds=OffsetCase(
        time_format="%Y-%m-%d %H-%M-%S %f %Z %z",
        offset=7230.099,
        expected="2018-06-09 01-02-03 000000 ABC +020030.099000",
    ),
    tokens_with_whole_seconds=OffsetCase(
        time_format="YYYY-MM-DD HH-mm-ss zz Z ZZ",
        offset=6543,
        expected="2018-06-09 01-02-03 ABC +01:49:03 +014903",
    ),
    negative_offset=OffsetCase(
        time_format="HH-mm-ss zz Z ZZ",
        offset=-12345.06702,
        expected="01-02-03 ABC -03:26:45.067020 -032645.067020",
    ),
)
def test_formatting_timezone_offset_down_to_the_second(
    writer: Fixture[Writer],
    freeze_time: Fixture[FreezeTime],
    time_format: str,
    offset: float,
    expected: str,
) -> None:
    date = datetime.datetime(2018, 6, 9, 1, 2, 3)
    with freeze_time(date, ("ABC", offset)):
        logger.add(writer, format="{time:%s}" % time_format)
        logger.debug("Test")
        result = writer.read()
        assert result == expected + "\n", (
            "offsets are not always a whole number of minutes, so seconds and microseconds "
            "must be rendered rather than rounded away"
        )


def test_locale_formatting(writer: Fixture[Writer], freeze_time: Fixture[FreezeTime]) -> None:
    dt = datetime.datetime(2011, 1, 1, 22, 22, 22, 0)
    with freeze_time(dt):
        logger.add(writer, format="{time:MMMM MMM dddd ddd}")
        logger.debug("Test")
        assert writer.read() == dt.strftime("%B %b %A %a\n"), (
            "month and day names must come from the active locale, matching what strftime "
            "would produce, so logs read naturally on a localized system"
        )


def test_stdout_formatting(freeze_time: Fixture[FreezeTime], cap: StdCapture) -> None:
    with freeze_time("2015-12-25 19:13:18", ("A", 5400)):
        logger.add(sys.stdout, format="{time:YYYY [MM] DD HHmmss Z} {message}")
        logger.debug("Y")
        captured = cap.readouterr()
        assert (
            captured.out == "2015 MM 25 191318 +01:30 Y\n"
        ), "the time format must be applied identically for a stream sink as for any other"
        assert captured.err == "", "the sink targets stdout, so stderr must stay empty"


def test_file_formatting(freeze_time: Fixture[FreezeTime], tmp: TempDir) -> None:
    with freeze_time("2015-12-25 19:13:18", ("A", -5400)):
        logger.add(tmp.path / "{time:YYYY [MM] DD HHmmss ZZ}.log")
        logger.debug("Z")
        assert list(tmp.path.iterdir()) == [tmp.path / "2015 MM 25 191318 -0130.log"], (
            "the same time format must be usable in a file name, so log files can be named "
            "after the moment they were opened"
        )


def test_missing_struct_time_fields(
    writer: Fixture[Writer], freeze_time: Fixture[FreezeTime]
) -> None:
    with freeze_time("2011-01-02 03:04:05.6", ("A", 7200), include_tm_zone=False):
        logger.add(writer, format="{time:YYYY MM DD HH mm ss SSSSSS ZZ zz}")
        logger.debug("X")

        result = writer.read()
        zone = _expected_fallback_time_zone()

        assert result == "2011 01 02 03 04 05 600000 +0200 %s\n" % zone, (
            "some platforms omit tm_zone and tm_gmtoff, so loguru must fall back to the "
            "process time zone instead of raising AttributeError"
        )


@oxitest.parametrize(
    below_minimum=GmtoffCase(tm_gmtoff=-4294963696),
    above_maximum=GmtoffCase(tm_gmtoff=4294963696),
)
def test_value_of_gmtoff_is_invalid(
    writer: Fixture[Writer], freeze_time: Fixture[FreezeTime], tm_gmtoff: int
) -> None:
    with freeze_time("2011-01-02 03:04:05.6", ("ABC", -3600), tm_gmtoff_override=tm_gmtoff):
        logger.add(writer, format="{time:YYYY MM DD HH mm ss SSSSSS ZZ zz}")
        logger.debug("X")

        result = writer.read()
        zone = _expected_fallback_time_zone()

        assert result == "2011 01 02 03 04 05 600000 -0100 %s\n" % zone, (
            "an out-of-range tm_gmtoff must be rejected in favour of the process time zone, "
            "otherwise a broken C library would make datetime construction raise"
        )


@oxitest.parametrize(
    os_error=ExceptionCase(exception=OSError),
    overflow_error=ExceptionCase(exception=OverflowError),
)
def test_localtime_raising_exception(
    writer: Fixture[Writer], freeze_time: Fixture[FreezeTime], exception: Type[Exception]
) -> None:
    with freeze_time("2011-01-02 03:04:05.6", ("A", 7200), include_tm_zone=True):
        with conftest.patch_context() as context:
            mock = Mock(side_effect=exception)
            context.setattr(loguru._datetime, "localtime", mock, raising=True)

            logger.add(writer, format="{time:YYYY MM DD HH mm ss SSSSSS ZZ zz}")
            logger.debug("X")

            assert mock.called, "the patched localtime must be the one loguru calls"

            result = writer.read()
            zone = _expected_fallback_time_zone()

            assert result == "2011 01 02 03 04 05 600000 +0200 %s\n" % zone, (
                "localtime() can fail for dates outside the platform's range, so a failure "
                "must fall back to the process time zone rather than break logging entirely"
            )


@oxitest.mark.skip(when=os.name == "nt", reason="No IANA database available")
@oxitest.parametrize(
    summer=ZoneInfoCase(
        date="2023-07-01 12:00:00",
        expected_result="2023 07 01 14 00 00 000000 +0200 CEST +02:00",  # DST.
    ),
    winter=ZoneInfoCase(
        date="2023-01-01 12:00:00",
        expected_result="2023 01 01 13 00 00 000000 +0100 CET +01:00",  # Non-DST.
    ),
)
def test_update_with_zone_info(
    writer: Fixture[Writer], freeze_time: Fixture[FreezeTime], date: str, expected_result: str
) -> None:
    from zoneinfo import ZoneInfo

    def tz_converter(record):
        record["time"] = record["time"].astimezone(tz=ZoneInfo("Europe/Paris"))

    with freeze_time(date):
        logger.add(writer, format="{time:YYYY MM DD HH mm ss SSSSSS ZZ zz Z}")

        logger.patch(tz_converter).debug("Message")

        result = writer.read()
        assert result == expected_result + "\n", (
            "a patcher must be able to replace the record's tzinfo, and the abbreviation and "
            "offset must then be read from that zone rather than from the original one"
        )


def test_freezegun_mocking(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="[{time:YYYY MM DD HH:mm:ss}] {message}")

    with freezegun.freeze_time("2000-01-01 18:00:05"):
        logger.info("Frozen")

    assert writer.read() == "[2000 01 01 18:00:05] Frozen\n", (
        "loguru must read the clock through the standard functions freezegun patches, "
        "otherwise time cannot be frozen in users' own tests"
    )


@oxitest.parametrize(
    seven_fractional_digits=InvalidFormatCase(time_format="ss.SSSSSSS"),
    eight_fractional_digits=InvalidFormatCase(time_format="SS.SSSSSSSS.SS"),
    nine_fractional_digits=InvalidFormatCase(time_format="HH:mm:ss.SSSSSSSSS"),
    ten_fractional_digits=InvalidFormatCase(time_format="SSSSSSSSSS"),
)
def test_invalid_time_format(writer: Fixture[Writer], time_format: str) -> None:
    logger.add(writer, format="{time:%s} {message}" % time_format, catch=False)
    with oxitest.raises(ValueError, match="Invalid time format"):
        logger.info("Test")
