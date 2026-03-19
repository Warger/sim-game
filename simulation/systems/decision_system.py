"""
DecisionSystem — utility-based AI, выбор действия каждый тик.

Алгоритм:
    1. Для каждой потребности: urgency = 1.0 - current_value
    2. final_weight = urgency × base_weight × night_modifier
    3. social weight дополнительно × sociality trait
    4. Бросок curiosity: random() < curiosity × CURIOSITY_FACTOR → wander
    5. Иначе — действие с максимальным final_weight
    6. Если агент уже выполняет действие (action_timer > 0) — пропуск

Маппинг потребность → действие:
    thirst  → go_drink  → nearest water
    hunger  → go_eat    → nearest food
    energy  → go_sleep  → текущая позиция
    social  → socialize → wants_social = True
    safety, mood, health → wander

При DEBUG=True: все веса, бросок, итоговый выбор — в лог.
"""

from __future__ import annotations

import logging
import math
import random
from collections import Counter
from typing import Dict, Optional, Tuple

import config
from simulation.world import World
from simulation.components.body import Body
from simulation.components.memory import Memory
from simulation.components.needs import Needs
from simulation.components.position import Position
from simulation.components.traits import Traits
from simulation.systems.memory_system import MemorySystem
from simulation.systems.time_system import is_night

logger = logging.getLogger(__name__)

# Потребность → какое действие запускать
_NEED_TO_ACTION: Dict[str, str] = {
    "thirst": "go_drink",
    "hunger": "go_eat",
    "energy": "go_sleep",
    "social": "socialize",
    "safety": "wander",
    "mood":   "wander",
    "health": "wander",
}


