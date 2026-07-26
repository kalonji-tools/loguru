from conftest import Writer
from oxitest import Fixture

from loguru import logger

# See "test_catch_exceptions.py" for extended testing


def test_backtrace(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message}", backtrace=True)
    try:
        1 / 0  # noqa: B018
    except Exception:
        logger.exception("")
    result_with = writer.read().strip()

    logger.remove()
    writer.clear()

    logger.add(writer, format="{message}", backtrace=False)
    try:
        1 / 0  # noqa: B018
    except Exception:
        logger.exception("")
    result_without = writer.read().strip()

    assert len(result_with.splitlines()) > len(result_without.splitlines()), (
        "backtrace=True must add the frames leading up to the error, otherwise the option has "
        "no effect and users cannot see which call path produced the exception"
    )
