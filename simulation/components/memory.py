"""
Компонент памяти агента.

Агент идёт к ближайшему ИЗВЕСТНОМУ источнику.
known_tiles ограничен MEMORY_KNOWN_TILES_LIMIT (LRU-eviction).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

import config


class BoundedTileSet:
    """Set with bounded size. Evicts oldest entries when full."""

    __slots__ = ("_set", "_order")

    def __init__(self, maxlen: int = 5000):
        self._set: Set[Tuple[int, int]] = set()
        self._order: deque[Tuple[int, int]] = deque(maxlen=maxlen)

    def add(self, tile: Tuple[int, int]) -> None:
        if tile not in self._set:
            if len(self._order) == self._order.maxlen:
                oldest = self._order[0]
                self._set.discard(oldest)
            self._order.append(tile)
            self._set.add(tile)

    def __contains__(self, tile: object) -> bool:
        return tile in self._set

    def __len__(self) -> int:
        return len(self._set)

    def __iter__(self):
        return iter(self._set)


@dataclass
class Memory:
    known_tiles: BoundedTileSet = field(
        default_factory=lambda: BoundedTileSet(config.MEMORY_KNOWN_TILES_LIMIT)
    )
    resource_locations: Dict[str, Set[Tuple[int, int]]] = field(default_factory=dict)
    last_successful: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    wants_social: bool = False
    social_cooldown: int = 0
    ask_cooldown: int = 0
    personal_log: List[dict] = field(default_factory=list)
    home_comfort: float = 0.5
    exploring: bool = False
