from __future__ import annotations

import argparse
import os
import random

import numpy as np
import torch

from gupb.training.rl.dqn import DQNAgent
from gupb.training.rl.dqn import DQNConfig
from gupb.training.rl.meta_bot.env import RLMetaBotEnv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train DQN-based RL meta-bot for GUPB.")
    parser.add_argument("--episodes", type=int, default=200, help="Number of training games.")
    parser.add_argument("--max-rl-steps", type=int, default=256, help="Max RL decisions per game.")
    parser.add_argument("--hold-turns", type=int, default=3, help="How many own turns each chosen style remains active.")
    parser.add_argument("--max-cycles", type=int, default=10_000, help="Hard cap for raw game cycles in one game.")
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
        default="results/rl_meta_dqn_state_dict.pt",
        help="Path to output checkpoint containing policy state_dict.",
    )

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

    env = RLMetaBotEnv(
        arenas=arenas,
        style_hold_turns=args.hold_turns,
        max_cycles_per_episode=args.max_cycles,
        seed=args.seed,
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
    for episode in range(1, args.episodes + 1):
        state = env.reset()
        episode_return = 0.0
        episode_losses: list[float] = []
        done = False
        info = {"won": False, "meta_alive": True}

        for _ in range(args.max_rl_steps):
            action = agent.select_action(state, explore=True)
            next_state, reward, done, info = env.step(action)

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
            f"alive={int(bool(info.get('meta_alive', False)))} "
            f"loss={loss_str}"
        )

    os.makedirs(os.path.dirname(args.save_path) or ".", exist_ok=True)
    agent.save(
        args.save_path,
        extra={
            "arenas": arenas,
            "hold_turns": args.hold_turns,
            "observation_dim": env.observation_dim,
            "action_dim": env.action_space_n,
        },
    )
    print(f"Saved checkpoint to: {args.save_path}")


if __name__ == "__main__":
    main()
