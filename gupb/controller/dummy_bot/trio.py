from __future__ import annotations

from .dummy_bot import DummyBot


class DummyBot1(DummyBot):
    def __init__(self, bot_name: str = "Dummy_bot_1") -> None:
        super().__init__(bot_name)


class DummyBot2(DummyBot):
    def __init__(self, bot_name: str = "Dummy_bot_2") -> None:
        super().__init__(bot_name)


class DummyBot3(DummyBot):
    def __init__(self, bot_name: str = "Dummy_bot_3") -> None:
        super().__init__(bot_name)


def build_dummy_trio() -> list[DummyBot]:
    return [DummyBot1(), DummyBot2(), DummyBot3()]


__all__ = [
    "DummyBot1",
    "DummyBot2",
    "DummyBot3",
    "build_dummy_trio",
]

