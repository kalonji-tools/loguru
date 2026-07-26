import contextlib
import os
from dataclasses import dataclass
from stat import S_IMODE
from typing import Iterator

import oxitest
from oxitest import TempDir

from loguru import logger


@contextlib.contextmanager
def cleared_umask() -> Iterator[None]:
    """Neutralize the process umask so the opener's mode is applied verbatim."""
    default = os.umask(0)
    try:
        yield
    finally:
        os.umask(default)


@dataclass(frozen=True)
class PermissionsCase:
    permissions: int


PERMISSIONS_CASES = {
    "all": PermissionsCase(permissions=0o777),
    "no_others_execute": PermissionsCase(permissions=0o766),
    "group_and_others_read": PermissionsCase(permissions=0o744),
    "owner_only": PermissionsCase(permissions=0o700),
    "owner_write_others_execute": PermissionsCase(permissions=0o611),
}


@oxitest.parametrize(**PERMISSIONS_CASES)
def test_log_file_permissions(tmp: TempDir, permissions: int) -> None:
    def file_permission_opener(file, flags):
        return os.open(file, flags, permissions)

    filepath = tmp.path / "file.log"

    with cleared_umask():
        logger.add(filepath, opener=file_permission_opener)
        logger.debug("Message")

    stat_result = os.stat(str(filepath))
    expected = 0o666 if os.name == "nt" else permissions
    assert S_IMODE(stat_result.st_mode) == expected, (
        "the custom opener must decide the log file mode, otherwise the caller cannot restrict "
        "who is able to read logs that may contain sensitive data"
    )


@oxitest.parametrize(**PERMISSIONS_CASES)
def test_rotation_permissions(tmp: TempDir, permissions: int) -> None:
    def file_permission_opener(file, flags):
        return os.open(file, flags, permissions)

    with cleared_umask():
        logger.add(tmp.path / "file.log", rotation=0, opener=file_permission_opener)
        logger.debug("Message")

        files = list(tmp.path.iterdir())
        assert len(files) == 2, (
            "rotating on the first message must leave the rotated file next to the new one, "
            "otherwise there is nothing to check the permissions of"
        )

        for filepath in files:
            stat_result = os.stat(str(filepath))
            expected = 0o666 if os.name == "nt" else permissions
            assert S_IMODE(stat_result.st_mode) == expected, (
                "files created by rotation must reuse the custom opener, otherwise rotated "
                "logs silently become more permissive than the original file"
            )
