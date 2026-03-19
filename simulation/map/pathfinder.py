"""
A* патфайндинг с кешированием путей.

Строит маршрут по статичной карте (вода и скалы непроходимы).
Выдаёт список waypoints: [(x1,y1), (x2,y2), ...].
Кеш: пересчёт только при смене цели.

При 100+ агентах — профилировать этот модуль.

Импортирует:
    simulation.map.tile.TileMap

Экспортирует:
    find_path(tile_map, start, goal) -> list[tuple[int,int]]
    PathCache — кеш маршрутов с инвалидацией по смене цели
"""

from __future__ import annotations

import heapq
from typing import Dict, List, Optional, Tuple

from simulation.map.tile import TileMap

Coord = Tuple[int, int]


def _heuristic(a: Coord, b: Coord) -> float:
    """Chebyshev distance (8-directional movement)."""
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def find_path(
    tile_map: TileMap,
    start: Coord,
    goal: Coord,
) -> List[Coord]:
    """A* search on the tile grid.

    Returns list of (x, y) from start (exclusive) to goal (inclusive).
    Returns empty list if no path found or start == goal.
    """
    if start == goal:
        return []

    # Goal must be passable (or we'll never reach it)
    if not tile_map.is_passable(goal[0], goal[1]):
        return []

    open_heap: list[Tuple[float, Coord]] = []
    heapq.heappush(open_heap, (0.0, start))

    came_from: Dict[Coord, Optional[Coord]] = {start: None}
    g_score: Dict[Coord, float] = {start: 0.0}

    while open_heap:
        _, current = heapq.heappop(open_heap)

        if current == goal:
            # Reconstruct path (start exclusive, goal inclusive)
            path: List[Coord] = []
            node: Optional[Coord] = current
            while node is not None and node != start:
                path.append(node)
                node = came_from[node]
            path.reverse()
            return path

        current_g = g_score[current]

        for nx, ny in tile_map.neighbors(current[0], current[1], passable_only=True):
            neighbor = (nx, ny)
            new_g = current_g + 1.0
            if neighbor not in g_score or new_g < g_score[neighbor]:
                g_score[neighbor] = new_g
                f = new_g + _heuristic(neighbor, goal)
                heapq.heappush(open_heap, (f, neighbor))
                came_from[neighbor] = current

    return []


def get_next_waypoint(
    path: List[Coord],
    current_tile: Coord,
) -> Optional[Coord]:
    """Returns next waypoint to move towards.

    Scans path for current_tile position and returns the next step.
    If current_tile is not on the path, returns path[0] (head towards start of path).
    If path is empty or current_tile is the last point, returns None.
    """
    if not path:
        return None

    # Find current position in path
    for i, point in enumerate(path):
        if point == current_tile:
            if i + 1 < len(path):
                return path[i + 1]
            return None  # already at end

    # Not on path — head towards first waypoint
    return path[0]


class PathCache:
    """Per-agent path cache. Invalidated when goal changes."""

    __slots__ = ("_cache",)

    def __init__(self) -> None:
        # eid -> (start, goal, path)
        self._cache: Dict[int, Tuple[Coord, Coord, List[Coord]]] = {}

    def get_path(
        self,
        eid: int,
        tile_map: TileMap,
        start: Coord,
        goal: Coord,
    ) -> List[Coord]:
        """Returns cached path or computes and caches a new one."""
        cached = self._cache.get(eid)
        if cached is not None and cached[0] == start and cached[1] == goal:
            return cached[2]

        path = find_path(tile_map, start, goal)
        self._cache[eid] = (start, goal, path)
        return path

    def invalidate(self, eid: int) -> None:
        self._cache.pop(eid, None)

    def invalidate_all(self) -> None:
        self._cache.clear()
