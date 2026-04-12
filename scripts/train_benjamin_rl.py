from __future__ import annotations

import argparse
import os
import random

import numpy as np
import torch

from gupb.training.rl.benjamin.env import BenjaminRLEnv
from gupb.training.rl.dqn import DQNAgent
from gupb.training.rl.dqn import DQNConfig
from gupb.training.rl.reward import RewardConfig

MODE_INDEX_TO_NAME = {
    0: "normal",
    1: "aggressive",
    2: "passive",
}


def _phase_name(champions_alive: int) -> str:
    if champions_alive >= 5:
        return "early"
    if champions_alive >= 3:
        return "mid"
    return "late"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train DQN mode selector for BenjaminNetanyahu.")
    parser.add_argument("--episodes", type=int, default=200, help="Number of training games.")
    parser.add_argument("--max-rl-steps", type=int, default=256, help="Max RL mode decisions per game.")
    parser.add_argument("--mode-horizon", type=int, default=3, help="How many own turns chosen mode remains active.")
    parser.add_argument("--max-cycles", type=int, default=10_000, help="Hard cap for raw game cycles per game.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed.")
    parser.add_argument(
        "--device",
        type=str,
        default="auto",
        help="Torch device: auto, cpu or cuda. 'auto' uses cuda when available.",
    )
    parser.add_argument(
        "--arenas",
        type=str,
        default="ordinary_chaos,mini,isolated_shrine,lone_sanctum",
        help="Comma-separated arena names.",
    )
    parser.add_argument(
        "--save-path",
        type=str,
        default="results/benjamin_dqn_state_dict.pt",
        help="Path to output checkpoint containing policy state_dict.",
    )
    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=0,
        help="Save intermediate checkpoints every N episodes (0 disables).",
    )
    parser.add_argument(
        "--checkpoint-dir",
        type=str,
        default="",
        help="Directory for intermediate checkpoints (defaults to save-path directory).",
    )
    parser.add_argument(
        "--checkpoint-prefix",
        type=str,
        default="benjamin_dqn",
        help="File prefix for intermediate checkpoints.",
    )
    parser.add_argument(
        "--allow-oracle-menhir",
        action="store_true",
        help="If set, training bot keeps oracle menhir behavior from baseline heuristics.",
    )

    parser.add_argument("--win-reward", type=float, default=40.0)
    parser.add_argument("--death-penalty", type=float, default=-25.0)
    parser.add_argument("--survival-progress-bonus", type=float, default=0.15)

    parser.add_argument("--gamma", type=float, default=0.99)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--buffer-size", type=int, default=50_000)
    parser.add_argument("--min-buffer-size", type=int, default=1_000)
    parser.add_argument("--target-update-interval", type=int, default=250)
    parser.add_argument("--epsilon-start", type=float, default=1.0)
    parser.add_argument("--epsilon-end", type=float, default=0.05)
    parser.add_argument("--epsilon-decay-steps", type=int, default=20_000)
    parser.add_argument("--gradient-clip-norm", type=float, default=5.0)
    return parser.parse_args()


def resolve_device(requested: str) -> str:
    requested_norm = requested.strip().lower()
    if requested_norm == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if requested_norm == "cuda" and not torch.cuda.is_available():
        print("Requested CUDA, but CUDA is unavailable. Falling back to CPU.")
        return "cpu"
    return requested_norm


