"""
DeathSystem — смерть агентов, тела на карте, усыновление.

Порядок:
1. Тикаем orphan_timer у сирот
2. Проверяем условия смерти (жажда, голод, старость, сиротство)
3. При смерти: лог, событие, тело, усыновление
4. Тикаем corpses, удаляем просроченные

Запускается после ReproductionSystem.
"""

from __future__ import annotations

import math
import random
from typing import List, Optional, Tuple

import config
from simulation.world import World
from simulation.components.body import Body
from simulation.components.identity import Identity
from simulation.components.needs import Needs
from simulation.components.position import Position


class DeathSystem:
    """Обработка смерти, тел и усыновления."""

    def __init__(self) -> None:
        self._current_day: int = -1
        # Ежедневная статистика
        self.daily_deaths: dict[str, int] = {}
        self.daily_orphans: int = 0

    def update(self, world: World) -> None:
        day = world.tick // config.TICKS_PER_DAY

        # Сброс дневной статистики
        if day != self._current_day:
            self._current_day = day
            self.daily_deaths = {}
            self.daily_orphans = 0

        # ── 1. Тикаем orphan_timer ───────────────────────────────
        for eid, body in world.get_all_with(Body):
            if body.orphaned:
                body.orphan_timer += 1

        # ── 2. Собираем кандидатов на смерть ─────────────────────
        dead: List[Tuple[int, str]] = []

        for eid, body in list(world.get_all_with(Body)):
            cause = self._check_death(body)
            if cause is not None:
                dead.append((eid, cause))

        # ── 3. Обрабатываем каждую смерть ────────────────────────
        for eid, cause in dead:
            self._process_death(world, eid, cause)

        # ── 4. Тикаем corpses ────────────────────────────────────
        remaining = []
        for corpse in world.corpses:
            corpse["ticks_left"] -= 1
            if corpse["ticks_left"] > 0:
                remaining.append(corpse)
        world.corpses = remaining

    # ── Проверка условий смерти ──────────────────────────────────

    @staticmethod
    def _check_death(body: Body) -> Optional[str]:
        """Возвращает причину смерти или None."""
        if body.dehydration_ticks > config.DEHYDRATION_DEATH_TICKS:
            return "thirst"

        if body.starving_ticks > config.STARVATION_DEATH_TICKS:
            return "hunger"

        if body.age > config.ELDER_DEATH_AGE_TICKS:
            return "_elder_candidate"

        if body.orphaned and body.orphan_timer > config.ORPHAN_DEATH_TICKS:
            return "orphaned"

        return None

    @staticmethod
    def _check_elder_death(needs: Optional[Needs]) -> bool:
        """Проверяет вероятностную смерть от старости на основе health."""
        if needs is None:
            return True
        health = max(0.0, needs.health)
        # chance растёт квадратично: health=1→0%, health=0.5→25%, health=0→100%
        chance = (1.0 - health) ** 2
        return random.random() < chance

    # ── Обработка смерти ─────────────────────────────────────────

    def _process_death(self, world: World, eid: int, cause: str) -> None:
        body = world.get_component(eid, Body)
        if body is None:
            return

        # Elder candidate: проверяем health-based шанс
        if cause == "_elder_candidate":
            needs = world.get_component(eid, Needs)
            if not self._check_elder_death(needs):
                return
            cause = "old_age"

        identity = world.get_component(eid, Identity)
        needs = world.get_component(eid, Needs)
        pos = world.get_component(eid, Position)

        name = identity.name if identity else "?"
        age_years = body.age // config.TICKS_PER_YEAR
        tile = (pos.tile_x, pos.tile_y) if pos else (0, 0)

        # Считаем детей (сколько живых агентов имеют этого агента в parent_ids)
        children_count = self._count_children(world, eid)

        # ── Событие смерти ───────────────────────────────────────
        world.event_queue.append({
            "type": "death",
            "eid": eid,
            "name": name,
            "age_years": age_years,
            "cause": cause,
            "children": children_count,
            "tile": tile,
            "tick": world.tick,
        })

        # ── Мертворождение ───────────────────────────────────────
        if body.is_pregnant:
            world.event_queue.append({
                "type": "stillbirth",
                "mother_id": eid,
                "tick": world.tick,
            })

        # ── Усыновление ──────────────────────────────────────────
        self._handle_adoption(world, eid, tile)

        # ── Тело на карте ────────────────────────────────────────
        world.corpses.append({
            "tile": tile,
            "ticks_left": config.DEATH_BODY_TICKS,
        })

        # ── Удаляем entity ───────────────────────────────────────
        world.remove_entity(eid)

        # ── Статистика ───────────────────────────────────────────
        self.daily_deaths[cause] = self.daily_deaths.get(cause, 0) + 1

    # ── Усыновление ──────────────────────────────────────────────

    def _handle_adoption(self, world: World, dead_eid: int, dead_tile: Tuple[int, int]) -> None:
        """Находит детей умершего и назначает нового опекуна."""
        orphans = []
        for eid, identity in world.get_all_with(Identity):
            if identity.guardian_id == dead_eid:
                orphans.append(eid)

        if not orphans:
            return

        # Собираем взрослых кандидатов
        adults = []
        for eid, body in world.get_all_with(Body):
            if body.is_child or eid == dead_eid:
                continue
            pos = world.get_component(eid, Position)
            if pos is not None:
                adults.append((eid, pos.tile_x, pos.tile_y))

        for orphan_eid in orphans:
            identity = world.get_component(orphan_eid, Identity)
            if identity is None:
                continue

            if adults:
                # Ближайший взрослый (Manhattan distance)
                best_eid = None
                best_dist = math.inf
                for a_eid, ax, ay in adults:
                    dist = abs(ax - dead_tile[0]) + abs(ay - dead_tile[1])
                    if dist < best_dist:
                        best_dist = dist
                        best_eid = a_eid
                identity.guardian_id = best_eid
            else:
                body = world.get_component(orphan_eid, Body)
                if body is not None:
                    body.orphaned = True
                    body.orphan_timer = 0
                identity.guardian_id = None
                self.daily_orphans += 1

    # ── Вспомогательные ──────────────────────────────────────────

    @staticmethod
    def _count_children(world: World, parent_eid: int) -> int:
        """Считает живых агентов, у которых parent_eid в parent_ids."""
        count = 0
        for eid, identity in world.get_all_with(Identity):
            if identity.parent_ids and parent_eid in identity.parent_ids:
                count += 1
        return count

    def get_daily_report(self) -> dict:
        """Данные для ежедневного отчёта."""
        return {
            "deaths_by_cause": dict(self.daily_deaths),
            "total_deaths": sum(self.daily_deaths.values()),
            "orphans_today": self.daily_orphans,
        }

    @staticmethod
    def get_corpse_count(world: World) -> int:
        """Текущее кол-во тел на карте."""
        return len(world.corpses)

    @staticmethod
    def get_orphan_count(world: World) -> int:
        """Текущее кол-во осиротевших детей."""
        count = 0
        for _eid, body in world.get_all_with(Body):
            if body.orphaned:
                count += 1
        return count
