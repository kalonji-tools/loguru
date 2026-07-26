import itertools
import time
from threading import Barrier, Thread

from conftest import Writer
from oxitest import Fixture, StdCapture

from loguru import logger

NO_OUTPUT_EXPECTED = (
    "nothing may reach the standard streams: with catch=False any concurrency error would "
    "surface there as a traceback"
)


class NonSafeSink:
    def __init__(self, sleep_time, stop_time=0):
        self.sleep_time = sleep_time
        self.stop_time = stop_time
        self.written = ""
        self.stopped = False

    def write(self, message):
        if self.stopped:
            raise RuntimeError("Can't write on stopped sink")

        length = len(message)
        self.written += message[:length]
        time.sleep(self.sleep_time)
        self.written += message[length:]

    def stop(self):
        time.sleep(self.stop_time)
        self.stopped = True


def test_safe_logging() -> None:
    barrier = Barrier(2)
    counter = itertools.count()

    sink = NonSafeSink(1)
    logger.add(sink, format="{message}", catch=False)

    def threaded():
        barrier.wait()
        logger.info("___{}___", next(counter))

    threads = [Thread(target=threaded) for _ in range(2)]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join()

    logger.remove()

    assert sink.written in ("___0___\n___1___\n", "___1___\n___0___\n"), (
        "the sink sleeps mid-write, so without a handler lock the two messages would "
        "interleave into a corrupted line; only the order between them may vary"
    )


def test_safe_adding_while_logging(writer: Fixture[Writer]) -> None:
    barrier = Barrier(2)
    counter = itertools.count()

    sink_1 = NonSafeSink(1)
    sink_2 = NonSafeSink(1)
    logger.add(sink_1, format="{message}", catch=False)

    def thread_1():
        barrier.wait()
        logger.info("aaa{}bbb", next(counter))

    def thread_2():
        barrier.wait()
        time.sleep(0.5)
        logger.add(sink_2, format="{message}", catch=False)
        logger.info("ccc{}ddd", next(counter))

    threads = [Thread(target=thread_1), Thread(target=thread_2)]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join()

    logger.remove()

    assert sink_1.written == "aaa0bbb\nccc1ddd\n", (
        "adding a sink while another thread is mid-write must not disturb the existing "
        "sink, which has to receive both messages intact"
    )
    assert sink_2.written == "ccc1ddd\n", (
        "a sink added later must receive only what is logged after it was added"
    )


def test_safe_removing_while_logging(cap: StdCapture) -> None:
    barrier = Barrier(2)
    counter = itertools.count()

    sink = NonSafeSink(1)
    i = logger.add(sink, format="{message}", catch=False)

    def thread_1():
        barrier.wait()
        logger.info("aaa{}bbb", next(counter))

    def thread_2():
        barrier.wait()
        time.sleep(0.5)
        logger.remove(i)
        logger.info("ccc{}ddd", next(counter))

    threads = [Thread(target=thread_1), Thread(target=thread_2)]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join()

    captured = cap.readouterr()
    assert captured.out == "", NO_OUTPUT_EXPECTED
    assert captured.err == "", NO_OUTPUT_EXPECTED
    assert sink.written == "aaa0bbb\n", (
        "remove() must wait for the in-flight write to finish and then stop delivery, so the "
        "first message is complete and the second never arrives"
    )


def test_safe_removing_all_while_logging(cap: StdCapture) -> None:
    barrier = Barrier(2)

    for _ in range(1000):
        logger.add(lambda _: None, format="{message}", catch=False)

    def thread_1():
        barrier.wait()
        logger.remove()

    def thread_2():
        barrier.wait()
        for _ in range(100):
            logger.info("Some message")

    threads = [Thread(target=thread_1), Thread(target=thread_2)]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join()

    captured = cap.readouterr()
    assert captured.out == "", NO_OUTPUT_EXPECTED
    assert captured.err == "", NO_OUTPUT_EXPECTED


def test_safe_slow_removing_all_while_logging(cap: StdCapture) -> None:
    barrier = Barrier(2)

    for _ in range(10):
        sink = NonSafeSink(0.1, 0.1)
        logger.add(sink, format="{message}", catch=False)

    def thread_1():
        barrier.wait()
        logger.remove()

    def thread_2():
        barrier.wait()
        time.sleep(0.5)
        logger.info("Some message")

    threads = [Thread(target=thread_1), Thread(target=thread_2)]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join()

    captured = cap.readouterr()
    assert captured.out == "", NO_OUTPUT_EXPECTED
    assert captured.err == "", NO_OUTPUT_EXPECTED


def test_safe_writing_after_removing(cap: StdCapture) -> None:
    barrier = Barrier(2)

    logger.add(NonSafeSink(1), format="{message}", catch=False)
    i = logger.add(NonSafeSink(1), format="{message}", catch=False)

    def write():
        barrier.wait()
        logger.info("Writing")

    def remove():
        barrier.wait()
        time.sleep(0.5)
        logger.remove(i)

    threads = [Thread(target=write), Thread(target=remove)]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join()

    logger.remove()

    captured = cap.readouterr()
    assert captured.out == "", NO_OUTPUT_EXPECTED
    assert captured.err == "", NO_OUTPUT_EXPECTED


def test_heavily_threaded_logging(cap: StdCapture) -> None:
    logger.remove()

    def function():
        i = logger.add(NonSafeSink(0.1), format="{message}", catch=False)
        logger.debug("AAA")
        logger.info("BBB")
        logger.success("CCC")
        logger.remove(i)

    threads = [Thread(target=function) for _ in range(10)]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join()

    logger.remove()

    captured = cap.readouterr()
    assert captured.out == "", NO_OUTPUT_EXPECTED
    assert captured.err == "", NO_OUTPUT_EXPECTED
