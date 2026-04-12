from __future__ import annotations

import random
from typing import Optional

import numpy as np

from gupb import controller
from gupb.controller import agressive_bot
from gupb.controller import coward_bot
from gupb.controller import dummy_bot
from gupb.controller import random as random_controller
from gupb.model import characters
from gupb.model import games

from .meta_bot import RLMetaBot
from gupb.training.rl.features import FEATURE_DIM
from gupb.training.rl.features import extract_features
from gupb.training.rl.reward import RewardConfig
from gupb.training.rl.reward import build_snapshot
from gupb.training.rl.reward import compute_reward


class RLMetaBotEnv:
    """
    Minimal RL environment for a style-selection meta-bot.
    One RL action = choose style; chosen style stays active for `style_hold_turns`.
    """

    def __init__(
            self,
            arenas: list[str],
            opponents: Optional[list[controller.Controller]] = None,
            style_hold_turns: int = 3,
            max_cycles_per_episode: int = 10_000,
            seed: Optional[int] = None,
            bot_name: str = "RLMetaBotTrain",
            reward_config: Optional[RewardConfig] = None,
    ) -> None:
        if not arenas:
            raise ValueError("At least one arena is required.")
        if style_hold_turns < 1:
            raise ValueError("style_hold_turns must be >= 1.")
        self.arenas = arenas
        self.style_hold_turns = int(style_hold_turns)
        self.max_cycles_per_episode = int(max_cycles_per_episode)
        self.reward_config = reward_config or RewardConfig()
        self.bot_name = bot_name
        self._rng = random.Random(seed)

        self._opponents: list[controller.Controller] = opponents or [
            dummy_bot.DummyBot("DummyOpponent"),
            agressive_bot.AgressiveBot("AgressiveOpponent"),
            coward_bot.CowardBot("CowardOpponent"),
            random_controller.RandomController("Alice"),
            random_controller.RandomController("Bob"),
        ]

        self.action_space_n = 3
        self.observation_dim = FEATURE_DIM
        self._game_no = 0
        self._cycles_elapsed = 0

        self.meta_bot: Optional[RLMetaBot] = None
        self.game: Optional[games.Game] = None
        self.meta_champion: Optional[characters.Champion] = None

    def reset(self) -> np.ndarray:
        self._game_no += 1
        self._cycles_elapsed = 0

        self.meta_bot = RLMetaBot(
            bot_name=self.bot_name,
            hold_turns=self.style_hold_turns,
        )
        to_spawn = [self.meta_bot, *self._opponents]
        self._rng.shuffle(to_spawn)
        arena_name = self._rng.choice(self.arenas)

        self.game = games.Game(
            game_no=self._game_no,
            arena_name=arena_name,
            to_spawn=to_spawn,
        )
        self.meta_champion = next(champion for champion in self.game.champions if champion.controller is self.meta_bot)

        self._advance_to_decision_point()
        if self._episode_done():
            return np.zeros(self.observation_dim, dtype=np.float32)
        return self._current_observation()

    def step(self, style_action: int) -> tuple[np.ndarray, float, bool, dict]:
        self._ensure_ready()
        self._advance_to_decision_point()

        if self._episode_done():
            return np.zeros(self.observation_dim, dtype=np.float32), 0.0, True, self._build_info(done=True, won=False)

        before_snapshot = self._snapshot()
        turns_before = self.meta_bot.turns_taken
        self.meta_bot.set_pending_style(style_action)

        while True:
            if self._episode_done():
                break
            if self.meta_bot.turns_taken > turns_before and self._at_decision_point():
                break
            self._cycle_once()

        done = self._episode_done()
        won = self._did_meta_win() if done else False
        after_snapshot = self._snapshot()
        reward = compute_reward(
            before=before_snapshot,
            after=after_snapshot,
            done=done,
            won=won,
            reward_config=self.reward_config,
        )

        next_observation = np.zeros(self.observation_dim, dtype=np.float32) if done else self._current_observation()
        info = self._build_info(done=done, won=won)
        return next_observation, reward, done, info

    def _ensure_ready(self) -> None:
        if self.game is None or self.meta_bot is None or self.meta_champion is None:
            raise RuntimeError("Environment is not ready. Call reset() before step().")

    def _current_observation(self) -> np.ndarray:
        knowledge = self._meta_knowledge()
        return extract_features(
            knowledge=knowledge,
            current_style=self.meta_bot.current_style,
            turns_until_switch=self.meta_bot.turns_until_style_change,
            hold_turns=self.style_hold_turns,
        )

    def _meta_knowledge(self) -> characters.ChampionKnowledge:
        visible_tiles = self.game.arena.visible_tiles(self.meta_champion)
        return characters.ChampionKnowledge(
            position=self.meta_champion.position,
            no_of_champions_alive=self.game.arena.no_of_champions_alive,
            visible_tiles=visible_tiles,
        )

    def _snapshot(self):
        tile = self.game.arena.terrain[self.meta_champion.position]
        effect_types = {effect.description().type for effect in tile.effects}
        return build_snapshot(
            health=self.meta_champion.health,
            weapon_name=self.meta_champion.weapon.description().name,
            position=self.meta_champion.position,
            on_mist="mist" in effect_types,
            on_fire="fire" in effect_types,
            alive=self.meta_champion.alive,
            champions_alive=self.game.arena.no_of_champions_alive,
        )

    def _at_decision_point(self) -> bool:
        if self._episode_done():
            return False
        if not self.meta_bot.needs_style_choice:
            return False
        if not self.game.action_queue:
            return False
        current_state = getattr(self.game, "current_state", None)
        state_id = getattr(current_state, "id", None)
        if state_id != "actions_done":
            return False
        return self.game.action_queue[-1] is self.meta_champion

    def _advance_to_decision_point(self) -> None:
        while not self._episode_done() and not self._at_decision_point():
            self._cycle_once()

    def _cycle_once(self) -> None:
        self.game.cycle()
        self._cycles_elapsed += 1

    def _episode_done(self) -> bool:
        if self.game is None or self.meta_champion is None:
            return True
        if self._cycles_elapsed >= self.max_cycles_per_episode:
            return True
        if self.game.finished:
            return True
        if not self.meta_champion.alive:
            return True
        return False

    def _did_meta_win(self) -> bool:
        if not self.game.finished or not self.game.deaths:
            return False
        return self.game.deaths[-1].champion.controller is self.meta_bot

    def _build_info(self, done: bool, won: bool) -> dict:
        return {
            "done": done,
            "won": won,
            "meta_alive": bool(self.meta_champion and self.meta_champion.alive),
            "game_finished": bool(self.game and self.game.finished),
            "current_style": int(self.meta_bot.current_style if self.meta_bot else 0),
            "style_name": self.meta_bot.active_style_name if self.meta_bot else "unknown",
            "cycles_elapsed": self._cycles_elapsed,
            "game_episode": int(self.game.episode if self.game else 0),
            "arena_name": self.game.arena.name if self.game else None,
        }
