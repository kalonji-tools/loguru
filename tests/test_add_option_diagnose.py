from conftest import Writer
from oxitest import Fixture

from loguru import logger

# See "test_catch_exceptions.py" for extended testing


def test_diagnose(writer: Fixture[Writer]) -> None:
    logger.add(writer, format="{message}", diagnose=True)
    try:
        1 / 0  # noqa: B018
    except Exception:
        logger.exception("")
    result_with = writer.read().strip()

    logger.remove()
    writer.clear()

    logger.add(writer, format="{message}", diagnose=False)
    try:
        1 / 0  # noqa: B018
    except Exception:
        logger.exception("")
    result_without = writer.read().strip()

    assert len(result_with.splitlines()) > len(result_without.splitlines()), (
        "diagnose=True must annotate the traceback with variable values, otherwise the option "
        "has no effect and users lose the context that makes the error understandable"
    )
