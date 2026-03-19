"""
Тесты ReproductionSystem.

Проверяет:
    - Зачатие не происходит если потребности < порога
    - Беременность: таймер декрементится
    - Зачатие требует male + female рядом
"""

import random

import config
from simulation.map.tile import TileMap
from simulation.world import World
from simulation.components.body import Body
from simulation.components.memory import Memory
from simulation.components.needs import Needs
from simulation.components.position import Position
from simulation.components.traits import Traits
from simulation.components.identity import Identity
from simulation.systems.reproduction_system import ReproductionSystem
from simulation.namegen import generate_name


def _make_world(width=20, height=20):
    tile_map = TileMap(width, height)
    return World(tile_map)


def _add_agent(world, x, y, sex, needs=None, age=None):
    eid = world.add_entity()
    world.add_component(eid, Position(
        float_x=float(x), float_y=float(y),
        tile_x=x, tile_y=y,
        prev_tile_x=x, prev_tile_y=y,
    ))
    if age is None:
        age = config.START_AGE_MIN_TICKS
    world.add_component(eid, Body(age=age, sex=sex, is_child=age < config.CHILD_END_TICKS))
    world.add_component(eid, needs or Needs(
        hunger=1.0, thirst=1.0, energy=1.0,
        health=1.0, mood=1.0, social=1.0, safety=1.0,
    ))
    world.add_component(eid, Traits())
    world.add_component(eid, Memory())
    world.add_component(eid, Identity(name=generate_name(random.Random(42))))
    return eid


def _rebuild_spatial(world):
    world.spatial.rebuild(
        (eid, pos.tile_x, pos.tile_y)
        for eid, pos in world.get_all_with(Position)
    )


def test_no_conception_below_needs_threshold():
    """Conception should not happen if mother's needs are below threshold."""
    world = _make_world()
    # Mother with low hunger
    low_needs = Needs(hunger=0.1, thirst=1.0, energy=1.0,
                      health=1.0, mood=1.0, social=1.0, safety=1.0)
    female_eid = _add_agent(world, 10, 10, "female", needs=low_needs)
    male_eid = _add_agent(world, 10, 11, "male")

    _rebuild_spatial(world)

    system = ReproductionSystem()
    random.seed(0)  # seed where random() < BIRTH_CHANCE_PER_TICK
    # Run many ticks to give plenty of chances
    for _ in range(1000):
        _rebuild_spatial(world)
        system.update(world)

    body = world.get_component(female_eid, Body)
    assert not body.is_pregnant, "Conception happened despite low needs"


def test_pregnancy_timer_decrements():
    """Pregnancy timer should decrease by 1 each tick."""
    world = _make_world()
    female_eid = _add_agent(world, 10, 10, "female")

    body = world.get_component(female_eid, Body)
    body.is_pregnant = True
    body.pregnancy_timer = 100
    body.father_id = 999

    _rebuild_spatial(world)

    system = ReproductionSystem()
    system.update(world)

    assert body.pregnancy_timer == 99, f"Timer={body.pregnancy_timer}, expected 99"


def test_conception_possible_with_good_needs():
    """With all needs above threshold and male nearby, conception should be possible."""
    world = _make_world()
    female_eid = _add_agent(world, 10, 10, "female")
    male_eid = _add_agent(world, 10, 11, "male")

    _rebuild_spatial(world)

    system = ReproductionSystem()
    conceived = False
    # Try many seeds — one should trigger conception
    for seed in range(10000):
        random.seed(seed)
        body = world.get_component(female_eid, Body)
        if body.is_pregnant:
            conceived = True
            break
        _rebuild_spatial(world)
        system.update(world)

    assert conceived, "Conception never happened in 10000 attempts despite good conditions"
