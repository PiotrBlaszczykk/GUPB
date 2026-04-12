from __future__ import annotations

import random
from typing import Optional

import numpy as np

from gupb import controller
from gupb.controller import agressive_bot
from gupb.controller import coward_bot
from gupb.controller.dummy_bot.trio import DummyBot1, DummyBot2, DummyBot3
from gupb.controller.benjamin_netanyahu.mode_features import FEATURE_DIM
from gupb.controller.benjamin_netanyahu.mode_features import TemporalFeatureTracker
from gupb.controller.benjamin_netanyahu.mode_features import extract_benjamin_features
from gupb.model import characters
from gupb.model import games
from gupb.training.rl.reward import RewardConfig
from gupb.training.rl.reward import build_snapshot
from gupb.training.rl.reward import compute_reward

from gupb.controller.benjamin_netanyahu.benjamin_netanyahu import BenjaminNetanyahu


class BenjaminRLEnv:
    """
    Minimal environment for training mode-selection policy for BenjaminNetanyahu.
    One RL action = mode choice:
    0 NORMAL, 1 AGGRESSIVE, 2 PASSIVE.
    """

    def __init__(
            self,
            arenas: list[str],
            opponents: Optional[list[controller.Controller]] = None,
            mode_horizon_turns: int = 3,
            max_cycles_per_episode: int = 10_000,
            seed: Optional[int] = None,
            bot_name: str = "BenjaminRLTrain",
            reward_config: Optional[RewardConfig] = None,
            allow_oracle_menhir: bool = False,
    ) -> None:
        if not arenas:
            raise ValueError("At least one arena is required.")
        if mode_horizon_turns < 1:
            raise ValueError("mode_horizon_turns must be >= 1.")

        self.arenas = arenas
        self.mode_horizon_turns = int(mode_horizon_turns)
        self.max_cycles_per_episode = int(max_cycles_per_episode)
        self.reward_config = reward_config or RewardConfig()
        self.bot_name = bot_name
        self.allow_oracle_menhir = bool(allow_oracle_menhir)
        self._rng = random.Random(seed)

        self._opponents: list[controller.Controller] = opponents or [
            agressive_bot.AgressiveBot("AgressiveOpponent"),
            coward_bot.CowardBot("CowardOpponent"),
            DummyBot1(),
            DummyBot2(),
            DummyBot3(),
        ]

        self.action_space_n = 3
        self.observation_dim = FEATURE_DIM
        self._game_no = 0
        self._cycles_elapsed = 0

        self.benjamin: Optional[BenjaminNetanyahu] = None
        self.game: Optional[games.Game] = None
        self.benjamin_champion: Optional[characters.Champion] = None
        self._feature_tracker = TemporalFeatureTracker()

    def reset(self) -> np.ndarray:
        self._game_no += 1
        self._cycles_elapsed = 0
        self._feature_tracker.reset()

        self.benjamin = BenjaminNetanyahu(
            bot_name=self.bot_name,
            mode_horizon_turns=self.mode_horizon_turns,
            mode_selector=None,
            allow_oracle_menhir=self.allow_oracle_menhir,
        )
        to_spawn = [self.benjamin, *self._opponents]
        self._rng.shuffle(to_spawn)
        arena_name = self._rng.choice(self.arenas)

        self.game = games.Game(
            game_no=self._game_no,
            arena_name=arena_name,
            to_spawn=to_spawn,
        )
        self.benjamin_champion = next(
            champion for champion in self.game.champions if champion.controller is self.benjamin
        )

        self._advance_to_decision_point()
        if self._episode_done():
            return np.zeros(self.observation_dim, dtype=np.float32)
        return self._current_observation()

    def step(self, mode_action: int) -> tuple[np.ndarray, float, bool, dict]:
        self._ensure_ready()
        self._advance_to_decision_point()

        if self._episode_done():
            return np.zeros(self.observation_dim, dtype=np.float32), 0.0, True, self._build_info(done=True, won=False)

        before_snapshot = self._snapshot()
        turns_before = self.benjamin.turns_taken
        self.benjamin.set_pending_mode(int(mode_action))

        while True:
            if self._episode_done():
                break
            if self.benjamin.turns_taken > turns_before and self._at_decision_point():
                break
            self._cycle_once()

        done = self._episode_done()
        won = self._did_benjamin_win() if done else False
        after_snapshot = self._snapshot()
        reward = compute_reward(
            before=before_snapshot,
            after=after_snapshot,
            done=done,
            won=won,
            reward_config=self.reward_config,
        )
        next_observation = np.zeros(self.observation_dim, dtype=np.float32) if done else self._current_observation()
        info = self._build_info(
            done=done,
            won=won,
            champions_alive_before=int(before_snapshot.champions_alive),
            champions_alive_after=int(after_snapshot.champions_alive),
        )
        return next_observation, reward, done, info

    def _ensure_ready(self) -> None:
        if self.game is None or self.benjamin is None or self.benjamin_champion is None:
            raise RuntimeError("Environment is not ready. Call reset() before step().")

    def _current_observation(self) -> np.ndarray:
        knowledge = self._benjamin_knowledge()
        temporal = self._feature_tracker.update(knowledge)
        return extract_benjamin_features(
            knowledge=knowledge,
            current_mode=self.benjamin.current_mode,
            known_menhir=temporal.known_menhir,
            recent_damage_sum=temporal.recent_damage_sum,
            panic_turns=temporal.panic_turns,
            hp_delta_prev=temporal.hp_delta_prev,
            turns_since_enemy_seen=temporal.turns_since_enemy_seen,
            nearest_enemy_distance_delta=temporal.nearest_enemy_distance_delta,
            was_hit_recently_override=temporal.was_hit_recently,
        )

    def _benjamin_knowledge(self) -> characters.ChampionKnowledge:
        visible_tiles = self.game.arena.visible_tiles(self.benjamin_champion)
        return characters.ChampionKnowledge(
            position=self.benjamin_champion.position,
            no_of_champions_alive=self.game.arena.no_of_champions_alive,
            visible_tiles=visible_tiles,
        )

    def _snapshot(self):
        tile = self.game.arena.terrain[self.benjamin_champion.position]
        effect_types = {effect.description().type for effect in tile.effects}
        return build_snapshot(
            health=self.benjamin_champion.health,
            weapon_name=self.benjamin_champion.weapon.description().name,
            position=self.benjamin_champion.position,
            on_mist="mist" in effect_types,
            on_fire="fire" in effect_types,
            alive=self.benjamin_champion.alive,
            champions_alive=self.game.arena.no_of_champions_alive,
        )

    def _at_decision_point(self) -> bool:
        if self._episode_done():
            return False
        if not self.benjamin.needs_mode_choice:
            return False
        if not self.game.action_queue:
            return False
        current_state = getattr(self.game, "current_state", None)
        state_id = getattr(current_state, "id", None)
        if state_id != "actions_done":
            return False
        return self.game.action_queue[-1] is self.benjamin_champion

    def _advance_to_decision_point(self) -> None:
        while not self._episode_done() and not self._at_decision_point():
            self._cycle_once()

    def _cycle_once(self) -> None:
        self.game.cycle()
        self._cycles_elapsed += 1

    def _episode_done(self) -> bool:
        if self.game is None or self.benjamin_champion is None:
            return True
        if self._cycles_elapsed >= self.max_cycles_per_episode:
            return True
        if self.game.finished:
            return True
        if not self.benjamin_champion.alive:
            return True
        return False

    def _did_benjamin_win(self) -> bool:
        if not self.game.finished or not self.game.deaths:
            return False
        return self.game.deaths[-1].champion.controller is self.benjamin

    def _build_info(
            self,
            done: bool,
            won: bool,
            champions_alive_before: Optional[int] = None,
            champions_alive_after: Optional[int] = None,
    ) -> dict:
        current_alive = int(self.game.arena.no_of_champions_alive) if self.game else 0
        return {
            "done": done,
            "won": won,
            "benjamin_alive": bool(self.benjamin_champion and self.benjamin_champion.alive),
            "game_finished": bool(self.game and self.game.finished),
            "current_mode": self.benjamin.current_mode.value if self.benjamin else "unknown",
            "current_mode_index": int(self.benjamin.current_mode_index if self.benjamin else 0),
            "champions_alive_before": int(champions_alive_before if champions_alive_before is not None else current_alive),
            "champions_alive": int(champions_alive_after if champions_alive_after is not None else current_alive),
            "cycles_elapsed": self._cycles_elapsed,
            "game_episode": int(self.game.episode if self.game else 0),
            "arena_name": self.game.arena.name if self.game else None,
        }
