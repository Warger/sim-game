"""
Компонент физического состояния агента.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Body:
    age: int = 0
    sex: str = "male"
    is_child: bool = False
    is_pregnant: bool = False
    pregnancy_timer: int = 0
    father_id: int = -1
    elder_decay_coeff: float = 1.0
    starving_ticks: int = 0
    dehydration_ticks: int = 0
    orphaned: bool = False
    orphan_timer: int = 0
