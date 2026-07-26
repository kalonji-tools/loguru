import io
import pathlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import oxitest
from oxitest import TempDir

from loguru import logger

TEXT = "This\nIs\nRandom\nText\n123456789\nABC!DEF\nThis Is The End\n"


@dataclass(frozen=True)
class ChunkCase:
    chunk: int


@dataclass(frozen=True)
class InvalidValueCase:
    value: Any


INVALID_VALUE_CASES = {
    "object_instance": InvalidValueCase(value=object()),
    "integer": InvalidValueCase(value=123),
    "type_object": InvalidValueCase(value=dict),
}


def test_parse_file(tmp: TempDir) -> None:
    file = tmp.path / "test.log"
    file.write_text(TEXT)
    result, *_ = list(logger.parse(file, r"(?P<num>\d+)"))
    assert result == dict(num="123456789"), (
        "parse() must accept a path-like object and open it itself, otherwise callers have "
        "to manage the file handle for the common case"
    )


def test_parse_fileobj(tmp: TempDir) -> None:
    file = tmp.path / "test.log"
    file.write_text(TEXT)
    with open(str(file)) as fileobj:
        result, *_ = list(logger.parse(fileobj, r"^(?P<t>\w+)"))
    assert result == dict(t="This"), (
        "parse() must accept an already-open file object, so callers can control encoding "
        "and buffering themselves"
    )


def test_parse_pathlib(tmp: TempDir) -> None:
    file = tmp.path / "test.log"
    file.write_text(TEXT)
    result, *_ = list(logger.parse(pathlib.Path(str(file)), r"(?P<r>Random)"))
    assert result == dict(r="Random"), (
        "parse() must accept a pathlib.Path, which is the idiomatic way to name a file"
    )


def test_parse_string_pattern() -> None:
    with io.StringIO(TEXT) as fileobj:
        result, *_ = list(logger.parse(fileobj, r"(?P<num>\d+)"))
    assert result == dict(num="123456789"), (
        "a pattern given as a string must be compiled by parse(), otherwise every caller "
        "has to pre-compile it"
    )


def test_parse_regex_pattern() -> None:
    with io.StringIO(TEXT) as fileobj:
        regex = re.compile(r"(?P<maj>[a-z]*![a-z]*)", flags=re.I)
        result, *_ = list(logger.parse(fileobj, regex))
    assert result == dict(maj="ABC!DEF"), (
        "a pre-compiled pattern must be used as given, flags included, otherwise the caller "
        "cannot control matching behaviour"
    )


def test_parse_multiline_pattern() -> None:
    with io.StringIO(TEXT) as fileobj:
        result, *_ = list(logger.parse(fileobj, r"(?P<text>This[\s\S]*Text\n)"))
    assert result == dict(text="This\nIs\nRandom\nText\n"), (
        "matching must run across line boundaries, otherwise multi-line records such as "
        "tracebacks could never be recovered from a log file"
    )


def test_parse_without_group() -> None:
    with io.StringIO(TEXT) as fileobj:
        result, *_ = list(logger.parse(fileobj, r"\d+"))
    assert result == {}, (
        "a pattern with no named group must still yield one empty dict per match, so the "
        "caller can count occurrences without the API raising"
    )


def test_parse_bytes() -> None:
    with io.BytesIO(b"Testing bytes!") as fileobj:
        result, *_ = list(logger.parse(fileobj, rb"(?P<ponct>[?!:])"))
    assert result == dict(ponct=b"!"), (
        "binary files must be parsed with bytes patterns and yield bytes groups, otherwise "
        "logs written in an unknown encoding cannot be parsed at all"
    )


@oxitest.parametrize(
    whole_file=ChunkCase(chunk=-1),
    single_byte=ChunkCase(chunk=1),
    large_block=ChunkCase(chunk=2**16),
)
def test_chunk(chunk: int) -> None:
    with io.StringIO(TEXT) as fileobj:
        result, *_ = list(logger.parse(fileobj, r"(?P<a>[ABC]+)", chunk=chunk))
    assert result == dict(a="ABC"), (
        "the chunk size is a memory/throughput trade-off only, so results must not depend "
        "on it even when a match spans a chunk boundary"
    )


