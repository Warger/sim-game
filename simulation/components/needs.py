"""
Компонент потребностей агента.

Все float 0.0–1.0. Логика убывания — в NeedsSystem.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import config


@dataclass
class Needs:
    hunger: float = field(default_factory=lambda: config.START_NEEDS_MAX)
    thirst: float = field(default_factory=lambda: config.START_NEEDS_MAX)
    energy: float = field(default_factory=lambda: config.START_NEEDS_MAX)
    health: float = 1.0
    mood: float = field(default_factory=lambda: config.START_NEEDS_MAX)
    social: float = field(default_factory=lambda: config.START_NEEDS_MAX)
    safety: float = field(default_factory=lambda: config.START_NEEDS_MAX)
