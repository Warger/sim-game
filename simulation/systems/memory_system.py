"""
MemorySystem — обновление known_tiles по радиусу обзора.

Каждый тик для каждого агента:
    - Все тайлы в радиусе AGENT_VISION_RADIUS добавляются в known_tiles
    - Если тайл содержит еду (forest) или воду (shore/water) —
      добавляется в resource_locations["food"] / resource_locations["water"]
    - Память не забывается в MVP 1
"""

from __future__ import annotations

import logging
import math
import random
from typing import Optional, Tuple

import config
from simulation.world import World
from simulation.components.position import Position
from simulation.components.memory import Memory
from simulation.components.traits import Traits

logger = logging.getLogger(__name__)


class MemorySystem:

    def update(self, world: World) -> None:
        tile_map = world.map
        radius = config.AGENT_VISION_RADIUS
        interval = config.VISION_UPDATE_INTERVAL

        for eid, pos in world.get_all_with(Position):
            mem = world.get_component(eid, Memory)
            if mem is None:
                continue

            if mem.ask_cooldown > 0:
                mem.ask_cooldown -= 1

            # Полное сканирование видимости только раз в N тиков,
            # распределяя агентов по разным тикам через eid % interval
            if (world.tick + eid) % interval != 0:
                continue

            cx, cy = pos.tile_x, pos.tile_y

            x_min = max(0, cx - radius)
            x_max = min(tile_map.width - 1, cx + radius)
            y_min = max(0, cy - radius)
            y_max = min(tile_map.height - 1, cy + radius)

            r_sq = radius * radius

            for ty in range(y_min, y_max + 1):
                dy = ty - cy
                dy_sq = dy * dy
                for tx in range(x_min, x_max + 1):
                    dx = tx - cx
                    if dx * dx + dy_sq > r_sq:
                        continue

                    coord = (tx, ty)
                    mem.known_tiles.add(coord)

                    tile = tile_map.get_type(tx, ty)
                    # Запоминаем только проходимые ресурсные тайлы,
                    # чтобы pathfinder мог до них довести
                    if tile.gives_food and tile.passable:
                        if "food" not in mem.resource_locations:
                            mem.resource_locations["food"] = set()
                        mem.resource_locations["food"].add(coord)
                    if tile.gives_water and tile.passable:
                        if "water" not in mem.resource_locations:
                            mem.resource_locations["water"] = set()
                        mem.resource_locations["water"].add(coord)

    @staticmethod
    def get_nearest_resource(
        world: World, eid: int, resource_type: str
    ) -> Optional[Tuple[int, int]]:
        """Возвращает (tile_x, tile_y) ближайшего известного ресурса или None."""
        mem = world.get_component(eid, Memory)
        if mem is None:
            return None

        locations = mem.resource_locations.get(resource_type)
        if not locations:
            return None

        pos = world.get_component(eid, Position)
        if pos is None:
            return None

        cx, cy = pos.tile_x, pos.tile_y
        best: Optional[Tuple[int, int]] = None
        best_dist_sq = float("inf")

        for tx, ty in locations:
            dist_sq = (tx - cx) ** 2 + (ty - cy) ** 2
            if dist_sq < best_dist_sq:
                best_dist_sq = dist_sq
                best = (tx, ty)

        return best

    @staticmethod
    def ask_nearby_for_resource(
        world: World, eid: int, resource_type: str
    ) -> bool:
        """Спрашивает ближайшего агента в радиусе ASK_RESOURCE_RADIUS,
        знает ли тот, где находится ресурс. При успехе — копирует знания."""
        mem = world.get_component(eid, Memory)
        pos = world.get_component(eid, Position)
        traits = world.get_component(eid, Traits)
        if mem is None or pos is None:
            return False

        if mem.ask_cooldown > 0:
            return False

        cx, cy = pos.tile_x, pos.tile_y
        asker_soc = traits.sociality if traits is not None else config.TRAIT_MEAN

        for other_eid, _, _ in world.spatial.query_chebyshev(
            cx, cy, config.ASK_RESOURCE_RADIUS
        ):
            if other_eid == eid:
                continue

            other_mem = world.get_component(other_eid, Memory)
            if other_mem is None:
                continue

            other_locs = other_mem.resource_locations.get(resource_type)
            if not other_locs:
                continue

            other_traits = world.get_component(other_eid, Traits)
            sharer_soc = other_traits.sociality if other_traits is not None else config.TRAIT_MEAN
            chance = asker_soc * sharer_soc

            if random.random() >= chance:
                continue

            # Успех — копируем знания о ресурсе
            if resource_type not in mem.resource_locations:
                mem.resource_locations[resource_type] = set()
            mem.resource_locations[resource_type].update(other_locs)

            mem.ask_cooldown = config.ASK_RESOURCE_COOLDOWN_TICKS

            world.event_queue.append({
                "type": "knowledge_shared",
                "participants": [eid, other_eid],
                "resource": resource_type,
                "tick": world.tick,
            })

            if config.DEBUG:
                logger.debug(
                    "tick=%d eid=%d asked eid=%d for %s → shared %d locations",
                    world.tick, eid, other_eid, resource_type, len(other_locs),
                )
            return True

        # Никто не поделился — ставим cooldown чтобы не спамить
        mem.ask_cooldown = config.ASK_RESOURCE_COOLDOWN_TICKS
        return False
