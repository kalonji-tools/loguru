import os
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any
from unittest.mock import Mock

import oxitest
import conftest
from conftest import FreezeTime
from oxitest import Fixture, StdCapture, TempDir

from loguru import logger


@dataclass(frozen=True)
class CompressionCase:
    compression: Any


@dataclass(frozen=True)
class ModeCase:
    mode: str


@dataclass(frozen=True)
class DelayCase:
    delay: bool


@dataclass(frozen=True)
class ExtensionCase:
    ext: str


MODE_CASES = {
    "append": ModeCase(mode="a"),
    "append_and_read": ModeCase(mode="a+"),
    "write": ModeCase(mode="w"),
    "exclusive_create": ModeCase(mode="x"),
}

DELAY_CASES = {
    "delayed": DelayCase(delay=True),
    "immediate": DelayCase(delay=False),
}


@oxitest.parametrize(
    gzip=CompressionCase(compression="gz"),
    bzip2=CompressionCase(compression="bz2"),
    zip_archive=CompressionCase(compression="zip"),
    xz=CompressionCase(compression="xz"),
    lzma=CompressionCase(compression="lzma"),
    tar=CompressionCase(compression="tar"),
    tar_gz=CompressionCase(compression="tar.gz"),
    tar_bz2=CompressionCase(compression="tar.bz2"),
    tar_xz=CompressionCase(compression="tar.xz"),
)
def test_compression_ext(tmp: TempDir, compression: str) -> None:
    i = logger.add(tmp.path / "file.log", compression=compression)
    logger.remove(i)

    conftest.check_dir(tmp.path, files=[("file.log.%s" % compression, None)])


def test_compression_function(tmp: TempDir) -> None:
    def compress(file):
        os.replace(file, file + ".rar")

    i = logger.add(tmp.path / "file.log", compression=compress)
    logger.remove(i)

    conftest.check_dir(tmp.path, files=[("file.log.rar", None)])


@oxitest.parametrize(**MODE_CASES)
def test_compression_at_rotation(tmp: TempDir, mode: str, freeze_time: Fixture[FreezeTime]) -> None:
    with freeze_time("2010-10-09 11:30:59"):
        logger.add(
            tmp.path / "file.log", format="{message}", rotation=0, compression="gz", mode=mode
        )
        logger.debug("After compression")

    conftest.check_dir(
        tmp.path,
        files=[
            ("file.2010-10-09_11-30-59_000000.log.gz", None),
            ("file.log", "After compression\n"),
        ],
    )


@oxitest.parametrize(**MODE_CASES)
def test_compression_at_remove_without_rotation(tmp: TempDir, mode: str) -> None:
    i = logger.add(tmp.path / "file.log", compression="gz", mode=mode)
    logger.debug("test")
    logger.remove(i)

    conftest.check_dir(tmp.path, files=[("file.log.gz", None)])


@oxitest.parametrize(**MODE_CASES)
def test_no_compression_at_remove_with_rotation(tmp: TempDir, mode: str) -> None:
    i = logger.add(tmp.path / "test.log", compression="gz", rotation="100 MB", mode=mode)
    logger.debug("test")
    logger.remove(i)

    conftest.check_dir(tmp.path, files=[("test.log", None)])


def test_rename_existing_with_creation_time(tmp: TempDir, freeze_time: Fixture[FreezeTime]) -> None:
    with freeze_time("2018-01-01") as frozen:
        i = logger.add(tmp.path / "test.log", compression="tar.gz")
        logger.debug("test")
        logger.remove(i)
        frozen.tick()
        j = logger.add(tmp.path / "test.log", compression="tar.gz")
        logger.debug("test")
        logger.remove(j)

    conftest.check_dir(
        tmp.path,
        files=[("test.2018-01-01_00-00-00_000000.log.tar.gz", None), ("test.log.tar.gz", None)],
    )


def test_renaming_compression_dest_exists(freeze_time: Fixture[FreezeTime], tmp: TempDir) -> None:
    with freeze_time("2019-01-02 03:04:05.000006"):
        for i in range(4):
            logger.add(tmp.path / "rotate.log", compression=".tar.gz", format="{message}")
            logger.info(str(i))
            logger.remove()

    conftest.check_dir(
        tmp.path,
        files=[
            ("rotate.log.tar.gz", None),
            ("rotate.2019-01-02_03-04-05_000006.log.tar.gz", None),
            ("rotate.2019-01-02_03-04-05_000006.2.log.tar.gz", None),
            ("rotate.2019-01-02_03-04-05_000006.3.log.tar.gz", None),
        ],
    )


