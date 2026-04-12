from gupb.controller import agressive_bot
from gupb.controller import coward_bot
from gupb.controller import dummy_bot
from gupb.controller import random

CONFIGURATION = {
    "arenas": [
        "ordinary_chaos",
        "mini",
        "isolated_shrine",
        "lone_sanctum",
    ],
    "controllers": [
        dummy_bot.DummyBot("DummyBot"),
        agressive_bot.AgressiveBot("AgressiveBot"),
        coward_bot.CowardBot("CowardBot"),
        random.RandomController("Alice"),
        random.RandomController("Bob"),
        random.RandomController("Cecilia"),
    ],
    "start_balancing": True,
    "visualise": False,
    "show_sight": False,
    "parallel_processes": 8,
    "runs_no": 800,
    "profiling_metrics": [],
}