def test_positive_lookbehind_pattern() -> None:
    text = "ab" * 100
    pattern = r"(?<=a)(?P<b>b)"
    with io.StringIO(text) as file:
        result = list(logger.parse(file, pattern, chunk=9))
    assert result == [dict(b="b")] * 100, (
        "chunk boundaries must keep enough preceding text for lookbehind to work, otherwise "
        "matches are silently missed at every boundary"
    )


def test_greedy_pattern() -> None:
    text = ("\n" + "a" * 100) * 1000
    pattern = r"\n(?P<a>a+)"
    with io.StringIO(text) as file:
        result = list(logger.parse(file, pattern, chunk=30))
    assert result == [dict(a="a" * 100)] * 1000, (
        "a greedy match longer than the chunk must be completed by reading further, "
        "otherwise long records are truncated at an arbitrary point"
    )


def test_cast_dict(tmp: TempDir) -> None:
    file = tmp.path / "test.log"
    file.write_text("[123] [1.1] [2017-03-29 11:11:11]\n")
    regex = r"\[(?P<num>.*)\] \[(?P<val>.*)\] \[(?P<date>.*)\]"
    caster = dict(num=int, val=float, date=lambda d: datetime.strptime(d, "%Y-%m-%d %H:%M:%S"))
    result = next(logger.parse(file, regex, cast=caster))
    assert result == dict(num=123, val=1.1, date=datetime(2017, 3, 29, 11, 11, 11)), (
        "a per-group cast mapping must convert each group, otherwise callers get strings and "
        "have to post-process every result themselves"
    )


def test_cast_function(tmp: TempDir) -> None:
    file = tmp.path / "test.log"
    file.write_text("[123] [1.1] [2017-03-29 11:11:11]\n")
    regex = r"\[(?P<num>.*)\] \[(?P<val>.*)\] \[(?P<date>.*)\]"

    def caster(groups):
        groups["num"] = int(groups["num"])
        groups["val"] = float(groups["val"])
        groups["date"] = datetime.strptime(groups["date"], "%Y-%m-%d %H:%M:%S")

    result = next(logger.parse(file, regex, cast=caster))
    assert result == dict(num=123, val=1.1, date=datetime(2017, 3, 29, 11, 11, 11)), (
        "a cast callable must be able to mutate the whole group dict, which is the only way "
        "to express conversions that depend on more than one group"
    )


def test_cast_with_irrelevant_arg(tmp: TempDir) -> None:
    file = tmp.path / "test.log"
    file.write_text("[123] Blabla")
    regex = r"\[(?P<a>\d+)\] .*"
    caster = dict(a=int, b=float)
    result = next(logger.parse(file, regex, cast=caster))
    assert result == dict(a=123), (
        "a cast entry for a group the pattern does not define must be ignored, so one "
        "caster can be reused across several patterns"
    )


def test_cast_with_irrelevant_value(tmp: TempDir) -> None:
    file = tmp.path / "test.log"
    file.write_text("[123] Blabla")
    regex = r"\[(?P<a>\d+)\] (?P<b>.*)"
    caster = dict(a=int)
    result = next(logger.parse(file, regex, cast=caster))
    assert result == dict(a=123, b="Blabla"), (
        "groups with no cast entry must be returned untouched rather than dropped"
    )


@oxitest.parametrize(**INVALID_VALUE_CASES)
def test_invalid_file(value: Any) -> None:
    with oxitest.raises(TypeError):
        next(logger.parse(value, r"pattern"))


@oxitest.parametrize(**INVALID_VALUE_CASES)
def test_invalid_pattern(value: Any) -> None:
    with io.StringIO(TEXT) as fileobj, oxitest.raises(TypeError):
        next(logger.parse(fileobj, value))


@oxitest.parametrize(
    object_instance=InvalidValueCase(value=object()),
    integer=InvalidValueCase(value=123),
)
def test_invalid_cast(value: Any) -> None:
    with io.StringIO(TEXT) as fileobj, oxitest.raises(TypeError):
        next(logger.parse(fileobj, r"pattern", cast=value))
