"""
TileType — перечисление типов тайлов.
TileMap  — хранение и доступ к тайлам карты.

Все свойства (цвет, проходимость) берутся из config.py.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Tuple

import config


class TileType(Enum):
    GRASS = "grass"
    FOREST = "forest"
    WATER = "water"
    ROCK = "rock"
    SHORE = "shore"

    @property
    def passable(self) -> bool:
        return config.TILE_PASSABLE[self.value]

    @property
    def color(self) -> Tuple[int, int, int]:
        return config.TILE_COLORS[self.value]

    @property
    def gives_food(self) -> bool:
        return self is TileType.FOREST

    @property
    def gives_water(self) -> bool:
        return self is TileType.SHORE or self is TileType.WATER


class TileMap:
    """2D-массив тайлов MAP_WIDTH × MAP_HEIGHT."""

    __slots__ = ("width", "height", "tiles")

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        # tiles[y][x] — строки × столбцы
        self.tiles: List[List[TileType]] = [
            [TileType.GRASS] * width for _ in range(height)
        ]

    # ── Доступ ──────────────────────────────────────────────────────

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def get_type(self, x: int, y: int) -> TileType:
        return self.tiles[y][x]

    def set_type(self, x: int, y: int, tile_type: TileType) -> None:
        self.tiles[y][x] = tile_type

    def is_passable(self, x: int, y: int) -> bool:
        if not self.in_bounds(x, y):
            return False
        return self.tiles[y][x].passable

    # ── Соседи ──────────────────────────────────────────────────────

    _DIRS = [(-1, 0), (1, 0), (0, -1), (0, 1),
             (-1, -1), (-1, 1), (1, -1), (1, 1)]

    def neighbors(self, x: int, y: int, passable_only: bool = True) -> List[Tuple[int, int]]:
        """Возвращает 8-связных соседей."""
        result: List[Tuple[int, int]] = []
        for dx, dy in self._DIRS:
            nx, ny = x + dx, y + dy
            if self.in_bounds(nx, ny):
                if not passable_only or self.tiles[ny][nx].passable:
                    result.append((nx, ny))
        return result

    def resource_tiles_near(self, x: int, y: int, resource: str) -> List[Tuple[int, int]]:
        """Соседние тайлы определённого типа (food / water)."""
        result: List[Tuple[int, int]] = []
        for dx, dy in self._DIRS:
            nx, ny = x + dx, y + dy
            if not self.in_bounds(nx, ny):
                continue
            t = self.tiles[ny][nx]
            if resource == "food" and t.gives_food:
                result.append((nx, ny))
            elif resource == "water" and t.gives_water:
                result.append((nx, ny))
        return result
