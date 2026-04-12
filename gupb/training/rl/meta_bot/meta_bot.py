from __future__ import annotations

from typing import Callable, Optional

from gupb import controller
from gupb.controller.agressive_bot.agressive_bot import AgressiveBot
from gupb.controller.coward_bot.coward_bot import CowardBot
from gupb.controller.dummy_bot.dummy_bot import DummyBot
from gupb.model import arenas
from gupb.model import characters

STYLE_DUMMY = 0
STYLE_AGRESSIVE = 1
STYLE_COWARD = 2
STYLE_COUNT = 3
STYLE_NAMES = {
    STYLE_DUMMY: "dummy",
    STYLE_AGRESSIVE: "agressive",
    STYLE_COWARD: "coward",
}

StyleSelector = Callable[[characters.ChampionKnowledge, int, int], int]


class _NoOracleDummyBot(DummyBot):
    def _update_oracle_menhir(self) -> None:
        return


class _NoOracleAgressiveBot(AgressiveBot):
    def _update_oracle_menhir(self) -> None:
        return


class _NoOracleCowardBot(CowardBot):
    def _update_oracle_menhir(self) -> None:
        return


class RLMetaBot(controller.Controller):
    """
    Meta-controller selecting one of three heuristic styles:
    0 = DummyBot, 1 = AgressiveBot, 2 = CowardBot.
    """

    def __init__(
            self,
            bot_name: str = "RLMetaBot",
            hold_turns: int = 3,
            style_selector: Optional[StyleSelector] = None,
    ) -> None:
        if hold_turns < 1:
            raise ValueError("hold_turns must be >= 1")
        self.bot_name = bot_name
        self.hold_turns = int(hold_turns)
        self._style_selector = style_selector
        self._subbots: list[controller.Controller] = [
            _NoOracleDummyBot(bot_name),
            _NoOracleAgressiveBot(bot_name),
            _NoOracleCowardBot(bot_name),
        ]
        self._current_style: int = STYLE_DUMMY
        self._turns_until_style_change: int = 0
        self._pending_style: Optional[int] = None
        self._turns_taken: int = 0

    def __eq__(self, other: object) -> bool:
        if isinstance(other, RLMetaBot):
            return self.bot_name == other.bot_name
        return False

    def __hash__(self) -> int:
        return hash(self.bot_name)

    def set_pending_style(self, style_id: int) -> None:
        self._pending_style = self._normalise_style(style_id)

    def set_style_selector(self, selector: Optional[StyleSelector]) -> None:
        self._style_selector = selector

    @property
    def needs_style_choice(self) -> bool:
        return self._turns_until_style_change <= 0

    @property
    def current_style(self) -> int:
        return self._current_style

    @property
    def turns_until_style_change(self) -> int:
        return max(0, self._turns_until_style_change)

    @property
    def turns_taken(self) -> int:
        return self._turns_taken

    @property
    def active_style_name(self) -> str:
        return STYLE_NAMES.get(self._current_style, "unknown")

    def decide(self, knowledge: characters.ChampionKnowledge) -> characters.Action:
        if self.needs_style_choice:
            chosen_style = self._resolve_style_choice(knowledge)
            self._current_style = chosen_style
            self._turns_until_style_change = self.hold_turns

        action = self._subbots[self._current_style].decide(knowledge)
        self._turns_until_style_change -= 1
        self._turns_taken += 1
        return action

    def _resolve_style_choice(self, knowledge: characters.ChampionKnowledge) -> int:
        if self._pending_style is not None:
            selected = self._pending_style
            self._pending_style = None
            return selected
        if self._style_selector is not None:
            try:
                selected = self._style_selector(knowledge, self._current_style, self._turns_taken)
                return self._normalise_style(selected)
            except Exception:
                return self._current_style
        return self._current_style

    @staticmethod
    def _normalise_style(style_id: int) -> int:
        style_value = int(style_id)
        if style_value < 0 or style_value >= STYLE_COUNT:
            raise ValueError(f"Style id out of range: {style_id}")
        return style_value

    def praise(self, score: int) -> None:
        for subbot in self._subbots:
            subbot.praise(score)

    def reset(self, game_no: int, arena_description: arenas.ArenaDescription) -> None:
        for subbot in self._subbots:
            subbot.reset(game_no, arena_description)
        self._current_style = STYLE_DUMMY
        self._turns_until_style_change = 0
        self._pending_style = None
        self._turns_taken = 0

    @property
    def name(self) -> str:
        return self.bot_name

    @property
    def preferred_tabard(self) -> characters.Tabard:
        return characters.Tabard.TURQUOISE
