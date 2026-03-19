"""
GameLoop — единственное место где задаётся порядок систем.

Порядок систем: Time → Needs → Memory → Decision → Movement → Action.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import config
from simulation.world import World
from simulation.components.position import Position
from simulation.systems.time_system import TimeSystem
from simulation.systems.needs_system import NeedsSystem
from simulation.systems.memory_system import MemorySystem
from simulation.systems.decision_system import DecisionSystem
from simulation.systems.movement_system import MovementSystem
from simulation.systems.action_system import ActionSystem
from simulation.systems.social_system import SocialSystem
from simulation.systems.reproduction_system import ReproductionSystem
from simulation.systems.death_system import DeathSystem
from simulation.systems.event_system import EventSystem

if TYPE_CHECKING:
    from storage.logger import SimLogger

_LOGGED_EVENT_TYPES = {"death", "birth", "stillbirth", "pregnant"}


class GameLoop:
    """Запускает системы в правильном порядке каждый тик."""

    def __init__(self, logger: Optional[SimLogger] = None) -> None:
        self.social_system = SocialSystem()
        self.reproduction_system = ReproductionSystem()
        self.death_system = DeathSystem()
        self.event_system = EventSystem()
        self.logger = logger
        self.systems = [
            TimeSystem(),
            NeedsSystem(),
            MemorySystem(),
            DecisionSystem(),
            MovementSystem(),
            ActionSystem(),
            self.social_system,
            self.reproduction_system,
            self.death_system,
            self.event_system,
        ]

    def tick(self, world: World) -> None:
        """Один тик симуляции."""
        world.event_queue.clear()
        # Перестраиваем spatial grid один раз за тик
        world.spatial.rebuild(
            (eid, pos.tile_x, pos.tile_y)
            for eid, pos in world.get_all_with(Position)
        )
        for system in self.systems:
            system.update(world)

        # ── Логирование ──────────────────────────────────────────────
        if self.logger is not None:
            self._log_tick(world)

    def _log_tick(self, world: World) -> None:
        """Вызывает методы логгера по результатам тика."""
        logger = self.logger

        # События
        for ev in world.event_queue:
            ev_type = ev.get("type")
            if ev_type in _LOGGED_EVENT_TYPES:
                logger.log_event(world.tick, ev)
            if ev_type == "death":
                logger.log_death(world.tick, ev, world)

        # Снимок агентов
        if world.tick % config.LOG_SNAPSHOT_INTERVAL == 0:
            logger.log_snapshot(world)

        # Агрегированная статистика
        if world.tick % config.LOG_STATS_INTERVAL == 0:
            logger.log_stats(world, self)
