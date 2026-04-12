from gupb.controller import agressive_bot
from gupb.controller import benjamin_netanyahu
from gupb.controller import coward_bot
from gupb.controller import dummy_bot

CONFIGURATION = {
    "arenas": [
        "ordinary_chaos",
        "mini",
        "isolated_shrine",
        "lone_sanctum",
    ],
    "controllers": [
        benjamin_netanyahu.BenjaminNetanyahu("BenjaminNetanyahu"),
        dummy_bot.DummyBot("DummyBot"),
        agressive_bot.AgressiveBot("AgressiveBot"),
        coward_bot.CowardBot("CowardBot"),
    ],
    "start_balancing": True,
    "visualise": False,
    "show_sight": False,
    "parallel_processes": 8,
    "focus_controller_name": "BenjaminNetanyahu",
    "runs_no": 400,
    "profiling_metrics": [],
}
