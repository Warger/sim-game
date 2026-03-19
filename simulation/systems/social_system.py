"""
SocialSystem — фоновая социализация при близости.

Социализация не занимает action слот. Работает параллельно с другими действиями:
    - Агент с достаточно высоким social urgency активирует wants_social
      (порог зависит от sociality trait)
    - Если рядом (≤ config.SOCIAL_INTERACTION_RADIUS тайлов) другой агент
      с активным wants_social — оба получают бонус к social и mood
    - Агент с низким sociality активирует флаг редко → социализируется редко

Импортирует:
    config (SOCIAL_INTERACTION_RADIUS, SOCIAL_SUCCESS_MOOD_BONUS, SOCIAL_SUCCESS_SOCIAL_BONUS,
            SOCIAL_COOLDOWN_TICKS)
    simulation.world.World
    simulation.components.position.Position
    simulation.components.needs.Needs
    simulation.components.memory.Memory
    simulation.components.body.Body

Экспортирует: SocialSystem
"""

from __future__ import annotations

import random
from typing import List, Tuple

import config
from simulation.world import World
from simulation.components.position import Position
from simulation.components.needs import Needs
from simulation.components.memory import Memory
from simulation.components.body import Body


class SocialSystem:
    """Фоновая социализация: пары агентов рядом друг с другом."""

    def __init__(self) -> None:
        self.daily_social_count: int = 0
        self.daily_socialized_agents: set = set()
        self._last_reset_day: int = -1

    def update(self, world: World) -> None:
        current_day = world.tick // config.TICKS_PER_DAY

        # Сброс дневных счётчиков
        if current_day != self._last_reset_day:
            self.daily_social_count = 0
            self.daily_socialized_agents.clear()
            self._last_reset_day = current_day

        # Декремент cooldown для всех агентов
        for _, mem in world.get_all_with(Memory):
            if mem.social_cooldown > 0:
                mem.social_cooldown -= 1

        # Инициаторы: wants_social, не спит, не ребёнок, cooldown == 0
        initiators: List[Tuple[int, Position, Needs, Memory]] = []
        # Доступные собеседники: любой взрослый не спящий
        available: dict = {}  # eid → (pos, needs, mem)
        for eid, mem in world.get_all_with(Memory):
            body = world.get_component(eid, Body)
            if body is not None and body.is_child:
                continue
            pos = world.get_component(eid, Position)
            needs = world.get_component(eid, Needs)
            if pos is None or needs is None:
                continue
            if pos.current_action == "sleeping":
                continue

            available[eid] = (pos, needs, mem)

            if mem.wants_social and mem.social_cooldown <= 0:
                initiators.append((eid, pos, needs, mem))

        if not initiators:
            return

        random.shuffle(initiators)

        used: set = set()
        radius = config.SOCIAL_INTERACTION_RADIUS

        for eid_a, pos_a, needs_a, mem_a in initiators:
            if eid_a in used:
                continue

            # Ищем ближайшего доступного собеседника (не обязан wants_social)
            eid_b = None
            for near_eid, _, _ in world.spatial.query_chebyshev(
                pos_a.tile_x, pos_a.tile_y, radius
            ):
                if near_eid != eid_a and near_eid in available and near_eid not in used:
                    eid_b = near_eid
                    break

            if eid_b is None:
                continue

            _, needs_b, mem_b = available[eid_b]

            used.add(eid_a)
            used.add(eid_b)

            # Бонус к social и mood
            needs_a.social = min(1.0, needs_a.social + config.SOCIAL_SUCCESS_SOCIAL_BONUS)
            needs_a.mood = min(1.0, needs_a.mood + config.SOCIAL_SUCCESS_MOOD_BONUS)
            needs_b.social = min(1.0, needs_b.social + config.SOCIAL_SUCCESS_SOCIAL_BONUS)
            needs_b.mood = min(1.0, needs_b.mood + config.SOCIAL_SUCCESS_MOOD_BONUS)

            # Cooldown
            mem_a.wants_social = False
            mem_b.wants_social = False
            mem_a.social_cooldown = config.SOCIAL_COOLDOWN_TICKS
            mem_b.social_cooldown = config.SOCIAL_COOLDOWN_TICKS

            # Home comfort бонус
            mem_a.home_comfort = min(
                config.HOME_COMFORT_MAX,
                mem_a.home_comfort + config.HOME_COMFORT_SUCCESS_BONUS,
            )
            mem_b.home_comfort = min(
                config.HOME_COMFORT_MAX,
                mem_b.home_comfort + config.HOME_COMFORT_SUCCESS_BONUS,
            )

            # Событие
            world.event_queue.append({
                "type": "socialized",
                "eid_a": eid_a,
                "eid_b": eid_b,
                "tick": world.tick,
            })

            # Дневная статистика
            self.daily_social_count += 1
            self.daily_socialized_agents.add(eid_a)
            self.daily_socialized_agents.add(eid_b)
