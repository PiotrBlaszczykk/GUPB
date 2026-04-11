from __future__ import annotations

from collections import deque
from typing import Optional

from gupb import controller
from gupb.model import arenas
from gupb.model import characters
from gupb.model import coordinates
from gupb.model import tiles

PASSABLE_TILE_TYPES = {"land", "forest", "menhir"}
TRANSPARENT_TILE_TYPES = {"land", "sea", "menhir"}
HAZARD_EFFECT_TYPES = {"fire", "mist"}
MOVE_ACTIONS = {
    characters.Action.STEP_FORWARD,
    characters.Action.STEP_BACKWARD,
    characters.Action.STEP_LEFT,
    characters.Action.STEP_RIGHT,
}
CARDINALS = (
    coordinates.Coords(1, 0),
    coordinates.Coords(-1, 0),
    coordinates.Coords(0, 1),
    coordinates.Coords(0, -1),
)


class DummyBot(controller.Controller):
    """
    Heuristic baseline bot:
    - avoids hazards (fire/mist),
    - takes direct fights with visible enemies,
    - picks potion on low HP and upgrades weapon when reasonable,
    - uses simple BFS on visible passable tiles to avoid spinning in place.
    """

    def __init__(self, bot_name: str = "DummyBot"):
        self.bot_name: str = bot_name
        self._last_position: Optional[coordinates.Coords] = None
        self._last_action: characters.Action = characters.Action.DO_NOTHING
        self._failed_moves: int = 0
        self._recent_positions: deque[coordinates.Coords] = deque(maxlen=12)
        self._known_menhir: Optional[coordinates.Coords] = None

    def __eq__(self, other: object) -> bool:
        if isinstance(other, DummyBot):
            return self.bot_name == other.bot_name
        return False

    def __hash__(self) -> int:
        return hash(self.bot_name)

    def decide(self, knowledge: characters.ChampionKnowledge) -> characters.Action:
        self._update_failed_moves(knowledge.position)
        self._update_menhir_memory(knowledge)

        current_tile = knowledge.visible_tiles.get(knowledge.position)
        current_champion = current_tile.character if current_tile else None
        facing = current_champion.facing if current_champion else characters.Facing.UP
        current_weapon = current_champion.weapon.name if current_champion else "knife"
        current_hp = current_champion.health if current_champion else characters.CHAMPION_STARTING_HP
        enemy_positions = self._enemy_positions(knowledge)

        if self._failed_moves >= 2:
            return self._store_action(characters.Action.TURN_RIGHT, knowledge.position)

        if current_tile and self._is_hazardous(current_tile):
            escape_action = self._best_safe_step(knowledge, facing)
            if escape_action is not None:
                return self._store_action(escape_action, knowledge.position)
            return self._store_action(characters.Action.TURN_RIGHT, knowledge.position)

        adjacent_enemy = self._nearest_adjacent_enemy(knowledge.position, enemy_positions)
        if adjacent_enemy is not None:
            face_action = self._face_target_action(knowledge.position, facing, adjacent_enemy)
            if face_action is None:
                return self._store_action(characters.Action.ATTACK, knowledge.position)
            return self._store_action(face_action, knowledge.position)

        if enemy_positions and self._enemy_in_range(knowledge, facing, current_weapon, enemy_positions):
            return self._store_action(characters.Action.ATTACK, knowledge.position)

        if enemy_positions:
            chase_action = self._move_towards_enemy(knowledge, facing, enemy_positions)
            if chase_action is not None:
                return self._store_action(chase_action, knowledge.position)

        target = self._choose_resource_target(knowledge, current_hp, current_weapon)
        if target is not None:
            move_action = self._move_towards(knowledge, facing, target, target_is_enemy=False)
            if move_action is not None:
                return self._store_action(move_action, knowledge.position)

        explore_action = self._explore_action(knowledge, facing)
        return self._store_action(explore_action, knowledge.position)

    def _update_failed_moves(self, current_position: coordinates.Coords) -> None:
        if self._last_position is None:
            self._failed_moves = 0
            return
        if self._last_action in MOVE_ACTIONS and current_position == self._last_position:
            self._failed_moves += 1
        else:
            self._failed_moves = 0

    def _update_menhir_memory(self, knowledge: characters.ChampionKnowledge) -> None:
        for raw_coords, tile_description in knowledge.visible_tiles.items():
            coords = self._to_coords(raw_coords)
            if tile_description.type == "menhir":
                self._known_menhir = coords
                return

    def _store_action(self, action: characters.Action, position: coordinates.Coords) -> characters.Action:
        self._last_action = action
        self._last_position = position
        self._recent_positions.append(position)
        return action

    def _choose_resource_target(
            self,
            knowledge: characters.ChampionKnowledge,
            current_hp: int,
            current_weapon: str,
    ) -> Optional[coordinates.Coords]:
        potion_tiles: list[coordinates.Coords] = []
        better_weapon_tiles: list[coordinates.Coords] = []
        for raw_coords, tile_description in knowledge.visible_tiles.items():
            coords = self._to_coords(raw_coords)
            if tile_description.consumable and tile_description.consumable.name == "potion":
                potion_tiles.append(coords)
            if (
                tile_description.loot
                and self._weapon_rank(tile_description.loot.name) > self._weapon_rank(current_weapon)
            ):
                better_weapon_tiles.append(coords)

        if current_hp <= 4 and potion_tiles:
            return self._nearest(knowledge.position, potion_tiles)

        if better_weapon_tiles:
            return self._nearest(knowledge.position, better_weapon_tiles)

        if potion_tiles:
            return self._nearest(knowledge.position, potion_tiles)

        if self._known_menhir is not None and knowledge.no_of_champions_alive <= 3:
            return self._known_menhir

        return None

    def _move_towards_enemy(
            self,
            knowledge: characters.ChampionKnowledge,
            facing: characters.Facing,
            enemy_positions: list[coordinates.Coords],
    ) -> Optional[characters.Action]:
        nearest_enemy = self._nearest(knowledge.position, enemy_positions)
        return self._move_towards(knowledge, facing, nearest_enemy, target_is_enemy=True)

    def _move_towards(
            self,
            knowledge: characters.ChampionKnowledge,
            facing: characters.Facing,
            target: coordinates.Coords,
            target_is_enemy: bool,
    ) -> Optional[characters.Action]:
        goals: set[coordinates.Coords]
        if target_is_enemy:
            goals = {
                target + delta
                for delta in CARDINALS
                if self._is_walkable_coord(knowledge, target + delta, avoid_hazards=True)
            }
            if not goals:
                return None
        else:
            goals = {target}

        path_action = self._bfs_first_action(knowledge, facing, goals)
        if path_action is not None:
            return path_action

        return self._best_greedy_step(knowledge, facing, target)

    def _bfs_first_action(
            self,
            knowledge: characters.ChampionKnowledge,
            facing: characters.Facing,
            goals: set[coordinates.Coords],
    ) -> Optional[characters.Action]:
        start = knowledge.position
        if start in goals:
            return None

        queue = deque([start])
        visited = {start}
        parent: dict[coordinates.Coords, Optional[coordinates.Coords]] = {start: None}

        while queue:
            current = queue.popleft()
            if current in goals:
                return self._reconstruct_first_action(start, current, parent, facing)

            for neighbor in self._neighbors(current):
                if neighbor in visited:
                    continue
                if not self._is_walkable_coord(knowledge, neighbor, avoid_hazards=True):
                    continue
                visited.add(neighbor)
                parent[neighbor] = current
                queue.append(neighbor)

        return None

    def _reconstruct_first_action(
            self,
            start: coordinates.Coords,
            goal: coordinates.Coords,
            parent: dict[coordinates.Coords, Optional[coordinates.Coords]],
            facing: characters.Facing,
    ) -> Optional[characters.Action]:
        current = goal
        while parent[current] is not None and parent[current] != start:
            current = parent[current]

        first_step = current if parent[current] == start else goal
        delta = first_step - start
        return self._relative_action_for_delta(facing, delta)

    def _best_greedy_step(
            self,
            knowledge: characters.ChampionKnowledge,
            facing: characters.Facing,
            target: coordinates.Coords,
    ) -> Optional[characters.Action]:
        best_action: Optional[characters.Action] = None
        best_score = float("inf")
        for action, candidate in self._move_candidates(knowledge.position, facing):
            if not self._is_walkable_coord(knowledge, candidate, avoid_hazards=True):
                continue
            score = float(self._distance(candidate, target))
            if candidate in self._recent_positions:
                score += 1.5
            if score < best_score:
                best_score = score
                best_action = action
        return best_action

    def _best_safe_step(
            self,
            knowledge: characters.ChampionKnowledge,
            facing: characters.Facing,
    ) -> Optional[characters.Action]:
        best_action: Optional[characters.Action] = None
        best_score = float("inf")
        for action, candidate in self._move_candidates(knowledge.position, facing):
            if not self._is_walkable_coord(knowledge, candidate, avoid_hazards=True):
                continue
            score = 0.0
            if candidate in self._recent_positions:
                score += 1.0
            if score < best_score:
                best_score = score
                best_action = action
        return best_action

    def _explore_action(self, knowledge: characters.ChampionKnowledge, facing: characters.Facing) -> characters.Action:
        position = knowledge.position

        for action, candidate in self._move_candidates(position, facing):
            if not self._is_walkable_coord(knowledge, candidate, avoid_hazards=True):
                continue
            if candidate not in self._recent_positions:
                return action

        for action, candidate in self._move_candidates(position, facing):
            if self._is_walkable_coord(knowledge, candidate, avoid_hazards=True):
                return action

        unknown_forward = position + facing.value
        if unknown_forward not in knowledge.visible_tiles:
            return characters.Action.STEP_FORWARD
        return characters.Action.TURN_RIGHT

    def _enemy_in_range(
            self,
            knowledge: characters.ChampionKnowledge,
            facing: characters.Facing,
            current_weapon: str,
            enemy_positions: list[coordinates.Coords],
    ) -> bool:
        enemy_set = set(enemy_positions)
        for attack_position in self._attack_positions(knowledge, facing, current_weapon):
            if attack_position in enemy_set:
                return True
        return False

    def _attack_positions(
            self,
            knowledge: characters.ChampionKnowledge,
            facing: characters.Facing,
            current_weapon: str,
    ) -> list[coordinates.Coords]:
        position = knowledge.position
        weapon_name = self._weapon_base(current_weapon)

        if weapon_name in {"knife", "scroll"}:
            return [position + facing.value]
        if weapon_name == "sword":
            return self._line_attack_positions(knowledge.visible_tiles, position, facing, reach=3)
        if weapon_name == "bow":
            return self._line_attack_positions(knowledge.visible_tiles, position, facing, reach=50)
        if weapon_name == "axe":
            centre = position + facing.value
            return [centre + facing.turn_left().value, centre, centre + facing.turn_right().value]
        if weapon_name == "amulet":
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

    def _line_attack_positions(
            self,
            visible_tiles: dict[coordinates.Coords, tiles.TileDescription],
            position: coordinates.Coords,
            facing: characters.Facing,
            reach: int,
    ) -> list[coordinates.Coords]:
        output: list[coordinates.Coords] = []
        current = position
        for _ in range(reach):
            current = current + facing.value
            output.append(current)
            tile_description = visible_tiles.get(current)
            if tile_description and not self._is_transparent(tile_description):
                break
        return output

    def _nearest_adjacent_enemy(
            self,
            position: coordinates.Coords,
            enemies: list[coordinates.Coords],
    ) -> Optional[coordinates.Coords]:
        adjacent = [coords for coords in enemies if self._distance(position, coords) == 1]
        if not adjacent:
            return None
        return self._nearest(position, adjacent)

    def _face_target_action(
            self,
            position: coordinates.Coords,
            facing: characters.Facing,
            target: coordinates.Coords,
    ) -> Optional[characters.Action]:
        delta = target - position
        if delta == facing.value:
            return None
        if delta == facing.turn_left().value:
            return characters.Action.TURN_LEFT
        if delta == facing.turn_right().value:
            return characters.Action.TURN_RIGHT
        if delta == facing.opposite().value:
            return characters.Action.TURN_RIGHT
        return None

    def _move_candidates(
            self,
            position: coordinates.Coords,
            facing: characters.Facing,
    ) -> list[tuple[characters.Action, coordinates.Coords]]:
        return [
            (characters.Action.STEP_FORWARD, position + facing.value),
            (characters.Action.STEP_LEFT, position + facing.turn_left().value),
            (characters.Action.STEP_RIGHT, position + facing.turn_right().value),
            (characters.Action.STEP_BACKWARD, position + facing.opposite().value),
        ]

    @staticmethod
    def _neighbors(position: coordinates.Coords) -> list[coordinates.Coords]:
        return [position + delta for delta in CARDINALS]

    @staticmethod
    def _relative_action_for_delta(
            facing: characters.Facing,
            delta: coordinates.Coords,
    ) -> Optional[characters.Action]:
        if delta == facing.value:
            return characters.Action.STEP_FORWARD
        if delta == facing.turn_left().value:
            return characters.Action.STEP_LEFT
        if delta == facing.turn_right().value:
            return characters.Action.STEP_RIGHT
        if delta == facing.opposite().value:
            return characters.Action.STEP_BACKWARD
        return None

    def _enemy_positions(self, knowledge: characters.ChampionKnowledge) -> list[coordinates.Coords]:
        enemies: list[coordinates.Coords] = []
        for raw_coords, tile_description in knowledge.visible_tiles.items():
            coords = self._to_coords(raw_coords)
            if tile_description.character and tile_description.character.controller_name != self.name:
                enemies.append(coords)
        return enemies

    @staticmethod
    def _to_coords(raw_coords: coordinates.Coords | tuple[int, int]) -> coordinates.Coords:
        if isinstance(raw_coords, coordinates.Coords):
            return raw_coords
        return coordinates.Coords(raw_coords[0], raw_coords[1])

    def _is_walkable_coord(
            self,
            knowledge: characters.ChampionKnowledge,
            coords: coordinates.Coords,
            avoid_hazards: bool,
    ) -> bool:
        tile_description = knowledge.visible_tiles.get(coords)
        if tile_description is None:
            return False
        if not self._is_passable(tile_description):
            return False
        if avoid_hazards and self._is_hazardous(tile_description):
            return False
        return True

    @staticmethod
    def _weapon_base(weapon_name: str) -> str:
        return weapon_name.split("_", 1)[0].lower()

    @classmethod
    def _weapon_rank(cls, weapon_name: str) -> int:
        ranks = {
            "knife": 0,
            "amulet": 1,
            "sword": 2,
            "scroll": 3,
            "axe": 3,
            "bow": 4,
        }
        return ranks.get(cls._weapon_base(weapon_name), 0)

    @staticmethod
    def _is_passable(tile_description: tiles.TileDescription) -> bool:
        return tile_description.type in PASSABLE_TILE_TYPES and tile_description.character is None

    @staticmethod
    def _is_transparent(tile_description: tiles.TileDescription) -> bool:
        return tile_description.type in TRANSPARENT_TILE_TYPES and tile_description.character is None

    @staticmethod
    def _is_hazardous(tile_description: tiles.TileDescription) -> bool:
        return any(effect.type in HAZARD_EFFECT_TYPES for effect in tile_description.effects)

    @staticmethod
    def _distance(a: coordinates.Coords, b: coordinates.Coords) -> int:
        return abs(a.x - b.x) + abs(a.y - b.y)

    @classmethod
    def _nearest(
            cls,
            origin: coordinates.Coords,
            candidates: list[coordinates.Coords],
    ) -> coordinates.Coords:
        return min(candidates, key=lambda coords: cls._distance(origin, coords))

    def praise(self, score: int) -> None:
        pass

    def reset(self, game_no: int, arena_description: arenas.ArenaDescription) -> None:
        self._last_position = None
        self._last_action = characters.Action.DO_NOTHING
        self._failed_moves = 0
        self._recent_positions.clear()
        self._known_menhir = None

    @property
    def name(self) -> str:
        return self.bot_name

    @property
    def preferred_tabard(self) -> characters.Tabard:
        return characters.Tabard.GREEN
