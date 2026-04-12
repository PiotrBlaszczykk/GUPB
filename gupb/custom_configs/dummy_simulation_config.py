from gupb.controller import random
from gupb.controller import dummy_bot

CONFIGURATION = {
    'arenas': [
        'ordinary_chaos',
        'mini',
        'isolated_shrine',
        'lone_sanctum',
    ],
    'controllers': [
        dummy_bot.DummyBot("DummyBot"),
        random.RandomController("Alice"),
        random.RandomController("Bob"),
        random.RandomController("Cecilia"),
        random.RandomController("Darius"),
    ],
    'start_balancing': True,
    'visualise': False,
    'show_sight': False,
    'parallel_processes': 8,
    'runs_no': 400,
    'profiling_metrics': [],
}
