import sys

from oxitest import helpers

import loguru
from loguru._get_frame import load_get_frame_function


def test_with_sys_getframe() -> None:
    def patched():
        return

    with helpers.common.patch_context() as context:
        context.setattr(sys, "_getframe", patched())
        assert load_get_frame_function() == patched(), (
            "loguru must use sys._getframe() when the interpreter provides it, otherwise it "
            "falls back to the much slower exception-based frame lookup"
        )


def test_without_sys_getframe() -> None:
    with helpers.common.patch_context() as context:
        context.delattr(sys, "_getframe")
        assert load_get_frame_function() == loguru._get_frame.get_frame_fallback, (
            "loguru must fall back to its own frame lookup on interpreters lacking "
            "sys._getframe(), otherwise importing loguru there raises AttributeError"
        )


def test_get_frame_fallback() -> None:
    frame_root = frame_a = frame_b = None

    def a():
        nonlocal frame_a
        frame_a = loguru._get_frame.get_frame_fallback(1)
        b()

    def b():
        nonlocal frame_b
        frame_b = loguru._get_frame.get_frame_fallback(2)

    frame_root = loguru._get_frame.get_frame_fallback(0)
    a()

    assert frame_a == frame_b == frame_root, (
        "the fallback must count stack levels the same way from any depth, otherwise records "
        "would be attributed to the wrong caller"
    )
