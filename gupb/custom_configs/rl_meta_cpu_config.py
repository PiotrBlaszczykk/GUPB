import os

from gupb.controller import agressive_bot
from gupb.controller import coward_bot
from gupb.controller import random
from gupb.training.rl.meta_bot.inference_bot import RLMetaDQNBot

CHECKPOINT_PATH = os.environ.get("RL_META_CHECKPOINT", "results/rl_meta_dqn_state_dict.pt")

CONFIGURATION = {
    "arenas": [
        "ordinary_chaos",
        "mini",
        "isolated_shrine",
        "lone_sanctum",
    ],
    "controllers": [
        RLMetaDQNBot("RLMetaDQNBot", hold_turns=3, checkpoint_path=CHECKPOINT_PATH),
        agressive_bot.AgressiveBot("AgressiveBot"),
        coward_bot.CowardBot("CowardBot"),
        random.RandomController("Alice"),
        random.RandomController("Bob"),
    ],
    "start_balancing": True,
    "visualise": False,
    "show_sight": False,
    "parallel_processes": 1,
    "runs_no": 200,
    "profiling_metrics": [],
}
