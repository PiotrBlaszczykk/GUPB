from __future__ import annotations

from typing import Iterable, Optional

import numpy as np

from gupb.model import characters
from gupb.model import coordinates
from gupb.model import tiles

WEAPON_BASES = ("knife", "sword", "bow", "axe", "amulet", "scroll")
WEAPON_TO_INDEX = {weapon_name: idx for idx, weapon_name in enumerate(WEAPON_BASES)}
TRANSPARENT_TILE_TYPES = {"land", "sea", "menhir"}
FEATURE_DIM = 28


def weapon_base(weapon_name: str) -> str:
    return weapon_name.split("_", 1)[0].lower()


def weapon_rank(weapon_name: str) -> int:
    rank_map = {
        "knife": 0,
        "amulet": 1,
        "sword": 2,
        "scroll": 3,
        "axe": 3,
        "bow": 4,
    }
    return rank_map.get(weapon_base(weapon_name), 0)


def extract_features(
        knowledge: characters.ChampionKnowledge,
        current_style: int,
        turns_until_switch: int,
        hold_turns: int,
) -> np.ndarray:
    current_tile = knowledge.visible_tiles.get(knowledge.position)
    self_desc = current_tile.character if current_tile and current_tile.character else None
    self_name = self_desc.controller_name if self_desc else ""
    current_hp = float(self_desc.health if self_desc else characters.CHAMPION_STARTING_HP)
    current_facing = self_desc.facing if self_desc else characters.Facing.UP
    current_weapon = self_desc.weapon.name if self_desc else "knife"

    enemy_positions: list[coordinates.Coords] = []
    potion_positions: list[coordinates.Coords] = []
    loot_positions: list[coordinates.Coords] = []
    menhir_positions: list[coordinates.Coords] = []
    mist_positions: list[coordinates.Coords] = []
    fire_positions: list[coordinates.Coords] = []

    for raw_coords, tile_description in knowledge.visible_tiles.items():
        coords = _to_coords(raw_coords)
        if tile_description.character and tile_description.character.controller_name != self_name:
            enemy_positions.append(coords)
        if tile_description.consumable and tile_description.consumable.name == "potion":
            potion_positions.append(coords)
        if tile_description.loot:
            loot_positions.append(coords)
        if tile_description.type == "menhir":
            menhir_positions.append(coords)
        effect_types = {effect.type for effect in tile_description.effects}
        if "mist" in effect_types:
            mist_positions.append(coords)
        if "fire" in effect_types:
            fire_positions.append(coords)

    nearest_enemy = _normalised_distance(knowledge.position, enemy_positions, max_distance=20.0)
    nearest_potion = _normalised_distance(knowledge.position, potion_positions, max_distance=20.0)
    nearest_loot = _normalised_distance(knowledge.position, loot_positions, max_distance=20.0)
    nearest_menhir = _normalised_distance(knowledge.position, menhir_positions, max_distance=20.0)

    adjacent_enemy = 1.0 if _has_adjacent_enemy(knowledge.position, enemy_positions) else 0.0
    enemy_in_range = 1.0 if _enemy_in_attack_range(
        knowledge=knowledge,
        facing=current_facing,
        weapon_name=current_weapon,
        enemy_positions=enemy_positions,
    ) else 0.0

    on_mist = 1.0 if _position_has_effect(current_tile, "mist") else 0.0
    on_fire = 1.0 if _position_has_effect(current_tile, "fire") else 0.0
    menhir_visible = 1.0 if menhir_positions else 0.0

    weapon_one_hot = np.zeros(len(WEAPON_BASES), dtype=np.float32)
    weapon_idx = WEAPON_TO_INDEX.get(weapon_base(current_weapon))
    if weapon_idx is not None:
        weapon_one_hot[weapon_idx] = 1.0

    style_one_hot = np.zeros(3, dtype=np.float32)
    if 0 <= int(current_style) < 3:
        style_one_hot[int(current_style)] = 1.0

    vector = np.array([
        1.0,  # bias
        np.clip(current_hp / 15.0, 0.0, 1.5),
        np.clip(float(knowledge.no_of_champions_alive) / 8.0, 0.0, 1.0),
        np.clip(float(len(knowledge.visible_tiles)) / 120.0, 0.0, 1.0),
        np.clip(float(len(enemy_positions)) / 8.0, 0.0, 1.0),
        np.clip(float(len(potion_positions)) / 8.0, 0.0, 1.0),
        np.clip(float(len(loot_positions)) / 8.0, 0.0, 1.0),
        np.clip(float(len(mist_positions)) / 16.0, 0.0, 1.0),
        np.clip(float(len(fire_positions)) / 16.0, 0.0, 1.0),
        adjacent_enemy,
        enemy_in_range,
        on_mist,
        on_fire,
        nearest_enemy,
        nearest_potion,
        nearest_loot,
        menhir_visible,
        nearest_menhir,
        np.clip(float(turns_until_switch) / float(max(1, hold_turns)), 0.0, 1.0),
    ], dtype=np.float32)

    full_vector = np.concatenate((vector, weapon_one_hot, style_one_hot), dtype=np.float32)
    if full_vector.shape[0] != FEATURE_DIM:
        raise RuntimeError(f"Unexpected feature size: {full_vector.shape[0]} (expected {FEATURE_DIM})")
    return full_vector


