"""Pin the dotted name a test module is known by.

Loguru derives a record's ``name`` field from the ``__name__`` of the module that
issued the log call, and a fair number of tests assert on that value (activation
matching, sink filters, ``{name}`` formatting, propagation to ``logging``).

oxitest loads each test module under an opaque, content-hashed internal name, so
those tests would otherwise see something like ``_oxitest_exec_1a2b3c4d5e6f``.
Pinning restores the package-qualified name the tests are written against, and
registers the alias in ``sys.modules`` so that machinery resolving a class back to
its defining module (``dataclasses``, ``pickle``, ``copy``) keeps working.
"""

import sys


def pin_module_name(namespace, name):
    """Rename the calling module to *name*, given its ``globals()`` namespace."""
    namespace["__name__"] = name
    spec = namespace.get("__spec__")
    if spec is not None:
        sys.modules[name] = sys.modules[spec.name]
