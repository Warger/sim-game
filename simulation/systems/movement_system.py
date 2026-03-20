"""
MovementSystem — перемещение агентов к цели.

Два уровня навигации:
    Уровень 1 — A* (глобальный путь):
        Строит маршрут по статичной карте через pathfinder.
        Кешируется — пересчёт только при смене цели.

    Уровень 2 — Steering (локальное избегание):
        direction   = нормализованный вектор к следующему waypoint
        separation  = сумма векторов отталкивания от агентов в радиусе 2 тайлов
        final_vec   = normalize(direction + separation × 0.5)
        float_pos  += final_vec × speed

Правила:
    - Один агент на один tile_pos
    - При коллизии — порядок обработки случайный (перемешивание каждый тик)
    - Ребёнок перемещается на тайл где опекун БЫЛ в прошлом тике
    - Тела умерших занимают тайл config.DEATH_BODY_TICKS

Импортирует:
    config (AGENT_BASE_SPEED, STEERING_SEPARATION_RADIUS, STEERING_SEPARATION_WEIGHT, MAX_AGENTS_PER_TILE)
    simulation.world.World
    simulation.components.position.Position
    simulation.components.body.Body
    simulation.components.identity.Identity
    simulation.map.pathfinder

Экспортирует: MovementSystem
"""

from __future__ import annotations

import random
from typing import Dict, List, Optional, Tuple

import config
from simulation.world import World
from simulation.components.body import Body
from simulation.components.identity import Identity
from simulation.components.position import Position
from simulation.map.pathfinder import PathCache

Coord = Tuple[int, int]


_STUCK_THRESHOLD = 10  # тиков без движения → сброс цели и рерут


