"""
NeedsSystem — убывание потребностей каждый тик.

- Decay по config.NEED_DECAY
- Energy быстрее ночью (UTILITY_NIGHT_MODIFIER)
- Health убывает только у стариков (age > ADULT_END_TICKS)
- Критические пороги → событие need_critical
- hunger=0 / thirst=0 → счётчик смерти в Body
"""

from __future__ import annotations

import config
from simulation.world import World
from simulation.components.needs import Needs
from simulation.components.body import Body
from simulation.components.traits import Traits
from simulation.components.position import Position
from simulation.components.memory import Memory
from simulation.components.identity import Identity
from simulation.systems.time_system import is_night


class NeedsSystem:
    """Убывание потребностей. Не принимает решений — только меняет числа."""

    def update(self, world: World) -> None:
        night = is_night(world)
        spatial = world.spatial

        for eid, needs in world.get_all_with(Needs):
            body = world.get_component(eid, Body)
            traits = world.get_component(eid, Traits)
            pos = world.get_component(eid, Position)
            mem = world.get_component(eid, Memory)

            # ── Кэш guardian данных (один раз на агента) ────────────
            is_child = body is not None and body.is_child
            guardian_pos = None
            guardian_alive = False
            guardian_sleeping = False
            child_near_guardian = False
            if is_child:
                identity = world.get_component(eid, Identity)
                if identity is not None and identity.guardian_id is not None:
                    guardian_body = world.get_component(
                        identity.guardian_id, Body
                    )
                    guardian_alive = guardian_body is not None
                    if guardian_alive:
                        guardian_pos = world.get_component(
                            identity.guardian_id, Position
                        )
                        if guardian_pos is not None:
                            guardian_sleeping = guardian_pos.current_action == "sleeping"
                            if pos is not None:
                                dx = abs(pos.tile_x - guardian_pos.tile_x)
                                dy = abs(pos.tile_y - guardian_pos.tile_y)
                                child_near_guardian = max(dx, dy) <= config.CHILD_GUARDIAN_PROXIMITY

            # ── Decay обычных потребностей ──────────────────────────
            for need_name, decay in config.NEED_DECAY.items():
                if need_name == "health":
                    continue  # health обрабатывается отдельно

                rate = decay

                # Energy не падает во сне (сон полностью восстанавливает)
                if need_name == "energy":
                    sleeping = (pos is not None and pos.current_action == "sleeping") or (is_child and guardian_sleeping)
                    if sleeping:
                        continue

                # Activity не падает во время local_wander (занятость восстанавливается)
                if need_name == "activity":
                    if pos is not None and pos.current_action == "local_wander":
                        continue

                # Energy быстрее ночью
                if need_name == "energy" and night:
                    rate *= config.UTILITY_NIGHT_MODIFIER["energy"]

                # Sociality trait модифицирует social decay
                if need_name == "social" and traits is not None:
                    rate *= (0.5 + traits.sociality)

                # Ребёнок рядом с guardian — decay замедлен
                if child_near_guardian:
                    rate *= config.CHILD_NEAR_GUARDIAN_DECAY_FACTOR

                old_value = getattr(needs, need_name)
                new_value = max(0.0, old_value - rate)
                setattr(needs, need_name, new_value)

                # Критический порог
                threshold = config.CRITICAL_THRESHOLD.get(need_name)
                if (threshold is not None
                        and old_value >= threshold
                        and new_value < threshold):
                    world.event_queue.append({
                        "type": "need_critical",
                        "eid": eid,
                        "need": need_name,
                        "value": new_value,
                        "tick": world.tick,
                    })

            # ── Ребёнок: пассивное восстановление ─────────────────
            if is_child and guardian_alive:
                restore = config.CHILD_PASSIVE_RESTORE
                needs.thirst = min(1.0, needs.thirst + restore)
                needs.hunger = min(1.0, needs.hunger + restore)
                # Energy: восстанавливается во сне guardian
                if guardian_sleeping:
                    sleep_restore = 1.0 / config.ACTION_DURATION["sleeping"]
                    needs.energy = min(1.0, needs.energy + sleep_restore)

            # ── Safety: восстановление при близости к другим ──────
            if pos is not None:
                if pos.current_action == "sleeping":
                    needs.safety = min(
                        1.0, needs.safety + config.SAFETY_SLEEP_RESTORE
                    )
                for other_eid, _, _ in spatial.query_chebyshev(
                    pos.tile_x, pos.tile_y, config.SAFETY_PROXIMITY_RADIUS
                ):
                    if other_eid != eid:
                        needs.safety = min(
                            1.0, needs.safety + config.SAFETY_PROXIMITY_RESTORE
                        )
                        needs.social = min(
                            1.0, needs.social + config.SOCIAL_PROXIMITY_RESTORE
                        )
                        break  # один сосед достаточно

            # ── Mood: восстановление от сна и сытости ─────────────
            if pos is not None and pos.current_action == "sleeping":
                needs.mood = min(1.0, needs.mood + config.MOOD_SLEEP_RESTORE)
            if needs.hunger > config.MOOD_WELL_FED_THRESHOLD:
                needs.mood = min(
                    1.0, needs.mood + config.MOOD_WELL_FED_RESTORE
                )

            # ── Home comfort: пассивный decay + exploration flag ──
            if mem is not None:
                mem.home_comfort = max(
                    0.0, mem.home_comfort - config.HOME_COMFORT_DECAY
                )
                threshold = config.HOME_COMFORT_EXPLORE_THRESHOLD
                if traits is not None:
                    threshold -= (
                        traits.curiosity * config.HOME_COMFORT_CURIOSITY_FACTOR
                    )
                    threshold = max(0.05, threshold)
                mem.exploring = mem.home_comfort < threshold

            # ── Health: только у стариков ───────────────────────────
            if body is not None and body.age > config.ADULT_END_TICKS:
                decay_rate = config.ELDER_HEALTH_DECAY * body.elder_decay_coeff
                old_health = needs.health
                needs.health = max(0.0, needs.health - decay_rate)

                threshold = config.CRITICAL_THRESHOLD.get("health")
                if (threshold is not None
                        and old_health >= threshold
                        and needs.health < threshold):
                    world.event_queue.append({
                        "type": "need_critical",
                        "eid": eid,
                        "need": "health",
                        "value": needs.health,
                        "tick": world.tick,
                    })

            # ── Счётчики голода/жажды → death_system ───────────────
            if body is not None:
                if needs.hunger <= 0.0:
                    body.starving_ticks += 1
                else:
                    body.starving_ticks = 0

                if needs.thirst <= 0.0:
                    body.dehydration_ticks += 1
                else:
                    body.dehydration_ticks = 0

            # ── Старение ───────────────────────────────────────────
            if body is not None:
                body.age += 1
                body.is_child = body.age < config.CHILD_END_TICKS
