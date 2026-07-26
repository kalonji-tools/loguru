from dataclasses import dataclass

import oxitest
from conftest import Writer
from oxitest import Fixture

from loguru import logger


@dataclass(frozen=True)
class LevelOwnerCase:
    using_bound: bool


def test_bind_after_add(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{extra[a]} {message}")
    logger_bound = logger.bind(a=0)
    logger_bound.debug("A")

    assert writer.read() == "0 A\n", (
        "a logger bound after the sink was added must still see that sink, otherwise bind() "
        "would snapshot the handler list instead of sharing it"
    )


def test_bind_before_add(writer: Fixture[Writer]) -> None:
    logger_bound = logger.bind(a=0)
    logger.add(writer, format="{extra[a]} {message}")
    logger_bound.debug("A")

    assert writer.read() == "0 A\n", (
        "a logger bound before the sink was added must pick up the later sink, otherwise "
        "bind() would snapshot the handler list instead of sharing it"
    )


def test_add_using_bound(writer: Fixture[Writer]) -> None:
    logger.configure(extra={"a": -1})
    logger_bound = logger.bind(a=0)
    logger_bound.add(writer, format="{extra[a]} {message}")
    logger.debug("A")
    logger_bound.debug("B")

    assert writer.read() == "-1 A\n0 B\n", (
        "each logger must contribute its own extra values to the shared sink, otherwise the "
        "binding that happened to add the sink would leak into unrelated records"
    )


def test_not_override_parent_logger(writer: Fixture[Writer]) -> None:
    logger_1 = logger.bind(a="a")
    logger_2 = logger_1.bind(a="A")
    logger.add(writer, format="{extra[a]} {message}")

    logger_1.debug("1")
    logger_2.debug("2")

    assert writer.read() == "a 1\nA 2\n", (
        "re-binding a key must produce a new logger rather than mutate its parent, otherwise "
        "a child binding would retroactively change what the parent logs"
    )


def test_override_previous_bound(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{extra[x]} {message}")
    logger.bind(x=1).bind(x=2).debug("3")
    assert writer.read() == "2 3\n", (
        "the innermost bind() must win for a repeated key, otherwise chained bindings would "
        "resolve in an order users cannot predict"
    )


def test_no_conflict(writer: Fixture[Writer]) -> None:
    logger_ = logger.bind()
    logger_2 = logger_.bind(a=2)
    logger_3 = logger_.bind(a=3)

    logger.add(writer, format="{extra[a]} {message}")

    logger_2.debug("222")
    logger_3.debug("333")

    assert writer.read() == "2 222\n3 333\n", (
        "sibling bindings from one parent must not observe each other, otherwise per-request "
        "context from one code path bleeds into another"
    )


@oxitest.parametrize(
    from_bound_logger=LevelOwnerCase(using_bound=True),
    from_root_logger=LevelOwnerCase(using_bound=False),
)
def test_bind_and_add_level(writer: Fixture[Writer], using_bound: bool) -> None:
    logger_bound = logger.bind()
    logger.add(writer, format="{level.name} {message}")

    if using_bound:
        logger_bound.level("bar", 15)
    else:
        logger.level("bar", 15)

    logger.log("bar", "root")
    logger_bound.log("bar", "bound")

    assert writer.read() == "bar root\nbar bound\n", (
        "custom levels live on the shared core, so registering one through either logger "
        "must make it usable from both"
    )


def test_override_configured(writer: Fixture[Writer]) -> None:
    logger.configure(extra={"a": 1})
    logger2 = logger.bind(a=2)

    logger2.add(writer, format="{extra[a]} {message}")

    logger2.debug("?")

    assert writer.read() == "2 ?\n", (
        "bind() must take precedence over configure(extra=...), otherwise per-call context "
        "could never override an application-wide default"
    )
