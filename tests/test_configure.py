import sys

import oxitest
from conftest import Writer
from oxitest import Fixture, StdCapture, TempDir

from loguru import logger
from tests._naming import pin_module_name

# Activation and filter entries below are written against the caller's dotted module name.
pin_module_name(globals(), "tests.test_configure")


def test_handlers(cap: StdCapture, tmp: TempDir) -> None:
    file = tmp.path / "test.log"

    handlers = [
        {"sink": file, "format": "FileSink: {message}"},
        {"sink": sys.stdout, "format": "StdoutSink: {message}"},
    ]

    logger.configure(handlers=handlers)
    logger.debug("test")

    captured = cap.readouterr()

    assert file.read_text() == "FileSink: test\n", (
        "each entry of the handlers list must be installed with its own options, so one "
        "configure() call can set up a whole application's logging"
    )
    assert captured.out == "StdoutSink: test\n", (
        "each entry of the handlers list must be installed with its own options, so one "
        "configure() call can set up a whole application's logging"
    )
    assert captured.err == "", "no handler targets stderr here, so anything there is a leak"


def test_levels(writer: Fixture[Writer]) -> None:
    levels = [{"name": "my_level", "icon": "X", "no": 12}, {"name": "DEBUG", "icon": "!"}]

    logger.add(writer, format="{level.no}|{level.name}|{level.icon}|{message}")
    logger.configure(levels=levels)

    logger.log("my_level", "test")
    logger.debug("no bug")

    assert writer.read() == ("12|my_level|X|test\n" "10|DEBUG|!|no bug\n"), (
        "configure(levels=...) must both create new levels and update existing ones, "
        "otherwise built-in levels could not be re-styled from configuration"
    )


def test_extra(writer: Fixture[Writer]) -> None:
    extra = {"a": 1, "b": 9}

    logger.add(writer, format="{extra[a]} {extra[b]}")
    logger.configure(extra=extra)

    logger.debug("")

    assert writer.read() == "1 9\n", (
        "configure(extra=...) must set the application-wide defaults that every record "
        "starts from"
    )


