import sys

import oxitest

try:
    mypy_api = None  # type: Optional[ModuleType]
    import mypy.api as mypy_api  # noqa: F811
except ImportError:
    pass


@oxitest.mark.skip(when=mypy_api is None, reason="Requires mypy to be installed.")
def test_mypy_import() -> None:
    # Check stub file is valid and can be imported by Mypy.
    # There exist others tests in "typesafety" subfolder but they require a recent Python version.
    out, _, result = mypy_api.run(["--strict", "-c", "from loguru import logger"])
    print("".join(out), file=sys.stderr)
    assert result == 0, (
        "mypy --strict must accept the bundled stub file, otherwise every user running a type "
        "checker against loguru gets errors from the library itself"
    )
