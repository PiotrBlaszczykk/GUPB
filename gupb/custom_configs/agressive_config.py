from gupb.controller import agressive_bot
from gupb.controller import random

CONFIGURATION = {
    "arenas": [
        "ordinary_chaos",
        "mini",
        "isolated_shrine",
        "lone_sanctum",
    ],
    "controllers": [
        agressive_bot.AgressiveBot("AgressiveBot"),
        random.RandomController("Alice"),
        random.RandomController("Bob"),
        random.RandomController("Cecilia"),
        random.RandomController("Darius"),
    ],
    "start_balancing": True,
    "visualise": False,
    "show_sight": False,
    "parallel_processes": 8,
    "runs_no": 200,
    "profiling_metrics": [],
}
