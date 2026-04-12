from gupb.controller import agressive_bot
from gupb.controller import benjamin_netanyahu
from gupb.controller import coward_bot
from gupb.controller.dummy_bot.trio import DummyBot1, DummyBot2, DummyBot3

CONFIGURATION = {
    "arenas": [
        "ordinary_chaos",
        "mini",
        "isolated_shrine",
        "lone_sanctum",
    ],
    "controllers": [
        benjamin_netanyahu.BenjaminNetanyahu(
            "BenjaminNetanyahu",
            mode_horizon_turns=3,
            allow_oracle_menhir=False,
        ),
        agressive_bot.AgressiveBot("AgressiveBot"),
        coward_bot.CowardBot("CowardBot"),
        DummyBot1(),
        DummyBot2(),
        DummyBot3(),
    ],
    "start_balancing": True,
    "visualise": False,
    "show_sight": False,
    "parallel_processes": 8,
    "focus_controller_name": "BenjaminNetanyahu",
    "runs_no": 400,
    "profiling_metrics": [],
}
