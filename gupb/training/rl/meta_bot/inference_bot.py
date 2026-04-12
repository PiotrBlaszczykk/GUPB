from __future__ import annotations

import os
from typing import Optional

import numpy as np
import torch
from torch import nn

from gupb.model import characters

from .meta_bot import RLMetaBot
from .meta_bot import STYLE_COUNT
from gupb.training.rl.features import extract_features


class _InferenceQNetwork(nn.Module):
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


class CPUStylePolicy:
    """
    CPU-only style policy loader.
    Always loads weights with map_location="cpu".
    """

    def __init__(self, checkpoint_path: str) -> None:
        payload = torch.load(checkpoint_path, map_location="cpu")
        self.input_dim = int(payload["input_dim"])
        self.action_dim = int(payload["action_dim"])
        if self.action_dim != STYLE_COUNT:
            raise ValueError(f"Invalid action_dim in checkpoint: {self.action_dim}, expected {STYLE_COUNT}.")
        state_dict = payload.get("state_dict", payload.get("policy_state_dict"))
        if state_dict is None:
            raise RuntimeError("Checkpoint does not contain state_dict.")

        self.device = torch.device("cpu")
        self.model = _InferenceQNetwork(self.input_dim, self.action_dim)
        self.model.load_state_dict(state_dict)
        self.model.eval()

    def select_style(self, state_features: np.ndarray) -> int:
        with torch.no_grad():
            state_tensor = torch.as_tensor(state_features, dtype=torch.float32, device=self.device).unsqueeze(0)
            q_values = self.model(state_tensor)
            return int(torch.argmax(q_values, dim=1).item())


class RLMetaDQNBot(RLMetaBot):
    """
    Final inference bot for GUPB.
    Uses a DQN checkpoint on CPU only; never requires CUDA in runtime.
    """

    def __init__(
            self,
            bot_name: str = "RLMetaDQNBot",
            hold_turns: int = 3,
            checkpoint_path: Optional[str] = None,
    ) -> None:
        self.checkpoint_path = checkpoint_path
        self.policy: Optional[CPUStylePolicy] = None
        if checkpoint_path and os.path.exists(checkpoint_path):
            self.policy = CPUStylePolicy(checkpoint_path)
        super().__init__(
            bot_name=bot_name,
            hold_turns=hold_turns,
            style_selector=self._select_style,
        )

    def _select_style(
            self,
            knowledge: characters.ChampionKnowledge,
            current_style: int,
            turns_taken: int,
    ) -> int:
        _ = turns_taken
        if self.policy is None:
            return current_style
        features = extract_features(
            knowledge=knowledge,
            current_style=current_style,
            turns_until_switch=0,
            hold_turns=self.hold_turns,
        )
        if int(features.shape[0]) != self.policy.input_dim:
            return current_style
        return self.policy.select_style(features)
