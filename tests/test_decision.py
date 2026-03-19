"""
Тесты DecisionSystem.

Проверяет:
    - При низком thirst выбирается go_drink
    - Emergency override при thirst < 0.5 + known water
    - Дети не принимают решений (пропускаются)
    - Curiosity с вероятностью вызывает wander
"""

import random

import config
from simulation.map.tile import TileMap, TileType
from simulation.world import World
from simulation.components.body import Body
from simulation.components.memory import Memory
from simulation.components.needs import Needs
from simulation.components.position import Position
from simulation.components.traits import Traits
from simulation.systems.decision_system import DecisionSystem


def _make_world(width=20, height=20):
    tile_map = TileMap(width, height)
    return World(tile_map)


def _add_agent(world, needs=None, age=None, sex="male", curiosity=0.5):
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
    world.add_component(eid, Traits(curiosity=curiosity))
    world.add_component(eid, Memory())
    return eid


def _rebuild_spatial(world):
    world.spatial.rebuild(
        (eid, pos.tile_x, pos.tile_y)
        for eid, pos in world.get_all_with(Position)
    )


def test_low_thirst_picks_go_drink():
    """When thirst is critically low and water is known, agent should go_drink."""
    world = _make_world()
    # Put a shore tile at (5, 5) so water exists
    world.map.set_type(5, 5, TileType.SHORE)

    needs = Needs(hunger=1.0, thirst=0.15, energy=1.0,
                  health=1.0, mood=1.0, social=1.0, safety=1.0)
    eid = _add_agent(world, needs=needs, curiosity=0.0)

    mem = world.get_component(eid, Memory)
    mem.resource_locations["water"] = {(5, 5)}
    mem.last_successful["water"] = (5, 5)

    _rebuild_spatial(world)

    system = DecisionSystem()
    random.seed(42)
    system.update(world)

    pos = world.get_component(eid, Position)
    assert pos.current_action == "go_drink", f"Expected go_drink, got {pos.current_action}"


def test_children_skip_decisions():
    """Children should not have their action changed by DecisionSystem."""
    world = _make_world()
    eid = _add_agent(world, age=100)  # child (< CHILD_END_TICKS)

    pos = world.get_component(eid, Position)
    pos.current_action = None

    _rebuild_spatial(world)

    system = DecisionSystem()
    system.update(world)

    # Action should remain None — children are skipped
    assert pos.current_action is None, f"Child action was set to {pos.current_action}"


def test_curiosity_triggers_wander():
    """High curiosity agent with all needs satisfied should sometimes wander."""
    world = _make_world()
    needs = Needs(hunger=1.0, thirst=1.0, energy=1.0,
                  health=1.0, mood=1.0, social=1.0, safety=1.0)
    eid = _add_agent(world, needs=needs, curiosity=1.0)

    _rebuild_spatial(world)

    system = DecisionSystem()
    # With curiosity=1.0, probability = 1.0 * CURIOSITY_FACTOR = 0.2
    # Run multiple times to confirm wander occurs at least once
    wander_count = 0
    for seed in range(50):
        random.seed(seed)
        pos = world.get_component(eid, Position)
        pos.current_action = None
        pos.action_timer = 0
        system.update(world)
        if pos.current_action == "wander":
            wander_count += 1

    assert wander_count > 0, "Curiosity never triggered wander in 50 attempts"
