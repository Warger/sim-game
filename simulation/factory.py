"""
Фабрика агентов — создание entity с полным набором компонентов.
"""

from __future__ import annotations

import random
from typing import Optional

import config
from simulation.components import Body, Identity, Memory, Needs, Position, Traits
from simulation.namegen import generate_name
from simulation.world import World


def create_agent(
    world: World,
    x: float,
    y: float,
    sex: str,
    age: Optional[int] = None,
    rng: Optional[random.Random] = None,
) -> int:
    """Создаёт агента со всеми компонентами. Возвращает entity ID.

    age — возраст в тиках. Если None, случайный 18–35 лет.
    """
    r = rng or random.Random()

    if age is None:
        age = r.randint(config.START_AGE_MIN_TICKS, config.START_AGE_MAX_TICKS)

    eid = world.add_entity()

    # Position
    tile_x, tile_y = int(x), int(y)
    world.add_component(eid, Position(
        float_x=float(x),
        float_y=float(y),
        tile_x=tile_x,
        tile_y=tile_y,
        prev_tile_x=tile_x,
        prev_tile_y=tile_y,
    ))

    # Body
    is_child = age < config.CHILD_END_TICKS
    elder_coeff = max(0.1, r.gauss(1.0, config.ELDER_DECAY_COEFF_STD))
    world.add_component(eid, Body(
        age=age,
        sex=sex,
        is_child=is_child,
        elder_decay_coeff=elder_coeff,
    ))

    # Needs — случайно 0.7–1.0
    def _rand_need() -> float:
        return r.uniform(config.START_NEEDS_MIN, config.START_NEEDS_MAX)

    world.add_component(eid, Needs(
        hunger=_rand_need(),
        thirst=_rand_need(),
        energy=_rand_need(),
        health=1.0,
        mood=_rand_need(),
        social=_rand_need(),
        safety=_rand_need(),
    ))

    # Traits — нормальное распределение, клэмп [0, 1]
    def _rand_trait() -> float:
        return max(0.0, min(1.0, r.gauss(config.TRAIT_MEAN, config.TRAIT_STD)))

    world.add_component(eid, Traits(
        fearfulness=_rand_trait(),
        sociality=_rand_trait(),
        curiosity=_rand_trait(),
        resilience=_rand_trait(),
        faith=_rand_trait(),
    ))

    # Memory — пустая
    world.add_component(eid, Memory())

    # Identity
    world.add_component(eid, Identity(name=generate_name(r)))

    return eid


def create_starter_population(world: World, rng: Optional[random.Random] = None) -> list[int]:
    """Создаёт START_AGENT_COUNT агентов (половина M, половина F) в стартовой зоне.

    Стартовая зона — area 20×20 вокруг центра карты.
    Возвращает список entity ID.
    """
    r = rng or random.Random()

    cx = world.map.width // 2
    cy = world.map.height // 2

    # Собираем проходимые тайлы в стартовой зоне
    spawn_tiles = []
    for dy in range(-10, 10):
        for dx in range(-10, 10):
            x, y = cx + dx, cy + dy
            if world.map.is_passable(x, y):
                spawn_tiles.append((x, y))

    count = config.START_AGENT_COUNT
    males = count // 2
    females = count - males

    eids = []
    for i in range(count):
        sex = "male" if i < males else "female"
        sx, sy = r.choice(spawn_tiles)
        eid = create_agent(world, sx, sy, sex, rng=r)
        eids.append(eid)

    return eids
