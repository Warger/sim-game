"""
World — единственный источник правды о состоянии симуляции.

Хранит:
    entities: set[int]                          — множество живых entity ID
    components: dict[type, dict[int, Component]] — компоненты по типу и entity ID
    map: TileMap                                — карта тайлов
    event_queue: list                           — события текущего тика (очищается каждый тик)
    tick: int                                   — текущий тик симуляции

Ни одна система не хранит данные у себя — всё через World.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, Optional, Set, Tuple, Type, TypeVar

from simulation.map.tile import TileMap
from simulation.spatial_index import SpatialGrid

T = TypeVar("T")


class World:
    __slots__ = ("entities", "components", "map", "event_queue", "tick", "_next_id", "corpses", "spatial")

    def __init__(self, tile_map: TileMap) -> None:
        self.entities: Set[int] = set()
        self.components: Dict[type, Dict[int, Any]] = {}
        self.map: TileMap = tile_map
        self.event_queue: list = []
        self.tick: int = 0
        self._next_id: int = 0
        self.corpses: list = []
        self.spatial: SpatialGrid = SpatialGrid(cell_size=16)

    # ── Entity lifecycle ──────────────────────────────────────────────

    def add_entity(self) -> int:
        """Создаёт новый entity, возвращает его ID."""
        eid = self._next_id
        self._next_id += 1
        self.entities.add(eid)
        return eid

    def remove_entity(self, eid: int) -> None:
        """Удаляет entity и все его компоненты."""
        self.entities.discard(eid)
        for store in self.components.values():
            store.pop(eid, None)

    # ── Component access ──────────────────────────────────────────────

    def add_component(self, eid: int, component: Any) -> None:
        """Привязывает компонент к entity."""
        comp_type = type(component)
        if comp_type not in self.components:
            self.components[comp_type] = {}
        self.components[comp_type][eid] = component

    def get_component(self, eid: int, comp_type: Type[T]) -> Optional[T]:
        """Возвращает компонент или None."""
        store = self.components.get(comp_type)
        if store is None:
            return None
        return store.get(eid)

    def has_component(self, eid: int, comp_type: type) -> bool:
        store = self.components.get(comp_type)
        return store is not None and eid in store

    def get_all_with(self, comp_type: Type[T]) -> Iterator[Tuple[int, T]]:
        """Итератор (entity_id, component) для всех entity с данным компонентом."""
        store = self.components.get(comp_type)
        if store is None:
            return
        for eid, comp in store.items():
            if eid in self.entities:
                yield eid, comp
