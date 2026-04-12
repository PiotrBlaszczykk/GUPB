from enum import Enum

from gupb import controller
from gupb.controller.benjamin_netanyahu.aggressive_mode import BenjaminAggressiveMode
from gupb.controller.benjamin_netanyahu.normal_mode import BenjaminNormalMode
from gupb.controller.benjamin_netanyahu.passive_mode import BenjaminPassiveMode
from gupb.model import arenas
from gupb.model import characters

MODE_HORIZON_TURNS = 3


class BenjaminMode(Enum):
    AGGRESSIVE = "aggressive"
    NORMAL = "normal"
    PASSIVE = "passive"


class BenjaminNetanyahu(controller.Controller):
    def __init__(self, bot_name: str) -> None:
        self.bot_name = bot_name
        self.current_mode: BenjaminMode = BenjaminMode.NORMAL
        self._turns_left_in_mode: int = 0
        self._aggressive_expert = BenjaminAggressiveMode(bot_name)
        self._normal_expert = BenjaminNormalMode(bot_name)
        self._passive_expert = BenjaminPassiveMode(bot_name)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, BenjaminNetanyahu):
            return self.bot_name == other.bot_name
        return False

    def __hash__(self) -> int:
        return hash(self.bot_name)

    def decide(self, knowledge: characters.ChampionKnowledge) -> characters.Action:
        if self._turns_left_in_mode <= 0:
            self.current_mode = self._choose_mode(knowledge)
            self._turns_left_in_mode = MODE_HORIZON_TURNS
        expert = self._expert_for_mode(self.current_mode)
        action = expert.decide(knowledge)
        self._turns_left_in_mode -= 1
        return action

    def praise(self, score: int) -> None:
        for expert in self._experts():
            expert.praise(score)

    def reset(self, game_no: int, arena_description: arenas.ArenaDescription) -> None:
        self.current_mode = BenjaminMode.NORMAL
        self._turns_left_in_mode = 0
        for expert in self._experts():
            expert.reset(game_no, arena_description)

    @staticmethod
    def _choose_mode(knowledge: characters.ChampionKnowledge) -> BenjaminMode:
        current_hp = BenjaminNetanyahu._current_hp(knowledge)
        starting_hp = characters.CHAMPION_STARTING_HP
        if current_hp >= 0.4 * starting_hp:
            return BenjaminMode.AGGRESSIVE
        if current_hp < 0.4 * starting_hp:
            return BenjaminMode.PASSIVE
        return BenjaminMode.NORMAL

    @staticmethod
    def _current_hp(knowledge: characters.ChampionKnowledge) -> int:
        current_tile = knowledge.visible_tiles.get(knowledge.position)
        if current_tile is None or current_tile.character is None:
            return characters.CHAMPION_STARTING_HP
        return current_tile.character.health

    def _expert_for_mode(self, mode: BenjaminMode) -> controller.Controller:
        if mode == BenjaminMode.AGGRESSIVE:
            return self._aggressive_expert
        if mode == BenjaminMode.PASSIVE:
            return self._passive_expert
        return self._normal_expert

    def _experts(self) -> tuple[controller.Controller, controller.Controller, controller.Controller]:
        return self._aggressive_expert, self._normal_expert, self._passive_expert

    @property
    def name(self) -> str:
        return self.bot_name

    @property
    def preferred_tabard(self) -> characters.Tabard:
        return characters.Tabard.BENJAMIN_NETANYAHU
