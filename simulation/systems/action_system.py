"""
ActionSystem — выполнение действий на месте.

Обрабатывает агентов у которых current_action установлен и они на целевом тайле:
    eating   — 40 тиков, градуально восполняет hunger (стоя рядом с лесом)
    drinking — 20 тиков, градуально восполняет thirst (стоя рядом с берегом/водой)
    sleeping — 160 тиков, градуально восполняет energy

Каждый тик: восполняет потребность на (1.0 / duration), уменьшает action_timer.
По завершении сбрасывает current_action.
Агент не заходит на тайл ресурса — ест/пьёт стоя на соседнем тайле.

Порядок в GameLoop: ... → Movement → Action.

Импортирует:
    config (ACTION_DURATION)
    simulation.world.World
    simulation.components.position.Position
    simulation.components.needs.Needs
    simulation.components.memory.Memory

Экспортирует: ActionSystem
"""

from __future__ import annotations

import logging
from typing import Dict, Optional, Tuple

import config
from simulation.world import World
from simulation.components.needs import Needs
from simulation.components.position import Position
from simulation.components.memory import Memory
from simulation.components.identity import Identity
from simulation.components.body import Body

logger = logging.getLogger(__name__)

# go_action → (in-place action name, need to restore)
_GO_TO_ACTION: Dict[str, Tuple[str, str]] = {
    "go_eat":      ("eating",       "hunger"),
    "go_drink":    ("drinking",     "thirst"),
    "go_sleep":    ("sleeping",     "energy"),
    "go_activity": ("local_wander", "activity"),
}

# Reverse: in-place action → need to restore
_ACTION_TO_NEED: Dict[str, str] = {act: need for act, need in _GO_TO_ACTION.values()}