class MovementSystem:
    """Moves agents towards their targets each tick."""

    def __init__(self) -> None:
        self._path_cache = PathCache()
        self._stuck_ticks: Dict[int, int] = {}  # eid -> тиков без движения
        self._last_tile: Dict[int, Coord] = {}   # eid -> прошлая позиция

    def update(self, world: World) -> None:
        # Collect all agents with positions
        agents: List[Tuple[int, Position]] = [
            (eid, pos) for eid, pos in world.get_all_with(Position)
        ]

        # Random processing order each tick
        random.shuffle(agents)

        # Build occupancy map: tile -> eid (for collision)
        occupied: Dict[Coord, int] = {}
        for eid, pos in agents:
            occupied[(pos.tile_x, pos.tile_y)] = eid

        # Index: parent eid -> set of child eids (for passthrough)
        children_of: Dict[int, set] = {}
        for eid, identity in world.get_all_with(Identity):
            if identity.guardian_id is not None:
                b = world.get_component(eid, Body)
                if b is not None and b.is_child:
                    children_of.setdefault(identity.guardian_id, set()).add(eid)

        for eid, pos in agents:
            body = world.get_component(eid, Body)
            identity = world.get_component(eid, Identity)

            # Busy agents don't move (eating, drinking, sleeping, local_wander)
            if pos.current_action in ("eating", "drinking", "sleeping", "local_wander"):
                continue

            # Children follow guardian
            if body is not None and body.is_child and identity is not None:
                self._move_child(world, eid, pos, identity, occupied)
                continue

            # No target — nothing to do
            if pos.target_x is None or pos.target_y is None:
                self._stuck_ticks.pop(eid, None)
                continue

            goal: Coord = (pos.target_x, pos.target_y)
            start: Coord = (pos.tile_x, pos.tile_y)

            # ── Stuck detection ───────────────────────────────────
            last = self._last_tile.get(eid)
            if last == start:
                stuck = self._stuck_ticks.get(eid, 0) + 1
                self._stuck_ticks[eid] = stuck
                if stuck >= _STUCK_THRESHOLD:
                    # Застряли — сбрасываем цель и выбираем побег в случайную сторону
                    self._path_cache.invalidate(eid)
                    escape = self._pick_escape_target(pos, world.map)
                    pos.target_x, pos.target_y = escape
                    pos.path.clear()
                    pos.current_action = "wander"
                    self._stuck_ticks[eid] = 0
                    continue
            else:
                self._stuck_ticks[eid] = 0
            self._last_tile[eid] = start

            # Already at goal
            if start == goal:
                pos.path.clear()
                continue

            # Get path (cached or compute)
            path = self._path_cache.get_path(eid, world.map, start, goal)

            if not path:
                # No path found — escape instead of retrying same target
                self._path_cache.invalidate(eid)
                escape = self._pick_escape_target(pos, world.map)
                pos.target_x, pos.target_y = escape
                pos.path.clear()
                pos.current_action = "wander"
                continue

            pos.path = path

            # ── Tile-based path following ─────────────────────────
            # Walk along the A* path step by step, up to speed tiles per tick.
            # This prevents overshooting turns and landing on impassable tiles.
            steps = int(config.AGENT_BASE_SPEED)
            final_tile = start
            advanced = False
            waypoints_consumed = 0

            for wp in path:
                if steps <= 0:
                    break
                if wp == start:
                    continue

                # Passability (should pass since A* uses passable tiles, but defensive)
                if not world.map.is_passable(wp[0], wp[1]):
                    break

                # Occupancy check — try sidestep if blocked
                occupant = occupied.get(wp)
                my_children = children_of.get(eid, set())
                if occupant is not None and occupant != eid:
                    if occupant in my_children:
                        pass  # свой ребёнок — проходим насквозь
                    else:
                        side = self._try_sidestep(
                            pos, wp, world.map, occupied, eid
                        )
                        if side is not None:
                            final_tile = side
                            steps -= 1
                            advanced = True
                            waypoints_consumed += 1
                            continue
                        break  # sidestep не удался — стоп

                final_tile = wp
                steps -= 1
                advanced = True
                waypoints_consumed += 1

            if advanced:
                old_tile: Coord = (pos.tile_x, pos.tile_y)

                # Если на целевом тайле стоит свой ребёнок — подвинуть его
                child_on_tile = occupied.get(final_tile)
                if child_on_tile is not None and child_on_tile in children_of.get(eid, set()):
                    child_pos = world.get_component(child_on_tile, Position)
                    if child_pos is not None:
                        # Ребёнок встаёт на старое место родителя или рядом
                        child_dest = old_tile
                        if occupied.get(child_dest) is not None and occupied.get(child_dest) != child_on_tile:
                            child_dest = self._find_free_adjacent(
                                final_tile, world.map, occupied, child_on_tile
                            ) or old_tile
                        child_old = (child_pos.tile_x, child_pos.tile_y)
                        if occupied.get(child_old) == child_on_tile:
                            del occupied[child_old]
                        occupied[child_dest] = child_on_tile
                        child_pos.prev_tile_x = child_pos.tile_x
                        child_pos.prev_tile_y = child_pos.tile_y
                        child_pos.tile_x = child_dest[0]
                        child_pos.tile_y = child_dest[1]
                        child_pos.float_x = float(child_dest[0])
                        child_pos.float_y = float(child_dest[1])

                # Update occupancy
                if occupied.get(old_tile) == eid:
                    del occupied[old_tile]
                occupied[final_tile] = eid

                pos.prev_tile_x = pos.tile_x
                pos.prev_tile_y = pos.tile_y
                pos.tile_x = final_tile[0]
                pos.tile_y = final_tile[1]
                pos.float_x = float(final_tile[0])
                pos.float_y = float(final_tile[1])

                # Trim consumed waypoints instead of full recompute
                self._path_cache.trim_path(eid, waypoints_consumed)

                # Reached goal
                if final_tile == goal:
                    pos.path.clear()
                    pos.target_x = None
                    pos.target_y = None

    def _move_child(
        self,
        world: World,
        eid: int,
        pos: Position,
        identity: Identity,
        occupied: Dict[Coord, int],
    ) -> None:
        """Child teleports to stay adjacent to guardian."""
        if identity.guardian_id is None:
            return

        guardian_pos = world.get_component(identity.guardian_id, Position)
        if guardian_pos is None:
            return

        gx, gy = guardian_pos.tile_x, guardian_pos.tile_y
        current: Coord = (pos.tile_x, pos.tile_y)

        # Already adjacent — stay put
        if max(abs(pos.tile_x - gx), abs(pos.tile_y - gy)) <= 1:
            return

        # Teleport to free tile adjacent to guardian
        for ddx in range(-1, 2):
            for ddy in range(-1, 2):
                if ddx == 0 and ddy == 0:
                    continue
                candidate = (gx + ddx, gy + ddy)
                occupant = occupied.get(candidate)
                if occupant is None or occupant == eid:
                    if occupied.get(current) == eid:
                        del occupied[current]
                    occupied[candidate] = eid
                    pos.prev_tile_x = pos.tile_x
                    pos.prev_tile_y = pos.tile_y
                    pos.tile_x = candidate[0]
                    pos.tile_y = candidate[1]
                    pos.float_x = float(candidate[0])
                    pos.float_y = float(candidate[1])
                    return

    @staticmethod
    def _is_blocking(
        child: Coord, guardian: Coord, guardian_target: Coord
    ) -> bool:
        """Check if child tile is on the line between guardian and target."""
        # Simple check: child is adjacent to guardian and closer to target
        dist_g = abs(guardian[0] - guardian_target[0]) + abs(
            guardian[1] - guardian_target[1]
        )
        dist_c = abs(child[0] - guardian_target[0]) + abs(
            child[1] - guardian_target[1]
        )
        return dist_c < dist_g

    @staticmethod
    def _swap_positions(
        child_pos: Position,
        guardian_pos: Position,
        occupied: Dict[Coord, int],
    ) -> None:
        """Swap tile positions of child and guardian."""
        # Save
        cx, cy = child_pos.tile_x, child_pos.tile_y
        gx, gy = guardian_pos.tile_x, guardian_pos.tile_y

        c_tile = (cx, cy)
        g_tile = (gx, gy)
        c_eid = occupied.get(c_tile)
        g_eid = occupied.get(g_tile)

        # Swap positions
        child_pos.prev_tile_x = cx
        child_pos.prev_tile_y = cy
        child_pos.tile_x = gx
        child_pos.tile_y = gy
        child_pos.float_x = float(gx)
        child_pos.float_y = float(gy)

        guardian_pos.prev_tile_x = gx
        guardian_pos.prev_tile_y = gy
        guardian_pos.tile_x = cx
        guardian_pos.tile_y = cy
        guardian_pos.float_x = float(cx)
        guardian_pos.float_y = float(cy)

        # Update occupancy
        if c_eid is not None:
            occupied[g_tile] = c_eid
        if g_eid is not None:
            occupied[c_tile] = g_eid

    @staticmethod
    def _try_sidestep(
        pos: Position,
        blocked: Coord,
        tile_map,
        occupied: Dict[Coord, int],
        eid: int,
    ) -> Optional[Coord]:
        """Try stepping to a side tile when the path is blocked."""
        cx, cy = pos.tile_x, pos.tile_y
        bx, by = blocked
        dx, dy = bx - cx, by - cy
        if dx == 0 and dy == 0:
            return None
        # Two perpendicular options
        sides = [(-dy, dx), (dy, -dx)]
        for sdx, sdy in sides:
            nx, ny = cx + sdx, cy + sdy
            if not tile_map.is_passable(nx, ny):
                continue
            occ = occupied.get((nx, ny))
            if occ is not None and occ != eid:
                continue
            return (nx, ny)
        return None

    @staticmethod
    def _find_free_adjacent(
        center: Coord, tile_map, occupied: Dict[Coord, int], eid: int,
    ) -> Optional[Coord]:
        """Find a free passable tile adjacent to center."""
        cx, cy = center
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = cx + dx, cy + dy
                if not tile_map.is_passable(nx, ny):
                    continue
                occ = occupied.get((nx, ny))
                if occ is None or occ == eid:
                    return (nx, ny)
        return None

    @staticmethod
    def _pick_escape_target(pos: Position, tile_map) -> Coord:
        """Pick a random nearby passable tile to escape when stuck."""
        cx, cy = pos.tile_x, pos.tile_y
        # Try random directions at increasing distances
        for radius in (5, 10, 20):
            for _ in range(8):
                dx = random.randint(-radius, radius)
                dy = random.randint(-radius, radius)
                tx = max(0, min(tile_map.width - 1, cx + dx))
                ty = max(0, min(tile_map.height - 1, cy + dy))
                if tile_map.is_passable(tx, ty):
                    return (tx, ty)
        return (cx, cy)
