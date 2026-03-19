"""
Тесты NeedsSystem.

Проверяет:
    - Потребности убывают с правильной скоростью
    - Не опускаются ниже 0.0
    - Health убывает только у стариков
    - Критический порог → событие need_critical
"""

import config
from simulation.map.tile import TileMap
from simulation.world import World
from simulation.components.body import Body
from simulation.components.memory import Memory
from simulation.components.needs import Needs
from simulation.components.position import Position
from simulation.components.traits import Traits
from simulation.systems.needs_system import NeedsSystem


def _make_world(width=20, height=20):
    tile_map = TileMap(width, height)
    return World(tile_map)


def _add_agent(world, needs=None, age=None, sex="male"):
    """Add minimal agent with all required components. Returns eid."""
    eid = world.add_entity()
    world.add_component(eid, Position(
        float_x=10.0, float_y=10.0,
        tile_x=10, tile_y=10,
        prev_tile_x=10, prev_tile_y=10,
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
    return eid


def _rebuild_spatial(world):
    world.spatial.rebuild(
        (eid, pos.tile_x, pos.tile_y)
        for eid, pos in world.get_all_with(Position)
    )


def test_thirst_decays_correctly():
    world = _make_world()
    eid = _add_agent(world)
    _rebuild_spatial(world)

    needs = world.get_component(eid, Needs)
    initial = needs.thirst

    system = NeedsSystem()
    ticks = 100
    for _ in range(ticks):
        system.update(world)

    expected = initial - config.NEED_DECAY["thirst"] * ticks
    assert abs(needs.thirst - expected) < 1e-9, f"thirst={needs.thirst}, expected={expected}"


def test_needs_do_not_go_below_zero():
    world = _make_world()
    needs = Needs(hunger=0.001, thirst=0.001, energy=0.001,
                  health=1.0, mood=0.001, social=0.001, safety=0.001)
    eid = _add_agent(world, needs=needs)
    _rebuild_spatial(world)

    system = NeedsSystem()
    for _ in range(100):
        system.update(world)

    assert needs.hunger >= 0.0
    assert needs.thirst >= 0.0
    assert needs.energy >= 0.0
    assert needs.mood >= 0.0
    assert needs.social >= 0.0
    assert needs.safety >= 0.0


def test_health_only_decays_for_elders():
    world = _make_world()

    # Young adult — health should not decay
    young_eid = _add_agent(world, age=config.START_AGE_MIN_TICKS)
    young_needs = world.get_component(young_eid, Needs)

    # Elder — health should decay
    elder_eid = _add_agent(world, age=config.ADULT_END_TICKS + 1000)
    elder_needs = world.get_component(elder_eid, Needs)

    _rebuild_spatial(world)

    system = NeedsSystem()
    for _ in range(100):
        _rebuild_spatial(world)
        system.update(world)

    assert young_needs.health == 1.0, f"Young health decayed to {young_needs.health}"
    assert elder_needs.health < 1.0, f"Elder health did not decay: {elder_needs.health}"


def test_critical_threshold_fires_event():
    world = _make_world()
    needs = Needs(
        hunger=1.0,
        thirst=config.CRITICAL_THRESHOLD["thirst"] + 0.0001,
        energy=1.0, health=1.0, mood=1.0, social=1.0, safety=1.0,
    )
    eid = _add_agent(world, needs=needs)
    _rebuild_spatial(world)

    system = NeedsSystem()
    system.update(world)

    critical_events = [e for e in world.event_queue if e["type"] == "need_critical"]
    assert len(critical_events) == 1, f"Expected 1 critical event, got {len(critical_events)}"
    assert critical_events[0]["need"] == "thirst"
    assert critical_events[0]["eid"] == eid
