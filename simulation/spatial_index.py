"""
SpatialGrid — пространственный индекс для быстрого поиска соседей.

Разбивает карту на ячейки cell_size × cell_size.
Перестраивается один раз за тик в GameLoop, используется всеми системами
для proximity-запросов вместо O(N²) перебора.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterator, List, Tuple


class SpatialGrid:
    __slots__ = ("cell_size", "_cells")

    def __init__(self, cell_size: int = 16) -> None:
        self.cell_size = cell_size
        self._cells: dict[Tuple[int, int], List[Tuple[int, int, int]]] = defaultdict(list)

    def rebuild(self, entities_positions: Iterator[Tuple[int, int, int]]) -> None:
        """Перестраивает индекс из итератора (eid, x, y)."""
        self._cells.clear()
        cs = self.cell_size
        for eid, x, y in entities_positions:
            self._cells[(x // cs, y // cs)].append((eid, x, y))

    def query_radius(self, x: int, y: int, radius: int) -> Iterator[Tuple[int, int, int]]:
        """Возвращает (eid, ex, ey) всех агентов в квадрате Chebyshev-радиуса."""
        cs = self.cell_size
        r = radius // cs + 1
        cx, cy = x // cs, y // cs
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                cell = self._cells.get((cx + dx, cy + dy))
                if cell:
                    yield from cell

    def query_chebyshev(self, x: int, y: int, radius: int) -> Iterator[Tuple[int, int, int]]:
        """Возвращает (eid, ex, ey) с точной Chebyshev-фильтрацией."""
        for eid, ex, ey in self.query_radius(x, y, radius):
            if max(abs(ex - x), abs(ey - y)) <= radius:
                yield eid, ex, ey