def main() -> None:
    args = parse_args()
    arenas = [arena.strip() for arena in args.arenas.split(",") if arena.strip()]
    if not arenas:
        raise ValueError("At least one arena is required.")

    device = resolve_device(args.device)
    print(f"Using torch device: {device}")

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    reward_config = RewardConfig(
        win_reward=args.win_reward,
        death_penalty=args.death_penalty,
        survival_progress_bonus=args.survival_progress_bonus,
    )
    env = BenjaminRLEnv(
        arenas=arenas,
        mode_horizon_turns=args.mode_horizon,
        max_cycles_per_episode=args.max_cycles,
        seed=args.seed,
        reward_config=reward_config,
        allow_oracle_menhir=args.allow_oracle_menhir,
    )
    config = DQNConfig(
        gamma=args.gamma,
        learning_rate=args.learning_rate,
        batch_size=args.batch_size,
        buffer_size=args.buffer_size,
        min_buffer_size=args.min_buffer_size,
        target_update_interval=args.target_update_interval,
        epsilon_start=args.epsilon_start,
        epsilon_end=args.epsilon_end,
        epsilon_decay_steps=args.epsilon_decay_steps,
        gradient_clip_norm=args.gradient_clip_norm,
    )
    agent = DQNAgent(
        input_dim=env.observation_dim,
        action_dim=env.action_space_n,
        config=config,
        device=device,
    )

    recent_returns: list[float] = []
    mode_usage_global: dict[str, int] = {mode_name: 0 for mode_name in MODE_INDEX_TO_NAME.values()}
    mode_usage_by_phase: dict[str, dict[str, int]] = {
        "early": {mode_name: 0 for mode_name in MODE_INDEX_TO_NAME.values()},
        "mid": {mode_name: 0 for mode_name in MODE_INDEX_TO_NAME.values()},
        "late": {mode_name: 0 for mode_name in MODE_INDEX_TO_NAME.values()},
    }

    checkpoint_every = max(0, int(args.checkpoint_every))
    checkpoint_dir = args.checkpoint_dir.strip() if args.checkpoint_dir else ""
    if not checkpoint_dir:
        checkpoint_dir = os.path.dirname(args.save_path) or "."

    save_extra = {
        "arenas": arenas,
        "mode_horizon_turns": args.mode_horizon,
        "observation_dim": env.observation_dim,
        "action_dim": env.action_space_n,
        "allow_oracle_menhir": bool(args.allow_oracle_menhir),
        "reward": {
            "win_reward": args.win_reward,
            "death_penalty": args.death_penalty,
            "survival_progress_bonus": args.survival_progress_bonus,
        },
    }

    for episode in range(1, args.episodes + 1):
        state = env.reset()
        episode_return = 0.0
        episode_losses: list[float] = []
        done = False
        info = {"won": False, "benjamin_alive": True, "current_mode": "normal"}

        for _ in range(args.max_rl_steps):
            action = agent.select_action(state, explore=True)
            next_state, reward, done, info = env.step(action)

            mode_name = MODE_INDEX_TO_NAME.get(int(action), "unknown")
            mode_usage_global[mode_name] = mode_usage_global.get(mode_name, 0) + 1
            phase = _phase_name(int(info.get("champions_alive_before", info.get("champions_alive", 0))))
            if phase not in mode_usage_by_phase:
                mode_usage_by_phase[phase] = {mode: 0 for mode in MODE_INDEX_TO_NAME.values()}
            mode_usage_by_phase[phase][mode_name] = mode_usage_by_phase[phase].get(mode_name, 0) + 1

            agent.observe(state, action, reward, next_state, done)
            loss = agent.update()
            if loss is not None:
                episode_losses.append(loss)

            state = next_state
            episode_return += reward
            if done:
                break

        recent_returns.append(episode_return)
        if len(recent_returns) > 30:
            recent_returns.pop(0)
        avg_recent_return = float(np.mean(recent_returns)) if recent_returns else 0.0
        avg_loss = float(np.mean(episode_losses)) if episode_losses else float("nan")
        loss_str = f"{avg_loss:.4f}" if episode_losses else "n/a"
        print(
            f"episode={episode:4d} "
            f"return={episode_return:8.3f} "
            f"avg30={avg_recent_return:8.3f} "
            f"epsilon={agent.epsilon:5.3f} "
            f"win={int(bool(info.get('won', False)))} "
            f"alive={int(bool(info.get('benjamin_alive', False)))} "
            f"mode={str(info.get('current_mode', 'unknown'))} "
            f"loss={loss_str}"
        )

        if checkpoint_every > 0 and episode % checkpoint_every == 0:
            os.makedirs(checkpoint_dir, exist_ok=True)
            checkpoint_path = os.path.join(
                checkpoint_dir,
                f"{args.checkpoint_prefix}_ep{episode:04d}.pt",
            )
            agent.save(
                checkpoint_path,
                extra={
                    **save_extra,
                    "episode": int(episode),
                    "epsilon": float(agent.epsilon),
                },
            )
            print(f"Saved intermediate checkpoint to: {checkpoint_path}")

    os.makedirs(os.path.dirname(args.save_path) or ".", exist_ok=True)
    agent.save(
        args.save_path,
        extra=save_extra,
    )
    print(f"Saved checkpoint to: {args.save_path}")

    total_mode_choices = int(sum(mode_usage_global.values()))
    print("Policy usage (global):")
    for mode_name in MODE_INDEX_TO_NAME.values():
        count = int(mode_usage_global.get(mode_name, 0))
        share = (100.0 * float(count) / float(total_mode_choices)) if total_mode_choices > 0 else 0.0
        print(f"  {mode_name:10s}: {count:6d} ({share:5.1f}%)")

    print("Policy usage (by phase):")
    for phase_name in ("early", "mid", "late"):
        phase_counts = mode_usage_by_phase.get(phase_name, {})
        phase_total = int(sum(phase_counts.values()))
        print(f"  {phase_name}: total={phase_total}")
        for mode_name in MODE_INDEX_TO_NAME.values():
            count = int(phase_counts.get(mode_name, 0))
            share = (100.0 * float(count) / float(phase_total)) if phase_total > 0 else 0.0
            print(f"    {mode_name:10s}: {count:6d} ({share:5.1f}%)")


if __name__ == "__main__":
    main()
