from __future__ import annotations

from collections import deque
from dataclasses import asdict
from dataclasses import dataclass
import random
from typing import Any, Optional

import numpy as np
import torch
from torch import nn
from torch import optim
import torch.nn.functional as F


@dataclass(frozen=True)
class DQNConfig:
    gamma: float = 0.99
    learning_rate: float = 1e-3
    batch_size: int = 64
    buffer_size: int = 50_000
    min_buffer_size: int = 1_000
    target_update_interval: int = 250
    epsilon_start: float = 1.0
    epsilon_end: float = 0.05
    epsilon_decay_steps: int = 20_000
    gradient_clip_norm: float = 5.0


class ReplayBuffer:
    def __init__(self, capacity: int) -> None:
        self._buffer: deque[tuple[np.ndarray, int, float, np.ndarray, bool]] = deque(maxlen=capacity)

    def __len__(self) -> int:
        return len(self._buffer)

    def add(
            self,
            state: np.ndarray,
            action: int,
            reward: float,
            next_state: np.ndarray,
            done: bool,
    ) -> None:
        self._buffer.append((state.copy(), int(action), float(reward), next_state.copy(), bool(done)))

    def sample(
            self,
            batch_size: int,
            device: torch.device,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        batch = random.sample(self._buffer, batch_size)
        states, actions, rewards, next_states, dones = zip(*batch)
        state_tensor = torch.as_tensor(np.stack(states), dtype=torch.float32, device=device)
        action_tensor = torch.as_tensor(actions, dtype=torch.long, device=device).unsqueeze(1)
        reward_tensor = torch.as_tensor(rewards, dtype=torch.float32, device=device).unsqueeze(1)
        next_state_tensor = torch.as_tensor(np.stack(next_states), dtype=torch.float32, device=device)
        done_tensor = torch.as_tensor(dones, dtype=torch.float32, device=device).unsqueeze(1)
        return state_tensor, action_tensor, reward_tensor, next_state_tensor, done_tensor


class QNetwork(nn.Module):
    def __init__(self, input_dim: int, output_dim: int) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, 64),
            nn.ReLU(),
            nn.Linear(64, 64),
            nn.ReLU(),
            nn.Linear(64, output_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


class DQNAgent:
    def __init__(
            self,
            input_dim: int,
            action_dim: int,
            config: Optional[DQNConfig] = None,
            device: str = "cpu",
    ) -> None:
        self.input_dim = int(input_dim)
        self.action_dim = int(action_dim)
        self.config = config or DQNConfig()
        self.device = torch.device(device)

        self.policy_net = QNetwork(self.input_dim, self.action_dim).to(self.device)
        self.target_net = QNetwork(self.input_dim, self.action_dim).to(self.device)
        self.target_net.load_state_dict(self.policy_net.state_dict())
        self.target_net.eval()

        self.optimizer = optim.Adam(self.policy_net.parameters(), lr=self.config.learning_rate)
        self.replay_buffer = ReplayBuffer(self.config.buffer_size)

        self.env_steps: int = 0
        self.gradient_steps: int = 0

    @property
    def epsilon(self) -> float:
        progress = min(1.0, float(self.env_steps) / float(max(1, self.config.epsilon_decay_steps)))
        return float(self.config.epsilon_start + progress * (self.config.epsilon_end - self.config.epsilon_start))

    def select_action(self, state: np.ndarray, explore: bool = True) -> int:
        if explore and random.random() < self.epsilon:
            return random.randrange(self.action_dim)
        with torch.no_grad():
            state_tensor = torch.as_tensor(state, dtype=torch.float32, device=self.device).unsqueeze(0)
            q_values = self.policy_net(state_tensor)
            action = int(torch.argmax(q_values, dim=1).item())
            return action

    def observe(
            self,
            state: np.ndarray,
            action: int,
            reward: float,
            next_state: np.ndarray,
            done: bool,
    ) -> None:
        self.replay_buffer.add(state, action, reward, next_state, done)
        self.env_steps += 1

    def update(self) -> Optional[float]:
        required = max(self.config.batch_size, self.config.min_buffer_size)
        if len(self.replay_buffer) < required:
            return None

        states, actions, rewards, next_states, dones = self.replay_buffer.sample(
            self.config.batch_size,
            device=self.device,
        )
        q_values = self.policy_net(states).gather(1, actions)
        with torch.no_grad():
            next_q_values = self.target_net(next_states).max(dim=1, keepdim=True).values
            target_values = rewards + self.config.gamma * (1.0 - dones) * next_q_values

        loss = F.smooth_l1_loss(q_values, target_values)

        self.optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self.policy_net.parameters(), self.config.gradient_clip_norm)
        self.optimizer.step()

        self.gradient_steps += 1
        if self.gradient_steps % self.config.target_update_interval == 0:
            self.target_net.load_state_dict(self.policy_net.state_dict())

        return float(loss.item())

    def save(self, path: str, extra: Optional[dict[str, Any]] = None) -> None:
        payload = {
            "state_dict": self.policy_net.state_dict(),
            "input_dim": self.input_dim,
            "action_dim": self.action_dim,
            "config": asdict(self.config),
            "env_steps": self.env_steps,
            "gradient_steps": self.gradient_steps,
            "extra": extra or {},
        }
        torch.save(payload, path)


class DQNGreedyPolicy:
    """
    CPU-only inference policy. Safe for environments without CUDA.
    """

    def __init__(self, checkpoint_path: str) -> None:
        payload = torch.load(checkpoint_path, map_location="cpu")
        input_dim = int(payload["input_dim"])
        action_dim = int(payload["action_dim"])
        state_dict = payload.get("state_dict", payload.get("policy_state_dict"))
        if state_dict is None:
            raise RuntimeError("Checkpoint does not contain policy state dict.")
        self.device = torch.device("cpu")
        self.model = QNetwork(input_dim, action_dim).to(self.device)
        self.model.load_state_dict(state_dict)
        self.model.eval()

    def __call__(self, state: np.ndarray) -> int:
        with torch.no_grad():
            state_tensor = torch.as_tensor(state, dtype=torch.float32, device=self.device).unsqueeze(0)
            q_values = self.model(state_tensor)
            return int(torch.argmax(q_values, dim=1).item())
