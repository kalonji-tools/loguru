"""Stateless utilities that test modules need outside a running session.

Everything here is plain module-level code rather than a ``conftest.py`` helper
because these are needed in two places where a session is not running: ``@oxitest.parametrize``
case values, which are built as the test module is imported, and worker functions
executed in a child process. Utilities that are only ever called from inside a test
body live in ``conftest.py`` instead, as plain module-level functions.
"""

import asyncio
import contextlib
import io

import loguru


@contextlib.contextmanager
def new_event_loop_context():
    loop = asyncio.new_event_loop()
    try:
        yield loop
    finally:
        loop.close()


@contextlib.contextmanager
def set_event_loop_context(loop):
    asyncio.set_event_loop(loop)
    try:
        yield
    finally:
        asyncio.set_event_loop(None)


def parse(text, *, strip=False, strict=True):
    """Render loguru color markup the way a colorized sink would."""
    parser = loguru._colorizer.AnsiParser()
    parser.feed(text)
    tokens = parser.done(strict=strict)

    if strip:
        return parser.strip(tokens)
    return parser.colorize(tokens, "")


class StubStream(io.StringIO):
    def fileno(self):
        return 1


class StreamIsattyTrue(StubStream):
    def isatty(self):
        return True


class StreamIsattyFalse(StubStream):
    def isatty(self):
        return False


class StreamIsattyException(StubStream):
    def isatty(self):
        raise RuntimeError


class StreamFilenoException(StreamIsattyTrue):
    def fileno(self):
        raise RuntimeError
