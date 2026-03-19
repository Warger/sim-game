"""
TimeSystem — обновление времени симуляции.

Каждый тик:
    - Инкрементирует world.tick
    - Определяет время суток (день/ночь)
    - При смене дня/ночи добавляет событие в event_queue
"""

from __future__ import annotations

import config
from simulation.world import World


def is_night(world: World) -> bool:
    """Утилита — True если сейчас ночь. Импортируется другими системами."""
    time_of_day = world.tick % config.TICKS_PER_DAY
    return time_of_day >= config.NIGHT_START_TICK


class TimeSystem:
    """Обновляет world.tick, логирует смену дня/ночи."""

    def update(self, world: World) -> None:
        prev_tick = world.tick
        world.tick += 1

        prev_time_of_day = prev_tick % config.TICKS_PER_DAY
        curr_time_of_day = world.tick % config.TICKS_PER_DAY

        # Смена на день (начало нового дня)
        if curr_time_of_day == config.DAY_START_TICK and prev_tick > 0:
            day_number = world.tick // config.TICKS_PER_DAY
            world.event_queue.append({
                "type": "day_start",
                "tick": world.tick,
                "day": day_number,
            })

        # Смена на ночь
        if (prev_time_of_day < config.NIGHT_START_TICK
                and curr_time_of_day >= config.NIGHT_START_TICK):
            day_number = world.tick // config.TICKS_PER_DAY
            world.event_queue.append({
                "type": "night_start",
                "tick": world.tick,
                "day": day_number,
            })
