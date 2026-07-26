import re
from dataclasses import dataclass
from typing import Any

import oxitest
from conftest import Writer
from oxitest import Fixture, helpers

from loguru import logger
from tests._naming import pin_module_name

# Filters match against the caller's dotted module name, which most cases below spell out.
pin_module_name(globals(), "tests.test_add_option_filter")


@dataclass(frozen=True)
class FilterCase:
    filter: Any


@dataclass(frozen=True)
class IncompleteFrameFilterCase:
    filter: Any
    simulate: str


def _incomplete_frame_cases(**filters: Any) -> dict:
    """Expand each filter into one case per way of breaking the caller's frame."""
    simulations = {
        "no_globals_name": "simulate_f_globals_name_absent",
        "no_frame": "simulate_no_frame_available",
    }
    return {
        "%s-%s" % (filter_name, simulation_name): IncompleteFrameFilterCase(
            filter=filter_value, simulate=helper_name
        )
        for filter_name, filter_value in filters.items()
        for simulation_name, helper_name in simulations.items()
    }


@oxitest.parametrize(
    none=FilterCase(filter=None),
    empty_string=FilterCase(filter=""),
    package=FilterCase(filter="tests"),
    module=FilterCase(filter="tests.test_add_option_filter"),
    callable_always_true=FilterCase(filter=lambda r: True),
    callable_on_level=FilterCase(filter=lambda r: r["level"].name == "DEBUG"),
    empty_dict=FilterCase(filter={}),
    root_level_name=FilterCase(filter={"": "DEBUG"}),
    package_enabled=FilterCase(filter={"tests": True}),
    module_level_number=FilterCase(filter={"tests.test_add_option_filter": 10}),
    package_overrides_root=FilterCase(filter={"": "WARNING", "tests": 0}),
    module_overrides_package=FilterCase(
        filter={"tests.test_add_option_filter": 5, "tests": False}
    ),
    unrelated_submodule_disabled=FilterCase(
        filter={"tests.test_add_option_filter.foobar": False}
    ),
    package_with_trailing_dot=FilterCase(filter={"tests.": False}),
    module_with_trailing_dot=FilterCase(filter={"tests.test_add_option_filter.": False}),
)
def test_filtered_in(filter: Any, writer: Fixture[Writer]) -> None:
    logger.add(writer, filter=filter, format="{message}")
    logger.debug("Test Filter")
    assert writer.read() == "Test Filter\n", (
        "this filter must accept the record: filters resolve by longest matching module "
        "prefix, and the most specific entry here allows DEBUG from this module"
    )


@oxitest.parametrize(
    truncated_package=FilterCase(filter="test"),
    extended_package=FilterCase(filter="testsx"),
    package_with_trailing_dot=FilterCase(filter="tests."),
    module_with_trailing_dot=FilterCase(filter="tests.test_add_option_filter."),
    dot=FilterCase(filter="."),
    callable_always_false=FilterCase(filter=lambda r: False),
    callable_on_level=FilterCase(filter=lambda r: r["level"].no != 10),
    root_disabled=FilterCase(filter={"": False}),
    package_level_too_high=FilterCase(filter={"": True, "tests": 50}),
    module_disabled=FilterCase(filter={"tests.test_add_option_filter": False}),
    package_level_name_too_high=FilterCase(filter={"tests": "WARNING"}),
    module_overrides_package=FilterCase(
        filter={"tests": 5, "tests.test_add_option_filter": 40}
    ),
    unrelated_submodule_enabled=FilterCase(
        filter={"": 100, "tests.test_add_option_filter.foobar": True}
    ),
)
def test_filtered_out(filter: Any, writer: Fixture[Writer]) -> None:
    logger.add(writer, filter=filter, format="{message}")
    logger.debug("Test Filter")
    assert writer.read() == "", (
        "this filter must reject the record: filters resolve by longest matching module "
        "prefix, and the most specific entry here excludes DEBUG from this module"
    )


