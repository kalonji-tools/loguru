from conftest import Writer
from oxitest import Fixture

from loguru import logger


def test_patch_after_add(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{extra[a]} {message}")
    logger_patched = logger.patch(lambda r: r["extra"].update(a=0))
    logger_patched.debug("A")

    assert writer.read() == "0 A\n", (
        "a logger patched after the sink was added must still see that sink, otherwise "
        "patch() would snapshot the handler list instead of sharing it"
    )


def test_patch_before_add(writer: Fixture[Writer]) -> None:
    logger_patched = logger.patch(lambda r: r["extra"].update(a=0))
    logger.add(writer, format="{extra[a]} {message}")
    logger_patched.debug("A")

    assert writer.read() == "0 A\n", (
        "a logger patched before the sink was added must pick up the later sink, otherwise "
        "patch() would snapshot the handler list instead of sharing it"
    )


def test_add_using_patched(writer: Fixture[Writer]) -> None:
    logger.configure(patcher=lambda r: r["extra"].update(a=-1))
    logger_patched = logger.patch(lambda r: r["extra"].update(a=0))
    logger_patched.add(writer, format="{extra[a]} {message}")
    logger.debug("A")
    logger_patched.debug("B")

    assert writer.read() == "-1 A\n0 B\n", (
        "each logger must run its own patcher against the shared sink, otherwise the patcher "
        "that happened to add the sink would leak into unrelated records"
    )


def test_not_override_parent_logger(writer: Fixture[Writer]) -> None:
    logger_1 = logger.patch(lambda r: r["extra"].update(a="a"))
    logger_2 = logger_1.patch(lambda r: r["extra"].update(a="A"))
    logger.add(writer, format="{extra[a]} {message}")

    logger_1.debug("1")
    logger_2.debug("2")

    assert writer.read() == "a 1\nA 2\n", (
        "patching a child must not mutate its parent, otherwise a derived logger would "
        "retroactively change what the parent records"
    )


def test_override_previous_patched(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{extra[x]} {message}")
    logger2 = logger.patch(lambda r: r["extra"].update(x=3))
    logger2.patch(lambda r: r["extra"].update(x=2)).debug("4")
    assert writer.read() == "2 4\n", (
        "patchers must run outermost-first so the innermost one has the final say, otherwise "
        "the resolution order would be unpredictable"
    )


def test_no_conflict(writer: Fixture[Writer]) -> None:
    logger_ = logger.patch(lambda r: None)
    logger_2 = logger_.patch(lambda r: r["extra"].update(a=2))
    logger_3 = logger_.patch(lambda r: r["extra"].update(a=3))

    logger.add(writer, format="{extra[a]} {message}")

    logger_2.debug("222")
    logger_3.debug("333")

    assert writer.read() == "2 222\n3 333\n", (
        "sibling patchers from one parent must not observe each other, otherwise per-request "
        "context from one code path bleeds into another"
    )


def test_override_configured(writer: Fixture[Writer]) -> None:
    logger.configure(patcher=lambda r: r["extra"].update(a=123, b=678))
    logger2 = logger.patch(lambda r: r["extra"].update(a=456))

    logger2.add(writer, format="{extra[a]} {extra[b]} {message}")

    logger2.debug("!")

    assert writer.read() == "456 678 !\n", (
        "a local patcher must run after the configured one and may override individual keys "
        "without discarding the rest of what configure() set"
    )


def test_multiple_patches(writer: Fixture[Writer]) -> None:
    def patch_1(record):
        record["extra"]["a"] = 5

    def patch_2(record):
        record["extra"]["a"] += 1

    def patch_3(record):
        record["extra"]["a"] *= 2

    logger.add(writer, format="{extra[a]} {message}")
    logger.patch(patch_1).patch(patch_2).patch(patch_3).info("Test")

    assert writer.read() == "12 Test\n", (
        "chained patchers must all run, in declaration order: (5 + 1) * 2 only holds if none "
        "is skipped and none is applied out of sequence"
    )


def test_patcher_added_keys_work_in_format(writer: Fixture[Writer]) -> None:
    def patcher(record):
        record["my_value"] = 42

    logger.add(writer, format="{message} | {my_value}")
    logger.configure(patcher=patcher)
    logger.info("Hello")
    assert "Hello | 42" in writer.read(), (
        "a patcher must be able to add entirely new record keys, otherwise formats cannot "
        "reference application-specific fields"
    )
