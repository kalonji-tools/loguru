from dataclasses import dataclass
from typing import Any, Union

import oxitest
from conftest import Writer
from oxitest import Fixture

from loguru import logger


@dataclass(frozen=True)
class LevelCase:
    level: Union[int, str]


@dataclass(frozen=True)
class InvalidLevelCase:
    level: Any


@oxitest.parametrize(
    zero=LevelCase(level=0),
    lowest_name=LevelCase(level="TRACE"),
    matching_name=LevelCase(level="INFO"),
    matching_severity=LevelCase(level=20),
)
def test_level_low_enough(writer: Fixture[Writer], level: Union[int, str]) -> None:
    logger.add(writer, level=level, format="{message}")
    logger.info("Test level")
    assert writer.read() == "Test level\n", (
        "a sink whose level is at or below INFO must receive the message, otherwise the "
        "severity comparison rejects records it should let through"
    )


@oxitest.parametrize(
    name=LevelCase(level="WARNING"),
    severity=LevelCase(level=25),
)
def test_level_too_high(writer: Fixture[Writer], level: Union[int, str]) -> None:
    logger.add(writer, level=level, format="{message}")
    logger.info("Test level")
    assert writer.read() == "", (
        "a sink whose level is above INFO must drop the message, otherwise level filtering "
        "does not protect sinks from records they opted out of"
    )


@oxitest.parametrize(
    float_level=InvalidLevelCase(level=3.4),
    object_level=InvalidLevelCase(level=object()),
)
def test_invalid_level_type(writer: Fixture[Writer], level: Any) -> None:
    with oxitest.raises(TypeError):
        logger.add(writer, level=level)


def test_invalid_level_value(writer: Fixture[Writer]) -> None:
    with oxitest.raises(
        ValueError, match=r"^Invalid level value, it should be a positive integer, not: -1$"
    ):
        logger.add(writer, level=-1)


def test_unknown_level(writer: Fixture[Writer]) -> None:
    with oxitest.raises(ValueError, match=r"^Level 'foo' does not exist$"):
        logger.add(writer, level="foo")
