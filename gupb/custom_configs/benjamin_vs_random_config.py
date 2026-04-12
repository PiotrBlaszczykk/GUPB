from gupb.controller import benjamin_netanyahu
from gupb.controller import random

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
        random.RandomController("Alice"),
        random.RandomController("Bob"),
        random.RandomController("Cecilia"),
        random.RandomController("Darius"),
    ],
    "start_balancing": True,
    "visualise": False,
    "show_sight": False,
    "parallel_processes": 8,
    "focus_controller_name": "BenjaminNetanyahu",
    "runs_no": 400,
    "profiling_metrics": [],
}
