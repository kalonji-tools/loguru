import copy

from oxitest import StdCapture

from loguru import logger


def print_(message):
    print(message, end="")


def test_add_sink_after_deepcopy(cap: StdCapture) -> None:
    logger_ = copy.deepcopy(logger)

    logger_.add(print_, format="{message}", catch=False)

    logger_.info("A")
    logger.info("B")

    captured = cap.readouterr()
    assert captured.out == "A\n", (
        "a sink added to the copy must not be shared with the original, otherwise deepcopy "
        "hands back a logger that is still entangled with the one it was copied from"
    )
    assert captured.err == "", "no sink writes to stderr, so anything there is a leak"


def test_add_sink_before_deepcopy(cap: StdCapture) -> None:
    logger.add(print_, format="{message}", catch=False)

    logger_ = copy.deepcopy(logger)

    logger_.info("A")
    logger.info("B")

    captured = cap.readouterr()
    assert captured.out == "A\nB\n", (
        "a sink added before the copy must be present on both loggers, otherwise deepcopy "
        "loses the configuration it is supposed to duplicate"
    )
    assert captured.err == "", "no sink writes to stderr, so anything there is a leak"


def test_remove_from_original(cap: StdCapture) -> None:
    logger.add(print_, format="{message}", catch=False)

    logger_ = copy.deepcopy(logger)
    logger.remove()

    logger_.info("A")
    logger.info("B")

    captured = cap.readouterr()
    assert captured.out == "A\n", (
        "removing a sink from the original must leave the copy intact, otherwise the two "
        "loggers still share one handler registry"
    )
    assert captured.err == "", "no sink writes to stderr, so anything there is a leak"


def test_remove_from_copy(cap: StdCapture) -> None:
    logger.add(print_, format="{message}", catch=False)

    logger_ = copy.deepcopy(logger)
    logger_.remove()

    logger_.info("A")
    logger.info("B")

    captured = cap.readouterr()
    assert captured.out == "B\n", (
        "removing a sink from the copy must leave the original intact, otherwise the two "
        "loggers still share one handler registry"
    )
    assert captured.err == "", "no sink writes to stderr, so anything there is a leak"