class ActionSystem:
    """Запускает и завершает действия на месте."""

    def update(self, world: World) -> None:
        for eid, pos in world.get_all_with(Position):
            needs = world.get_component(eid, Needs)

            # ── Тикаем таймер ───────────────────────────────────────
            if pos.action_timer > 0:
                # Градуальное восполнение каждый тик
                need_name = _ACTION_TO_NEED.get(pos.current_action)  # type: ignore[arg-type]
                if need_name is not None and needs is not None:
                    duration = config.ACTION_DURATION.get(pos.current_action, 1)  # type: ignore[arg-type]
                    restore_per_tick = 1.0 / duration
                    current = getattr(needs, need_name)
                    setattr(needs, need_name, min(1.0, current + restore_per_tick))

                pos.action_timer -= 1

                if pos.action_timer == 0:
                    self._finish_action(world, eid, pos, needs)
                continue

            # ── Проверяем: агент дошёл до цели? ─────────────────────
            if pos.current_action not in _GO_TO_ACTION:
                continue

            if pos.target_x is None or pos.target_y is None:
                continue

            action_name, _ = _GO_TO_ACTION[pos.current_action]

            # Для eating/drinking: достаточно быть РЯДОМ с ресурсным тайлом
            if action_name in ("eating", "drinking"):
                resource = "food" if action_name == "eating" else "water"
                if not world.map.resource_tiles_near(
                    pos.tile_x, pos.tile_y, resource
                ):
                    # Не рядом с ресурсом — проверяем дошёл ли до цели
                    if pos.tile_x != pos.target_x or pos.tile_y != pos.target_y:
                        continue
                    # Дошёл до цели но ресурса нет — сбрасываем
                    pos.current_action = None
                    pos.target_x = None
                    pos.target_y = None
                    continue
            elif action_name == "local_wander":
                # local_wander: достаточно быть в радиусе 3 от цели
                dx = abs(pos.tile_x - pos.target_x)
                dy = abs(pos.tile_y - pos.target_y)
                if max(dx, dy) > 3:
                    continue
            else:
                # sleeping: exact target match
                if pos.tile_x != pos.target_x or pos.tile_y != pos.target_y:
                    continue

            # Агент рядом с ресурсом (или на месте для сна) — запускаем действие
            duration = config.ACTION_DURATION[action_name]

            pos.current_action = action_name
            pos.action_timer = duration
            pos.target_x = None
            pos.target_y = None
            pos.path.clear()

            # Запоминаем успешное место ресурса
            mem = world.get_component(eid, Memory)
            if mem is not None:
                if action_name == "eating":
                    mem.last_successful["food"] = (pos.tile_x, pos.tile_y)
                elif action_name == "drinking":
                    mem.last_successful["water"] = (pos.tile_x, pos.tile_y)

            world.event_queue.append({
                "type": "action_start",
                "eid": eid,
                "action": action_name,
                "duration": duration,
                "tick": world.tick,
            })

            if config.DEBUG:
                logger.debug(
                    "tick=%d eid=%d started %s (%d ticks)",
                    world.tick, eid, action_name, duration,
                )

    @staticmethod
    def _finish_action(
        world: World,
        eid: int,
        pos: Position,
        needs: Optional[Needs],
    ) -> None:
        """Применяет эффект завершённого действия."""
        action = pos.current_action

        world.event_queue.append({
            "type": "action_end",
            "eid": eid,
            "action": action,
            "tick": world.tick,
        })

        if config.DEBUG:
            logger.debug(
                "tick=%d eid=%d finished %s",
                world.tick, eid, action,
            )

        pos.current_action = None

        # ── Home comfort: бонус за успешное действие ──────────
        if action in ("eating", "drinking"):
            mem = world.get_component(eid, Memory)
            if mem is not None:
                mem.home_comfort = min(
                    config.HOME_COMFORT_MAX,
                    mem.home_comfort + config.HOME_COMFORT_SUCCESS_BONUS,
                )
            # ── Кормим/поим ребёнка рядом с guardian-ом ────────
            need_name = _ACTION_TO_NEED.get(action)  # type: ignore[arg-type]
            ActionSystem._feed_nearby_children(world, eid, need_name)
            # ── Повторяем если ребёнок ещё голоден/хочет пить ────
            if need_name and ActionSystem._child_needs_more(
                world, eid, need_name
            ):
                duration = config.ACTION_DURATION[action]
                pos.current_action = action
                pos.action_timer = duration

    @staticmethod
    def _child_needs_more(
        world: World, guardian_eid: int, need_name: str
    ) -> bool:
        """Вернуть True если хотя бы один ребёнок guardian-а ещё не насыщен."""
        guardian_pos = world.get_component(guardian_eid, Position)
        if guardian_pos is None:
            return False
        for child_eid, identity in world.get_all_with(Identity):
            if identity.guardian_id != guardian_eid:
                continue
            child_body = world.get_component(child_eid, Body)
            if child_body is None or not child_body.is_child:
                continue
            child_pos = world.get_component(child_eid, Position)
            if child_pos is None:
                continue
            dx = abs(child_pos.tile_x - guardian_pos.tile_x)
            dy = abs(child_pos.tile_y - guardian_pos.tile_y)
            if max(dx, dy) > config.CHILD_GUARDIAN_PROXIMITY:
                continue
            child_needs = world.get_component(child_eid, Needs)
            if child_needs is None:
                continue
            if getattr(child_needs, need_name, 1.0) < config.CHILD_NEED_SATISFIED:
                return True
        return False

    @staticmethod
    def _feed_nearby_children(
        world: World, guardian_eid: int, need_name: str | None
    ) -> None:
        """Когда guardian заканчивает есть/пить, ребёнок рядом тоже получает."""
        if need_name is None:
            return
        guardian_pos = world.get_component(guardian_eid, Position)
        if guardian_pos is None:
            return

        for child_eid, identity in world.get_all_with(Identity):
            if identity.guardian_id != guardian_eid:
                continue
            child_body = world.get_component(child_eid, Body)
            if child_body is None or not child_body.is_child:
                continue
            child_pos = world.get_component(child_eid, Position)
            if child_pos is None:
                continue
            dx = abs(child_pos.tile_x - guardian_pos.tile_x)
            dy = abs(child_pos.tile_y - guardian_pos.tile_y)
            if max(dx, dy) > config.CHILD_GUARDIAN_PROXIMITY:
                continue
            child_needs = world.get_component(child_eid, Needs)
            if child_needs is None:
                continue
            current = getattr(child_needs, need_name)
            setattr(
                child_needs,
                need_name,
                min(1.0, current + config.CHILD_GUARDIAN_FEED_FRACTION),
            )