def _enemy_in_attack_range(
        knowledge: characters.ChampionKnowledge,
        facing: characters.Facing,
        weapon_name: str,
        enemy_positions: Iterable[coordinates.Coords],
) -> bool:
    enemy_set = set(enemy_positions)
    for attack_pos in _attack_positions(knowledge, facing, weapon_name):
        if attack_pos in enemy_set:
            return True
    return False


def _attack_positions(
        knowledge: characters.ChampionKnowledge,
        facing: characters.Facing,
        weapon_name: str,
) -> list[coordinates.Coords]:
    position = knowledge.position
    base_weapon = weapon_base(weapon_name)
    if base_weapon in {"knife", "scroll"}:
        return [position + facing.value]
    if base_weapon == "sword":
        return _line_positions(knowledge.visible_tiles, position, facing, reach=3)
    if base_weapon == "bow":
        return _line_positions(knowledge.visible_tiles, position, facing, reach=50)
    if base_weapon == "axe":
        centre = position + facing.value
        return [centre + facing.turn_left().value, centre, centre + facing.turn_right().value]
    if base_weapon == "amulet":
        return [
            coordinates.Coords(position.x + 1, position.y + 1),
            coordinates.Coords(position.x - 1, position.y + 1),
            coordinates.Coords(position.x + 1, position.y - 1),
            coordinates.Coords(position.x - 1, position.y - 1),
            coordinates.Coords(position.x + 2, position.y + 2),
            coordinates.Coords(position.x - 2, position.y + 2),
            coordinates.Coords(position.x + 2, position.y - 2),
            coordinates.Coords(position.x - 2, position.y - 2),
        ]
    return [position + facing.value]


def _line_positions(
        visible_tiles: dict[coordinates.Coords, tiles.TileDescription],
        start: coordinates.Coords,
        facing: characters.Facing,
        reach: int,
) -> list[coordinates.Coords]:
    output: list[coordinates.Coords] = []
    current = start
    for _ in range(reach):
        current = current + facing.value
        output.append(current)
        tile_description = visible_tiles.get(current)
        if tile_description is not None and not _is_transparent(tile_description):
            break
    return output


def _is_transparent(tile_description: tiles.TileDescription) -> bool:
    return tile_description.type in TRANSPARENT_TILE_TYPES and tile_description.character is None


def _position_has_effect(
        tile_description: Optional[tiles.TileDescription],
        effect_name: str,
) -> bool:
    if tile_description is None:
        return False
    return any(effect.type == effect_name for effect in tile_description.effects)


def _has_adjacent_enemy(
        position: coordinates.Coords,
        enemy_positions: list[coordinates.Coords],
) -> bool:
    return any(_manhattan(position, enemy_pos) == 1 for enemy_pos in enemy_positions)


def _normalised_distance(
        origin: coordinates.Coords,
        candidates: list[coordinates.Coords],
        max_distance: float,
) -> float:
    if not candidates:
        return 1.0
    nearest = min(float(_manhattan(origin, candidate)) for candidate in candidates)
    return np.clip(nearest / max_distance, 0.0, 1.0).item()


def _manhattan(a: coordinates.Coords, b: coordinates.Coords) -> int:
    return abs(a.x - b.x) + abs(a.y - b.y)


def _to_coords(raw_coords: coordinates.Coords | tuple[int, int]) -> coordinates.Coords:
    if isinstance(raw_coords, coordinates.Coords):
        return raw_coords
    return coordinates.Coords(raw_coords[0], raw_coords[1])
