from dataclasses import dataclass
from typing import Any

import oxitest
import conftest
from conftest import Writer
from oxitest import Fixture

from loguru import logger
from tests._naming import pin_module_name

# These cases assert on how activation matches the caller's dotted module name.
pin_module_name(globals(), "tests.test_activation")


@dataclass(frozen=True)
class ActivationCase:
    name: str
    should_log: bool


@dataclass(frozen=True)
class IncompleteFrameCase:
    simulate: str


@dataclass(frozen=True)
class InvalidNameCase:
    name: Any


INCOMPLETE_FRAME_CASES = {
    "no_globals_name": IncompleteFrameCase(simulate="simulate_f_globals_name_absent"),
    "no_frame": IncompleteFrameCase(simulate="simulate_no_frame_available"),
}

INVALID_NAME_CASES = {
    "integer": InvalidNameCase(name=42),
    "list": InvalidNameCase(name=[]),
    "object": InvalidNameCase(name=object()),
}


@oxitest.parametrize(
    empty=ActivationCase(name="", should_log=False),
    package=ActivationCase(name="tests", should_log=False),
    truncated_package=ActivationCase(name="test", should_log=True),
    extended_package=ActivationCase(name="testsx", should_log=True),
    package_with_dot=ActivationCase(name="tests.", should_log=True),
    module=ActivationCase(name="tests.test_activation", should_log=False),
    module_with_dot=ActivationCase(name="tests.test_activation.", should_log=True),
    module_without_package=ActivationCase(name="test_activation", should_log=True),
    dot=ActivationCase(name=".", should_log=True),
)
def test_disable(writer: Fixture[Writer], name: str, should_log: bool) -> None:
    logger.add(writer, format="{message}")
    logger.disable(name)
    logger.debug("message")
    result = writer.read()

    expected = "message\n" if should_log else ""
    assert result == expected, (
        "disabling %r must only silence the logger when the name matches the current module, "
        "otherwise activation matching is too greedy or too narrow" % name
    )


@oxitest.parametrize(
    empty=ActivationCase(name="", should_log=True),
    package=ActivationCase(name="tests", should_log=True),
    truncated_package=ActivationCase(name="test", should_log=False),
    extended_package=ActivationCase(name="testsx", should_log=False),
    package_with_dot=ActivationCase(name="tests.", should_log=False),
    module=ActivationCase(name="tests.test_activation", should_log=True),
    module_with_dot=ActivationCase(name="tests.test_activation.", should_log=False),
    module_without_package=ActivationCase(name="test_activation", should_log=False),
    dot=ActivationCase(name=".", should_log=False),
)
def test_enable(writer: Fixture[Writer], name: str, should_log: bool) -> None:
    logger.add(writer, format="{message}")
    logger.disable("")
    logger.enable(name)
    logger.debug("message")
    result = writer.read()

    expected = "message\n" if should_log else ""
    assert result == expected, (
        "re-enabling %r must only un-silence the logger when the name matches the current "
        "module, otherwise activation matching is too greedy or too narrow" % name
    )


def test_log_before_enable(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message}")
    logger.disable("")
    logger.debug("nope")
    logger.enable("tests")
    logger.debug("yes")
    result = writer.read()
    assert result == "yes\n", (
        "only the message logged after enable() may reach the sink, otherwise activation is "
        "applied retroactively or not at all"
    )


def test_log_before_disable(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message}")
    logger.enable("")
    logger.debug("yes")
    logger.disable("tests")
    logger.debug("nope")
    result = writer.read()
    assert result == "yes\n", (
        "only the message logged before disable() may reach the sink, otherwise deactivation "
        "does not take effect immediately"
    )


def test_multiple_activations() -> None:
    def n() -> int:
        return len(logger._core.activation_list)

    why = (
        "the activation list must stay minimal: redundant entries mean the logger keeps state "
        "that is already implied by a parent name, which slows down every log call"
    )

    assert n() == 0, why
    logger.enable("")
    assert n() == 0, why
    logger.disable("")
    assert n() == 1, why
    logger.enable("foo")
    assert n() == 2, why
    logger.enable("foo.bar")
    assert n() == 2, why
    logger.disable("foo")
    assert n() == 1, why
    logger.disable("foo.bar")
    assert n() == 1, why
    logger.enable("foo.bar")
    assert n() == 2, why
    logger.disable("foo.bar.baz")
    assert n() == 3, why
    logger.disable("foo.baz")
    assert n() == 3, why
    logger.disable("foo.baz.bar")
    assert n() == 3, why
    logger.enable("foo.baz.bar")
    assert n() == 4, why
    logger.enable("")
    assert n() == 0, why


@oxitest.parametrize(**INCOMPLETE_FRAME_CASES)
def test_log_before_enable_incomplete_frame_context(writer: Fixture[Writer], simulate: str) -> None:
    with getattr(conftest, simulate)():
        logger.add(writer, format="{message}")
        logger.disable(None)
        logger.debug("nope")
        logger.enable(None)
        logger.debug("yes")
        result = writer.read()
    assert result == "yes\n", (
        "activation must still work when the caller frame is incomplete, otherwise loguru "
        "breaks under Dask and Cython where module names cannot be resolved"
    )


@oxitest.parametrize(**INCOMPLETE_FRAME_CASES)
def test_log_before_disable_incomplete_frame_context(
    writer: Fixture[Writer], simulate: str
) -> None:
    with getattr(conftest, simulate)():
        logger.add(writer, format="{message}")
        logger.enable(None)
        logger.debug("yes")
        logger.disable(None)
        logger.debug("nope")
        result = writer.read()
    assert result == "yes\n", (
        "deactivation must still work when the caller frame is incomplete, otherwise loguru "
        "breaks under Dask and Cython where module names cannot be resolved"
    )


@oxitest.parametrize(**INCOMPLETE_FRAME_CASES)
def test_incomplete_frame_context_with_others(writer: Fixture[Writer], simulate: str) -> None:
    with getattr(conftest, simulate)():
        logger.add(writer, format="{message}")
        logger.info("1")
        logger.enable(None)
        logger.disable("foobar")
        logger.enable("foo.bar")
        logger.disable(None)
        logger.info("2")
        logger.enable("foobar")
        logger.enable(None)
        logger.info("3")
        result = writer.read()
    assert result == "1\n3\n", (
        "the None activation entry must be tracked independently of named ones, otherwise "
        "enabling an unrelated module would resurrect messages from an unknown frame"
    )


@oxitest.parametrize(**INVALID_NAME_CASES)
def test_invalid_enable_name(name: Any) -> None:
    with oxitest.raises(TypeError):
        logger.enable(name)


@oxitest.parametrize(**INVALID_NAME_CASES)
def test_invalid_disable_name(name: Any) -> None:
    with oxitest.raises(TypeError):
        logger.disable(name)