class DecisionSystem:
    """Выбирает действие для каждого агента на основе utility весов."""

    def __init__(self) -> None:
        self._action_counts: Counter[str] = Counter()

    def update(self, world: World) -> None:
        night = is_night(world)
        self._action_counts.clear()


        for eid, pos in world.get_all_with(Position):
            # Не перебивать текущее действие (кроме сна при критическом голоде/жажде)
            if pos.action_timer > 0:
                if pos.current_action == "sleeping":
                    needs_check = world.get_component(eid, Needs)
                    if needs_check is not None:
                        hunger_crit = needs_check.hunger <= config.CRITICAL_THRESHOLD.get("hunger", 0.2)
                        thirst_crit = needs_check.thirst <= config.CRITICAL_THRESHOLD.get("thirst", 0.2)
                        if hunger_crit or thirst_crit:
                            # Просыпаемся — сбрасываем сон
                            pos.action_timer = 0
                            pos.current_action = None
                            world.event_queue.append({
                                "type": "wake_up",
                                "eid": eid,
                                "reason": "hunger" if hunger_crit else "thirst",
                                "tick": world.tick,
                            })
                            # Продолжаем дальше — примем новое решение ниже
                        else:
                            self._action_counts["sleeping"] += 1
                            continue
                else:
                    if pos.current_action:
                        self._action_counts[pos.current_action] += 1
                    continue

            needs = world.get_component(eid, Needs)
            if needs is None:
                continue

            # ── Commitment: не перерешаем go_* пока агент идёт к цели ──
            if (pos.current_action in ("go_eat", "go_drink", "go_sleep")
                    and pos.target_x is not None):
                # Критическая жажда перебивает go_eat
                if (pos.current_action == "go_eat"
                        and needs.thirst <= config.CRITICAL_THRESHOLD.get("thirst", 0.2)):
                    pos.current_action = None
                    pos.target_x = None
                    pos.target_y = None
                    # Продолжаем — примем новое решение ниже
                else:
                    self._action_counts[pos.current_action] += 1
                    continue

            body = world.get_component(eid, Body)
            if body is not None and body.is_child:
                continue

            traits = world.get_component(eid, Traits)
            mem = world.get_component(eid, Memory)

            # ── Расчёт весов ──────────────────────────────────────
            weights: Dict[str, float] = {}
            for need_name, base_w in config.UTILITY_BASE_WEIGHT.items():
                current_value = getattr(needs, need_name, 0.0)
                urgency = 1.0 - current_value

                night_mod = config.UTILITY_NIGHT_MODIFIER.get(need_name, 1.0)
                modifier = night_mod if night else 1.0

                final = urgency * base_w * modifier

                # social × sociality trait
                if need_name == "social" and traits is not None:
                    final *= traits.sociality

                weights[need_name] = final

            # ── Curiosity бросок ──────────────────────────────────
            curiosity = traits.curiosity if traits is not None else config.TRAIT_MEAN
            curiosity_roll = random.random()
            curiosity_triggered = curiosity_roll < curiosity * config.CURIOSITY_FACTOR

            if curiosity_triggered:
                chosen_action = "wander"
                chosen_need = None
            else:
                chosen_need = max(weights, key=weights.get)  # type: ignore[arg-type]
                chosen_action = _NEED_TO_ACTION[chosen_need]

            # ── Маппинг действия на цель ──────────────────────────
            target: Optional[Tuple[int, int]] = None

            if chosen_action == "go_eat":
                target = MemorySystem.get_nearest_resource(world, eid, "food")
                if target is None:
                    if MemorySystem.ask_nearby_for_resource(world, eid, "food"):
                        target = MemorySystem.get_nearest_resource(world, eid, "food")
                    if target is None:
                        chosen_action = "wander"
                        if mem is not None:
                            mem.home_comfort = max(
                                0.0,
                                mem.home_comfort - config.HOME_COMFORT_FAIL_DROP,
                            )

            elif chosen_action == "go_drink":
                target = MemorySystem.get_nearest_resource(world, eid, "water")
                if target is None:
                    if MemorySystem.ask_nearby_for_resource(world, eid, "water"):
                        target = MemorySystem.get_nearest_resource(world, eid, "water")
                    if target is None:
                        chosen_action = "wander"
                        if mem is not None:
                            mem.home_comfort = max(
                                0.0,
                                mem.home_comfort - config.HOME_COMFORT_FAIL_DROP,
                            )

            elif chosen_action == "go_sleep":
                target = (pos.tile_x, pos.tile_y)

            elif chosen_action == "socialize":
                if mem is not None:
                    mem.wants_social = True
                # Идём к ближайшему взрослому агенту
                target = self._find_nearest_agent(world, eid, pos)

            # wander: frontier exploration если есть память, иначе случайный
            if chosen_action == "wander":
                exploring = mem.exploring if mem is not None else False
                target = self._pick_wander_target(pos, exploring, mem)

            # ── Записываем решение ────────────────────────────────
            pos.current_action = chosen_action
            if target is not None:
                pos.target_x, pos.target_y = target

            self._action_counts[chosen_action] += 1

            # ── Debug лог ─────────────────────────────────────────
            if config.DEBUG:
                logger.debug(
                    "tick=%d eid=%d weights=%s curiosity_roll=%.3f "
                    "triggered=%s action=%s target=%s",
                    world.tick, eid,
                    {k: f"{v:.3f}" for k, v in weights.items()},
                    curiosity_roll, curiosity_triggered,
                    chosen_action, target,
                )

        # ── Ежедневный отчёт: распределение действий ──────────────
        time_of_day = world.tick % config.TICKS_PER_DAY
        if time_of_day == config.DAY_START_TICK and world.tick > 0:
            day = world.tick // config.TICKS_PER_DAY
            logger.info(
                "Day %d action distribution: %s",
                day, dict(self._action_counts),
            )

    @staticmethod
    def _pick_wander_target(
        pos: Position, exploring: bool = False, mem=None,
    ) -> Tuple[int, int]:
        """Frontier exploration: идём к краю известных тайлов в случайном направлении.

        Fallback на случайный wander если память пуста.
        """
        # Frontier: выбираем случайное направление и ищем самый дальний
        # известный тайл в этом направлении → идём к границе знаний
        if mem is not None and len(mem.known_tiles) > 10:
            angle = random.random() * 2.0 * math.pi
            dir_x, dir_y = math.cos(angle), math.sin(angle)
            cx, cy = pos.tile_x, pos.tile_y

            best = None
            best_dot = -float("inf")
            # Сэмплируем до 200 тайлов для скорости
            tiles = mem.known_tiles
            if len(tiles) > 200:
                tiles = random.sample(list(tiles), 200)
            for t in tiles:
                dot = (t[0] - cx) * dir_x + (t[1] - cy) * dir_y
                if dot > best_dot:
                    best_dot = dot
                    best = t
            if best is not None:
                return best

        # Fallback — случайный wander
        wander_r = (
            config.EXPLORE_WANDER_RADIUS if exploring else config.WANDER_RADIUS
        )
        dx = random.randint(-wander_r, wander_r)
        dy = random.randint(-wander_r, wander_r)
        tx = max(0, min(config.MAP_WIDTH - 1, pos.tile_x + dx))
        ty = max(0, min(config.MAP_HEIGHT - 1, pos.tile_y + dy))
        return (tx, ty)

    @staticmethod
    def _find_nearest_agent(
        world: World, eid: int, pos: Position
    ) -> Optional[Tuple[int, int]]:
        """Ближайший взрослый агент — цель для социализации."""
        best_dist_sq = float("inf")
        best_pos: Optional[Tuple[int, int]] = None
        cx, cy = pos.tile_x, pos.tile_y

        for other_eid, other_pos in world.get_all_with(Position):
            if other_eid == eid:
                continue
            other_body = world.get_component(other_eid, Body)
            if other_body is not None and other_body.is_child:
                continue
            dx = other_pos.tile_x - cx
            dy = other_pos.tile_y - cy
            dist_sq = dx * dx + dy * dy
            if dist_sq < best_dist_sq:
                best_dist_sq = dist_sq
                best_pos = (other_pos.tile_x, other_pos.tile_y)

        return best_pos
