from .aggressive_mode import BenjaminAggressiveMode
from .benjamin_netanyahu import BenjaminMode, BenjaminNetanyahu
from .normal_mode import BenjaminNormalMode
from .passive_mode import BenjaminPassiveMode

__all__ = [
    "BenjaminAggressiveMode",
    "BenjaminMode",
    "BenjaminNormalMode",
    "BenjaminNetanyahu",
    "BenjaminPassiveMode",
    "POTENTIAL_CONTROLLERS",
]

POTENTIAL_CONTROLLERS = [
    BenjaminNetanyahu("Benjamin Netanyahu"),
]
