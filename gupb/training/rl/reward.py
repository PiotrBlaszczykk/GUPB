from __future__ import annotations

from dataclasses import dataclass

from gupb.model import coordinates

from .features import weapon_rank


@dataclass(frozen=True)
class ChampionSnapshot:
    health: int
    weapon_name: str
    weapon_rank: int
    position: coordinates.Coords
    on_mist: bool
    on_fire: bool
    alive: bool
    champions_alive: int


@dataclass(frozen=True)
class RewardConfig:
    win_reward: float = 40.0
    death_penalty: float = -25.0
    hp_loss_penalty: float = 0.8
    mist_penalty: float = 0.25
    fire_penalty: float = 0.35
    potion_bonus: float = 0.6
    weapon_upgrade_bonus: float = 0.5
    stall_penalty: float = 0.06
    survival_progress_bonus: float = 0.15


def build_snapshot(
        health: int,
        weapon_name: str,
        position: coordinates.Coords,
        on_mist: bool,
        on_fire: bool,
        alive: bool,
        champions_alive: int,
) -> ChampionSnapshot:
    return ChampionSnapshot(
        health=int(health),
        weapon_name=weapon_name,
        weapon_rank=weapon_rank(weapon_name),
        position=position,
        on_mist=bool(on_mist),
        on_fire=bool(on_fire),
        alive=bool(alive),
        champions_alive=int(champions_alive),
    )


def compute_reward(
        before: ChampionSnapshot,
        after: ChampionSnapshot,
        done: bool,
        won: bool,
        reward_config: RewardConfig,
) -> float:
    reward = 0.0

    hp_delta = after.health - before.health
    if hp_delta < 0:
        reward += reward_config.hp_loss_penalty * float(hp_delta)
    elif hp_delta > 0:
        reward += reward_config.potion_bonus

    weapon_delta = after.weapon_rank - before.weapon_rank
    if weapon_delta > 0:
        reward += reward_config.weapon_upgrade_bonus * float(weapon_delta)

    if after.on_mist:
        reward -= reward_config.mist_penalty
    if after.on_fire:
        reward -= reward_config.fire_penalty

    if after.position == before.position:
        reward -= reward_config.stall_penalty

    if before.alive and after.alive and after.champions_alive < before.champions_alive:
        progress = before.champions_alive - after.champions_alive
        reward += reward_config.survival_progress_bonus * float(progress)

    if done:
        if won:
            reward += reward_config.win_reward
        elif before.alive and not after.alive:
            reward += reward_config.death_penalty

    return float(reward)
