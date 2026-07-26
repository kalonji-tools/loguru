import oxitest
from oxitest import TempDir

from loguru import logger


def test_file_mode_a(tmp: TempDir) -> None:
    file = tmp.path / "test.log"
    file.write_text("base\n")
    logger.add(file, format="{message}", mode="a")
    logger.debug("msg")
    assert file.read_text() == "base\nmsg\n", (
        'mode="a" must be forwarded to open(), otherwise a restarted application silently '
        "destroys the log history it was supposed to append to"
    )


def test_file_mode_w(tmp: TempDir) -> None:
    file = tmp.path / "test.log"
    file.write_text("base\n")
    logger.add(file, format="{message}", mode="w")
    logger.debug("msg")
    assert file.read_text() == "msg\n", (
        'mode="w" must be forwarded to open(), otherwise the caller cannot ask for a clean '
        "log file on start-up"
    )


def test_file_auto_buffering(tmp: TempDir) -> None:
    # There doesn't seem to be a reliable way to known buffer size for text files.
    # We perform a preliminary test to ensure empirically that 128 <= buffer size <= 65536.
    dummy_filepath = tmp.path / "dummy.txt"
    with open(str(dummy_filepath), buffering=-1, mode="w") as dummy_file:
        dummy_file.write("." * 127)
        if dummy_filepath.read_text() != "":
            oxitest.skip("Size buffer for text files is too small.")
        dummy_file.write("." * (65536 - 127))
        if dummy_filepath.read_text() == "":
            oxitest.skip("Size buffer for text files is too big.")

    filepath = tmp.path / "test.log"
    logger.add(filepath, format="{message}", buffering=-1)
    logger.debug("A short message.")
    assert filepath.read_text() == "", (
        "buffering=-1 must be forwarded to open(), so a short message stays in the buffer "
        "instead of costing a write syscall per record"
    )
    logger.debug("A long message" + "." * 65536)
    assert filepath.read_text() != "", (
        "the buffer must still flush once it fills up, otherwise records are held in memory "
        "indefinitely and lost if the process dies"
    )


def test_file_line_buffering(tmp: TempDir) -> None:
    filepath = tmp.path / "test.log"
    logger.add(filepath, format=lambda _: "{message}", buffering=1)
    logger.debug("Without newline")
    assert filepath.read_text() == "", (
        "buffering=1 must be forwarded to open(), so output is held until a newline arrives"
    )
    logger.debug("With newline\n")
    assert filepath.read_text() != "", (
        "a newline must flush a line-buffered file, otherwise the option gives no guarantee "
        "that a completed line has reached disk"
    )


def test_invalid_function_kwargs() -> None:
    def function(message):
        pass

    with oxitest.raises(TypeError, match=r"add\(\) got an unexpected keyword argument"):
        logger.add(function, b="X")


def test_invalid_file_object_kwargs() -> None:
    class Writer:
        def __init__(self):
            self.out = ""

        def write(self, m):
            pass

    writer = Writer()

    with oxitest.raises(TypeError, match=r"add\(\) got an unexpected keyword argument"):
        logger.add(writer, format="{message}", kw1="1", kw2="2")


def test_invalid_file_kwargs() -> None:
    with oxitest.raises(TypeError, match=r".*keyword argument;*"):
        logger.add("file.log", nope=123)


def test_invalid_coroutine_kwargs() -> None:
    async def foo():
        pass

    with oxitest.raises(TypeError, match=r"add\(\) got an unexpected keyword argument"):
        logger.add(foo, nope=123)
