"""
Компонент позиции и текущего действия агента.

float_x/float_y — точная позиция для движения и рендера.
tile_x/tile_y — floor(float_pos), для логики симуляции.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class Position:
    float_x: float = 0.0
    float_y: float = 0.0
    tile_x: int = 0
    tile_y: int = 0
    prev_tile_x: int = 0
    prev_tile_y: int = 0
    current_action: Optional[str] = None
    action_timer: int = 0
    target_x: Optional[int] = None
    target_y: Optional[int] = None
    path: List[Tuple[int, int]] = field(default_factory=list)
