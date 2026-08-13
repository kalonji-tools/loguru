import os
from dataclasses import dataclass
from typing import Any, Callable, Optional
from unittest.mock import Mock

import oxitest
import conftest
from oxitest import TempDir

from loguru import logger

WINDOWS_KEEPS_FILES_LOCKED = "Windows can't delete file in use"


@dataclass
class ClosedCase:
    delay: bool
    compression: Optional[Callable[[Any], None]]


@oxitest.mark.skip(when=os.name == "nt", reason=WINDOWS_KEEPS_FILES_LOCKED)
def test_file_deleted_before_write_without_delay(tmp: TempDir) -> None:
    file = tmp.path / "test.log"
    logger.add(file, format="{message}", watch=True, delay=False)
    os.remove(str(file))
    logger.info("Test")
    assert file.read_text() == "Test\n", (
        "watch=True must re-create a file removed behind loguru's back, otherwise messages "
        "written after log rotation by an external tool go nowhere"
    )


@oxitest.mark.skip(when=os.name == "nt", reason=WINDOWS_KEEPS_FILES_LOCKED)
def test_file_deleted_before_write_with_delay(tmp: TempDir) -> None:
    file = tmp.path / "test.log"
    logger.add(file, format="{message}", watch=True, delay=True)
    logger.info("Test 1")
    os.remove(str(file))
    logger.info("Test 2")
    assert file.read_text() == "Test 2\n", (
        "the watch check must also run for a delayed sink, otherwise combining delay with "
        "watch would leave the file un-monitored after its deferred creation"
    )


@oxitest.mark.skip(when=os.name == "nt", reason=WINDOWS_KEEPS_FILES_LOCKED)
def test_file_path_containing_placeholder(tmp: TempDir) -> None:
    logger.add(tmp.path / "test_{time}.log", format="{message}", watch=True)
    conftest.check_dir(tmp.path, size=1)
    filepath = next(tmp.path.iterdir())
    os.remove(str(filepath))
    logger.info("Test")
    conftest.check_dir(tmp.path, size=1)
    assert filepath.read_text() == "Test\n", (
        "re-creating the file must reuse the already-resolved name, otherwise a {time} "
        "placeholder would produce a brand-new file on every re-open"
    )


@oxitest.mark.skip(when=os.name == "nt", reason=WINDOWS_KEEPS_FILES_LOCKED)
def test_file_reopened_with_arguments(tmp: TempDir) -> None:
    file = tmp.path / "test.log"
    logger.add(file, format="{message}", watch=True, encoding="ascii", errors="replace")
    os.remove(str(file))
    logger.info("é")
    assert file.read_text() == "?\n", (
        "the re-opened file must keep the original encoding and error policy, otherwise a "
        "silent re-open would change how bytes are written half-way through a run"
    )


@oxitest.mark.skip(when=os.name == "nt", reason=WINDOWS_KEEPS_FILES_LOCKED)
def test_file_manually_changed(tmp: TempDir) -> None:
    file = tmp.path / "test.log"
    logger.add(file, format="{message}", watch=True, mode="w")
    os.remove(str(file))
    file.write_text("Placeholder")
    logger.info("Test")
    assert file.read_text() == "Test\n", (
        'the re-opened file must keep mode="w", so a file replaced externally is truncated '
        "exactly as it was on the initial open"
    )


@oxitest.mark.skip(when=os.name == "nt", reason=WINDOWS_KEEPS_FILES_LOCKED)
def test_file_folder_deleted(tmp: TempDir) -> None:
    file = tmp.path / "foo/bar/test.log"
    logger.add(file, format="{message}", watch=True)
    os.remove(str(file))
    os.rmdir(str(tmp.path / "foo/bar"))
    logger.info("Test")
    assert file.read_text() == "Test\n", (
        "re-creating the file must re-create its parent directories too, otherwise removing "
        "the log folder permanently breaks the sink"
    )


@oxitest.mark.skip(when=os.name == "nt", reason=WINDOWS_KEEPS_FILES_LOCKED)
def test_file_deleted_before_rotation(tmp: TempDir) -> None:
    exists = None
    file = tmp.path / "test.log"

    def rotate(_, __):
        nonlocal exists
        exists = file.exists()
        return False

    logger.add(file, format="{message}", watch=True, rotation=rotate)
    os.remove(str(file))
    logger.info("Test")
    assert exists is True, (
        "the file must be restored before the rotation function is consulted, otherwise a "
        "user-supplied rotation callback has to cope with a missing file"
    )


@oxitest.mark.skip(when=os.name == "nt", reason=WINDOWS_KEEPS_FILES_LOCKED)
def test_file_deleted_before_compression(tmp: TempDir) -> None:
    exists = None
    file = tmp.path / "test.log"

    def compress(_):
        nonlocal exists
        exists = file.exists()
        return False

    logger.add(file, format="{message}", watch=True, compression=compress)
    os.remove(str(file))
    logger.remove()
    assert exists is True, (
        "the file must be restored before the compression function is consulted, otherwise "
        "a user-supplied compression callback has to cope with a missing file"
    )


@oxitest.mark.skip(when=os.name == "nt", reason=WINDOWS_KEEPS_FILES_LOCKED)
def test_file_deleted_before_retention(tmp: TempDir) -> None:
    exists = None
    file = tmp.path / "test.log"

    def retain(_):
        nonlocal exists
        exists = file.exists()
        return False

    logger.add(file, format="{message}", watch=True, retention=retain)
    os.remove(str(file))
    logger.remove()
    assert exists is True, (
        "the file must be restored before the retention function is consulted, otherwise a "
        "user-supplied retention callback has to cope with a missing file"
    )


def test_file_correctly_reused_after_rotation(tmp: TempDir) -> None:
    filepath = tmp.path / "test.log"
    logger.add(
        filepath,
        format="{message}",
        mode="w",
        watch=True,
        rotation=Mock(side_effect=[False, True, False]),
    )
    logger.info("Test 1")
    logger.info("Test 2")
    logger.info("Test 3")
    conftest.check_dir(tmp.path, size=2)
    rotated = next(f for f in tmp.path.iterdir() if f != filepath)
    assert rotated.read_text() == "Test 1\n", (
        "the rotated file must hold only what preceded the rotation, otherwise watch mode "
        "confuses the freshly re-opened file with the archived one"
    )
    assert filepath.read_text() == "Test 2\nTest 3\n", (
        "the new file must be appended to after rotation rather than truncated again, "
        'otherwise mode="w" plus watch would keep discarding earlier messages'
    )


@oxitest.parametrize(
    delayed=oxitest.partial(ClosedCase, delay=True),
    immediate=oxitest.partial(ClosedCase, delay=False),
)
@oxitest.parametrize(
    without_compression=oxitest.partial(ClosedCase, compression=None),
    with_compression=oxitest.partial(ClosedCase, compression=lambda _: None),
)
def test_file_closed_without_being_logged(
    tmp: TempDir, delay: bool, compression: Optional[Callable[[Any], None]]
) -> None:
    filepath = tmp.path / "test.log"
    logger.add(
        filepath,
        format="{message}",
        watch=True,
        delay=delay,
        compression=compression,
    )
    logger.remove()
    assert filepath.exists() is (False if delay else True), (
        "closing a watched sink that never logged must not create the file just to satisfy "
        "the watch check, otherwise delay=True would leave empty files behind"
    )