def test_renaming_compression_dest_exists_with_time(
    freeze_time: Fixture[FreezeTime], tmp: TempDir
) -> None:
    with freeze_time("2019-01-02 03:04:05.000006"):
        for i in range(4):
            logger.add(tmp.path / "rotate.{time}.log", compression=".tar.gz", format="{message}")
            logger.info(str(i))
            logger.remove()

    conftest.check_dir(
        tmp.path,
        files=[
            ("rotate.2019-01-02_03-04-05_000006.log.tar.gz", None),
            ("rotate.2019-01-02_03-04-05_000006.2019-01-02_03-04-05_000006.log.tar.gz", None),
            ("rotate.2019-01-02_03-04-05_000006.2019-01-02_03-04-05_000006.2.log.tar.gz", None),
            ("rotate.2019-01-02_03-04-05_000006.2019-01-02_03-04-05_000006.3.log.tar.gz", None),
        ],
    )


def test_compression_use_renamed_file_after_rotation(
    tmp: TempDir, freeze_time: Fixture[FreezeTime]
) -> None:
    def rotation(message, _):
        return message.record["extra"].get("rotate", False)

    compression = Mock()

    with freeze_time("2020-01-02"):
        logger.add(
            tmp.path / "test.log", format="{message}", compression=compression, rotation=rotation
        )

        logger.info("Before")
        logger.bind(rotate=True).info("Rotation")
        logger.info("After")

    compression.assert_called_once_with(str(tmp.path / "test.2020-01-02_00-00-00_000000.log"))

    conftest.check_dir(
        tmp.path,
        files=[
            ("test.2020-01-02_00-00-00_000000.log", "Before\n"),
            ("test.log", "Rotation\nAfter\n"),
        ],
    )


def test_threaded_compression_after_rotation(tmp: TempDir) -> None:
    thread = None

    def rename(filepath):
        time.sleep(1)
        os.rename(filepath, str(tmp.path / "test.log.mv"))

    def compression(filepath):
        nonlocal thread
        thread = threading.Thread(target=rename, args=(filepath,))
        thread.start()

    def rotation(message, _):
        return message.record["extra"].get("rotate", False)

    logger.add(
        tmp.path / "test.log", format="{message}", compression=compression, rotation=rotation
    )

    logger.info("Before")
    logger.bind(rotate=True).info("Rotation")
    logger.info("After")

    thread.join()

    conftest.check_dir(
        tmp.path,
        files=[
            ("test.log", "Rotation\nAfter\n"),
            ("test.log.mv", "Before\n"),
        ],
    )


@oxitest.parametrize(**DELAY_CASES)
def test_exception_during_compression_at_rotation(
    freeze_time: Fixture[FreezeTime], tmp: TempDir, cap: StdCapture, delay: bool
) -> None:
    with freeze_time("2017-07-01") as frozen:
        logger.add(
            tmp.path / "test.log",
            format="{message}",
            compression=Mock(side_effect=[Exception("Compression error"), None]),
            rotation=0,
            catch=True,
            delay=delay,
        )
        logger.debug("AAA")
        frozen.tick()
        logger.debug("BBB")

    conftest.check_dir(
        tmp.path,
        files=[
            ("test.2017-07-01_00-00-00_000000.log", ""),
            ("test.2017-07-01_00-00-01_000000.log", ""),
            ("test.log", "BBB\n"),
        ],
    )

    captured = cap.readouterr()
    assert captured.out == "", "the error report goes to stderr, so stdout must stay empty"
    assert captured.err.count("Logging error in Loguru Handler") == 1, (
        "a failing compression must be reported once and must not prevent the following "
        "rotation from succeeding"
    )
    assert captured.err.count("Exception: Compression error") == 1, (
        "the report must name the original error so the user knows why the archive is " "missing"
    )


