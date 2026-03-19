"""
ReproductionSystem — зачатие, беременность, рождение.

Каждый тик:
    1. Проверяет взрослых небеременных female рядом с взрослым male → зачатие.
    2. Декрементирует pregnancy_timer у беременных.
    3. При pregnancy_timer == 0 → рождение (ищет свободный тайл рядом с матерью).
"""

from __future__ import annotations

import random
from typing import List, Optional, Tuple

import config
from simulation.world import World
from simulation.components.body import Body
from simulation.components.needs import Needs
from simulation.components.position import Position
from simulation.components.traits import Traits
from simulation.components.memory import Memory
from simulation.components.identity import Identity
from simulation.factory import create_agent


class ReproductionSystem:
    """Зачатие, беременность и рождение агентов."""

    def __init__(self) -> None:
        self.daily_births: int = 0
        self._last_reset_day: int = -1

    def update(self, world: World) -> None:
        current_day = world.tick // config.TICKS_PER_DAY

        # Сброс дневного счётчика
        if current_day != self._last_reset_day:
            self.daily_births = 0
            self._last_reset_day = current_day

        # Индекс взрослых мужчин для быстрого lookup по eid
        male_needs: dict[int, Needs] = {}
        for eid, body in world.get_all_with(Body):
            if body.sex != "male" or body.is_child:
                continue
            needs = world.get_component(eid, Needs)
            if needs is not None:
                male_needs[eid] = needs

        # Обрабатываем каждую female
        for eid, body in list(world.get_all_with(Body)):
            if body.sex != "female":
                continue

            if body.is_pregnant:
                self._process_pregnancy(world, eid, body)
            elif not body.is_child:
                self._try_conception(world, eid, body, male_needs)

    # ── Зачатие ──────────────────────────────────────────────────────

    def _try_conception(
        self,
        world: World,
        eid: int,
        body: Body,
        male_needs: dict[int, Needs],
    ) -> None:
        pos = world.get_component(eid, Position)
        needs = world.get_component(eid, Needs)
        if pos is None or needs is None:
            return

        # Все потребности матери должны быть выше порога
        if not self._needs_above_threshold(needs):
            return

        # Ищем подходящего мужчину рядом через spatial grid
        father_id = self._find_mate(world, pos, male_needs)
        if father_id is None:
            return

        # Бросок вероятности
        if random.random() >= config.BIRTH_CHANCE_PER_TICK:
            return

        # Зачатие!
        body.is_pregnant = True
        body.pregnancy_timer = config.PREGNANCY_DURATION_TICKS
        body.father_id = father_id

        world.event_queue.append({
            "type": "pregnant",
            "eid": eid,
            "father_id": father_id,
            "tick": world.tick,
        })

    def _find_mate(
        self,
        world: World,
        mother_pos: Position,
        male_needs: dict[int, Needs],
    ) -> Optional[int]:
        """Возвращает ID подходящего мужчины рядом или None."""
        candidates: List[int] = []
        for mid, _, _ in world.spatial.query_chebyshev(
            mother_pos.tile_x, mother_pos.tile_y,
            config.REPRODUCTION_PROXIMITY_RADIUS,
        ):
            mneeds = male_needs.get(mid)
            if mneeds is None:
                continue
            if not self._needs_above_threshold(mneeds):
                continue
            candidates.append(mid)

        if not candidates:
            return None
        return random.choice(candidates)

    @staticmethod
    def _needs_above_threshold(needs: Needs) -> bool:
        threshold = config.REPRODUCTION_MIN_NEEDS
        return (
            needs.hunger > threshold
            and needs.thirst > threshold
            and needs.energy > threshold
            and needs.health > threshold
            # mood, social, safety исключены: не напрямую контролируемые
            # потребности, не должны блокировать размножение
        )

    # ── Беременность и рождение ──────────────────────────────────────

    def _process_pregnancy(self, world: World, eid: int, body: Body) -> None:
        if body.pregnancy_timer > 0:
            body.pregnancy_timer -= 1
            return

        # pregnancy_timer == 0 → попытка рождения
        pos = world.get_component(eid, Position)
        if pos is None:
            return

        spawn_pos = self._find_spawn_tile(world, pos.tile_x, pos.tile_y)
        if spawn_pos is None:
            # Нет свободного тайла — откладываем, попытка каждый тик
            return

        sx, sy = spawn_pos
        father_id = body.father_id

        # Наследование черт
        mother_traits = world.get_component(eid, Traits)
        father_traits = world.get_component(father_id, Traits) if father_id >= 0 else None

        # Создаём ребёнка
        child_sex = random.choice(["male", "female"])
        child_eid = create_agent(world, sx, sy, child_sex, age=0)

        # Перезаписываем черты: среднее родителей + шум
        child_traits = world.get_component(child_eid, Traits)
        if child_traits is not None and mother_traits is not None:
            for trait_name in config.TRAIT_NAMES:
                mother_val = getattr(mother_traits, trait_name)
                father_val = (
                    getattr(father_traits, trait_name)
                    if father_traits is not None
                    else mother_val
                )
                mean = (mother_val + father_val) / 2.0
                value = random.gauss(mean, config.TRAIT_INHERITANCE_SIGMA)
                value = max(0.0, min(1.0, value))
                setattr(child_traits, trait_name, value)

        # Наследование памяти матери (resource_locations)
        mother_mem = world.get_component(eid, Memory)
        child_mem = world.get_component(child_eid, Memory)
        if mother_mem is not None and child_mem is not None:
            for resource, locations in mother_mem.resource_locations.items():
                child_mem.resource_locations[resource] = set(locations)

        # Identity ребёнка
        child_identity = world.get_component(child_eid, Identity)
        if child_identity is not None:
            child_identity.parent_ids = (eid, father_id)
            child_identity.guardian_id = eid

        # Сброс беременности матери
        body.is_pregnant = False
        body.pregnancy_timer = 0
        body.father_id = -1

        # Событие
        traits_dict = {}
        if child_traits is not None:
            traits_dict = {
                name: getattr(child_traits, name) for name in config.TRAIT_NAMES
            }

        world.event_queue.append({
            "type": "birth",
            "eid": child_eid,
            "mother_id": eid,
            "father_id": father_id,
            "tile": (sx, sy),
            "traits": traits_dict,
            "tick": world.tick,
        })

        self.daily_births += 1

    @staticmethod
    def _find_spawn_tile(
        world: World, cx: int, cy: int, radius: int = 2
    ) -> Optional[Tuple[int, int]]:
        """Ищет свободный проходимый тайл в радиусе от (cx, cy)."""
        candidates: List[Tuple[int, int]] = []
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = cx + dx, cy + dy
                if not world.map.is_passable(nx, ny):
                    continue
                # Проверяем что тайл не занят
                occupied = False
                for _, pos in world.get_all_with(Position):
                    if pos.tile_x == nx and pos.tile_y == ny:
                        occupied = True
                        break
                if not occupied:
                    candidates.append((nx, ny))

        if not candidates:
            return None
        return random.choice(candidates)
