from .aggressive_mode import BenjaminAggressiveMode
from .benjamin_netanyahu import BenjaminMode, BenjaminNetanyahu
from .normal_mode import BenjaminNormalMode
from .passive_mode import BenjaminPassiveMode

try:
    from .inference_mode_selector import BenjaminNetanyahuDQN
except Exception:  # pragma: no cover - keep controller discovery robust.
    BenjaminNetanyahuDQN = None

__all__ = [
    "BenjaminAggressiveMode",
    "BenjaminMode",
    "BenjaminNormalMode",
    "BenjaminNetanyahu",
    "BenjaminNetanyahuDQN",
    "BenjaminPassiveMode",
    "POTENTIAL_CONTROLLERS",
]

POTENTIAL_CONTROLLERS = [
    BenjaminNetanyahu("Benjamin Netanyahu"),
]
