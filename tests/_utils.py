"""Stateless utilities that test modules need at *import* time.

Everything here is plain module-level code rather than a ``conftest.py`` helper
because ``@oxitest.parametrize`` case values are built while the test module is
being imported, and the ``oxitest.helpers`` proxy only resolves once a session is
running. Utilities that are only ever called from inside a test body live in
``conftest.py`` instead, registered on the ``common`` helper namespace.
"""

import io

import loguru


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
