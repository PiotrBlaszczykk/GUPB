from .dummy_bot import DummyBot
from .trio import DummyBot1, DummyBot2, DummyBot3, build_dummy_trio

__all__ = [
    "DummyBot",
    "DummyBot1",
    "DummyBot2",
    "DummyBot3",
    "build_dummy_trio",
    "POTENTIAL_CONTROLLERS",
]

POTENTIAL_CONTROLLERS = [
    DummyBot("DummyBot"),
]