@oxitest.parametrize(**DELAY_CASES)
def test_exception_during_compression_at_rotation_not_caught(
    freeze_time: Fixture[FreezeTime], tmp: TempDir, cap: StdCapture, delay: bool
) -> None:
    with freeze_time("2017-07-01") as frozen:
        logger.add(
            tmp.path / "test.log",
            format="{message}",
            compression=Mock(side_effect=[OSError("Compression error"), None]),
            rotation=0,
            catch=False,
            delay=delay,
        )
        with oxitest.raises(OSError, match=r"^Compression error$"):
            logger.debug("AAA")

        frozen.tick()
        logger.debug("BBB")

    conftest.check_dir(
        tmp.path,
        files=[
            ("test.2017-07-01_00-00-00_000000.log", ""),
            ("test.2017-07-01_00-00-01_000000.log", ""),
            ("test.log", "BBB\n"),
        ],
    )

    captured = cap.readouterr()
    assert captured.out == captured.err == "", (
        "with catch=False the error propagates to the caller, so loguru must not also print "
        "a report of its own"
    )


@oxitest.parametrize(**DELAY_CASES)
def test_exception_during_compression_at_remove(tmp: TempDir, cap: StdCapture, delay: bool) -> None:
    i = logger.add(
        tmp.path / "test.log",
        format="{message}",
        compression=Mock(side_effect=[OSError("Compression error"), None]),
        catch=True,
        delay=delay,
    )
    logger.debug("AAA")

    with oxitest.raises(OSError, match=r"^Compression error$"):
        logger.remove(i)

    logger.debug("Nope")

    conftest.check_dir(
        tmp.path,
        files=[
            ("test.log", "AAA\n"),
        ],
    )

    captured = cap.readouterr()
    assert captured.out == captured.err == "", (
        "catch only covers logging calls, so a failure during remove() must reach the "
        "caller rather than be reported and swallowed"
    )


@oxitest.parametrize(
    zero=CompressionCase(compression=0),
    boolean=CompressionCase(compression=True),
    module=CompressionCase(compression=os),
    object_instance=CompressionCase(compression=object()),
    set_instance=CompressionCase(compression={"zip"}),
)
def test_invalid_compression_type(compression: Any) -> None:
    with oxitest.raises(TypeError):
        logger.add("test.log", compression=compression)


@oxitest.parametrize(
    rar=CompressionCase(compression="rar"),
    seven_zip=CompressionCase(compression=".7z"),
    tar_zip=CompressionCase(compression="tar.zip"),
    dunder=CompressionCase(compression="__dict__"),
)
def test_unknown_compression(compression: str) -> None:
    with oxitest.raises(ValueError, match=r"^Invalid compression format: '[^']+'$"):
        logger.add("test.log", compression=compression)


@oxitest.parametrize(
    plain=ExtensionCase(ext="gz"),
    tarball=ExtensionCase(ext="tar.gz"),
)
def test_gzip_module_unavailable(ext: str) -> None:
    with conftest.patch_context() as context:
        context.setitem(sys.modules, "gzip", None)
        with oxitest.raises(ImportError):
            logger.add("test.log", compression=ext)


@oxitest.parametrize(
    plain=ExtensionCase(ext="bz2"),
    tarball=ExtensionCase(ext="tar.bz2"),
)
def test_bz2_module_unavailable(ext: str) -> None:
    with conftest.patch_context() as context:
        context.setitem(sys.modules, "bz2", None)
        with oxitest.raises(ImportError):
            logger.add("test.log", compression=ext)


@oxitest.parametrize(
    xz=ExtensionCase(ext="xz"),
    lzma=ExtensionCase(ext="lzma"),
    tarball=ExtensionCase(ext="tar.xz"),
)
def test_lzma_module_unavailable(ext: str) -> None:
    with conftest.patch_context() as context:
        context.setitem(sys.modules, "lzma", None)
        with oxitest.raises(ImportError):
            logger.add("test.log", compression=ext)


@oxitest.parametrize(
    plain=ExtensionCase(ext="tar"),
    gzip=ExtensionCase(ext="tar.gz"),
    bzip2=ExtensionCase(ext="tar.bz2"),
    xz=ExtensionCase(ext="tar.xz"),
)
def test_tarfile_module_unavailable(ext: str) -> None:
    with conftest.patch_context() as context:
        context.setitem(sys.modules, "tarfile", None)
        with oxitest.raises(ImportError):
            logger.add("test.log", compression=ext)


def test_zipfile_module_unavailable() -> None:
    with conftest.patch_context() as context:
        context.setitem(sys.modules, "zipfile", None)
        with oxitest.raises(ImportError):
            logger.add("test.log", compression="zip")
