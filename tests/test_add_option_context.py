import multiprocessing
import os
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

import oxitest

from loguru import logger


@dataclass(frozen=True)
class ForkContextCase:
    context_name: str


@dataclass(frozen=True)
class InvalidContextCase:
    context: Any


FORK_CONTEXT_CASES = {
    "fork": ForkContextCase(context_name="fork"),
    "forkserver": ForkContextCase(context_name="forkserver"),
}

WINDOWS_HAS_NO_FORK = "Windows does not support forking"


def test_using_multiprocessing_directly_if_context_is_none() -> None:
    logger.add(lambda _: None, enqueue=True, context=None)
    assert multiprocessing.get_start_method(allow_none=True) is not None, (
        "context=None must fall back to the multiprocessing module itself, which pins the "
        "global start method as a side effect the caller needs to be able to observe"
    )


@oxitest.mark.skip(when=os.name == "nt", reason=WINDOWS_HAS_NO_FORK)
@oxitest.parametrize(**FORK_CONTEXT_CASES)
def test_fork_context_as_string(context_name: str) -> None:
    context = multiprocessing.get_context(context_name)
    with patch.object(type(context), "Lock", wraps=context.Lock) as mock:
        logger.add(lambda _: None, context=context_name, enqueue=True)
        assert mock.called, (
            "the named context must be the one that creates the queue lock, otherwise the "
            "sink synchronizes through a different start method than the caller asked for"
        )
    assert multiprocessing.get_start_method(allow_none=True) is None, (
        "naming a context explicitly must not pin the global start method, otherwise loguru "
        "constrains multiprocessing for the whole application"
    )


def test_spawn_context_as_string() -> None:
    context = multiprocessing.get_context("spawn")
    with patch.object(type(context), "Lock", wraps=context.Lock) as mock:
        logger.add(lambda _: None, context="spawn", enqueue=True)
        assert mock.called, (
            "the named context must be the one that creates the queue lock, otherwise the "
            "sink synchronizes through a different start method than the caller asked for"
        )
    assert multiprocessing.get_start_method(allow_none=True) is None, (
        "naming a context explicitly must not pin the global start method, otherwise loguru "
        "constrains multiprocessing for the whole application"
    )


@oxitest.mark.skip(when=os.name == "nt", reason=WINDOWS_HAS_NO_FORK)
@oxitest.parametrize(**FORK_CONTEXT_CASES)
def test_fork_context_as_object(context_name: str) -> None:
    context = multiprocessing.get_context(context_name)
    with patch.object(type(context), "Lock", wraps=context.Lock) as mock:
        logger.add(lambda _: None, context=context, enqueue=True)
        assert mock.called, (
            "the supplied context object must be the one that creates the queue lock, "
            "otherwise the sink ignores the context it was handed"
        )
    assert multiprocessing.get_start_method(allow_none=True) is None, (
        "passing a context object must not pin the global start method, otherwise loguru "
        "constrains multiprocessing for the whole application"
    )


def test_spawn_context_as_object() -> None:
    context = multiprocessing.get_context("spawn")
    with patch.object(type(context), "Lock", wraps=context.Lock) as mock:
        logger.add(lambda _: None, context=context, enqueue=True)
        assert mock.called, (
            "the supplied context object must be the one that creates the queue lock, "
            "otherwise the sink ignores the context it was handed"
        )
    assert multiprocessing.get_start_method(allow_none=True) is None, (
        "passing a context object must not pin the global start method, otherwise loguru "
        "constrains multiprocessing for the whole application"
    )


def test_global_start_method_is_none_if_enqueue_is_false() -> None:
    logger.add(lambda _: None, enqueue=False, context=None)
    assert multiprocessing.get_start_method(allow_none=True) is None, (
        "without enqueue there is no queue to synchronize, so loguru must not touch "
        "multiprocessing at all"
    )


def test_invalid_context_name() -> None:
    with oxitest.raises(ValueError, match=r"cannot find context for"):
        logger.add(lambda _: None, context="foobar")


@oxitest.parametrize(
    integer=InvalidContextCase(context=42),
    object_instance=InvalidContextCase(context=object()),
)
def test_invalid_context_object(context: Any) -> None:
    with oxitest.raises(
        TypeError,
        match=r"Invalid context, it should be a string or a multiprocessing context",
    ):
        logger.add(lambda _: None, context=context)
