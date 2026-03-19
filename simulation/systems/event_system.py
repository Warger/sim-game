"""
EventSystem — рассылка событий и реакция агентов.

В конце каждого тика:
    1. Читает world.event_queue (заполняется другими системами)
    2. Для каждого события находит агентов в зоне воздействия
    3. Рассчитывает реакцию:
        delta = base_impact × trait_modifier × proximity_modifier
        proximity_modifier = 1.0 / (1.0 + distance / PROXIMITY_SCALE)
    4. Применяет delta к потребностям агентов
    5. Записывает в personal_log агента
    6. Собирает дневную статистику

Запускается после DeathSystem.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Dict, List, Optional, Tuple

import config
from simulation.world import World
from simulation.components.body import Body
from simulation.components.memory import Memory
from simulation.components.needs import Needs
from simulation.components.position import Position
from simulation.components.traits import Traits


# ── Спецификации событий ───────────────────────────────────────────

# radius=0 означает «только участники» (self-only)
_EVENT_SPEC: Dict[str, dict] = {
    "death": {
        "radius": 20,
        "impacts": {"mood": -0.2, "safety": -0.2},
        "sentiment": "threat",
    },
    "stillbirth": {
        "radius": 15,
        "impacts": {"mood": -0.15},
        "sentiment": "threat",
    },
    "birth": {
        "radius": 15,
        "impacts": {"mood": 0.15},
        "sentiment": "positive",
    },
    "socialized": {
        "radius": 0,
        "impacts": {"mood": 0.1},
        "sentiment": "positive",
    },
    "ate": {
        "radius": 0,
        "impacts": {"mood": 0.05},
        "sentiment": "positive",
    },
    "slept": {
        "radius": 0,
        "impacts": {"mood": 0.05},
        "sentiment": "positive",
    },
    "need_critical": {
        "radius": 0,
        "impacts": {"safety": -0.1},
        "sentiment": "threat",
    },
    "knowledge_shared": {
        "radius": 0,
        "impacts": {"mood": 0.05, "social": 0.05},
        "sentiment": "positive",
    },
}

PERSONAL_LOG_SIZE = 20


class EventSystem:
    """Обработка событий и реакция агентов."""

    def __init__(self) -> None:
        self._current_day: int = -1
        # Дневная статистика
        self._daily_event_counts: Counter = Counter()
        self._daily_mood_sum: float = 0.0
        self._daily_safety_sum: float = 0.0
        self._daily_agent_count: int = 0

    def update(self, world: World) -> None:
        day = world.tick // config.TICKS_PER_DAY

        # Сброс дневной статистики
        if day != self._current_day:
            self._current_day = day
            self._daily_event_counts = Counter()

        # ── Обрабатываем события ──────────────────────────────────
        for event in world.event_queue:
            self._process_event(world, event)

        # ── Считаем средние mood/safety (каждый тик обновляем) ────
        mood_sum = 0.0
        safety_sum = 0.0
        count = 0
        for _eid, needs in world.get_all_with(Needs):
            mood_sum += needs.mood
            safety_sum += needs.safety
            count += 1
        self._daily_mood_sum = mood_sum
        self._daily_safety_sum = safety_sum
        self._daily_agent_count = count

    # ── Обработка одного события ───────────────────────────────────

    def _process_event(self, world: World, event: dict) -> None:
        event_type = event.get("type", "")
        spec = _EVENT_SPEC.get(event_type)
        if spec is None:
            return

        self._daily_event_counts[event_type] += 1

        radius = spec["radius"]
        impacts = spec["impacts"]
        sentiment = spec["sentiment"]

        if radius == 0:
            # Self-only: применяем к конкретным участникам
            self._apply_self_event(world, event, impacts, sentiment)
        else:
            # Area: ищем агентов в радиусе
            event_tile = event.get("tile")
            if event_tile is None:
                return
            self._apply_area_event(
                world, event, event_tile, radius, impacts, sentiment,
            )

    # ── Self-only событие ──────────────────────────────────────────

    def _apply_self_event(
        self,
        world: World,
        event: dict,
        impacts: dict,
        sentiment: str,
    ) -> None:
        # Определяем список целевых eid
        targets: List[int] = []
        if "eid" in event:
            targets.append(event["eid"])
        if "participants" in event:
            targets.extend(event["participants"])

        for eid in targets:
            if eid not in world.entities:
                continue
            needs = world.get_component(eid, Needs)
            traits = world.get_component(eid, Traits)
            if needs is None:
                continue
            for need_name, base in impacts.items():
                delta = self._calc_delta(base, traits, sentiment, 1.0)
                self._apply_delta(needs, need_name, delta)
                self._log_to_agent(world, eid, event, need_name, delta)

    # ── Area событие ───────────────────────────────────────────────

    def _apply_area_event(
        self,
        world: World,
        event: dict,
        event_tile: Tuple[int, int],
        radius: float,
        impacts: dict,
        sentiment: str,
    ) -> None:
        ex, ey = event_tile
        source_eid = event.get("eid", -1)

        for eid, pos in world.get_all_with(Position):
            if eid == source_eid:
                continue
            dist = math.hypot(pos.tile_x - ex, pos.tile_y - ey)
            if dist > radius:
                continue

            needs = world.get_component(eid, Needs)
            traits = world.get_component(eid, Traits)
            if needs is None:
                continue

            prox = 1.0 / (1.0 + dist / config.PROXIMITY_SCALE)

            for need_name, base in impacts.items():
                delta = self._calc_delta(base, traits, sentiment, prox)
                self._apply_delta(needs, need_name, delta)
                self._log_to_agent(world, eid, event, need_name, delta)

    # ── Расчёт delta ───────────────────────────────────────────────

    @staticmethod
    def _calc_delta(
        base: float,
        traits: Optional[Traits],
        sentiment: str,
        proximity: float,
    ) -> float:
        if traits is None:
            return base * proximity

        # trait_modifier: fearfulness для угроз, sociality для позитивных
        if sentiment == "threat":
            trait_mod = traits.fearfulness
        else:
            trait_mod = traits.sociality

        delta = base * trait_mod * proximity

        # resilience снижает эффект
        delta *= (1.0 - traits.resilience * 0.5)

        return delta

    # ── Применение delta к потребности ─────────────────────────────

    @staticmethod
    def _apply_delta(needs: Needs, need_name: str, delta: float) -> None:
        current = getattr(needs, need_name, None)
        if current is None:
            return
        setattr(needs, need_name, max(0.0, min(1.0, current + delta)))

    # ── Личный лог агента ──────────────────────────────────────────

    @staticmethod
    def _log_to_agent(
        world: World,
        eid: int,
        event: dict,
        need_name: str,
        delta: float,
    ) -> None:
        memory = world.get_component(eid, Memory)
        if memory is None:
            return
        entry = {
            "tick": event.get("tick", world.tick),
            "type": event.get("type", ""),
            "need": need_name,
            "delta": round(delta, 4),
        }
        memory.personal_log.append(entry)
        # Ограничиваем размер
        if len(memory.personal_log) > PERSONAL_LOG_SIZE:
            memory.personal_log[:] = memory.personal_log[-PERSONAL_LOG_SIZE:]

    # ── Ежедневный отчёт ───────────────────────────────────────────

    def get_daily_report(self) -> dict:
        """Данные для ежедневного отчёта."""
        top3 = self._daily_event_counts.most_common(3)
        avg_mood = (
            self._daily_mood_sum / self._daily_agent_count
            if self._daily_agent_count > 0
            else 0.0
        )
        avg_safety = (
            self._daily_safety_sum / self._daily_agent_count
            if self._daily_agent_count > 0
            else 0.0
        )
        return {
            "top_events": [{"type": t, "count": c} for t, c in top3],
            "avg_mood": round(avg_mood, 3),
            "avg_safety": round(avg_safety, 3),
        }