def test_patcher(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{extra[a]} {extra[b]}")
    logger.configure(patcher=lambda record: record["extra"].update(a=1, b=2))

    logger.debug("")

    assert writer.read() == "1 2\n", (
        "configure(patcher=...) must install a patcher that runs for every record, not just "
        "for the logger the call was made on"
    )


def test_activation(writer: Fixture[Writer]) -> None:
    activation = [("tests", False), ("tests.test_configure", True)]

    logger.add(writer, format="{message}")
    logger.configure(activation=activation)

    logger.debug("Logging")

    assert writer.read() == "Logging\n", (
        "activation entries must be applied in order, so a later, more specific entry can "
        "re-enable a module disabled by a broader one"
    )


def test_dict_unpacking(writer: Fixture[Writer]) -> None:
    config = {
        "handlers": [{"sink": writer, "format": "{level.no} - {extra[x]} {extra[z]} - {message}"}],
        "levels": [{"name": "test", "no": 30}],
        "extra": {"x": 1, "y": 2, "z": 3},
    }

    logger.debug("NOPE")

    logger.configure(**config)

    logger.log("test", "Yes!")

    assert writer.read() == "30 - 1 3 - Yes!\n", (
        "the whole configuration must be expressible as one plain dict, which is what makes "
        "it possible to load logging setup from a config file"
    )


def test_returned_ids(cap: StdCapture) -> None:
    ids = logger.configure(
        handlers=[
            {"sink": sys.stdout, "format": "{message}"},
            {"sink": sys.stderr, "format": "{message}"},
        ]
    )

    assert len(ids) == 2, (
        "configure() must return one id per handler, since that is the only way to remove "
        "them individually later"
    )

    logger.debug("Test")

    captured = cap.readouterr()

    assert captured.out == "Test\n", "both configured handlers must be active"
    assert captured.err == "Test\n", "both configured handlers must be active"

    for i in ids:
        logger.remove(i)

    logger.debug("Nope")

    captured = cap.readouterr()

    assert captured.out == "", "the returned ids must actually identify the handlers"
    assert captured.err == "", "the returned ids must actually identify the handlers"


def test_dont_reset_by_default(writer: Fixture[Writer]) -> None:
    logger.configure(extra={"a": 1}, patcher=lambda r: r["extra"].update(b=2))
    logger.level("b", no=30)
    logger.add(writer, format="{level} {extra[a]} {extra[b]} {message}")

    logger.configure()

    logger.log("b", "Test")

    assert writer.read() == "b 1 2 Test\n", (
        "configure() with no arguments must change nothing, otherwise calling it to read the "
        "current setup would wipe it"
    )


def test_reset_previous_handlers(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message}")

    logger.configure(handlers=[])

    logger.debug("Test")

    assert (
        writer.read() == ""
    ), "passing handlers replaces the existing ones, so an empty list must remove them all"


def test_reset_previous_extra(writer: Fixture[Writer]) -> None:
    logger.configure(extra={"a": 123})
    logger.add(writer, format="{extra[a]}", catch=False)

    logger.configure(extra={})

    with oxitest.raises(ValueError, match=r"Failed to format log record: key 'a' not found."):
        logger.debug("Nope")


def test_reset_previous_patcher(writer: Fixture[Writer]) -> None:
    logger.configure(patcher=lambda r: r.update(a=123))
    logger.add(writer, format="{extra[a]}", catch=False)

    logger.configure(patcher=lambda r: None)

    with oxitest.raises(ValueError, match=r"Failed to format log record: key 'a' not found."):
        logger.debug("Nope")


def test_dont_reset_previous_levels(writer: Fixture[Writer]) -> None:
    logger.level("abc", no=30)

    logger.configure(levels=[])

    logger.add(writer, format="{level} {message}")

    logger.log("abc", "Test")

    assert writer.read() == "abc Test\n", (
        "levels are additive rather than replaced, because removing a level in use would "
        "break every record already referring to it"
    )


def test_configure_handler_using_new_level(writer: Fixture[Writer]) -> None:
    logger.configure(
        levels=[{"name": "CONF_LVL", "no": 33, "icon": "", "color": ""}],
        handlers=[
            {"sink": writer, "level": "CONF_LVL", "format": "{level.name} {level.no} {message}"}
        ],
    )

    logger.log("CONF_LVL", "Custom")
    assert writer.read() == "CONF_LVL 33 Custom\n", (
        "levels must be registered before handlers within a single configure() call, so a "
        "handler can name a level defined in the same call"
    )


def test_configure_filter_using_new_level(writer: Fixture[Writer]) -> None:
    logger.configure(
        levels=[{"name": "CONF_LVL_2", "no": 33, "icon": "", "color": ""}],
        handlers=[
            {"sink": writer, "level": 0, "filter": {"tests": "CONF_LVL_2"}, "format": "{message}"}
        ],
    )

    logger.log("CONF_LVL_2", "Custom")
    assert writer.read() == "Custom\n", (
        "a filter must be able to name a level defined in the same configure() call, for the "
        "same ordering reason as the handler level"
    )


def test_configure_before_bind(writer: Fixture[Writer]) -> None:
    logger.configure(extra={"a": "default_a", "b": "default_b"})
    logger.add(writer, format="{extra[a]} {extra[b]} {message}")

    logger.debug("init")

    logger_a = logger.bind(a="A")
    logger_b = logger.bind(b="B")

    logger_a.debug("aaa")
    logger_b.debug("bbb")

    assert writer.read() == (
        "default_a default_b init\n" "A default_b aaa\n" "default_a B bbb\n"
    ), (
        "bind() must override only the keys it names and inherit the rest from the "
        "configured defaults"
    )


def test_configure_after_bind(writer: Fixture[Writer]) -> None:
    logger_a = logger.bind(a="A")
    logger_b = logger.bind(b="B")

    logger.configure(extra={"a": "default_a", "b": "default_b"})
    logger.add(writer, format="{extra[a]} {extra[b]} {message}")

    logger.debug("init")

    logger_a.debug("aaa")
    logger_b.debug("bbb")

    assert writer.read() == (
        "default_a default_b init\n" "A default_b aaa\n" "default_a B bbb\n"
    ), (
        "defaults are resolved when a record is created, so configure() must apply to "
        "loggers that were bound before it was called"
    )
