from __future__ import annotations

import collections
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
import importlib.util
import logging
import multiprocessing
import os
import random
import sys
import time
import traceback
from typing import Any, List, Optional

from tqdm import tqdm

from gupb import controller
from gupb.logger import core as logger_core
from gupb.model import coordinates
from gupb.model import games
from gupb.model.profiling import PROFILE_RESULTS, print_stats

verbose_logger = logging.getLogger("verbose")


def _load_initial_config(config_path: str) -> dict[str, Any]:
    module_name = f"config_module_parallel_{os.getpid()}_{random.randint(0, 10**9)}"
    spec = importlib.util.spec_from_file_location(module_name, config_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load config from path: {config_path}")
    config_module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = config_module
    spec.loader.exec_module(config_module)
    return config_module.CONFIGURATION


def _split_runs(runs_no: int, processes: int) -> list[int]:
    chunks_no = max(1, min(processes, runs_no))
    base = runs_no // chunks_no
    remainder = runs_no % chunks_no
    chunks = [base + (1 if idx < remainder else 0) for idx in range(chunks_no)]
    return [chunk for chunk in chunks if chunk > 0]


class _ChunkRunner:
    def __init__(self, config: dict[str, Any], chunk_idx: int, seed: int) -> None:
        self.arenas: list[str] = config["arenas"]
        self.controllers: list[controller.Controller] = config["controllers"]
        self.chunk_idx = chunk_idx
        self.seed = seed
        self.runs_no: int = config["runs_no"]
        self.start_balancing: bool = config["start_balancing"]
        self.scores: dict[str, int] = collections.defaultdict(int)
        self.first_places: dict[str, int] = collections.defaultdict(int)
        self.games_by_arena: dict[str, int] = collections.defaultdict(int)
        self.dummy_first_places_by_arena: dict[str, int] = collections.defaultdict(int)
        self.dummy_losses_to: dict[str, int] = collections.defaultdict(int)
        self.game_summaries: list[dict[str, Any]] = []
        self.failed_game_reports: list[dict[str, Any]] = []
        self.controller_praise_exceptions: list[dict[str, str]] = []
        self.total_episodes: int = 0
        self.attempted_games: int = 0
        self.successful_games: int = 0
        self._last_arena: Optional[str] = None
        self._last_menhir_position: Optional[coordinates.Coords] = None
        self._last_initial_positions: Optional[list[coordinates.Coords]] = None
        self._longest_game: dict[str, Any] = {
            "game_number": None,
            "episodes": -1,
            "arena_name": None,
            "winner_name": None,
        }

    # noinspection PyBroadException
    def run_game(self, game_no: int, reported_game_no: int) -> dict[str, Any]:
        arena = random.choice(self.arenas)
        if not self.start_balancing or game_no % len(self.controllers) == 0:
            random.shuffle(self.controllers)
            game = games.Game(
                game_no=game_no,
                arena_name=arena,
                to_spawn=self.controllers,
            )
        else:
            self.controllers = self.controllers[1:] + [self.controllers[0]]
            game = games.Game(
                game_no=game_no,
                arena_name=self._last_arena,
                to_spawn=self.controllers,
                menhir_position=self._last_menhir_position,
                initial_champion_positions=self._last_initial_positions,
            )
        self._last_arena = game.arena.name
        self._last_menhir_position = game.arena.menhir_position
        self._last_initial_positions = game.initial_champion_positions
        self.games_by_arena[game.arena.name] += 1

        while not game.finished:
            game.cycle()

        self.total_episodes += game.episode
        round_scores = game.score()
        round_scores_by_name: dict[str, int] = {
            dead_controller.name: score for dead_controller, score in round_scores.items()
        }
        ranking = sorted(round_scores_by_name.items(), key=lambda item: item[1], reverse=True)
        winner_name = ranking[0][0]
        self.first_places[winner_name] += 1
        if winner_name == "DummyBot":
            self.dummy_first_places_by_arena[game.arena.name] += 1

        dummy_score = round_scores_by_name.get("DummyBot")
        dummy_rank = next((idx + 1 for idx, (name, _) in enumerate(ranking) if name == "DummyBot"), None)
        if dummy_rank is not None and dummy_rank != 1:
            self.dummy_losses_to[winner_name] += 1

        dummy_death_episode = None
        dummy_distance_to_menhir = None
        dummy_in_mist_on_death = None
        menhir_x = None
        menhir_y = None

        if game.arena.menhir_position is not None:
            menhir_x = game.arena.menhir_position.x
            menhir_y = game.arena.menhir_position.y

        for death in game.deaths:
            dead_controller = death.champion.controller
            if dead_controller and dead_controller.name == "DummyBot":
                dummy_death_episode = death.episode
                if game.arena.menhir_position is not None:
                    dx = death.champion.position.x - game.arena.menhir_position.x
                    dy = death.champion.position.y - game.arena.menhir_position.y
                    dummy_distance_to_menhir = int((dx * dx + dy * dy) ** 0.5)
                    dummy_in_mist_on_death = dummy_distance_to_menhir >= game.arena.mist_radius
                break

        game_summary = {
            "chunk_index": self.chunk_idx,
            "game_number": reported_game_no + 1,
            "arena_name": game.arena.name,
            "episodes": game.episode,
            "winner_name": winner_name,
            "controller_order": [controller_instance.name for controller_instance in self.controllers],
            "scores": round_scores_by_name,
            "mist_radius_end": game.arena.mist_radius,
            "menhir_x": menhir_x,
            "menhir_y": menhir_y,
            "dummy_score": dummy_score,
            "dummy_rank": dummy_rank,
            "dummy_death_episode": dummy_death_episode,
            "dummy_distance_to_menhir": dummy_distance_to_menhir,
            "dummy_in_mist_on_death": dummy_in_mist_on_death,
        }
        self.game_summaries.append(game_summary)
        self.successful_games += 1

        if game.episode > self._longest_game["episodes"]:
            self._longest_game = {
                "game_number": reported_game_no + 1,
                "episodes": game.episode,
                "arena_name": game.arena.name,
                "winner_name": winner_name,
            }

        for dead_controller, score in round_scores.items():
            verbose_logger.info(f"Controller {dead_controller.name} scored {score} points.")
            ControllerScoreReport(dead_controller.name, score).log(logging.INFO)
            try:
                dead_controller.praise(score)
            except Exception as e:
                verbose_logger.warning(f"Controller {dead_controller.name} throw an unexpected exception: {repr(e)}.")
                controller.ControllerExceptionReport(dead_controller.name, repr(e)).log(logging.WARN)
                self.controller_praise_exceptions.append({
                    "controller_name": dead_controller.name,
                    "error": repr(e),
                })
            self.scores[dead_controller.name] += score

        return game_summary

    # noinspection PyBroadException
    def run(self, game_offset: int = 0) -> None:
        for i in range(self.runs_no):
            reported_game_no = game_offset + i
            self.attempted_games += 1
            try:
                self.run_game(i, reported_game_no)
            except Exception as e:
                tb = traceback.format_exc(limit=10)
                self.failed_game_reports.append({
                    "chunk_index": self.chunk_idx,
                    "game_number": reported_game_no + 1,
                    "arena_name": self._last_arena,
                    "error": repr(e),
                    "traceback_tail": "\n".join(tb.splitlines()[-6:]),
                })


def _run_chunk(config_path: str, runs_no: int, chunk_idx: int, game_offset: int) -> dict[str, Any]:
    seed = (chunk_idx + 1) * 1_000_003 + runs_no * 131
    started_at = time.perf_counter()
    try:
        config = _load_initial_config(config_path)
        config["runs_no"] = runs_no
        config["visualise"] = False
        config["show_sight"] = None
        runner = _ChunkRunner(config, chunk_idx=chunk_idx, seed=seed)

        random.seed(seed)
        runner.run(game_offset=game_offset)

        return {
            "ok": True,
            "chunk_index": chunk_idx,
            "seed": seed,
            "runs_no": runs_no,
            "attempted_games": runner.attempted_games,
            "successful_games": runner.successful_games,
            "failed_games": len(runner.failed_game_reports),
            "duration_s": time.perf_counter() - started_at,
            "total_episodes": runner.total_episodes,
            "scores": dict(runner.scores),
            "first_places": dict(runner.first_places),
            "games_by_arena": dict(runner.games_by_arena),
            "dummy_first_places_by_arena": dict(runner.dummy_first_places_by_arena),
            "dummy_losses_to": dict(runner.dummy_losses_to),
            "longest_game": runner._longest_game,
            "game_summaries": runner.game_summaries,
            "failed_game_reports": runner.failed_game_reports,
            "controller_praise_exceptions": runner.controller_praise_exceptions,
        }
    except Exception as e:
        return {
            "ok": False,
            "chunk_index": chunk_idx,
            "seed": seed,
            "runs_no": runs_no,
            "attempted_games": 0,
            "successful_games": 0,
            "failed_games": runs_no,
            "duration_s": time.perf_counter() - started_at,
            "scores": {},
            "first_places": {},
            "games_by_arena": {},
            "dummy_first_places_by_arena": {},
            "dummy_losses_to": {},
            "longest_game": None,
            "game_summaries": [],
            "failed_game_reports": [],
            "controller_praise_exceptions": [],
            "error": repr(e),
            "traceback_tail": "\n".join(traceback.format_exc(limit=14).splitlines()[-8:]),
        }


class RunnerParallel:
    def __init__(self, config: dict[str, Any]) -> None:
        self.runs_no: int = config["runs_no"]
        self.profiling_metrics = config["profiling_metrics"] if "profiling_metrics" in config else None
        self.parallel_processes: int = int(config.get("parallel_processes", 1))
        self.config_path: Optional[str] = config.get("__config_path")
        self.scores: dict[str, int] = collections.defaultdict(int)
        self.first_places: dict[str, int] = collections.defaultdict(int)
        self.games_by_arena: dict[str, int] = collections.defaultdict(int)
        self.dummy_first_places_by_arena: dict[str, int] = collections.defaultdict(int)
        self.dummy_losses_to: dict[str, int] = collections.defaultdict(int)
        self.games_attempted: int = 0
        self.games_successful: int = 0
        self.games_failed: int = 0
        self.total_episodes: int = 0
        self.completed_chunks: int = 0
        self.failed_chunks: list[dict[str, Any]] = []
        self.controller_praise_exceptions: list[dict[str, str]] = []
        self.longest_game: dict[str, Any] = {
            "game_number": None,
            "episodes": -1,
            "arena_name": None,
            "winner_name": None,
        }
        self._controller_names: list[str] = [c.name for c in config.get("controllers", [])]

        if self.parallel_processes <= 1:
            raise ValueError("RunnerParallel requires config['parallel_processes'] > 1.")
        if not self.config_path:
            raise ValueError("RunnerParallel requires config['__config_path'] to spawn workers.")
        if config.get("__inquiry", False):
            raise ValueError("RunnerParallel does not support inquiry mode.")
        if config.get("visualise", False):
            raise ValueError("RunnerParallel requires visualise=False.")

    def run(self) -> None:
        chunks = _split_runs(self.runs_no, self.parallel_processes)
        ctx = multiprocessing.get_context("spawn")

        futures: dict[Any, dict[str, int]] = {}
        with ProcessPoolExecutor(max_workers=len(chunks), mp_context=ctx) as executor:
            game_offset = 0
            for chunk_idx, runs_no in enumerate(chunks):
                ParallelChunkSubmittedReport(
                    chunk_index=chunk_idx,
                    runs_no=runs_no,
                    game_offset=game_offset,
                    seed=(chunk_idx + 1) * 1_000_003 + runs_no * 131,
                ).log(logging.INFO)
                future = executor.submit(_run_chunk, self.config_path, runs_no, chunk_idx, game_offset)
                futures[future] = {
                    "chunk_index": chunk_idx,
                    "runs_no": runs_no,
                    "game_offset": game_offset,
                }
                game_offset += runs_no

            with tqdm(total=self.runs_no, desc=f"Playing games ({len(chunks)}x parallel)") as progress:
                for future in as_completed(futures):
                    chunk_meta = futures[future]
                    chunk_idx = chunk_meta["chunk_index"]
                    chunk_runs_no = chunk_meta["runs_no"]
                    try:
                        result = future.result()
                    except Exception as e:
                        error_message = repr(e)
                        self.failed_chunks.append({
                            "chunk_index": chunk_idx,
                            "error": error_message,
                        })
                        self.games_attempted += chunk_runs_no
                        self.games_failed += chunk_runs_no
                        ParallelChunkFailedReport(
                            chunk_index=chunk_idx,
                            runs_no=chunk_runs_no,
                            attempted_games=chunk_runs_no,
                            failed_games=chunk_runs_no,
                            error=error_message,
                            traceback_tail=None,
                        ).log(logging.WARN)
                        progress.update(chunk_runs_no)
                        continue

                    if not result.get("ok", False):
                        self.failed_chunks.append({
                            "chunk_index": result.get("chunk_index", chunk_idx),
                            "error": result.get("error", "unknown chunk failure"),
                            "traceback_tail": result.get("traceback_tail"),
                        })
                        self.games_attempted += chunk_runs_no
                        self.games_successful += result.get("successful_games", 0)
                        self.games_failed += result.get("failed_games", chunk_runs_no)
                        ParallelChunkFailedReport(
                            chunk_index=result.get("chunk_index", chunk_idx),
                            runs_no=result.get("runs_no", chunk_runs_no),
                            attempted_games=chunk_runs_no,
                            failed_games=result.get("failed_games", chunk_runs_no),
                            error=result.get("error", "unknown chunk failure"),
                            traceback_tail=result.get("traceback_tail"),
                        ).log(logging.WARN)
                        progress.update(chunk_runs_no)
                        continue

                    self.completed_chunks += 1
                    self.games_attempted += result["attempted_games"]
                    self.games_successful += result["successful_games"]
                    self.games_failed += result["failed_games"]
                    self.total_episodes += result["total_episodes"]

                    for name, score in result["scores"].items():
                        self.scores[name] += score
                    for name, wins in result["first_places"].items():
                        self.first_places[name] += wins
                    for arena_name, games_no in result["games_by_arena"].items():
                        self.games_by_arena[arena_name] += games_no
                    for arena_name, wins_no in result["dummy_first_places_by_arena"].items():
                        self.dummy_first_places_by_arena[arena_name] += wins_no
                    for winner_name, losses_no in result["dummy_losses_to"].items():
                        self.dummy_losses_to[winner_name] += losses_no

                    if result["longest_game"] and result["longest_game"]["episodes"] > self.longest_game["episodes"]:
                        self.longest_game = result["longest_game"]

                    self.controller_praise_exceptions.extend(result["controller_praise_exceptions"])

                    ParallelChunkFinishedReport(
                        chunk_index=result["chunk_index"],
                        seed=result["seed"],
                        runs_no=result["runs_no"],
                        attempted_games=result["attempted_games"],
                        successful_games=result["successful_games"],
                        failed_games=result["failed_games"],
                        duration_s=round(result["duration_s"], 3),
                        avg_episodes=round(
                            result["total_episodes"] / max(1, result["successful_games"]),
                            2,
                        ),
                    ).log(logging.INFO)

                    for game_report in result["game_summaries"]:
                        ParallelGameSummaryReport(
                            chunk_index=game_report["chunk_index"],
                            game_number=game_report["game_number"],
                            arena_name=game_report["arena_name"],
                            episodes=game_report["episodes"],
                            winner_name=game_report["winner_name"],
                            controller_order=game_report["controller_order"],
                            scores=game_report["scores"],
                            mist_radius_end=game_report["mist_radius_end"],
                            menhir_x=game_report["menhir_x"],
                            menhir_y=game_report["menhir_y"],
                            dummy_score=game_report["dummy_score"],
                            dummy_rank=game_report["dummy_rank"],
                            dummy_death_episode=game_report["dummy_death_episode"],
                            dummy_distance_to_menhir=game_report["dummy_distance_to_menhir"],
                            dummy_in_mist_on_death=game_report["dummy_in_mist_on_death"],
                        ).log(logging.DEBUG)

                    for failed_game in result["failed_game_reports"]:
                        ParallelGameFailedReport(
                            chunk_index=failed_game["chunk_index"],
                            game_number=failed_game["game_number"],
                            arena_name=failed_game["arena_name"],
                            error=failed_game["error"],
                            traceback_tail=failed_game["traceback_tail"],
                        ).log(logging.WARN)

                    progress.update(chunk_runs_no)

        avg_episodes = self.total_episodes / max(1, self.games_successful)
        ParallelRunSummaryReport(
            chunks_completed=self.completed_chunks,
            chunks_failed=len(self.failed_chunks),
            games_attempted=self.games_attempted,
            games_successful=self.games_successful,
            games_failed=self.games_failed,
            avg_episodes=round(avg_episodes, 2),
            dummy_first_places=self.first_places.get("DummyBot", 0),
        ).log(logging.INFO)

    def print_scores(self) -> None:
        verbose_logger.info("Final scores.")
        scores_to_log = []
        for i, (name, score) in enumerate(sorted(self.scores.items(), key=lambda x: x[1], reverse=True)):
            score_line = f"{int(i) + 1}.   {name}: {score}."
            verbose_logger.info(score_line)
            scores_to_log.append(ControllerScoreReport(name, score))
            print(score_line)
        FinalScoresReport(scores_to_log).log(logging.INFO)

        rate_base = self.games_successful if self.games_successful > 0 else self.runs_no
        if rate_base > 0:
            print("First-place rates:")
            for i, name in enumerate(sorted(self.scores.keys(), key=lambda n: self.first_places.get(n, 0), reverse=True)):
                wins = self.first_places.get(name, 0)
                rate = (wins / rate_base) * 100.0
                print(f"{int(i) + 1}.   {name}: {wins}/{rate_base} ({rate:.1f}%).")

            if "DummyBot" in self.scores:
                wins = self.first_places.get("DummyBot", 0)
                rate = (wins / rate_base) * 100.0
                print(f"DummyBot first-place rate: {wins}/{rate_base} ({rate:.1f}%).")

        print("Parallel observability:")
        print(
            f"chunks done: {self.completed_chunks}/{len(_split_runs(self.runs_no, self.parallel_processes))}, "
            f"chunk failures: {len(self.failed_chunks)}."
        )
        print(
            f"games attempted: {self.games_attempted}, successful: {self.games_successful}, "
            f"failed: {self.games_failed}."
        )
        if self.games_successful > 0:
            avg_episodes = self.total_episodes / self.games_successful
            print(f"avg episodes per successful game: {avg_episodes:.2f}.")
        if self.longest_game["episodes"] >= 0:
            print(
                "longest game: "
                f"#{self.longest_game['game_number']} "
                f"({self.longest_game['episodes']} episodes, arena={self.longest_game['arena_name']}, "
                f"winner={self.longest_game['winner_name']})."
            )
        if self.games_by_arena:
            print("Arena breakdown (DummyBot first-place):")
            for arena_name in sorted(self.games_by_arena.keys()):
                arena_games = self.games_by_arena[arena_name]
                dummy_wins = self.dummy_first_places_by_arena.get(arena_name, 0)
                dummy_rate = (dummy_wins / arena_games) * 100.0 if arena_games > 0 else 0.0
                print(f"{arena_name}: {dummy_wins}/{arena_games} ({dummy_rate:.1f}%).")
        if self.dummy_losses_to:
            print("DummyBot losses to:")
            for controller_name, losses_no in sorted(self.dummy_losses_to.items(), key=lambda item: item[1], reverse=True):
                print(f"{controller_name}: {losses_no}.")
        if self.controller_praise_exceptions:
            print(f"controller praise() exceptions observed: {len(self.controller_praise_exceptions)}.")
        if self.failed_chunks:
            print("Failed chunks:")
            for failed_chunk in self.failed_chunks:
                print(f"chunk {failed_chunk['chunk_index']}: {failed_chunk['error']}")

        if self.profiling_metrics:
            if PROFILE_RESULTS:
                for func in PROFILE_RESULTS.keys():
                    print_stats(func, **{m: True for m in self.profiling_metrics})
            else:
                print("Profiling metrics are not collected in parallel mode.")


@dataclass(frozen=True)
class GameStartReport(logger_core.LoggingMixin):
    game_number: int


@dataclass(frozen=True)
class RandomArenaPickReport(logger_core.LoggingMixin):
    arena_name: str


@dataclass(frozen=True)
class ControllerScoreReport(logger_core.LoggingMixin):
    controller_name: str
    score: int


@dataclass(frozen=True)
class FinalScoresReport(logger_core.LoggingMixin):
    scores: List[ControllerScoreReport]


@dataclass(frozen=True)
class ParallelChunkSubmittedReport(logger_core.LoggingMixin):
    chunk_index: int
    runs_no: int
    game_offset: int
    seed: int


@dataclass(frozen=True)
class ParallelChunkFinishedReport(logger_core.LoggingMixin):
    chunk_index: int
    seed: int
    runs_no: int
    attempted_games: int
    successful_games: int
    failed_games: int
    duration_s: float
    avg_episodes: float


@dataclass(frozen=True)
class ParallelChunkFailedReport(logger_core.LoggingMixin):
    chunk_index: int
    runs_no: int
    attempted_games: int
    failed_games: int
    error: str
    traceback_tail: Optional[str]


@dataclass(frozen=True)
class ParallelGameSummaryReport(logger_core.LoggingMixin):
    chunk_index: int
    game_number: int
    arena_name: str
    episodes: int
    winner_name: str
    controller_order: list[str]
    scores: dict[str, int]
    mist_radius_end: int
    menhir_x: Optional[int]
    menhir_y: Optional[int]
    dummy_score: Optional[int]
    dummy_rank: Optional[int]
    dummy_death_episode: Optional[int]
    dummy_distance_to_menhir: Optional[int]
    dummy_in_mist_on_death: Optional[bool]


@dataclass(frozen=True)
class ParallelGameFailedReport(logger_core.LoggingMixin):
    chunk_index: int
    game_number: int
    arena_name: Optional[str]
    error: str
    traceback_tail: str


@dataclass(frozen=True)
class ParallelRunSummaryReport(logger_core.LoggingMixin):
    chunks_completed: int
    chunks_failed: int
    games_attempted: int
    games_successful: int
    games_failed: int
    avg_episodes: float
    dummy_first_places: int
