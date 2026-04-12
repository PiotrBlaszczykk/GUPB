import os

from gupb.controller import agressive_bot
from gupb.controller import coward_bot
from gupb.controller.benjamin_netanyahu.inference_mode_selector import BenjaminNetanyahuDQN
from gupb.controller.dummy_bot.trio import DummyBot1, DummyBot2, DummyBot3

CHECKPOINT_PATH = os.environ.get("BENJAMIN_DQN_CHECKPOINT")

CONFIGURATION = {
    "arenas": [
        "ordinary_chaos",
        "mini",
        "isolated_shrine",
        "lone_sanctum",
    ],
    "controllers": [
        BenjaminNetanyahuDQN(
            "BenjaminNetanyahu",
            checkpoint_path=CHECKPOINT_PATH if CHECKPOINT_PATH else None,
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
    "parallel_processes": 1,
    "runs_no": 200,
    "profiling_metrics": [],
}
