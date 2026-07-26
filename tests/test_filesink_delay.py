import datetime
import time

from conftest import FreezeTime
from oxitest import Fixture, TempDir, helpers

from loguru import logger


def test_file_not_delayed(tmp: TempDir) -> None:
    file = tmp.path / "test.log"
    logger.add(file, format="{message}", delay=False)
    assert file.read_text() == "", (
        "without delay the file must exist and be empty right after add(), so that a missing "
        "log directory is reported at configuration time rather than on the first message"
    )
    logger.debug("Not delayed")
    assert file.read_text() == "Not delayed\n", (
        "the already-open file must receive the message, otherwise opening eagerly bought "
        "nothing"
    )


def test_file_delayed(tmp: TempDir) -> None:
    file = tmp.path / "test.log"
    logger.add(file, format="{message}", delay=True)
    assert not file.exists(), (
        "with delay the file must not be created until something is logged, otherwise every "
        "run leaves empty files behind for sinks that are never used"
    )
    logger.debug("Delayed")
    assert file.read_text() == "Delayed\n", (
        "the first message must trigger the deferred open, otherwise delay would drop records"
    )


def test_compression(tmp: TempDir) -> None:
    i = logger.add(tmp.path / "file.log", compression="gz", delay=True)
    logger.debug("a")
    logger.remove(i)

    helpers.common.check_dir(tmp.path, files=[("file.log.gz", None)])


def test_compression_early_remove(tmp: TempDir) -> None:
    i = logger.add(tmp.path / "file.log", compression="gz", delay=True)
    logger.remove(i)
    helpers.common.check_dir(tmp.path, size=0)


def test_retention(tmp: TempDir) -> None:
    for i in range(5):
        tmp.path.joinpath("test.2020-01-01_01-01-%d_000001.log" % i).write_text("test")

    i = logger.add(tmp.path / "test.log", retention=0, delay=True)
    logger.debug("a")
    logger.remove(i)

    helpers.common.check_dir(tmp.path, size=0)


def test_retention_early_remove(tmp: TempDir) -> None:
    for i in range(5):
        tmp.path.joinpath("test.2020-01-01_01-01-%d_000001.log" % i).write_text("test")

    i = logger.add(tmp.path / "test.log", retention=0, delay=True)
    logger.remove(i)

    helpers.common.check_dir(tmp.path, size=0)


def test_rotation(tmp: TempDir, freeze_time: Fixture[FreezeTime]) -> None:
    with freeze_time("2001-02-03"):
        i = logger.add(tmp.path / "file.log", rotation=0, delay=True, format="{message}")
        logger.debug("a")
        logger.remove(i)

    helpers.common.check_dir(
        tmp.path,
        files=[
            ("file.2001-02-03_00-00-00_000000.log", ""),
            ("file.log", "a\n"),
        ],
    )


def test_rotation_early_remove(tmp: TempDir) -> None:
    i = logger.add(tmp.path / "file.log", rotation=0, delay=True, format="{message}")
    logger.remove(i)

    helpers.common.check_dir(tmp.path, size=0)


def test_rotation_and_retention(freeze_time: Fixture[FreezeTime], tmp: TempDir) -> None:
    with freeze_time("1999-12-12") as frozen:
        filepath = tmp.path / "file.log"
        logger.add(filepath, rotation=30, retention=2, delay=True, format="{message}")
        for i in range(1, 10):
            time.sleep(0.05)  # Retention is based on mtime.
            frozen.tick(datetime.timedelta(seconds=0.05))
            logger.info(str(i) * 20)

    helpers.common.check_dir(
        tmp.path,
        files=[
            ("file.1999-12-12_00-00-00_350000.log", "7" * 20 + "\n"),
            ("file.1999-12-12_00-00-00_400000.log", "8" * 20 + "\n"),
            ("file.log", "9" * 20 + "\n"),
        ],
    )


def test_rotation_and_retention_timed_file(
    freeze_time: Fixture[FreezeTime], tmp: TempDir
) -> None:
    with freeze_time("1999-12-12") as frozen:
        filepath = tmp.path / "file.{time}.log"
        logger.add(filepath, rotation=30, retention=2, delay=True, format="{message}")
        for i in range(1, 10):
            time.sleep(0.05)  # Retention is based on mtime.
            frozen.tick(datetime.timedelta(seconds=0.05))
            logger.info(str(i) * 20)

    helpers.common.check_dir(
        tmp.path,
        files=[
            ("file.1999-12-12_00-00-00_350000.log", "7" * 20 + "\n"),
            ("file.1999-12-12_00-00-00_400000.log", "8" * 20 + "\n"),
            ("file.1999-12-12_00-00-00_450000.log", "9" * 20 + "\n"),
        ],
    )