@oxitest.parametrize(
    **_incomplete_frame_cases(
        none=None,
        callable_always_true=lambda _: True,
        empty_dict={},
        none_key_level_zero={None: 0},
        root_disabled={"": False},
        none_key_enabled={"tests": False, None: True},
        unrelated_module={"unrelated": 100},
        none_key_overrides_root={None: "INFO", "": "WARNING"},
    )
)
def test_filtered_in_incomplete_frame_context(
    writer: Fixture[Writer], filter: Any, simulate: str
) -> None:
    with getattr(helpers.common, simulate)():
        logger.add(writer, filter=filter, format="{message}", catch=False)
        logger.info("It's ok")
        result = writer.read()
    assert result == "It's ok\n", (
        "a record with no resolvable module name must be matched by the None key, so logs "
        "from Dask and Cython can still be filtered in"
    )


@oxitest.parametrize(
    **_incomplete_frame_cases(
        package="tests",
        empty_string="",
        callable_always_false=lambda _: False,
        none_key_disabled={None: False},
        none_key_level_too_high={"": 0, None: "WARNING"},
        none_key_overrides_package={None: 100, "tests": True},
    )
)
def test_filtered_out_incomplete_frame_context(
    writer: Fixture[Writer], filter: Any, simulate: str
) -> None:
    with getattr(helpers.common, simulate)():
        logger.add(writer, filter=filter, format="{message}", catch=False)
        logger.info("It's not ok")
        result = writer.read()
    assert result == "", (
        "a record with no resolvable module name must not be matched by a named entry, "
        "otherwise it would inherit rules meant for a module it does not belong to"
    )


@oxitest.parametrize(
    integer=FilterCase(filter=-1),
    float_value=FilterCase(filter=3.4),
    object_instance=FilterCase(filter=object()),
)
def test_invalid_filter(writer: Fixture[Writer], filter: Any) -> None:
    with oxitest.raises(TypeError):
        logger.add(writer, filter=filter)


@oxitest.parametrize(
    none_level=FilterCase(filter={"foo": None}),
    float_level=FilterCase(filter={"foo": 2.5}),
    object_level=FilterCase(filter={"a": "DEBUG", "b": object()}),
)
def test_invalid_filter_dict_level_types(writer: Fixture[Writer], filter: Any) -> None:
    with oxitest.raises(TypeError):
        logger.add(writer, filter=filter)


@oxitest.parametrize(
    integer_key=FilterCase(filter={1: "DEBUG"}),
    object_key=FilterCase(filter={object(): 10}),
)
def test_invalid_filter_dict_module_types(writer: Fixture[Writer], filter: Any) -> None:
    with oxitest.raises(TypeError):
        logger.add(writer, filter=filter)


@oxitest.parametrize(
    unknown_name=FilterCase(filter={"foo": "UNKNOWN_LEVEL"}),
    empty_name=FilterCase(filter={"tests.test_add_option_filter": ""}),
)
def test_invalid_filter_dict_values_unknown_level(
    writer: Fixture[Writer], filter: Any
) -> None:
    with oxitest.raises(
        ValueError,
        match=(
            r"The filter dict contains a module '[^']*' associated to "
            r"a level name which does not exist: '[^']*'"
        ),
    ):
        logger.add(writer, filter=filter)


def test_invalid_filter_dict_values_wrong_integer_value(writer: Fixture[Writer]) -> None:
    with oxitest.raises(
        ValueError,
        match=(
            r"The filter dict contains a module '[^']*' associated to an invalid level, "
            r"it should be a positive integer, not: '[^']*'"
        ),
    ):
        logger.add(writer, filter={"tests": -1})


def test_filter_dict_with_custom_level(writer: Fixture[Writer]) -> None:
    logger.level("MY_LEVEL", 6, color="", icon="")
    logger.add(writer, level=0, filter={"tests": "MY_LEVEL"}, format="{message}")
    logger.log(3, "No")
    logger.log(9, "Yes")
    assert writer.read() == "Yes\n", (
        "a filter dict must resolve custom level names to their severity, otherwise levels "
        "registered by the application cannot be used to filter"
    )


def test_invalid_filter_builtin(writer: Fixture[Writer]) -> None:
    with oxitest.raises(
        ValueError,
        match=re.escape(
            "The built-in 'filter()' function cannot be used as a 'filter' parameter, this is "
            "most likely a mistake (please double-check the arguments passed to 'logger.add()'"
        ),
    ):
        logger.add(writer, filter=filter)
